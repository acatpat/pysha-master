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
        self.push = push_device

    # -----------------------------------------------------------
    # ### BLOCK-PADS ###
    # -----------------------------------------------------------
    def set_pad_color(self, pad_ij, color):
        pass

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
        pass

    def display_text(self, *args, **kwargs):
        pass

    # -----------------------------------------------------------
    # ### BLOCK-SYSTEM ###
    # -----------------------------------------------------------
    def reconnect(self):
        pass

    def is_connected(self):
        pass



# =====================================================================
#  ████  SYNTHS_MIDI  ████
#  Gère TOUT le midi sauf Push2
#  Ports, synthés, Pyramid, routing, clock
# =====================================================================

class Synths_Midi:
    def __init__(self):
        self.app = None

        # stockage ports mido ouverts
        self.midi_in_ports = {}
        self.midi_out_ports = {}

        # À mettre dans __init__ si pas déjà fait :
        self._opened_in_ports = {}
        self._opened_out_ports = {}

        # mapping instrument -> ports mido
        self.instrument_midi_ports = {}
        # Noms de ports déclarés par l’utilisateur (UI ou preset)
        self.instrument_port_names = {}

        self._in_listeners = []  # liste de callbacks multiples


        # callback clock → sequencer
        self.clock_tick_callback = None

        # clock state
        self._bpm_provider = None
        self._clock_thread = None
        self._clock_thread_running = False
        self._await_first_tick = False

        self.bpm = 120.0
        self.clock_factor = 1.0

        self.incoming_midi_callback = None

        self._blacklist = ["Ableton Push", "RtMidi", "Through"]


    # -----------------------------------------------------------
    # ### BLOCK-PORTS ###
    # -----------------------------------------------------------
    def scan_available_ports(self):
        return {
            "in": mido.get_input_names(),
            "out": mido.get_output_names()
        }


    # -----------------------------------------------------------
    #  PORT CACHE GLOBAL  (PARTAGE A)
    # -----------------------------------------------------------

    # À mettre dans __init__ si pas déjà fait :
    # self._opened_in_ports = {}
    # self._opened_out_ports = {}

    def open_in_port(self, port_name):
        """
        Ouvre réellement un port MIDI IN seulement une fois
        et l'enregistre avec un callback unique qui renvoie
        tout vers app.midi_in_router(msg, port_name).

        - Même port partagé par plusieurs instruments = OK
          (un seul callback niveau MIDO, dispatch côté app).
        """
        if not port_name:
            return None

        # 1) Déjà ouvert → réutiliser
        if port_name in self._opened_in_ports:
            print(f"[MIDI] Reusing already open IN port '{port_name}'")
            return self._opened_in_ports[port_name]

        # 2) Ouverture réelle
        try:
            p = mido.open_input(port_name)
            print(f"[MIDI] Opening IN port '{port_name}'")
        except Exception as e:
            print(f"[MIDI] ERROR opening IN '{port_name}': {e}")
            return None

        # 3) Cache interne
        self._opened_in_ports[port_name] = p

        # 4) Référence dans midi_in_ports (utilisée par midi_in_router)
        self.midi_in_ports[port_name] = p

        # 5) Callback unique → route vers app.midi_in_router
        if self.app is not None:
            def _cb(msg, name=port_name):
                try:
                    # Nouveau système : routeur côté app
                    if hasattr(self.app, "midi_in_router"):
                        self.app.midi_in_router(msg, name)
                    # Old fallback si jamais tu réutilises incoming_midi_callback ailleurs
                    elif self.incoming_midi_callback:
                        self.incoming_midi_callback(msg)
                except Exception:
                    pass

            p.callback = _cb

        return p


    def open_out_port(self, port_name):
        """
        Ouvre réellement un port MIDI OUT seulement une fois.
        Retourne toujours la même instance si déjà ouverte.
        """
        # 1) Déjà ouvert → réutiliser
        if port_name in self._opened_out_ports:
            print(f"[MIDI] Reusing already open OUT port '{port_name}'")
            return self._opened_out_ports[port_name]

        # 2) Sinon ouvrir pour de vrai
        try:
            p = mido.open_output(port_name)
            self._opened_out_ports[port_name] = p
            print(f"[MIDI] Opening OUT port '{port_name}'")
            return p
        except Exception as e:
            print(f"[MIDI] ERROR opening OUT '{port_name}': {e}")
            return None


    def _generic_midi_in_callback(self, msg):
        if self.incoming_midi_callback:
            self.incoming_midi_callback(msg)


    def _input_dispatcher(self, msg):
        for cb in list(self._in_listeners):
            try:
                cb(msg)
            except Exception:
                pass


    # -----------------------------------------------------------
    # ### ASSIGNATION PORTS PAR INSTRUMENT ###
    # -----------------------------------------------------------

    def get_instrument_out_port(self, instrument_name):
        if instrument_name in self.instrument_port_names:
            return self.instrument_port_names[instrument_name].get("out")
        return None

    def get_instrument_in_port(self, instrument_name):
        if instrument_name in self.instrument_port_names:
            return self.instrument_port_names[instrument_name].get("in")
        return None

    def set_instrument_out_port(self, instrument_name, port_name):
        if instrument_name not in self.instrument_port_names:
            self.instrument_port_names[instrument_name] = {"in": None, "out": None}
        self.instrument_port_names[instrument_name]["out"] = port_name

    def set_instrument_in_port(self, instrument_name, port_name):
        if instrument_name not in self.instrument_port_names:
            self.instrument_port_names[instrument_name] = {"in": None, "out": None}
        self.instrument_port_names[instrument_name]["in"] = port_name


    def assign_instrument_ports(self, instrument_name, in_name, out_name):
        if instrument_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instrument_name] = {"in": None, "out": None}

        old_in = self.instrument_midi_ports[instrument_name].get("in")
        old_out = self.instrument_midi_ports[instrument_name].get("out")

        same_in = (
            in_name and old_in and hasattr(old_in, "name") and old_in.name == in_name
        )
        same_out = (
            out_name and old_out and hasattr(old_out, "name") and old_out.name == out_name
        )

        if (in_name in (None, "") or same_in) and (out_name in (None, "") or same_out):
            print(f"[Synths_Midi] Existing entries for {instrument_name}, reopening ports.")
            # Pas de return ici → on laisse continuer l'ouverture

        new_in_port = None
        new_out_port = None

        if in_name and isinstance(in_name, str) and in_name.strip():
            try:
                new_in_port = self.open_in_port(in_name)
            except Exception as e:
                print(f"[Synths_Midi] Could not open IN port '{in_name}' for {instrument_name}: {e}")

        if out_name and isinstance(out_name, str) and out_name.strip():
            try:
                new_out_port = self.open_out_port(out_name)
            except Exception as e:
                print(f"[Synths_Midi] Could not open OUT port '{out_name}' for {instrument_name}: {e}")

        self.instrument_midi_ports[instrument_name]["in"] = new_in_port
        self.instrument_midi_ports[instrument_name]["out"] = new_out_port

        # --- IMPORTANT ---
        # Garder instrument_port_names synchronisé (même structure que celle utilisée par l'UI)
        self.instrument_port_names[instrument_name] = {
            "in": in_name,
            "out": out_name
        }


        print(f"[Synths_Midi] Ports set for {instrument_name}: IN={in_name}, OUT={out_name}")


    # -----------------------------------------------------------
    # ### ROUTING MIDI ###
    # -----------------------------------------------------------
    def send(self, msg, instrument_name=None):
        if instrument_name is None:
            return

        if isinstance(instrument_name, str):
            targets = [instrument_name]
        else:
            try:
                targets = list(instrument_name)
            except:
                return

        for instr in targets:
            ports = self.instrument_midi_ports.get(instr)
            if not ports:
                print(f"[MIDI] No ports configured for '{instr}'")
                continue

            outp = ports.get("out")
            if not outp:
                print(f"[MIDI] No OUT port for '{instr}'")
                continue

            try:
                outp.send(msg)
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



    # -----------------------------------------------------------
    # ### CLOCK / START / STOP ###
    # -----------------------------------------------------------
    def _normalize(self, name):
        return "" if not name else str(name).strip().lower()


    def _should_skip_start_stop(self, instr, msg):
        if msg.type not in ("start", "stop"):
            return False

        seq_instr = None
        try:
            seq_instr = getattr(self.app.sequencer_window, "sequencer_output_instrument", None)
        except:
            pass

        return self._normalize(instr) == self._normalize(seq_instr)


    def _send_clock_message_to_outputs(self, msg):
        seq_instr = (
            getattr(self.app.sequencer_window, "sequencer_output_instrument", None)
            if hasattr(self.app, "sequencer_window")
            else None
        )
        seq_norm = self._normalize(seq_instr)

        for instr, ports in self.instrument_midi_ports.items():
            outp = ports.get("out")
            if outp is None:
                continue

            # skip start/stop for sequencer instrument
            if msg.type in ("start", "stop") and self._normalize(instr) == seq_norm:
                continue

            # PRO-800 double start
            if msg.type == "start":
                try:
                    port_name = getattr(outp, "name", "").lower()
                    if "pro 800" in port_name or "pro800" in port_name or "pro-800" in port_name:
                        outp.send(msg)
                        time.sleep(0.012)
                        outp.send(msg)
                        time.sleep(0.002)
                        continue
                except Exception as e:
                    print(f"[CLOCK] PRO-800 double-start failed: {e}")
                    continue

            # normal send
            try:
                outp.send(msg)
            except Exception as e:
                print(f"[CLOCK] Could not send {msg.type} to {instr}: {e}")


    # -----------------------------------------------------------
    # CLOCK THREAD
    # -----------------------------------------------------------
    def start_clock(self):
        print("[CLOCK] start_clock() called")

        # reset sequencer to -1 so first step is 0
        try:
            if hasattr(self.app, "sequencer_controller"):
                self.app.sequencer_controller.current_step = -1
            if hasattr(self.app, "sequencer_window"):
                self.app.sequencer_window.current_step = -1
            print("[CLOCK] Sequencer current_step reset to -1 before START")
        except:
            pass

        # request START at first tick
        self._await_first_tick = True

        # start thread
        if self._clock_thread is None or not self._clock_thread_running:
            self._clock_thread_running = True
            self._clock_thread = threading.Thread(
                target=self._clock_thread_loop,
                daemon=True
            )
            self._clock_thread.start()


    def _clock_thread_loop(self):
        print("[CLOCK] clock thread started")
        next_tick_time = time.perf_counter()

        while self._clock_thread_running:
            bpm = float(self.bpm)
            if self._bpm_provider:
                try:
                    bpm = float(self._bpm_provider())
                except:
                    pass

            seconds_per_quarter = 60.0 / bpm
            tick_interval = (seconds_per_quarter / 24.0) / max(self.clock_factor, 0.0001)

            now = time.perf_counter()
            if now >= next_tick_time:
                next_tick_time += tick_interval

                # FIRST TICK → send start
                if self._await_first_tick:
                    self._await_first_tick = False
                    try:
                        start_msg = mido.Message("start")
                        self._send_clock_message_to_outputs(start_msg)
                        print("[CLOCK] START sent")
                    except Exception as e:
                        print("[CLOCK] Could not send START on first tick:", e)

                # CLOCK tick
                try:
                    clk = mido.Message("clock")
                    self._send_clock_message_to_outputs(clk)
                except:
                    pass

                # notify sequencer
                if self.clock_tick_callback:
                    try:
                        self.clock_tick_callback()
                    except:
                        pass

            time.sleep(0.0005)

        print("[CLOCK] clock thread stopped")


    def stop_clock(self):
        print("[CLOCK] stop_clock() called")
        self._clock_thread_running = False

        # reset sequencer again
        try:
            if hasattr(self.app, "sequencer_controller"):
                self.app.sequencer_controller.current_step = -1
            if hasattr(self.app, "sequencer_window"):
                self.app.sequencer_window.current_step = -1
            print("[CLOCK] Sequencer current_step reset to -1 after STOP")
        except:
            pass

        # send STOP
        try:
            stop_msg = mido.Message("stop")
            self._send_clock_message_to_outputs(stop_msg)
        except:
            pass
