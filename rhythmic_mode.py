import definitions
import push2_python.constants

from melodic_mode import MelodicMode


class RhythmicMode(MelodicMode):




    rhythmic_notes_matrix = [
        [64, 65, 66, 67, 96, 97, 98, 99],
        [60, 61, 62, 63, 92, 93, 94, 95],
        [56, 57, 58, 59, 88, 89, 90, 91],
        [52, 53, 54, 55, 84, 85, 86, 87],
        [48, 49, 50, 51, 80, 81, 82, 83],
        [44, 45, 46, 47, 76, 77, 78, 79],
        [40, 41, 42, 43, 72, 73, 74, 75],
        [36, 37, 38, 39, 68, 69, 70, 71]
    ]

    def get_settings_to_save(self):
        return {}

    def pad_ij_to_midi_note(self, pad_ij):
        return self.rhythmic_notes_matrix[pad_ij[0]][pad_ij[1]]

    def update_octave_buttons(self):
        # Rhythmic does not have octave buttons
        pass

    def activate(self):
        super().activate()
        # Forcer l’update complet du feedback Push2
        if hasattr(self.app, 'sequencer_controller'):
            self.app.sequencer_controller.update_push_feedback()




    def update_pads(self):
        # Ici on ne fait rien car SequencerController gère le feedback
        pass

    def deactivate(self):
        super().deactivate()
        # Forcer update des pads à la sortie du mode
        self.app.pads_need_update = True
        self.app.buttons_need_update = True

    # -----------------------------------------------------------
    # ### BLOCK-ROUTING ###
    # -----------------------------------------------------------

    def get_current_instrument(self):
        return self.app.current_instrument_definition

    def send_note_on_current(self, note, velocity):
        instr = self.get_current_instrument()
        if instr:
            self.app.synths_midi.send_note_on(instr, note, velocity)

    def send_note_off_current(self, note, velocity):
        instr = self.get_current_instrument()
        if instr:
            self.app.synths_midi.send_note_off(instr, note, velocity)

    def send_aftertouch_current(self, note, value, poly=True):
        instr = self.get_current_instrument()
        if instr:
            if poly:
                self.app.synths_midi.send(
                    mido.Message("polytouch", note=note, value=value),
                    instr
                )
            else:
                self.app.synths_midi.send_aftertouch(instr, value)

    def send_pitchbend_current(self, value):
        instr = self.get_current_instrument()
        if instr:
            self.app.synths_midi.send_pitchbend(instr, value)


    def on_button_pressed(self, button_name):
        # Ignorer octave up/down
        if button_name in (push2_python.constants.BUTTON_OCTAVE_UP, push2_python.constants.BUTTON_OCTAVE_DOWN):
            return

        # Boutons Play / Résolution gérés ici
        elif button_name in ("1/4", "1/8", "1/16", "1/32"):
            self.app.sequencer_controller.handle_push2_button(button_name)
        else:
            # Les autres boutons sont traités par la classe parente
            super().on_button_pressed(button_name)

    def on_pad_pressed(self, pad_n, pad_ij, velocity):
        midi_note = self.pad_ij_to_midi_note(pad_ij)

        if hasattr(self.app, "sequencer_controller"):
            self.app.sequencer_controller.handle_rhythmic_input(midi_note)
            return True

        return super().on_pad_pressed(pad_n, pad_ij, velocity)



