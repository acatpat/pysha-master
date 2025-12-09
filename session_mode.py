import definitions
import push2_python.constants
from melodic_mode import MelodicMode

# ============================================================================
# SESSION MODE (Playtime-like)
# ============================================================================
# Structure vide, conforme à la charte :
# - aucune simplification
# - aucune logique modifiée dans les autres modes
# - uniquement la base nécessaire
# - tout le futur code SessionMode restera ici
# ============================================================================


class Clip:
    """
    Un clip MIDI avec 4 états:
    - empty
    - playing
    - recording
    - queued (attente démarrage)
    """
    STATE_EMPTY = 0
    STATE_PLAYING = 1
    STATE_RECORDING = 2
    STATE_QUEUED = 3
    STATE_QUEUED_RECORD = 4      # appui sur pad vide → enregistre à prochaine mesure
    STATE_WAIT_END_RECORD = 5    # ré-appui pendant enregistrement → arrêter à prochaine mesure


    def __init__(self):
        self.state = Clip.STATE_EMPTY
        self.data = []    # placeholder pour notes, steps ou events
        self.length = 16  # par défaut

    def clear(self):
        self.data = []
        self.state = Clip.STATE_EMPTY
        self.last_step_notes = []


    def set_playing(self):
        self.state = Clip.STATE_PLAYING

    def set_recording(self):
        self.state = Clip.STATE_RECORDING

    def set_queued(self):
        self.state = Clip.STATE_QUEUED

    def set_empty(self):
        self.state = Clip.STATE_EMPTY



class ClipMatrix:
    """
    Matrice 8x8 de clips, comme Ableton / Playtime.
    Aucune logique encore — structure vide conforme à la charte.
    """
    def __init__(self, rows=8, cols=8):
        self.rows = rows
        self.cols = cols
        self.clips = [[Clip() for _ in range(cols)] for _ in range(rows)]

    def get_clip(self, row, col):
        return self.clips[row][col]


    def to_color_matrix(self):
        """
        Version simple, SANS animations.
        Utilisée si un jour on veut juste une matrice de couleurs.
        SessionMode.update_pads reste la source principale pour le Push.
        """
        matrix = []
        for r in range(self.rows):
            row_colors = []
            for c in range(self.cols):
                clip = self.clips[r][c]

                if clip.state == Clip.STATE_RECORDING:
                    color = definitions.RED
                elif clip.state == Clip.STATE_PLAYING:
                    color = definitions.GREEN
                elif clip.state == Clip.STATE_QUEUED:
                    color = definitions.YELLOW
                elif clip.state == Clip.STATE_QUEUED_RECORD:
                    color = definitions.ORANGE
                elif clip.state == Clip.STATE_WAIT_END_RECORD:
                    color = definitions.RED
                else:
                    color = definitions.GRAY_DARK  # EMPTY visible

                row_colors.append(color)

            matrix.append(row_colors)
        return matrix



