import time
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

        # --- Nouveau : gestion du timing d'enregistrement ---
        self._record_start_time = None    # temps réel du début de la mesure d'enregistrement
        self._step_duration = None        # durée d'un step en secondes (calculé depuis tempo / steps_per_beat)
        self._num_steps = None            # nombre total de steps dans la boucle (num_steps reçu de SequencerController)

    # ----------------------------------------------------------------------
    #  ALL NOTES OFF pour une piste (colonne)
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

    # ----------------------------------------------------------------------
    #  Calcul du step courant à partir du temps réel
    # ----------------------------------------------------------------------
    def _get_step_from_time(self):
        """
        Convertit le temps écoulé depuis _record_start_time en indice de step,
        quantisé sur la grille du séquenceur (steps_per_beat / BPM),
        et replié modulo _num_steps pour rester calé sur la boucle.
        """
        # Fallback : si pas d'info temps → on rebascule sur current_step du séquenceur
        if self._record_start_time is None or not self._step_duration or self._step_duration <= 0:
            try:
                cs = getattr(self.app.sequencer_window, "current_step", 0)
            except Exception:
                cs = 0
            if cs < 0:
                cs = 0
            return cs

        elapsed = time.time() - self._record_start_time
        if elapsed < 0:
            elapsed = 0.0

        raw_step = int(elapsed / self._step_duration)

        if self._num_steps:
            step = raw_step % self._num_steps
        else:
            step = raw_step

        if step < 0:
            step = 0

        return step

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
        """
        Appelé à chaque step par SequencerController.
        On utilise num_steps et les infos du séquenceur pour
        garder l’enregistrement calé sur la boucle.
        """
        app = self.app
        tsm = app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", [])

        # Mémoriser la longueur de boucle et la durée d'un step
        self._num_steps = num_steps

        try:
            tempo = getattr(app.sequencer_window, "tempo_bpm", 120)
            steps_per_beat = getattr(app.sequencer_window, "steps_per_beat", 4)
            if tempo <= 0:
                tempo = 120
            if steps_per_beat <= 0:
                steps_per_beat = 4
            seconds_per_quarter = 60.0 / float(tempo)
            self._step_duration = seconds_per_quarter / float(steps_per_beat)
        except Exception:
            # Fallback : 120 BPM, 4 steps/beat
            self._step_duration = (60.0 / 120.0) / 4.0

        changed_states = False

        # --- START/STOP RECORD (à la mesure) ---
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                # Passage QUEUED_RECORD → RECORDING au début de mesure
                if clip.state == Clip.STATE_QUEUED_RECORD and is_measure_start:
                    clip.state = Clip.STATE_RECORDING
                    clip.data = []
                    clip.length = 0

                    # DÉBUT D'ENREGISTREMENT TEMPOREL :
                    # on cale _record_start_time exactement sur le début de la mesure
                    self._record_start_time = time.time()

                    print(f"[SESSION] START RECORDING ({r},{c}) step={current_step}")
                    changed_states = True

                # Passage WAIT_END_RECORD → QUEUED (fin d'enregistrement) au début de mesure
                if clip.state == Clip.STATE_WAIT_END_RECORD and is_measure_start:
                    clip.state = Clip.STATE_QUEUED
                    print(f"[SESSION] STOP RECORD ({r},{c}) step={current_step}")

                    # couper toutes les notes de ce clip
                    self._send_all_notes_off_for_track(c)

                    # Plus de clip en RECORDING → on peut couper le timing global
                    self._record_start_time = None

                    changed_states = True

        # Si un clip est encore en RECORDING, on garde _record_start_time
        # (si plusieurs devaient exister, on se contente du premier)
        if self.get_recording_clip() is None and self._record_start_time is not None:
            self._record_start_time = None

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
                            except Exception:
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
                            except Exception:
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

                # note off immédiat sur la piste
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
        """
        Enregistre les notes :
        - position de step calculée à partir du temps réel,
          calé sur la mesure d'entrée (QUEUED_RECORD → RECORDING sur is_measure_start)
        - les steps restent alignés sur la grille du séquenceur (steps_per_beat, tempo, num_steps)
        """
        clip = self.get_recording_clip()
        if clip is None:
            return False

        if msg.type not in ("note_on", "note_off"):
            return False

        # Step courant basé sur le temps (et donc sur la mesure où l'enregistrement a démarré)
        step = self._get_step_from_time()

        # --- NOTE ON (vrai ON : velocity > 0) ---
        if msg.type == "note_on" and msg.velocity > 0:
            ev = {
                "note": msg.note,
                "velocity": msg.velocity,
                "start": step,
                "end": None
            }
            clip.data.append(ev)
            print(f"[SESSION-REC] NOTE_ON {msg.note} step={step}")
            return True

        # --- NOTE OFF (note_off, ou note_on vel=0) ---
        if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            for ev in reversed(clip.data):
                if ev.get("note") == msg.note and ev.get("end") is None:
                    clip.length = max(clip.length, step + 1)
                    ev["end"] = step
                    print(f"[SESSION-REC] NOTE_OFF {msg.note} step={step}")
                    break
            return True

        return False

    # -----------------------------------------------------------
    # BOUTONS
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
