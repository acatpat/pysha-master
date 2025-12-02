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

    # --------------------
    # PLAY STEP
    # --------------------
    def play_step(self, pad_index, step_index, velocity=100):
        # Récupérer le port actuel de DDRM depuis l'app
        instrument_ports = getattr(self.app, 'instrument_midi_ports', {}).get("DDRM")
        if not instrument_ports:
            return

        midi_out_port = instrument_ports.get("out")
        if not midi_out_port:
            return  # pas de port actif

        # Vérifier indices
        if 0 <= pad_index < self.num_pads and 0 <= step_index < self.steps_per_pad:
            note = self.start_note + pad_index
            try:
                midi_out_port.send(mido.Message('note_on', note=note, velocity=velocity))
            except IOError:
                print(f"[MIDI] Failed to send note_on for DDRM pad {pad_index}")

            def send_note_off():
                try:
                    midi_out_port.send(mido.Message('note_off', note=note, velocity=0))
                except IOError:
                    print(f"[MIDI] Failed to send note_off for DDRM pad {pad_index}")

            import threading
            threading.Timer(self.step_duration, send_note_off).start()