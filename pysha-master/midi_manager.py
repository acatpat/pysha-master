# midi_manager.py

import mido
import push2_python
import definitions
import rtmidi     # ← AJOUT demandé


# =====================================================================
#  ████  PUSH2_MIDI  ████
#  Interface UNIQUE entre ton code et push2_python
#  Ne gère AUCUN port MIDO
# =====================================================================

class Push2_Midi:
    def __init__(self, push_device):
        """
        push_device = instance de push2_python.Push2
        """
        self.push = push_device

    # -----------------------------------------------------------
    # ### BLOCK-PADS ###
    # -----------------------------------------------------------
    def set_pad_color(self, pad_ij, color):
        pass  # wrapper futur

    def set_pads_color_matrix(self, matrix):
        pass

    def clear_pads(self):
        pass

    # -----------------------------------------------------------
    # ### BLOCK-BUTTONS ###
    # -----------------------------------------------------------
    def set_button_color(self, button_name, color, animation=None):
        pass

    def clear_buttons(self):
        pass

    # -----------------------------------------------------------
    # ### BLOCK-DISPLAY ###
    # -----------------------------------------------------------
    def display_notification(self, text):
        pass  # future abstraction autour de show_notification

    def display_text(self, *args, **kwargs):
        pass

    # -----------------------------------------------------------
    # ### BLOCK-SYSTEM ###
    # -----------------------------------------------------------
    def reconnect(self):
        """Tentative de reconnexion propre du Push2 si nécessaire."""
        pass

    def is_connected(self):
        pass



# =====================================================================
#  ████  SYNTHS_MIDI  ████
#  Gère TOUT le midi sauf Push2
#  Ports, synthés, Pyramid, routing, envoi messages
# =====================================================================

class Synths_Midi:
    def __init__(self):
        # stockage des ports MIDI ouvert
        self.midi_in_ports = {}
        self.midi_out_ports = {}

        # mapping instrument -> ports
        self.instrument_midi_ports = {}

        # pyramidi / clock / routing
        self.pyramid_channel = 15

    # -----------------------------------------------------------
    # ### BLOCK-PORTS ###
    # -----------------------------------------------------------
    def scan_available_ports(self):
        """Retourne liste des ports IN/OUT disponibles."""
        return {
            "in": mido.get_input_names(),
            "out": mido.get_output_names()
        }

    def open_in_port(self, name):
        """Ouvre un port IN (si pas déjà ouvert)."""
        pass

    def open_out_port(self, name):
        """Ouvre un port OUT (si pas déjà ouvert)."""
        pass

    def assign_instrument_ports(self, instrument_name, in_name, out_name):
        """Associe un synthé avec ses ports Mido."""
        pass

    # -----------------------------------------------------------
    # ### BLOCK-SEND GENERIC ###
    # -----------------------------------------------------------
    def send(self, msg, instrument_name=None):
        """
        Envoie un message MIDI :
        - soit vers un instrument (si instrument_name)
        - soit global (si None)
        """
        pass

    # -----------------------------------------------------------
    # ### BLOCK-SEND SHORTCUTS ###
    # -----------------------------------------------------------
    def send_note_on(self, instrument_name, note, velocity=100):
        pass

    def send_note_off(self, instrument_name, note):
        pass

    def send_cc(self, instrument_name, cc, value):
        pass

    def send_program_change(self, instrument_name, program):
        pass

    # -----------------------------------------------------------
    #  (SUPPRESSION demandée)
    #  ### BLOCK-PYRAMID ###
    #  -> retiré entièrement
    # -----------------------------------------------------------

    # -----------------------------------------------------------
    # ### BLOCK-ERROR & DIAGNOSTICS ###
    # -----------------------------------------------------------
    def port_exists(self, name):
        pass

    def reconnect_missing_ports(self):
        """Tentative de reconnexion automatique si un port disparaît."""
        pass

    def debug_print_ports(self):
        pass
