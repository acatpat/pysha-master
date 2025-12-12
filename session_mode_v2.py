# session_mode_v2.py
"""
SessionMode V2 — machine d’état bar-based

Version expérimentale.
NE REMPLACE PAS encore session_mode.py
"""

import mido
from enum import Enum


# ---------------------------------------------------------------------
# CLIP STATE
# ---------------------------------------------------------------------
class ClipState(Enum):
    EMPTY = 0
    ARMED = 1
    RECORDING = 2
    PLAYING = 3
    STOPPED = 4


# ---------------------------------------------------------------------
# CLIP
# ---------------------------------------------------------------------
class Clip:
    def __init__(self):
        self.state = ClipState.EMPTY

        # temps absolu
        self.start_global_tick = None
        self.start_global_step = None
        self.start_bar_index = None
        self.length_bars = None

        # intentions différées
        self.pending_record_start_bar = None
        self.pending_record_stop_bar = None
        self.pending_launch_bar = None
        self.pending_stop_bar = None

        # données musicales
        self.raw_events = []
        self.grid = {}
        self.steps_per_clip = None

    def clear(self):
        self.__init__()


# ---------------------------------------------------------------------
# SESSION MODE V2
# ---------------------------------------------------------------------
class SessionModeV2:

    def __init__(self, sequencer):
        self.sequencer = sequencer

        self.scenes = 8
        self.tracks = 8
        self.clips = [[Clip() for _ in range(self.tracks)]
                      for _ in range(self.scenes)]

        self.armed_clip = None
        self.recording_clip = None
        self.playing_clips = set()

        # note-off scheduler
        self.pending_note_offs = {}
        self.active_notes = set()

    # -----------------------------------------------------------------
    # INTENTIONS UTILISATEUR
    # -----------------------------------------------------------------
    def arm_clip(self, scene, track):
        if self.recording_clip:
            return

        clip = self.clips[scene][track]

        if self.armed_clip:
            self.armed_clip.state = ClipState.STOPPED

        self.armed_clip = clip
        clip.state = ClipState.ARMED
        clip.pending_record_start_bar = self.sequencer.global_bar + 1

    def stop_clip(self, scene, track):
        clip = self.clips[scene][track]

        if clip.state == ClipState.RECORDING:
            clip.pending_record_stop_bar = self.sequencer.global_bar + 1
        elif clip.state == ClipState.PLAYING:
            clip.pending_stop_bar = self.sequencer.global_bar + 1

    def launch_clip(self, scene, track):
        clip = self.clips[scene][track]
        if clip.state in (ClipState.EMPTY, ClipState.RECORDING):
            return
        clip.pending_launch_bar = self.sequencer.global_bar + 1

    # -----------------------------------------------------------------
    # TEMPS : BAR
    # -----------------------------------------------------------------
    def on_bar_start(self, global_bar):

        # --- démarrage record ---
        if self.armed_clip:
            clip = self.armed_clip
            if global_bar == clip.pending_record_start_bar:
                clip.state = ClipState.RECORDING
                clip.raw_events.clear()
                clip.start_global_tick = self.sequencer.global_tick
                clip.start_bar_index = global_bar
                self.recording_clip = clip
                self.armed_clip = None

        # --- arrêt record ---
        if self.recording_clip:
            clip = self.recording_clip
            if global_bar == clip.pending_record_stop_bar:
                clip.length_bars = max(1, global_bar - clip.start_bar_index)
                self.convert_raw_to_grid(clip)
                clip.start_global_step = self.sequencer.global_step
                clip.state = ClipState.PLAYING
                self.playing_clips.add(clip)
                self.recording_clip = None

        # --- lancement clips ---
        for row in self.clips:
            for clip in row:
                if clip.state == ClipState.STOPPED and clip.pending_launch_bar == global_bar:
                    clip.start_global_step = self.sequencer.global_step
                    clip.state = ClipState.PLAYING
                    self.playing_clips.add(clip)

        # --- arrêt clips ---
        to_stop = [c for c in self.playing_clips if c.pending_stop_bar == global_bar]
        for clip in to_stop:
            self._all_notes_off()
            clip.state = ClipState.STOPPED
            self.playing_clips.remove(clip)

    # -----------------------------------------------------------------
    # TEMPS : TICK
    # -----------------------------------------------------------------
    def on_tick(self, global_tick):
        pass

    # -----------------------------------------------------------------
    # TEMPS : STEP → PLAYBACK
    # -----------------------------------------------------------------
    def on_step(self, global_step, step_in_bar):

        self._process_due_note_offs(global_step)

        for clip in list(self.playing_clips):
            if clip.steps_per_clip is None:
                continue

            local_step = (global_step - clip.start_global_step) % clip.steps_per_clip
            events = clip.grid.get(local_step)
            if not events:
                continue

            for ev in events:
                note = ev["note"]
                vel = ev["velocity"]
                dur = ev["duration_steps"]

                self._send_note_on(note, vel)
                self._schedule_note_off(global_step + dur, note)

    # -----------------------------------------------------------------
    # MIDI RAW CAPTURE
    # -----------------------------------------------------------------
    def handle_midi_event(self, msg):
        if not self.recording_clip:
            return
        if msg.type not in ("note_on", "note_off"):
            return

        tick = self.sequencer.global_tick
        etype = msg.type
        if etype == "note_on" and msg.velocity == 0:
            etype = "note_off"

        self.recording_clip.raw_events.append({
            "type": etype,
            "note": msg.note,
            "velocity": msg.velocity,
            "tick": tick
        })

    # -----------------------------------------------------------------
    # RAW → GRID
    # -----------------------------------------------------------------
    def convert_raw_to_grid(self, clip):

        clip.grid.clear()
        ticks_per_step = self.sequencer.ticks_per_step
        steps_per_bar = self.sequencer.steps_per_bar

        clip.steps_per_clip = clip.length_bars * steps_per_bar
        for i in range(clip.steps_per_clip):
            clip.grid[i] = []

        active = {}

        for ev in clip.raw_events:
            local_tick = ev["tick"] - clip.start_global_tick
            step = round(local_tick / ticks_per_step)
            step = max(0, min(step, clip.steps_per_clip - 1))

            if ev["type"] == "note_on":
                active[ev["note"]] = (step, ev["velocity"])
            elif ev["type"] == "note_off" and ev["note"] in active:
                start, vel = active.pop(ev["note"])
                dur = max(1, step - start)
                clip.grid[start].append({
                    "note": ev["note"],
                    "velocity": vel,
                    "duration_steps": dur
                })

        for note, (start, vel) in active.items():
            dur = clip.steps_per_clip - start
            clip.grid[start].append({
                "note": note,
                "velocity": vel,
                "duration_steps": dur
            })

    # -----------------------------------------------------------------
    # MIDI OUT (minimal)
    # -----------------------------------------------------------------
    def _send_note_on(self, note, velocity=100, channel=0):
        app = getattr(self.sequencer, "app", None)
        if not app:
            return
        sm = getattr(app, "synths_midi", None)
        if not sm:
            return
        sm.send(mido.Message("note_on", note=int(note), velocity=int(velocity), channel=channel))
        self.active_notes.add(note)

    def _send_note_off(self, note, channel=0):
        app = getattr(self.sequencer, "app", None)
        if not app:
            return
        sm = getattr(app, "synths_midi", None)
        if not sm:
            return
        sm.send(mido.Message("note_off", note=int(note), velocity=0, channel=channel))
        self.active_notes.discard(note)

    def _schedule_note_off(self, step, note):
        self.pending_note_offs.setdefault(step, []).append(note)

    def _process_due_note_offs(self, global_step):
        notes = self.pending_note_offs.pop(global_step, [])
        for n in notes:
            self._send_note_off(n)

    def _all_notes_off(self):
        for n in list(self.active_notes):
            self._send_note_off(n)
        self.active_notes.clear()
        self.pending_note_offs.clear()