class SessionMode(MelodicMode):

    """
    Nouveau mode “Session” (Playtime-like).
    Implémentation vide, étape par étape.
    Aucun impact sur les autres modes.
    """

    def __init__(self, app, settings=None):
        super().__init__(app, settings=settings)

        #self.xor_group = 'pads'
        
        self.clips = ClipMatrix(8, 8)
        self.current_page = 0  # pour expansion future (banques)

        self.shift_is_held = False



    # -----------------------------------------------------------
    # ACTIVATION / DÉSACTIVATION
    # -----------------------------------------------------------


    def activate(self):
        super().activate()
        # Le SessionMode gère lui-même son feedback → pas d’appel au sequencer controller
        self.update_pads()


    def deactivate(self):
        super().deactivate()
        # Forcer update des pads à la sortie du mode
        self.app.pads_need_update = True
        self.app.buttons_need_update = True

    # -----------------------------------------------------------
    # UPDATE PADS / BUTTONS
    # -----------------------------------------------------------
    def update_pads(self):
        print("[DEBUG SESSION] update_pads called")
        """
        Mise à jour des pads avec animations :
        - EMPTY + no data          → gris
        - EMPTY + data (clip)      → couleur de la piste (clip existe mais à l’arrêt)
        - QUEUED                   → jaune clignotant
        - QUEUED_RECORD            → orange clignotant (en attente d’enregistrement)
        - RECORDING                → rouge pulsé
        - WAIT_END_RECORD          → rouge clignotant (en attente de fin d’enregistrement)
        - PLAYING                  → couleur de piste pulsée
        """
        push = self.push
        tsm = self.app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", None)
        if not tracks or len(tracks) < 8:
            # sécurité : empêche les pads de rester gris
            track_color = definitions.GRAY_DARK
            tracks = [{} for _ in range(8)]

        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                # Couleur de piste sécurisée
                if 0 <= c < len(tracks):
                    track_color = tracks[c].get('color', definitions.GRAY_DARK)
                else:
                    track_color = definitions.GRAY_DARK

                # --- PAD AVEC CLIP MAIS ÉTAT EMPTY (STOP) ---
                if clip.state == Clip.STATE_EMPTY and len(clip.data) > 0:
                    color = track_color
                    anim = None

                # --- PAD VIDE, AUCUN CLIP ---
                elif clip.state == Clip.STATE_EMPTY:
                    color = definitions.GRAY_DARK
                    anim = None

                # --- CLIP EN COURS DE LECTURE À LA PROCHAINE MESURE ---
                elif clip.state == Clip.STATE_QUEUED:
                    color = definitions.YELLOW
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF

                # --- ENREGISTREMENT PROGRAMMÉ (prochaine mesure) ---
                elif clip.state == Clip.STATE_QUEUED_RECORD:
                    color = definitions.ORANGE
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF

                # --- EN COURS D’ENREGISTREMENT ---
                elif clip.state == Clip.STATE_RECORDING:
                    color = definitions.RED
                    anim = push2_python.constants.ANIMATION_PULSING_QUARTER

                # --- ENREGISTREMENT VA S’ARRÊTER À LA PROCHAINE MESURE ---
                elif clip.state == Clip.STATE_WAIT_END_RECORD:
                    color = definitions.RED
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF

                # --- LECTURE CLIP ---
                elif clip.state == Clip.STATE_PLAYING:
                    color = track_color
                    anim = push2_python.constants.ANIMATION_PULSING_HALF

                else:
                    color = definitions.GRAY_DARK
                    anim = None

                if anim is None:
                    anim = push2_python.constants.ANIMATION_STATIC  # = 0

                push.pads.set_pad_color((r, c), color=color, animation=anim)


    def on_sequencer_step(self, current_step, is_measure_start, num_steps):
        """
        Appelé à chaque step par SequencerController.
        Gère :
        - démarrage/arrêt d’enregistrement (QUEUED_RECORD / WAIT_END_RECORD)
        - passage QUEUED → PLAYING
        - NOTE ON / NOTE OFF des clips PLAYING
        """
        app = self.app
        tsm = app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", [])

        # -----------------------------
        # 1) DÉMARRER / ARRÊTER ENREGISTREMENT
        # -----------------------------
        changed_states = False

        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                # START RECORD (à la prochaine mesure)
                if clip.state == Clip.STATE_QUEUED_RECORD and is_measure_start:
                    clip.state = Clip.STATE_RECORDING
                    clip.data = []
                    clip.length = 0
                    print(f"[SESSION] START RECORDING ({r},{c}) at step={current_step}")
                    changed_states = True

                # STOP RECORD (à la prochaine mesure)
                if clip.state == Clip.STATE_WAIT_END_RECORD and is_measure_start:
                    clip.state = Clip.STATE_QUEUED
                    # clip.length est déjà mis à jour au fil des NOTE_OFF
                    print(f"[SESSION] STOP RECORD ({r},{c}) at step={current_step} length={clip.length}")
                    changed_states = True

        if changed_states:
            app.pads_need_update = True

        # -----------------------------
        # 2) NOTE OFF : end == current_step
        # -----------------------------
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_PLAYING:
                    for ev in clip.data:
                        end = ev.get("end")
                        if end is not None and end == current_step:
                            try:
                                instr = tracks[c]['instrument_short_name'] if c < len(tracks) else None
                                if instr:
                                    note = ev["note"]
                                    print(f"[SESSION-PLAY] NOTE_OFF instr={instr} note={note} step={current_step}")
                                    app.synths_midi.send_note_off(instr, note)
                            except Exception as e:
                                print(f"[SESSION-PLAY] NOTE_OFF ERROR: {e}")

        # -----------------------------
        # 3) QUEUED → PLAYING au début de boucle
        # -----------------------------
        if current_step == 0:
            changed = False
            for r in range(8):
                for c in range(8):
                    clip = self.clips.get_clip(r, c)
                    if clip.state == Clip.STATE_QUEUED:
                        clip.state = Clip.STATE_PLAYING
                        changed = True
            if changed:
                app.pads_need_update = True

        # -----------------------------
        # 4) NOTE ON : start == current_step
        # -----------------------------
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_PLAYING:
                    for ev in clip.data:
                        start = ev.get("start")
                        if start is not None and start == current_step:
                            note = ev["note"]
                            vel = ev.get("velocity", 100)
                            try:
                                instr = tracks[c]['instrument_short_name'] if c < len(tracks) else None
                                if instr:
                                    print(f"[SESSION-PLAY] NOTE_ON instr={instr} note={note} vel={vel} step={current_step}")
                                    app.synths_midi.send_note_on(instr, note, vel)
                            except Exception as e:
                                print(f"[SESSION-PLAY] NOTE_ON ERROR: {e}")



    def update_buttons(self):
        """
        Placeholder — on pourra associer transport, rec, etc.
        Pour l’instant, rien n’est modifié.
        """
        pass

    def clear_buttons(self):
        """
        Éteint les boutons utilisés par ce mode.
        """
        # Aucun bouton défini pour l’instant
        pass

    # -----------------------------------------------------------
    # GESTION DES PADS PUSH2
    # -----------------------------------------------------------
    def on_pad_pressed(self, pad_n, pad_ij, velocity):
        if velocity == 0:
            return False

        row, col = pad_ij
        clip = self.clips.get_clip(row, col)
        # Interdit d'écraser un clip existant
        if len(clip.data) > 0:
            # seul le PLAY/STOP est autorisé
            if clip.state == Clip.STATE_PLAYING:
                clip.state = Clip.STATE_EMPTY
            else:
                clip.state = Clip.STATE_QUEUED
            self.app.pads_need_update = True
            return True


        # --- 1) EMPTY → en attente enregistrement (prochaine mesure) ---
        if clip.state == Clip.STATE_EMPTY:
            clip.state = Clip.STATE_QUEUED_RECORD
            print(f"[SESSION] Pad ({row},{col}) → QUEUED_RECORD")
            self.app.pads_need_update = True
            return True

        # --- 2) RECORDING → stop à prochaine mesure ---
        if clip.state == Clip.STATE_RECORDING:
            clip.state = Clip.STATE_WAIT_END_RECORD
            print(f"[SESSION] Pad ({row},{col}) → WAIT_END_RECORD")
            self.app.pads_need_update = True
            return True

        # --- 3) PLAYING → STOP immédiat ---
        if clip.state == Clip.STATE_PLAYING:
            clip.state = Clip.STATE_EMPTY
            print(f"[SESSION] Pad ({row},{col}) → EMPTY (stop)")
            self.app.pads_need_update = True
            return True

        # --- 4) QUEUED_RECORD → annuler si re-appui ---
        if clip.state == Clip.STATE_QUEUED_RECORD:
            clip.state = Clip.STATE_EMPTY
            print(f"[SESSION] Pad ({row},{col}) → EMPTY (cancel queued rec)")
            self.app.pads_need_update = True
            return True

        return False

    # -----------------------------------------------------------
    # GESTION DES BOUTONS PUSH2
    # -----------------------------------------------------------
    def on_button_pressed(self, button_name):
        """
        Placeholder : aucun bouton encore mappé.
        """
        return False

    def get_recording_clip(self):
        """
        Retourne le clip en train d’enregistrer, ou None.
        (Il ne peut y en avoir qu’un à la fois car tu enregistres pad par pad.)
        """
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_RECORDING:
                    return clip
        return None

    def on_midi_in(self, msg, source=None):
        print("[SESSION] MIDI IN RECEIVED", msg)
        """
        Enregistre les notes avec durée :
        - start = step du NOTE ON
        - end   = step du NOTE OFF
        Uniquement si un clip est en RECORDING.
        """

        # On ne fait rien s'il n'y a pas de clip en enregistrement
        clip = self.get_recording_clip()
        if clip is None:
            return False

        # On ne gère que les notes
        if msg.type not in ("note_on", "note_off"):
            return False

        # Récupérer le step courant du sequencer
        try:
            current_step = getattr(self.app.sequencer_window, "current_step", -1)
        except Exception:
            current_step = -1

        if current_step < 0:
            current_step = 0

        # --- NOTE ON (vrai ON : velocity > 0) ---
        if msg.type == "note_on" and msg.velocity > 0:
            ev = {
                "note": msg.note,
                "velocity": msg.velocity,
                "start": current_step,
                "end": None,
            }
            clip.data.append(ev)
            print(f"[SESSION-REC] NOTE_ON note={msg.note} vel={msg.velocity} start={current_step}")
            return True

        # --- NOTE OFF (note_off, ou note_on vel=0) ---
        if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            # On cherche la dernière note ON sans 'end'
            for ev in reversed(clip.data):
                if ev.get("note") == msg.note and ev.get("end") is None:
                    clip.length = max(clip.length, current_step+1)
                    ev["end"] = current_step

                    print(f"[SESSION-REC] NOTE_OFF note={msg.note} end={current_step}")
                    break
            return True

        return False



    def on_button_pressed(self, button_name):
        if button_name == "Shift":
            self.shift_is_held = True
            return True
        return False

    def on_button_released(self, button_name):
        if button_name == "Shift":
            self.shift_is_held = False
            return True
        return False
