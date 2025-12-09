# controller/sequencer_controller.py
from session_mode import Clip

import definitions
import mido
from PyQt6.QtCore import QMetaObject, Qt, Q_ARG


class SequencerController:
    """
    Contrôle le séquenceur interne et envoie le feedback sur Push 2.
    Pads et steps parfaitement alignés avec l’emplacement physique.
    Play et résolution gérés via push2_python par le nom du bouton.
    """

    def __init__(self, app, sequencer_model, sequencer_window):
        self.app = app
        # sequencer_model est typiquement une matrice 16 x 32 de bool (référence sur SequencerWindow.steps)
        self.model = sequencer_model
        self.window = sequencer_window           # ancien nom utilisé partout
        self.sequencer_window = sequencer_window # nouveau nom utilisé dans tick_from_clock_thread


        self._ignore_next_play = False

        # Initialisations des attributs
        self.pad_map = {}               # pitch → pad_name
        self.step_range_start = None
        self.step_range_end = None
        self.pad_to_push2 = {}          # pitch MIDI → (row, col) sur Push 2
        self.step_to_push2 = {}         # step_index → (row, col) sur Push 2
        self.step_pitch_to_index = {}   # pitch MIDI → step_index

        # Boutons Play / Résolution par nom Push2
        self.transport_buttons = {"Play": "play"}
        self.resolution_buttons = {"1/4": 1, "1/8": 2, "1/16": 4, "1/32": 8}


        # État de timing pour la clock maître MIDI
        # steps_per_beat vient de la fenêtre (1, 2, 4, 8)
        self.steps_per_beat = getattr(self.window, "steps_per_beat", 4)
        # 24 pulses MIDI par noire -> nombre de pulses nécessaires par step
        # (1, 2, 4, 8 divisent 24 donc c'est cohérent)
        self.ticks_per_step = max(1, int(24 / self.steps_per_beat))
        self._tick_counter = 0

        self._tick_count = 0


        # Initialisation pads/steps
        self._init_default_mapping()

    def on_first_clock_tick(self):
        """
        Appelé uniquement au tout premier tick clock après START.
        Force l’envoi du tout premier step (step 0).
        """
        try:
            self.current_step = 0
            instrument = getattr(self.app.sequencer_window, "sequencer_output_instrument", None)
            self.play_step(instrument, 0)
        except Exception as e:
            print("[SEQ] Error in on_first_clock_tick:", e)


    def set_tempo(self, bpm):
        """Synchronise le tempo entre UI et Synths_Midi."""
        try:
            self.app.synths_midi.bpm = bpm
            print(f"[SEQ CTRL] tempo updated -> {bpm} bpm")
        except Exception as e:
            print("[SEQ CTRL] set_tempo error:", e)


    # -------------------------------------------------------------------------
    # INITIALISATION DU MAPPING
    # -------------------------------------------------------------------------
    def _init_default_mapping(self):
        # Pads MIDI
        self.pad_map = {
            36: "kick", 37: "snare", 38: "closed_hh", 39: "open_hh",
            40: "pad5", 41: "pad6", 42: "pad7", 43: "pad8",
            44: "pad9", 45: "pad10", 46: "pad11", 47: "pad12",
            48: "pad13", 49: "pad14", 50: "pad15", 51: "pad16"
        }

        # Mapping pads → positions Push 2
        self.pad_to_push2 = {
            36: (7, 0), 37: (7, 1), 38: (7, 2), 39: (7, 3),
            40: (6, 0), 41: (6, 1), 42: (6, 2), 43: (6, 3),
            44: (5, 0), 45: (5, 1), 46: (5, 2), 47: (5, 3),
            48: (4, 0), 49: (4, 1), 50: (4, 2), 51: (4, 3)
        }

        # Steps (32 steps sur 4 lignes de 8)
        step_rows = [
            [64, 65, 66, 67, 96, 97, 98, 99],
            [60, 61, 62, 63, 92, 93, 94, 95],
            [56, 57, 58, 59, 88, 89, 90, 91],
            [52, 53, 54, 55, 84, 85, 86, 87]
        ]
        self.step_range_start = min(min(row) for row in step_rows)
        self.step_range_end = max(max(row) for row in step_rows)

        for row_idx, row_notes in enumerate(step_rows):
            for col_idx, pitch in enumerate(row_notes):
                step_index = row_idx * 8 + col_idx
                self.step_to_push2[step_index] = (row_idx, col_idx)
                self.step_pitch_to_index[pitch] = step_index

    # -----------------------------------------------------------
    # ### BLOCK-ROUTING ###
    # -----------------------------------------------------------
    def get_current_instrument(self):
        return getattr(self.app, "current_instrument_definition", None)

    def send_note_on_current(self, note, velocity):
        instr = self.get_current_instrument()
        if instr:
            try:
                self.app.synths_midi.send_note_on(instr, note, velocity)
            except Exception:
                pass

    def send_note_off_current(self, note, velocity):
        instr = self.get_current_instrument()
        if instr:
            try:
                self.app.synths_midi.send_note_off(instr, note, velocity)
            except Exception:
                pass

    def send_aftertouch_current(self, note, value, poly=True):
        instr = self.get_current_instrument()
        if not instr:
            return
        try:
            if poly:
                self.app.synths_midi.send(
                    mido.Message("polytouch", note=note, value=value),
                    instr
                )
            else:
                self.app.synths_midi.send_aftertouch(instr, value)
        except Exception:
            pass

    def send_pitchbend_current(self, value):
        instr = self.get_current_instrument()
        if instr:
            try:
                self.app.synths_midi.send_pitchbend(instr, value)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # GESTION DES NOTES (pads/steps)
    # -------------------------------------------------------------------------
    def handle_rhythmic_input(self, pitch, is_note_on=True):
        if not is_note_on:
            return

        # 1. Sélection pad
        if pitch in self.pad_map:
            return self._select_pad(self.pad_map[pitch])

        # 2. Toggle step
        if pitch in self.step_pitch_to_index:
            step_index = self.step_pitch_to_index[pitch]
            return self._toggle_step(step_index)

        # 3. Actions globales
        return self._global_action(pitch)

    # -------------------------------------------------------------------------
    # GESTION DES BOUTONS PUSH2 PAR NOM
    # -------------------------------------------------------------------------
    def handle_push2_button(self, button_name, pressed=True):
        print(f"[SEQ CTRL] button={button_name} pressed={pressed}")

        # Transport
        if button_name in self.transport_buttons:
            if pressed:
                print("[SEQ CTRL] Play pressed")
                self._toggle_play()
            else:
                print("[SEQ CTRL] Play released (ignored)")
            return

        # Résolution
        if pressed and button_name in self.resolution_buttons:
            steps_per_beat = self.resolution_buttons[button_name]
            self._set_resolution(steps_per_beat)
            return


    # -------------------------------------------------------------------------
    # SÉLECTION PAD
    # -------------------------------------------------------------------------
    def _select_pad(self, pad_name):
        # Trouver le pitch correspondant au pad_name
        pitch = [p for p, name in self.pad_map.items() if name == pad_name][0]
        # Index du pad dans l'ordre des clés pad_map
        self.window.selected_pad = list(self.pad_map.keys()).index(pitch)

        # Mise à jour UI
        if hasattr(self.window, "update_pad_display"):
            self.window.update_pad_display()
        if hasattr(self.window, "update_steps_display"):
            self.window.update_steps_display()

        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # TOGGLE D’UN STEP
    # -------------------------------------------------------------------------
    def _toggle_step(self, step_index):
        pad = self.window.selected_pad
        if pad < 0 or pad >= len(self.model):
            return

        # Toggle dans le modèle (matrice de booléens)
        pad_steps = self.model[pad]
        if 0 <= step_index < len(pad_steps):
            pad_steps[step_index] = not pad_steps[step_index]

            # Si un SequencerTarget est branché sur la fenêtre, informer
            target = getattr(self.window, "sequencer_target", None)
            if target is not None and hasattr(target, "set_step_state"):
                try:
                    target.set_step_state(pad, step_index, pad_steps[step_index])
                except Exception:
                    pass

            # Mise à jour UI
            if hasattr(self.window, "update_steps_display"):
                self.window.update_steps_display()

            self.update_push_feedback()

    # -------------------------------------------------------------------------
    # PLAY / STOP (thread-safe)
    # -------------------------------------------------------------------------
    def _toggle_play(self):
        print("[SEQ CTRL] _toggle_play -> invoking toggle_play_slot in UI thread")

        # --- RESET LOGIQUE DU SEQUENCER ---
        # (toujours remettre le sequencer au step 0 avant un nouveau démarrage)
        try:
            self.window.current_step = 0
        except Exception:
            pass

        # --- appel thread-safe de l'UI ---
        QMetaObject.invokeMethod(
            self.window,
            "toggle_play_slot",
            Qt.ConnectionType.QueuedConnection
        )

        self.update_push2_play_led()
        self.update_push_feedback()

    def reset_after_stop(self):
        """Remet le séquenceur dans un état propre après un STOP clock."""
        print("[SEQ] reset_after_stop()")

        # 1) Réinitialiser l'étape courante
        self.window.current_step = 0

        # 2) Reset visuel
        try:
            self.window.reset_step_highlight()
        except Exception:
            pass

        # 3) Mettre à jour Push2
        try:
            self.update_push_feedback()
        except Exception:
            pass


    # -------------------------------------------------------------------------
    # CHANGEMENT DE RÉSOLUTION (thread-safe depuis Push2)
    # -------------------------------------------------------------------------
    def _set_resolution(self, steps_per_beat):
        # 1) Propager vers la fenêtre (UI + état steps_per_beat)
        QMetaObject.invokeMethod(
            self.window,
            "set_resolution_slot",
            Qt.QueuedConnection,
            Q_ARG(int, int(steps_per_beat))
        )

        # 2) Mettre à jour la résolution interne pour la clock maître
        self.steps_per_beat = steps_per_beat
        # 24 pulses MIDI par beat / steps_per_beat = pulses par step
        self.ticks_per_step = max(1, int(24 / self.steps_per_beat))
        self._tick_counter = 0  # on resynchronise le compteur

        # 3) Feedback Push2
        self.update_push2_resolution_leds()
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # GESTION TEMPO (appelable depuis la fenêtre si besoin)
    # -------------------------------------------------------------------------
    def set_tempo(self, bpm):
        """
        Optionnel : permet de synchroniser un changement de tempo UI
        avec la clock interne (Synths_Midi).
        """
        try:
            # Mettre à jour le BPM dans Synths_Midi si présent
            if hasattr(self.app, "synths_midi") and self.app.synths_midi is not None:
                self.app.synths_midi.bpm = float(bpm)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # FEEDBACK PUSH 2
    # -------------------------------------------------------------------------
    def update_push2_play_led(self):
        if not getattr(self.app, "push", None):
            return
        play_color = definitions.GREEN if self.window.play_button.isChecked() else definitions.WHITE
        try:
            self.app.push.buttons.set_button_color("Play", play_color)
        except Exception:
            pass

    def update_push2_resolution_leds(self):
        if not getattr(self.app, "push", None):
            return
        try:
            for btn_name, steps in {
                "1/4": 1,
                "1/8": 2,
                "1/16": 4,
                "1/32": 8
            }.items():
                color = definitions.GREEN if steps == self.window.steps_per_beat else definitions.YELLOW
                self.app.push.buttons.set_button_color(btn_name, color)
        except Exception:
            pass

    def update_push_feedback(self):
        if not getattr(self.app, "push", None):
            return

        # --- NE FAIRE LE FEEDBACK RHYTHMIC QUE SI LE MODE EST ACTIF ---
        if not self.app.is_mode_active(self.app.rhyhtmic_mode):
            # Si Rhythmic n'est pas actif, laisser les autres modes gérer leurs pads
            return

        pad_matrix = [[definitions.BLACK for _ in range(8)] for _ in range(8)]

        # --- Pad sélectionné ---
        selected_pad_idx = self.window.selected_pad
        selected_pitch = list(self.pad_map.keys())[selected_pad_idx]
        row, col = self.pad_to_push2[selected_pitch]
        pad_matrix[row][col] = definitions.NOTE_ON_COLOR

        # --- Steps actifs ---
        steps = self.model[selected_pad_idx]
        for step_index, step_on in enumerate(steps):
            if step_index in self.step_to_push2 and step_on:
                step_row, step_col = self.step_to_push2[step_index]
                pad_matrix[step_row][step_col] = definitions.NOTE_ON_COLOR

        # --- Highlight du step courant (BLANC) ---
        current_step = self.window.current_step
        if current_step in self.step_to_push2:
            row, col = self.step_to_push2[current_step]
            pad_matrix[row][col] = definitions.WHITE

        # --- ENVOI DES COULEURS ---
        try:
            self.app.push.pads.set_pads_color(pad_matrix)
        except Exception:
            pass

        # --- Feedback PLAY et RESOLUTION ---
        self.update_push2_play_led()
        self.update_push2_resolution_leds()

    # -------------------------------------------------------------------------
    # AVANCÉE DU SÉQUENCEUR PILOTÉE PAR LA CLOCK MAÎTRE
    # -------------------------------------------------------------------------


    def advance_step(self):
        """
        Avance le step courant, joue les notes actives du SEQUENCER
        et notifie les modes (SessionMode, etc.).
        """
        # Sécurité
        if not self.model:
            return

        num_pads = len(self.model)
        if num_pads == 0:
            return

        # Nombre de steps par pad (on assume identique sur tous les pads)
        pad0 = self.model[0]
        if not pad0:
            return
        num_steps = len(pad0)

        # Step courant
        current_step = getattr(self.window, "current_step", -1)

        # Gestion du premier tick après START
        if current_step == -1:
            next_step = 0
        else:
            next_step = (current_step + 1) % num_steps

        # Mémoriser le step
        self.window.current_step = next_step
        self.current_step = next_step

        # Appliquer le nouveau highlight UI
        if hasattr(self.window, "highlight_step"):
            try:
                self.window.highlight_step(next_step, True)
            except Exception:
                pass

        # --- LECTURE DU SÉQUENCEUR (comme avant) ---
        target = getattr(self.window, "sequencer_target", None)
        if target is not None and hasattr(target, "play_step"):
            for pad_index, pad_steps in enumerate(self.model):
                if 0 <= next_step < len(pad_steps) and pad_steps[next_step]:
                    try:
                        target.play_step(pad_index, next_step)
                    except Exception:
                        pass

        # --- NOTIFICATION DES MODES (SessionMode, etc.) ---
        is_measure_start = (next_step == 0)
        try:
            modes = getattr(self.app, "active_modes", [])
            for mode in modes:
                cb = getattr(mode, "on_sequencer_step", None)
                if cb:
                    try:
                        # on passe aussi num_steps au cas où Session en a besoin
                        cb(next_step, is_measure_start, num_steps)
            
                    except Exception:
                        pass
        
        except Exception:
            pass

        # --- SESSION MODE TOUJOURS NOTIFIÉ ---
        session = getattr(self.app, "session_mode", None)
        if session:
            cb = getattr(session, "on_sequencer_step", None)
            if cb:
                try:
                    cb(next_step, is_measure_start, num_steps)
                except Exception:
                    pass


        # --- Feedback Push 2 du SEQUENCER (Rhythmic) ---
        # La méthode elle-même vérifie déjà si Rhythmic est actif
        self.update_push_feedback()

        print(f"[SEQ] advance_step → step {next_step}")




    def tick_from_clock_thread(self, event=None):
        if event == "stop":
            self._tick_count = 0
            self.current_step = 0
            return

        # 24ppqn → ticks MIDI
        ticks_per_step = 24 / float(self.steps_per_beat)

        self._tick_count += 1

        # Assez de ticks → avancer d’un step
        if self._tick_count >= ticks_per_step:
            self._tick_count = 0
            self.advance_step()

            # --- SESSION MODE: lancer clips QUEUED au début de la mesure ---
            if hasattr(self.app, "session_mode"):
                # début de mesure = current_step == 0
                if self.current_step == 0:
                    sm = self.app.session_mode
                    for r in range(8):
                        for c in range(8):
                            clip = sm.clips.get_clip(r, c)
                            if clip.state == Clip.STATE_QUEUED:
                                clip.state = Clip.STATE_PLAYING
                    self.app.pads_need_update = True




    # -------------------------------------------------------------------------
    # ACTIONS GLOBALES
    # -------------------------------------------------------------------------
    def _global_action(self, pitch):
        print(f"[SEQ] Action globale non définie pour pitch {pitch}")
