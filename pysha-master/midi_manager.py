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
        # stockage des ports MIDI ouvert
        self.midi_in_ports = {}
        self.midi_out_ports = {}

        # mapping instrument -> ports
        self.instrument_midi_ports = {}


        
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
        Associe un synthé avec ses ports Mido.
        - instrument_name : nom logique (ex: "PRO800")
        - in_name / out_name : fragments de nom de port (comme avant)
        """
        in_port = None
        out_port = None

        if in_name:
            in_port = self.open_in_port(in_name)

        if out_name:
            out_port = self.open_out_port(out_name)

        self.instrument_midi_ports[instrument_name] = {
            "in": in_port,
            "out": out_port,
        }


    # -----------------------------------------------------------
    # ### BLOCK-SEND GENERIC ###
    # -----------------------------------------------------------
    def send(self, msg, instrument_name=None):
        """
        Envoie un message MIDI :
        - instrument_name = None      -> pas de routage spécifique (à définir plus tard)
        - instrument_name = "PRO800"  -> envoi vers cet instrument
        - instrument_name = ["PRO800", "MINITAUR"] -> multi-cible
        """

        # Normaliser instrument_name en liste de cibles
        if instrument_name is None:
            targets = []
        elif isinstance(instrument_name, str):
            targets = [instrument_name]
        else:
            # liste / tuple / set ou autre itérable
            try:
                targets = list(instrument_name)
            except TypeError:
                targets = []

        # Si pas de cible explicite, pour l’instant on ne fait rien
        # (le comportement "instrument sélectionné" sera géré plus tard par l’appelant)
        if not targets:
            return

        for instr in targets:
            ports = self.instrument_midi_ports.get(instr, None)
            if not ports:
                print(f'[Synths_Midi] No ports configured for instrument "{instr}"')
                continue

            out_port = ports.get("out", None)
            if out_port is None:
                print(f'[Synths_Midi] No OUT port for instrument "{instr}"')
                continue

            try:
                out_port.send(msg)
            except Exception as e:
                print(f'[Synths_Midi] Error sending to "{instr}": {e}')


    # -----------------------------------------------------------
    # ### BLOCK-ROUTING SHORTCUTS ###
    # -----------------------------------------------------------

    def send(self, msg, instrument_name=None):
        """
        Envoi générique d'un message MIDI :
        - instrument_name : str = nom court (PRO800, MINITAUR, etc.)
        - si None → rien n'est envoyé (pas de port global)
        """
        if instrument_name is None:
            return  # pas de fallback global dans ta nouvelle architecture

        ports = self.instrument_midi_ports.get(instrument_name)
        if not ports:
            return

        out_port = ports.get("out")
        if not out_port:
            return

        try:
            out_port.send(msg)
        except Exception:
            print(f"[MIDI] Failed to send {msg} to {instrument_name}")

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



    # -----------------------------------------------------------
    # ### BLOCK-CLOCK ###
    # -----------------------------------------------------------

    def set_bpm(self, bpm):
        """Définit le tempo interne du moteur de clock."""
        try:
            bpm = float(bpm)
        except (TypeError, ValueError):
            return
        if bpm < 20.0:
            bpm = 20.0
        elif bpm > 300.0:
            bpm = 300.0
        self.bpm = bpm

    def set_clock_multiplier(self, factor):
        """
        Définit un multiplicateur interne pour le séquenceur.
        La clock MIDI reste à 24ppqn, seule la fréquence des ticks
        du séquenceur est affectée.

        Exemples :
        - 0.5 => séquenceur deux fois plus lent
        - 1.0 => normal
        - 2.0 => séquenceur deux fois plus rapide
        """
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return
        if factor <= 0:
            factor = 1.0
        self.clock_factor = factor

    def start_clock(self):
        """
        Démarre la clock interne :
        - lance le thread si nécessaire
        - envoie un message MIDI START aux sorties clock activées
        (le reset du séquenceur doit être géré par l'app)
        """
        if self._clock_thread_running:
            return

        self._clock_thread_running = True
        self._seq_tick_accumulator = 0.0

        # Thread clock
        self._clock_thread = threading.Thread(
            target=self._clock_thread_loop,
            daemon=True
        )
        self._clock_thread.start()

        # MIDI START
        start_msg = mido.Message('start')
        self._send_clock_message_to_outputs(start_msg)

    def stop_clock(self):
        """
        Arrête la clock interne :
        - stoppe le thread
        - envoie un message MIDI STOP
        """
        if not self._clock_thread_running:
            return

        self._clock_thread_running = False
        # on ne join pas forcément (daemon=True), pour ne pas bloquer l'UI

        stop_msg = mido.Message('stop')
        self._send_clock_message_to_outputs(stop_msg)

    def continue_clock(self):
        """
        Continue la clock interne sans reset :
        - relance le thread si nécessaire
        - envoie MIDI CONTINUE
        """
        if not self._clock_thread_running:
            self._clock_thread_running = True
            self._clock_thread = threading.Thread(
                target=self._clock_thread_loop,
                daemon=True
            )
            self._clock_thread.start()

        cont_msg = mido.Message('continue')
        self._send_clock_message_to_outputs(cont_msg)

    def enable_clock_output(self, port_name):
        """
        Autorise l'envoi de la clock vers un OUT.
        Si le port n'est pas encore ouvert, on essaie de l'ouvrir.
        """
        if port_name not in self.midi_out_ports:
            out_port = self.open_out_port(port_name)
            if out_port is None:
                print(f'Clock: could not enable clock on OUT "{port_name}"')
                return
        self._clock_out_ports.add(port_name)

    def disable_clock_output(self, port_name):
        """Désactive l'envoi de la clock vers ce port."""
        if port_name in self._clock_out_ports:
            self._clock_out_ports.remove(port_name)

    def _clock_thread_loop(self):
        """
        Boucle interne :
        - envoie la clock MIDI (24ppqn) vers les sorties activées
        - notifie le séquenceur via clock_tick_callback
        - applique clock_factor uniquement pour le séquenceur
        """
        # On utilise perf_counter pour minimiser la dérive
        next_tick_time = time.perf_counter()

        while self._clock_thread_running:
            # Intervalle entre deux ticks MIDI (24 ppqn)
            seconds_per_quarter = 60.0 / self.bpm
            tick_interval = seconds_per_quarter / 24.0

            now = time.perf_counter()
            if now >= next_tick_time:
                next_tick_time += tick_interval

                # 1) envoyer un tick MIDI clock (0xF8)
                clk_msg = mido.Message('clock')
                self._send_clock_message_to_outputs(clk_msg)

                # 2) notifier le séquenceur avec un facteur
                self._notify_sequencer_tick()

            # petit sleep pour éviter de monopoliser le CPU
            time.sleep(0.0005)

    def _send_clock_message_to_outputs(self, msg):
        """
        Envoie un message de type clock/start/stop/continue
        uniquement sur les ports OUT définis dans _clock_out_ports.
        """
        for name in list(self._clock_out_ports):
            port = self.midi_out_ports.get(name, None)
            if port is None:
                continue
            try:
                port.send(msg)
            except Exception as e:
                print(f'Clock: error sending on "{name}": {e}')

    def _notify_sequencer_tick(self):
        """
        Notifie le séquenceur, en appliquant clock_factor.
        - La clock MIDI reste à 24ppqn
        - clock_factor ajuste la fréquence des ticks du séquenceur
        """
        if self.clock_tick_callback is None:
            return

        # on accumule les ticks MIDI avec un facteur
        self._seq_tick_accumulator += self.clock_factor

        # dès que l'accumulateur dépasse 1.0, on envoie un tick séquenceur
        while self._seq_tick_accumulator >= 1.0:
            self._seq_tick_accumulator -= 1.0
            try:
                self.clock_tick_callback()
            except Exception:
                # ne jamais faire crasher le thread clock
                pass
