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
        """
        Joue le step du séquenceur sur le port MIDI de l'instrument DDRM.

        - pad_index : index du pad (0 → num_pads-1)
        - step_index : index du step (0 → steps_per_pad-1)
        - velocity : vélocité de la note
        """

        # Récupérer le port MIDI OUT de DDRM
        instrument_ports = self.app.instrument_midi_ports.get("DDRM", None)
        if instrument_ports is None or instrument_ports.get("out") is None:
            # Pas de port configuré
            return

        midi_out_port = instrument_ports["out"]

        # Vérifier les indices
        if 0 <= pad_index < self.num_pads and 0 <= step_index < self.steps_per_pad:
            # Calculer la note correspondant au pad
            note = self.start_note + pad_index

            # Créer et envoyer le message note_on
            msg_on = mido.Message('note_on', note=note, velocity=velocity)
            midi_out_port.send(msg_on)

            # Programmer note_off après step_duration
            def send_note_off():
                msg_off = mido.Message('note_off', note=note, velocity=0)
                midi_out_port.send(msg_off)

            threading.Timer(self.step_duration, send_note_off).start()

