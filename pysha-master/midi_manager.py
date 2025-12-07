# midi_manager.py

import mido
import push2_python
import definitions
import rtmidi     
import threading
import time

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
        self.app = None
        # stockage des ports MIDI ouvert
        self.midi_in_ports = {}
        self.midi_out_ports = {}

        # mapping instrument -> ports
        self.instrument_midi_ports = {}

        # clock interne
        self.clock_tick_callback = None  # ex: sequencer_controller.tick_from_clock_thread
        self._clock_running = False
        self._clock_thread = None
        self._bpm_provider = None  # fonction qui renvoie le BPM courant

        # --- Ports déjà ouverts pour éviter les doubles ouvertures ---
        self.open_output_ports = {}   # clé = nom du port → instance mido
        self.open_input_ports = {}    # clé = nom du port → instance mido

        
        # pour appeler les ports
        self.incoming_midi_callback = None

        self._blacklist = ["Ableton Push", "RtMidi", "Through"]

        # ---------------------------------------------------
        # ### CLOCK STATE (interne maître) ###
        # ---------------------------------------------------
        self.bpm = 120.0
        self.clock_factor = 1.0          # x0.5, x1, x2, etc. pour le séquenceur
        self._clock_thread = None
        self._clock_thread_running = False
        self._clock_out_ports = set()    # noms logiques (les mêmes que pour open_out_port)
        self._seq_tick_accumulator = 0.0

        # callback optionnelle appelée à chaque tick séquenceur
        # (à raccorder depuis l'app : ex. app.sequencer_controller.tick_from_clock_thread)
        self.clock_tick_callback = None


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

                # --- Vérifier si ce port système est déjà ouvert sous un autre alias ---
                for alias, existing_port in self.midi_out_ports.items():
                    if hasattr(existing_port, "name") and existing_port.name == full_name:
                        # On réutilise ce port déjà ouvert
                        self.midi_out_ports[name] = existing_port
                        print(f'[MIDI] Reusing already open OUT port "{full_name}" for alias "{name}" (alias original: "{alias}")')
                        return existing_port

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
        """
        Attribue les ports MIDI IN et OUT à un instrument donné.
        - in_name et out_name sont des noms de ports (str) ou "".
        - Cette fonction ouvre/ferme les ports si nécessaire.
        - Elle met toujours à jour self.instrument_midi_ports[instr].
        """

        # S'assurer que l'entrée existe dans le dictionnaire
        if instrument_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instrument_name] = {"in": None, "out": None}

        # -- FERME ANCIENS PORTS IN/OUT SI NÉCESSAIRE --
        old_in = self.instrument_midi_ports[instrument_name].get("in")
        old_out = self.instrument_midi_ports[instrument_name].get("out")

        # ⚠ IMPORTANT :
        # On NE FERME PLUS old_in / old_out ici.
        # Sinon, on peut fermer un port pendant qu'un autre thread (le séquenceur)
        # est en train de faire .send(), ce qui peut faire planter RtMidi.
        #
        # La gestion de la fermeture reste à la charge du code de plus haut niveau
        # (ou éventuellement d'une future passe de nettoyage), mais ici on privilégie
        # la stabilité pendant que le séquenceur tourne.

        # Si les noms demandés correspondent déjà aux ports actuels, on ne fait rien
        same_in = (
            in_name
            and old_in
            and hasattr(old_in, "name")
            and old_in.name == in_name
        )
        same_out = (
            out_name
            and old_out
            and hasattr(old_out, "name")
            and old_out.name == out_name
        )

        if (in_name is None or in_name == "" or same_in) and (out_name is None or out_name == "" or same_out):
            print(f"[Synths_Midi] Ports already set for {instrument_name}, nothing to change.")
            return

        # -- CALCUL NOUVEAUX PORTS --
        # Si le nom est vide ou None → pas de port
        new_in_port = None
        new_out_port = None

        # OUVERTURE PORT IN
        if in_name and isinstance(in_name, str) and in_name.strip() != "":
            try:
                new_in_port = self.open_in_port(in_name)
            except Exception as e:
                print(f"[Synths_Midi] Could not open IN port '{in_name}' for {instrument_name}: {e}")
                new_in_port = None

        # OUVERTURE PORT OUT
        if out_name and isinstance(out_name, str) and out_name.strip() != "":
            try:
                new_out_port = self.open_out_port(out_name)
            except Exception as e:
                print(f"[Synths_Midi] Could not open OUT port '{out_name}' for {instrument_name}: {e}")
                new_out_port = None

        # -- STOCKAGE TOUJOURS MIS À JOUR --
        self.instrument_midi_ports[instrument_name]["in"] = new_in_port
        self.instrument_midi_ports[instrument_name]["out"] = new_out_port

        print(f"[Synths_Midi] Ports set for {instrument_name}: IN={in_name}, OUT={out_name}")





    # -----------------------------------------------------------
    # ### BLOCK-ROUTING SHORTCUTS ###
    # -----------------------------------------------------------

    def send(self, msg, instrument_name=None):
        """
        Envoi MIDI unifié :
        - instrument_name = None -> rien
        - instrument_name = "DDRM" -> mono-cible
        - instrument_name = ["DDRM", "PRO800"] -> multi-cible
        """

        # --- Normalisation en liste ---
        if instrument_name is None:
            return  # pas de port global

        if isinstance(instrument_name, str):
            targets = [instrument_name]
        else:
            # liste / set / tuple
            try:
                targets = list(instrument_name)
            except TypeError:
                return

        # --- Pour chaque instrument cible ---
        for instr in targets:
            ports = self.instrument_midi_ports.get(instr)
            if not ports:
                print(f"[MIDI] No ports configured for '{instr}'")
                continue

            out_port = ports.get("out")
            if not out_port:
                print(f"[MIDI] No OUT port for '{instr}'")
                continue

            try:
                out_port.send(msg)
            except Exception as e:
                print(f"[MIDI] Failed to send {msg} to {instr}: {e}")


    def send_note_on(self, instrument_name, note, velocity=100):
        self.send(mido.Message("note_on", note=note, velocity=velocity), instrument_name)

    def send_note_off(self, instrument_name, note, velocity=0):
        self.send(mido.Message("note_off", note=note, velocity=velocity), instrument_name)

    def send_cc(self, instrument_name, cc, value):
        self.send(mido.Message("control_change", control=cc, value=value), instrument_name)

    def send_program_change(self, instrument_name, program):
        self.send(mido.Message("program_change", program=program), instrument_name)

    def send_aftertouch(self, instrument_name, value):
        self.send(mido.Message("aftertouch", value=value), instrument_name)

    def send_pitchbend(self, instrument_name, value):
        self.send(mido.Message("pitchwheel", pitch=value), instrument_name)


    # --------------------------
    # MIDI Clock global
    # --------------------------

    def _normalize(self, name):
        if not name:
            return ""
        return name.strip().lower()

    def _should_skip_start_stop(self, instr, msg):
        """
        Empêche Start/Stop d'être envoyé à l'instrument utilisé par le sequencer.
        """
        # On n'exclut que START et STOP
        if msg.type not in ("start", "stop"):
            return False

        # Récupérer l'instrument utilisé par le sequencer
        seq_instr = getattr(self.app.sequencer_window, "sequencer_output_instrument", None)

        # Comparaison sécurisée
        if self._normalize(instr) == self._normalize(seq_instr):
            return True

        return False


    def _send_clock_message_to_outputs(self, msg):
        """
        Envoie Clock / Start / Stop à tous les instruments ayant un OUT ouvert.
        ⚠️ Start/Stop ne sont PAS envoyés à l'instrument utilisé par le séquenceur.
        """

        # Récupérer l'instrument utilisé par le séquenceur
        seq_instr = None
        try:
            if hasattr(self.app, "sequencer_window"):
                seq_instr = getattr(self.app.sequencer_window, "sequencer_output_instrument", None)
        except Exception:
            seq_instr = None

        # Normalisation pour comparaison
        def norm(x):
            if not x:
                return ""
            return str(x).strip().lower()

        seq_norm = norm(seq_instr)

        for instr, ports in self.instrument_midi_ports.items():
            outp = ports.get("out")
            if outp is None:
                continue

            # Block START/STOP pour l'instrument du séquenceur
            if msg.type in ("start", "stop") and norm(instr) == seq_norm:
                # Debug (facultatif)
                # print(f"[CLOCK] Skipping {msg.type} for sequencer instrument {instr}")
                continue

            # Envoi du message
            try:
                outp.send(msg)
            except Exception as e:
                print(f"[CLOCK] Could not send {msg.type} to {instr}: {e}")



    def start_clock(self):
        """Démarre la clock interne."""
        print("[CLOCK] start_clock() called")

        if self._clock_thread is None or not self._clock_thread_running:
            self._clock_thread_running = True
            self._clock_thread = threading.Thread(
                target=self._clock_thread_loop,
                daemon=True
            )
            self._clock_thread.start()

        # Optionnel : message START pour les synthés
        try:
            start_msg = mido.Message("start")
            self._send_clock_message_to_outputs(start_msg)
        except Exception:
            pass

    def _clock_thread_loop(self):
        """
        Boucle interne :
        - envoie la clock MIDI (24ppqn) vers les sorties activées
        - notifie le séquenceur via clock_tick_callback
        """
        print("[CLOCK] clock thread started")
        next_tick_time = time.perf_counter()

        while self._clock_thread_running:
            # Intervalle entre deux ticks MIDI
            seconds_per_quarter = 60.0 / float(self.bpm)
            tick_interval = seconds_per_quarter / 24.0

            now = time.perf_counter()
            if now >= next_tick_time:
                next_tick_time += tick_interval

                # 1) envoyer clock (0xF8)
                try:
                    clk_msg = mido.Message("clock")
                    self._send_clock_message_to_outputs(clk_msg)
                except Exception:
                    pass

                # 2) notifier séquenceur
                if self.clock_tick_callback is not None:
                    try:
                        self.clock_tick_callback()
                    except Exception:
                        pass

            time.sleep(0.0005)

        print("[CLOCK] clock thread stopped")

    def stop_clock(self):
        """Stoppe la clock interne."""
        print("[CLOCK] stop_clock() called")
        self._clock_thread_running = False

        # Optionnel : message STOP pour les synthés
        try:
            stop_msg = mido.Message("stop")
            self._send_clock_message_to_outputs(stop_msg)
        except Exception:
            pass

