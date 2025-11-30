import mido
import threading

class SequencerTarget:
    """
    Cible du séquenceur : reçoit les steps activés et envoie les notes
    sur le port MIDI sélectionné dans SettingsMode.
    """

    def __init__(self, app, num_pads=16, steps_per_pad=32, start_note=36, bpm=120, step_duration=0.1):
        self.app = app
        self.num_pads = num_pads
        self.steps_per_pad = steps_per_pad
        self.start_note = start_note  # note du pad 0
        self.bpm = bpm
        self.step_duration = step_duration
        # step_states[pad_index][step_index] = True/False
        self.step_states = [[False]*steps_per_pad for _ in range(num_pads)]

    def set_step_state(self, pad_index, step_index, active=True):
        if 0 <= pad_index < self.num_pads and 0 <= step_index < self.steps_per_pad:
            self.step_states[pad_index][step_index] = active

    def play_step(self, pad_index, step_index, velocity=100):
        if self.app.midi_out is None:
            return
        if 0 <= pad_index < self.num_pads:
            note = self.start_note + pad_index  # mapping pad → note
            msg_on = mido.Message('note_on', note=note, velocity=velocity)
            self.app.send_midi(msg_on)
            threading.Timer(self.step_duration, lambda: self.app.send_midi(
                mido.Message('note_off', note=note, velocity=0)
            )).start()
