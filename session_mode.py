import definitions
import push2_python.constants
from melodic_mode import MelodicMode


class Clip:
    STATE_EMPTY = 0
    STATE_PLAYING = 1
    STATE_RECORDING = 2
    STATE_QUEUED = 3
    STATE_QUEUED_RECORD = 4
    STATE_WAIT_END_RECORD = 5

    def __init__(self):
        self.state = Clip.STATE_EMPTY
        self.data = []
        self.length = 16
        self.last_step_notes = []

    def clear(self):
        self.data = []
        self.state = Clip.STATE_EMPTY
        self.last_step_notes = []


class ClipMatrix:
    def __init__(self, rows=8, cols=8):
        self.rows = rows
        self.cols = cols
        self.clips = [[Clip() for _ in range(cols)] for _ in range(rows)]

    def get_clip(self, row, col):
        return self.clips[row][col]

    def to_color_matrix(self):
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
                    color = definitions.GRAY_DARK

                row_colors.append(color)

            matrix.append(row_colors)
        return matrix



class SessionMode(MelodicMode):

    def __init__(self, app, settings=None):
        super().__init__(app, settings=settings)

        self.clips = ClipMatrix(8, 8)
        self.current_page = 0
        self.shift_is_held = False


    # ----------------------------------------------------------------------
    #  FONCTION AJOUTÉE : coupe toutes les notes d'un instrument immédiatement
    # ----------------------------------------------------------------------
    def _send_all_notes_off_for_track(self, track_col):
        """
        Envoie note_off sur 0–127 pour l’instrument de la colonne (piste) donnée.
        Appelé lors d’un STOP clip pour éviter les notes bloquées.
        """
        try:
            tracks = getattr(self.app.track_selection_mode, "tracks_info", [])
            if track_col >= len(tracks):
                return

            instr = tracks[track_col].get("instrument_short_name")
            if not instr:
                return

            for n in range(0, 128):
                self.app.synths_midi.send_note_off(instr, n, velocity=0)

            print(f"[SESSION] ALL NOTES OFF sent for instrument '{instr}'")
        except Exception as e:
            print(f"[SESSION] ERROR ALL NOTES OFF: {e}")


    # -----------------------------------------------------------
    # ACTIVATION / DÉSACTIVATION
    # -----------------------------------------------------------
    def activate(self):
        super().activate()
        self.update_pads()

    def deactivate(self):
        super().deactivate()
        self.app.pads_need_update = True
        self.app.buttons_need_update = True


    # -----------------------------------------------------------
    # UPDATE PADS
    # -----------------------------------------------------------
    def update_pads(self):
        if not self.app.is_mode_active(self):
            return

        push = self.push
        tsm = self.app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", None)

        if not tracks or len(tracks) < 8:
            track_color = definitions.GRAY_DARK
            tracks = [{} for _ in range(8)]

        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                if 0 <= c < len(tracks):
                    track_color = tracks[c].get('color', definitions.GRAY_DARK)
                else:
                    track_color = definitions.GRAY_DARK

                if clip.state == Clip.STATE_EMPTY and len(clip.data) > 0:
                    color = track_color
                    anim = None
                elif clip.state == Clip.STATE_EMPTY:
                    color = definitions.GRAY_DARK
                    anim = None
                elif clip.state == Clip.STATE_QUEUED:
                    color = definitions.YELLOW
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF
                elif clip.state == Clip.STATE_QUEUED_RECORD:
                    color = definitions.ORANGE
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF
                elif clip.state == Clip.STATE_RECORDING:
                    color = definitions.RED
                    anim = push2_python.constants.ANIMATION_PULSING_QUARTER
                elif clip.state == Clip.STATE_WAIT_END_RECORD:
                    color = definitions.RED
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF
                elif clip.state == Clip.STATE_PLAYING:
                    color = track_color
                    anim = push2_python.constants.ANIMATION_PULSING_HALF
                else:
                    color = definitions.GRAY_DARK
                    anim = None

                if anim is None:
                    anim = push2_python.constants.ANIMATION_STATIC

                push.pads.set_pad_color((r, c), color, anim)


    # -----------------------------------------------------------
    #  STEP CALLBACK (PLAYBACK / RECORD)
    # -----------------------------------------------------------
    def on_sequencer_step(self, current_step, is_measure_start, num_steps):
        app = self.app
        tsm = app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", [])

        changed_states = False

        # --- START/STOP RECORD (à la mesure) ---
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                if clip.state == Clip.STATE_QUEUED_RECORD and is_measure_start:
                    clip.state = Clip.STATE_RECORDING
                    clip.data = []
                    clip.length = 0
                    print(f"[SESSION] START RECORDING ({r},{c}) step={current_step}")
                    changed_states = True

                if clip.state == Clip.STATE_WAIT_END_RECORD and is_measure_start:
                    clip.state = Clip.STATE_QUEUED
                    print(f"[SESSION] STOP RECORD ({r},{c}) step={current_step}")

                    # --- AJOUT : couper toutes les notes de ce clip ---
                    self._send_all_notes_off_for_track(c)

                    changed_states = True

        if changed_states:
            app.pads_need_update = True

        # --- NOTE OFF playback ---
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_PLAYING:
                    for ev in clip.data:
                        if ev.get("end") == current_step:
                            try:
                                instr = tracks[c]['instrument_short_name']
                                note = ev["note"]
                                print(f"[SESSION-PLAY] NOTE_OFF {note}")
                                app.synths_midi.send_note_off(instr, note)
                            except:
                                pass

        # --- QUEUED → PLAYING au début boucle ---
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

        # --- NOTE ON playback ---
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_PLAYING:
                    for ev in clip.data:
                        if ev.get("start") == current_step:
                            try:
                                instr = tracks[c]['instrument_short_name']
                                note = ev["note"]
                                vel = ev.get("velocity", 100)
                                print(f"[SESSION-PLAY] NOTE_ON {note}")
                                app.synths_midi.send_note_on(instr, note, vel)
                            except:
                                pass


    # -----------------------------------------------------------
    # GESTION PADS
    # -----------------------------------------------------------
    def on_pad_pressed(self, pad_n, pad_ij, velocity):
        if velocity == 0:
            return False

        row, col = pad_ij
        clip = self.clips.get_clip(row, col)

        # --- Clip existant : PLAY/STOP ---
        if len(clip.data) > 0:
            if clip.state == Clip.STATE_PLAYING:
                clip.state = Clip.STATE_EMPTY
                print(f"[SESSION] Pad ({row},{col}) → STOP")

                # --- AJOUT : note off immédiat ---
                self._send_all_notes_off_for_track(col)

            else:
                clip.state = Clip.STATE_QUEUED
            self.app.pads_need_update = True
            return True

        # --- EMPTY → enregistrement à prochaine mesure ---
        if clip.state == Clip.STATE_EMPTY:
            clip.state = Clip.STATE_QUEUED_RECORD
            print(f"[SESSION] QUEUED_RECORD ({row},{col})")
            self.app.pads_need_update = True
            return True

        # --- RECORDING → stop à prochaine mesure ---
        if clip.state == Clip.STATE_RECORDING:
            clip.state = Clip.STATE_WAIT_END_RECORD
            print(f"[SESSION] WAIT_END_RECORD ({row},{col})")
            self.app.pads_need_update = True
            return True

        return False


    # -----------------------------------------------------------
    # MIDI ENREGISTREMENT
    # -----------------------------------------------------------
    def get_recording_clip(self):
        for r in range(8):
            for c in range(8):
                if self.clips.get_clip(r, c).state == Clip.STATE_RECORDING:
                    return self.clips.get_clip(r, c)
        return None

    def on_midi_in(self, msg, source=None):
        clip = self.get_recording_clip()
        if clip is None:
            return False

        if msg.type not in ("note_on", "note_off"):
            return False

        try:
            current_step = getattr(self.app.sequencer_window, "current_step", -1)
        except:
            current_step = -1
        if current_step < 0:
            current_step = 0

        if msg.type == "note_on" and msg.velocity > 0:
            ev = {"note": msg.note, "velocity": msg.velocity, "start": current_step, "end": None}
            clip.data.append(ev)
            print(f"[SESSION-REC] NOTE_ON {msg.note}")
            return True

        if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            for ev in reversed(clip.data):
                if ev.get("note") == msg.note and ev.get("end") is None:
                    clip.length = max(clip.length, current_step+1)
                    ev["end"] = current_step
                    print(f"[SESSION-REC] NOTE_OFF {msg.note}")
                    break
            return True

        return False


    # -----------------------------------------------------------
    # BOUTONS (inchangé)
    # -----------------------------------------------------------
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
