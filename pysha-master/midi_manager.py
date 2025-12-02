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
        
        # pour appeler les ports
        self.incoming_midi_callback = None

        self._blacklist = ["Ableton Push", "RtMidi", "Through"]

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
        """
        Version répliquée du comportement original :
        - filtre Push2, RtMidi, Through
        - ouvre le port demandé
        - attache un callback synthétique (à définir plus tard)
        """
        available = [
            n for n in mido.get_input_names()
            if 'Ableton Push' not in n
            and 'RtMidi' not in n
            and 'Through' not in n
        ]

        if name is not None:
            try:
                full_name = [n for n in available if name in n][0]
            except IndexError:
                full_name = None

            if full_name is not None:
                if name in self.midi_in_ports:
                    try:
                        self.midi_in_ports[name].callback = None
                    except:
                        pass

                try:
                    port = mido.open_input(full_name)
                    port.callback = self._generic_midi_in_callback
                    self.midi_in_ports[name] = port
                    print(f'Receiving MIDI IN from "{full_name}"')
                except IOError:
                    print(f'Could not open MIDI input "{full_name}"')
                    print("Available filtered inputs:")
                    for n in available:
                        print(f" - {n}")

            else:
                print(f'No available input port for "{name}"')

        else:
            if name in self.midi_in_ports:
                try:
                    self.midi_in_ports[name].callback = None
                    self.midi_in_ports[name].close()
                except:
                    pass
                del self.midi_in_ports[name]

        return self.midi_in_ports.get(name, None)



    def open_out_port(self, name):
        """
        Version répliquée du comportement original :
        - filtre Push2, RtMidi, Through
        - ouvre le port demandé
        - gère 'Virtual'
        """

        # Filtrage comme l'ancien code
        available = [
            n for n in mido.get_output_names()
            if 'Ableton Push' not in n
            and 'RtMidi' not in n
            and 'Through' not in n
        ]
        # Ajout exact comme ton ancien init_midi_out
        available += ['Virtual']

        if name is not None:
            # Recherche du port complet
            try:
                full_name = [n for n in available if name in n][0]
            except IndexError:
                full_name = None

            if full_name is not None:

                # Fermer ancien OUT si existant
                if name in self.midi_out_ports:
                    try:
                        self.midi_out_ports[name].close()
                    except:
                        pass

                # Tentative d’ouverture
                try:
                    if full_name == 'Virtual':
                        port = mido.open_output(full_name, virtual=True)
                    else:
                        port = mido.open_output(full_name)

                    self.midi_out_ports[name] = port
                    print(f'Will send MIDI OUT to "{full_name}"')

                except IOError:
                    print(f'Could not open MIDI output "{full_name}"')
                    print("Available filtered outputs:")
                    for n in available:
                        print(f" - {n}")

            else:
                print(f'No available output port for "{name}"')

        else:
            # Fermeture si None
            if name in self.midi_out_ports:
                try:
                    self.midi_out_ports[name].close()
                except:
                    pass
                del self.midi_out_ports[name]

        return self.midi_out_ports.get(name, None)



    def _generic_midi_in_callback(self, msg):
        if self.incoming_midi_callback is not None:
            self.incoming_midi_callback(msg)



    def assign_instrument_ports(self, instrument_name, in_name, out_name):
        """Associe un synthé avec ses ports Mido."""
        if instrument_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instrument_name] = {"in": None, "out": None}

        # --- PHASE IN : ouverture du port IN ---
        if in_name is not None:
            in_port = self.open_in_port(in_name)
            if in_port is not None:
                self.instrument_midi_ports[instrument_name]["in"] = in_port
            else:
                print(f'Warning: IN port "{in_name}" not assigned for {instrument_name}')

        # --- PHASE OUT (déjà ajouté précédemment, on ne touche pas) ---
        if out_name is not None:
            out_port = self.open_out_port(out_name)
            if out_port is not None:
                self.instrument_midi_ports[instrument_name]["out"] = out_port
            else:
                print(f'Warning: OUT port "{out_name}" not assigned for {instrument_name}')


    # -----------------------------------------------------------
    # ### BLOCK-SEND GENERIC ###
    # -----------------------------------------------------------
    def send(self, msg, instrument_name=None):
        """
        Envoie un message MIDI :
        - soit vers un instrument (si instrument_name)
        - soit global (si None)
        """

        if instrument_name is not None:
            out_port = self.instrument_midi_ports.get(instrument_name, {}).get("out", None)
            if out_port is not None:
                try:
                    out_port.send(msg)
                except Exception as e:
                    print(f"Error sending MIDI to {instrument_name}: {e}")
            else:
                print(f"No OUT port for instrument '{instrument_name}'")
            return

        # Sinon : broadcast
        for name, port in self.midi_out_ports.items():
            try:
                port.send(msg)
            except Exception as e:
                print(f"Error sending MIDI on port '{name}': {e}")


    # -----------------------------------------------------------
    # ### BLOCK-SEND SHORTCUTS ###
    # -----------------------------------------------------------
    def send_note_on(self, instrument_name, note, velocity=100):
        msg = mido.Message('note_on', note=note, velocity=velocity)
        self.send(msg, instrument_name)

    def send_note_off(self, instrument_name, note):
        msg = mido.Message('note_off', note=note)
        self.send(msg, instrument_name)

    def send_cc(self, instrument_name, cc, value):
        msg = mido.Message('control_change', control=cc, value=value)
        self.send(msg, instrument_name)

    def send_program_change(self, instrument_name, program):
        msg = mido.Message('program_change', program=program)
        self.send(msg, instrument_name)


    # -----------------------------------------------------------
    # ### BLOCK-ERROR & DIAGNOSTICS ###
    # -----------------------------------------------------------
    def port_exists(self, name):
        return (name in mido.get_input_names()) or (name in mido.get_output_names())


    def debug_print_ports(self):
        print("=== Synths_Midi INPUT PORTS ===")
        for name, port in self.midi_in_ports.items():
            print(f"IN: {name} -> {port}")

        print("=== Synths_Midi OUTPUT PORTS ===")
        for name, port in self.midi_out_ports.items():
            print(f"OUT: {name} -> {port}")

