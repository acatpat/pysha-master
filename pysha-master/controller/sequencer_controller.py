# controller/sequencer_controller.py

import definitions
from PyQt6.QtCore import QMetaObject, Qt

class SequencerController:
    """
    Contrôle le séquenceur interne et envoie le feedback sur Push 2.
    Pads et steps parfaitement alignés avec l’emplacement physique.
    Play et résolution gérés via push2_python par le nom du bouton.
    """

    def __init__(self, app, sequencer_model, sequencer_window):
        self.app = app
        self.model = sequencer_model
        self.window = sequencer_window

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

        # Initialisation pads/steps
        self._init_default_mapping()
        self.window.timer.timeout.connect(self.update_push_feedback)


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
            36: (7,0), 37: (7,1), 38: (7,2), 39: (7,3),
            40: (6,0), 41: (6,1), 42: (6,2), 43: (6,3),
            44: (5,0), 45: (5,1), 46: (5,2), 47: (5,3),
            48: (4,0), 49: (4,1), 50: (4,2), 51: (4,3)
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
    def handle_push2_button(self, button_name):
        # Debug log
        print(f"[SEQ CTRL] handle_push2_button called with: {button_name!r}")

        # Transport
        if button_name in self.transport_buttons:
            print("[SEQ CTRL] recognized Play")
            self._toggle_play()
            return

        # Résolution
        if button_name in self.resolution_buttons:
            steps_per_beat = self.resolution_buttons[button_name]
            print(f"[SEQ CTRL] recognized resolution {button_name} -> {steps_per_beat}")
            self._set_resolution(steps_per_beat)
            return

        # fallback: try tolerant matching (strip/lower)
        bn = str(button_name).strip().lower()
        for k in list(self.resolution_buttons.keys()):
            if k.lower() == bn:
                spb = self.resolution_buttons[k]
                print(f"[SEQ CTRL] tolerant match {k} -> {spb}")
                self._set_resolution(spb)
                return

        print(f"[SEQ CTRL] Unknown button_name: {button_name!r}")

    # -------------------------------------------------------------------------
    # SÉLECTION PAD
    # -------------------------------------------------------------------------
    def _select_pad(self, pad_name):
        pitch = [p for p, name in self.pad_map.items() if name == pad_name][0]
        self.window.selected_pad = list(self.pad_map.keys()).index(pitch)

        self.window.update_pad_display()
        self.window.update_steps_display()

        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # TOGGLE D’UN STEP
    # -------------------------------------------------------------------------
    def _toggle_step(self, step_index):
        self.window.toggle_step(step_index)
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # PLAY / STOP (thread-safe)
    # -------------------------------------------------------------------------
    def _toggle_play(self):
        print("[SEQ CTRL] _toggle_play -> invoking toggle_play_slot in UI thread")
        QMetaObject.invokeMethod(self.window, "toggle_play_slot", Qt.ConnectionType.QueuedConnection)
        self.update_push2_play_led()
        self.update_push_feedback()


    # -------------------------------------------------------------------------
    # CHANGEMENT DE RÉSOLUTION (thread-safe)
    # -------------------------------------------------------------------------
    def _set_resolution(self, steps_per_beat):
        from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
        QMetaObject.invokeMethod(
            self.window,
            "set_resolution_slot",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, int(steps_per_beat))
        )
        self.update_push2_resolution_leds()
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # FEEDBACK PUSH 2
    # -------------------------------------------------------------------------
    def update_push_feedback(self):
        if not self.app.push:
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
        steps = self.window.steps[selected_pad_idx]
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
        self.app.push.pads.set_pads_color(pad_matrix)

        # --- Feedback PLAY et RESOLUTION (toujours ok) ---
        # Feedback Play
        play_color = definitions.GREEN if self.window.play_button.isChecked() else definitions.WHITE
        self.app.push.buttons.set_button_color("Play", play_color)

        # Feedback Résolution
        for btn_name, steps in {
            "1/4": 1,
            "1/8": 2,
            "1/16": 4,
            "1/32": 8
        }.items():
            color = definitions.GREEN if steps == self.window.steps_per_beat else definitions.YELLOW
            self.app.push.buttons.set_button_color(btn_name, color)





    # -------------------------------------------------------------------------
    # ACTIONS GLOBALES
    # -------------------------------------------------------------------------
    def _global_action(self, pitch):
        print(f"[SEQ] Action globale non définie pour pitch {pitch}")
