import definitions
import mido
import push2_python
import math
import json
import os
import time

from definitions import PyshaMode, OFF_BTN_COLOR
from display_utils import show_text


class MIDICCControl(object):
    color = definitions.GRAY_LIGHT
    color_rgb = None
    name = 'Unknown'
    section = 'unknown'
    cc_number = 10  # 0-127
    value = 64
    vmin = 0
    vmax = 127
    get_color_func = None
    send_midi_func = None
    value_labels_map = {}

    def __init__(self, cc_number, name, section_name, get_color_func, send_midi_func):
        self.cc_number = cc_number
        self.name = name
        self.section = section_name
        self.get_color_func = get_color_func
        self.send_midi_func = send_midi_func

    def draw(self, ctx, x_part):
        margin_top = 25
        name_height = 20
        show_text(ctx, x_part, margin_top, self.name, height=name_height, font_color=definitions.WHITE)

        val_height = 30
        color = self.get_color_func()
        show_text(ctx, x_part, margin_top + name_height,
                  self.value_labels_map.get(str(self.value), str(self.value)), height=val_height, font_color=color)

        ctx.save()
        circle_break_degrees = 80
        height = 55
        radius = height / 2
        display_w = push2_python.constants.DISPLAY_LINE_PIXELS
        x = (display_w // 8) * x_part
        y = margin_top + name_height + val_height + radius + 5
        start_rad = (90 + circle_break_degrees // 2) * (math.pi / 180)
        end_rad = (90 - circle_break_degrees // 2) * (math.pi / 180)
        xc = x + radius + 3
        yc = y

        def get_rad_for_value(value):
            total_degrees = 360 - circle_break_degrees
            return start_rad + total_degrees * ((value - self.vmin) / (self.vmax - self.vmin)) * (math.pi / 180)

        ctx.set_source_rgb(0, 0, 0)
        ctx.move_to(xc, yc)
        ctx.stroke()
        ctx.arc(xc, yc, radius, start_rad, end_rad)
        ctx.set_source_rgb(*definitions.get_color_rgb_float(definitions.GRAY_LIGHT))
        ctx.set_line_width(1)
        ctx.stroke()
        ctx.arc(xc, yc, radius, start_rad, get_rad_for_value(self.value))
        ctx.set_source_rgb(*definitions.get_color_rgb_float(color))
        ctx.set_line_width(3)
        ctx.stroke()
        ctx.restore()

    def update_value(self, increment):
        if self.value + increment > self.vmax:
            self.value = self.vmax
        elif self.value + increment < self.vmin:
            self.value = self.vmin
        else:
            self.value += increment

        msg = mido.Message('control_change', control=self.cc_number, value=self.value)
        if self.send_midi_func:
            self.send_midi_func(msg)

class MIDICCMode(PyshaMode):
    midi_cc_button_names = [
        push2_python.constants.BUTTON_UPPER_ROW_1,
        push2_python.constants.BUTTON_UPPER_ROW_2,
        push2_python.constants.BUTTON_UPPER_ROW_3,
        push2_python.constants.BUTTON_UPPER_ROW_4,
        push2_python.constants.BUTTON_UPPER_ROW_5,
        push2_python.constants.BUTTON_UPPER_ROW_6,
        push2_python.constants.BUTTON_UPPER_ROW_7,
        push2_python.constants.BUTTON_UPPER_ROW_8
    ]
    instrument_midi_control_ccs = {}
    active_midi_control_ccs = []
    current_selected_section_and_page = {}

    def initialize(self, settings=None):
        for instrument_short_name in self.get_all_distinct_instrument_short_names_helper():
            try:
                midi_cc = json.load(
                    open(os.path.join(definitions.INSTRUMENT_DEFINITION_FOLDER, f'{instrument_short_name}.json'))
                ).get('midi_cc', None)
            except FileNotFoundError:
                midi_cc = None

            if midi_cc is not None:
                self.instrument_midi_control_ccs[instrument_short_name] = []
                for section in midi_cc:
                    section_name = section['section']
                    for name, cc_number in section['controls']:
                        control = MIDICCControl(
                            cc_number, name, section_name,
                            self.get_current_track_color_helper,
                            self.send_cc_to_current_instrument  # <-- route vers port instrument
                        )
                        if section.get('control_value_label_maps', {}).get(name, False):
                            control.value_labels_map = section['control_value_label_maps'][name]
                        self.instrument_midi_control_ccs[instrument_short_name].append(control)
                print('Loaded {0} MIDI cc mappings for instrument {1}'.format(
                    len(self.instrument_midi_control_ccs[instrument_short_name]), instrument_short_name))
            else:
                # fallback: default CCs
                self.instrument_midi_control_ccs[instrument_short_name] = []
                for i in range(128):
                    section_s = (i // 16) * 16
                    section_e = section_s + 15
                    control = MIDICCControl(
                        i, f'CC {i}', f'{section_s} to {section_e}',
                        self.get_current_track_color_helper,
                        self.send_cc_to_current_instrument
                    )
                    self.instrument_midi_control_ccs[instrument_short_name].append(control)
                print('Loaded default MIDI cc mappings for instrument {0}'.format(instrument_short_name))

        for instrument_short_name in self.instrument_midi_control_ccs:
            self.current_selected_section_and_page[instrument_short_name] = (
                self.instrument_midi_control_ccs[instrument_short_name][0].section, 0)

    def send_cc_to_current_instrument(self, msg: mido.Message):
        # Instrument sélectionné via synth_window ou app
        instrument_name = getattr(self.app, 'current_instrument_definition', None)
        if not instrument_name:
            return

        instrument_ports = self.app.instrument_midi_ports.get(instrument_name, None)
        if instrument_ports is None or instrument_ports.get("out") is None:
            return

        midi_out_port = instrument_ports["out"]

        # Récupérer canal MIDI depuis JSON
        instrument_file = os.path.join(definitions.INSTRUMENT_DEFINITION_FOLDER, f'{instrument_name}.json')
        try:
            with open(instrument_file) as f:
                midi_channel = json.load(f).get('midi_channel', 1)
        except Exception:
            midi_channel = 1

        if hasattr(msg, 'channel'):
            msg = msg.copy(channel=midi_channel - 1)  # Mido 0-indexed

        self.app.synths_midi.send(msg, instrument_name=instrument_name)


    # -----------------------
    # Fonctions helpers existantes
    # -----------------------
    def get_all_distinct_instrument_short_names_helper(self):
        return self.app.track_selection_mode.get_all_distinct_instrument_short_names()

    def get_current_track_color_helper(self):
        return self.app.track_selection_mode.get_current_track_color()

    def get_current_track_instrument_short_name_helper(self):
        return self.app.track_selection_mode.get_current_track_instrument_short_name()

    def get_current_track_midi_cc_sections(self):
        section_names = []
        for control in self.instrument_midi_control_ccs.get(self.get_current_track_instrument_short_name_helper(), []):
            section_name = control.section
            if section_name not in section_names:
                section_names.append(section_name)
        return section_names

    def get_currently_selected_midi_cc_section_and_page(self):
        return self.current_selected_section_and_page[self.get_current_track_instrument_short_name_helper()]

    def get_midi_cc_controls_for_current_track_and_section(self):
        section, _ = self.get_currently_selected_midi_cc_section_and_page()
        return [control for control in self.instrument_midi_control_ccs.get(self.get_current_track_instrument_short_name_helper(), []) if control.section == section]

    def get_midi_cc_controls_for_current_track_section_and_page(self):
        all_section_controls = self.get_midi_cc_controls_for_current_track_and_section()
        _, page = self.get_currently_selected_midi_cc_section_and_page()
        try:
            return all_section_controls[page * 8:(page+1) * 8]
        except IndexError:
            return []

    def update_current_section_page(self, new_section=None, new_page=None):
        current_section, current_page = self.get_currently_selected_midi_cc_section_and_page()
        result = [current_section, current_page]
        if new_section is not None:
            result[0] = new_section
        if new_page is not None:
            result[1] = new_page
        self.current_selected_section_and_page[self.get_current_track_instrument_short_name_helper()] = result
        self.active_midi_control_ccs = self.get_midi_cc_controls_for_current_track_section_and_page()
        self.app.buttons_need_update = True

    def get_should_show_midi_cc_next_prev_pages_for_section(self):
        all_section_controls = self.get_midi_cc_controls_for_current_track_and_section()
        _, page = self.get_currently_selected_midi_cc_section_and_page()
        show_prev = False
        if page > 0:
            show_prev = True
        show_next = False
        if (page + 1) * 8 < len(all_section_controls):
            show_next = True
        return show_prev, show_next

    def new_track_selected(self):
        self.active_midi_control_ccs = self.get_midi_cc_controls_for_current_track_section_and_page()

    def activate(self):
        self.update_buttons()

    def deactivate(self):
        for button_name in self.midi_cc_button_names + [push2_python.constants.BUTTON_PAGE_LEFT, push2_python.constants.BUTTON_PAGE_RIGHT]:
            self.push.buttons.set_button_color(button_name, definitions.BLACK)

    def update_buttons(self):

        n_midi_cc_sections = len(self.get_current_track_midi_cc_sections())
        for count, name in enumerate(self.midi_cc_button_names):
            if count < n_midi_cc_sections:
                self.push.buttons.set_button_color(name, definitions.WHITE)
            else:
                self.push.buttons.set_button_color(name, definitions.BLACK)

        show_prev, show_next = self.get_should_show_midi_cc_next_prev_pages_for_section()
        if show_prev:
            self.push.buttons.set_button_color(push2_python.constants.BUTTON_PAGE_LEFT, definitions.WHITE)
        else:
            self.push.buttons.set_button_color(push2_python.constants.BUTTON_PAGE_LEFT, definitions.BLACK)
        if show_next:
            self.push.buttons.set_button_color(push2_python.constants.BUTTON_PAGE_RIGHT, definitions.WHITE)
        else:
            self.push.buttons.set_button_color(push2_python.constants.BUTTON_PAGE_RIGHT, definitions.BLACK)

    def draw_measure_progress(self, ctx, current_step, total_steps):
        """
        Dessine une barre d’avancement de la mesure.
        Style et structure identiques à _draw_sampler_waveform.
        S’affiche dans la même zone basse que le waveform sampler.
        """
        # Vérification des valeurs
        if total_steps is None or total_steps <= 0:
            return
        if current_step is None:
            return

        # Dimensions écran Push 2
        display_w = push2_python.constants.DISPLAY_LINE_PIXELS
        display_h = push2_python.constants.DISPLAY_N_LINES

        # Même zone horizontale que le waveform : moitié gauche
        x0 = 0
        x1 = display_w // 2
        region_width = max(2, x1 - x0)

        # Zone verticale : exactement la même base que le waveform
        # (top=30, bottom=display_h - 40) -> on place la barre juste AU-DESSOUS
        top = display_h - 40
        height = 6     # barre fine
        y0 = top + 5   # petit décalage pour ne pas toucher le waveform
        y1 = y0 + height

        # Nettoyage de la zone
        ctx.save()
        ctx.set_source_rgb(0.0, 0.0, 0.0)
        ctx.rectangle(x0, y0, region_width, height)
        ctx.fill()

        # Avancement (0..1)
        progress = current_step / float(total_steps)
        progress = max(0.0, min(1.0, progress))
        bar_width = int(region_width * progress)

        # Couleur de la barre (bleu clair)
        r, g, b = definitions.get_color_rgb_float(definitions.BLUE)
        ctx.set_source_rgb(r, g, b)

        # Dessin du segment
        ctx.rectangle(x0, y0, bar_width, height)
        ctx.fill()

        ctx.restore()


    def _draw_sampler_waveform(self, ctx, note):
        """
        Dessine l'onde du sample 'note' sur les 4 premiers x_part (0–3),
        en jaune sur fond noir, avec :
          - trim_start / trim_end sous forme de barres verticales
          - ce qui est avant START et après END aplati (ligne au centre)
          - attack / release qui déforment le dessin à partir de START/END
        """
        sampler = getattr(self.app, "sampler", None)
        if sampler is None:
            return

        # Récupérer le Sample correspondant à la note
        sample = sampler.samples.get(note)
        if sample is None:
            return

        data = sample.data
        if data is None or data.shape[0] < 2:
            return

        # Mono : on prend le premier canal
        mono = data[:, 0]
        n_frames = mono.shape[0]
        if n_frames < 2:
            return

        # Dimensions de l'écran Push 2
        display_w = push2_python.constants.DISPLAY_LINE_PIXELS
        display_h = push2_python.constants.DISPLAY_N_LINES

        # Zone d'affichage : x_part 0–3 => moitié gauche de l'écran
        x0 = 0
        x1 = display_w // 2
        region_width = max(2, x1 - x0)

        # Zone verticale (sous les titres, au-dessus du bas)
        top = 30
        bottom = display_h - 40
        height = bottom - top
        if height <= 0:
            return

        center_y = top + height / 2.0
        half_h = height / 2.0

        # Nettoyer la zone : fond noir
        ctx.save()
        ctx.set_source_rgb(0.0, 0.0, 0.0)
        ctx.rectangle(x0, top, region_width, height)
        ctx.fill()

        # Paramètres de trim et d'enveloppe
        trim_start = max(0.0, min(1.0, float(sample.trim_start)))
        trim_end = max(0.0, min(1.0, float(sample.trim_end)))
        if trim_end <= trim_start:
            # Trim incohérent => ligne plate
            ctx.set_source_rgb(*definitions.get_color_rgb_float(definitions.YELLOW))
            ctx.set_line_width(1.0)
            ctx.move_to(x0 + 0.5, center_y)
            ctx.line_to(x0 + region_width - 0.5, center_y)
            ctx.stroke()
            ctx.restore()
            return

        start_idx = int(trim_start * (n_frames - 1))
        end_idx = int(trim_end * (n_frames - 1))
        end_idx = max(end_idx, start_idx + 1)

        attack_samples = max(1, int(sample.attack_seconds * sampler.sample_rate))
        release_samples = max(1, int(sample.release_seconds * sampler.sample_rate))

        # 1er passage : calcul des amplitudes + max pour normalisation
        amplitudes = [0.0] * region_width
        max_amp = 0.0

        for x in range(region_width):
            # t = position horizontale 0..1
            if region_width > 1:
                t = x / float(region_width - 1)
            else:
                t = 0.0

            idx = int(t * (n_frames - 1))
            idx = max(0, min(n_frames - 1, idx))

            s = float(mono[idx])

            # Envelope basée sur trim + attack + release
            if idx < start_idx or idx > end_idx:
                env = 0.0
            else:
                rel_from_start = idx - start_idx
                rel_to_end = end_idx - idx

                if attack_samples <= 1:
                    attack_env = 1.0
                else:
                    attack_env = max(0.0, min(1.0, rel_from_start / float(attack_samples)))

                if release_samples <= 1:
                    release_env = 1.0
                else:
                    release_env = max(0.0, min(1.0, rel_to_end / float(release_samples)))

                env = min(attack_env, release_env)

            amp = abs(s * env)
            amplitudes[x] = amp
            if amp > max_amp:
                max_amp = amp

        # Si rien à afficher => simple ligne
        ctx.set_source_rgb(*definitions.get_color_rgb_float(definitions.YELLOW))
        ctx.set_line_width(1.0)

        if max_amp <= 1e-6:
            ctx.move_to(x0 + 0.5, center_y)
            ctx.line_to(x0 + region_width - 0.5, center_y)
            ctx.stroke()

            # Barres START / END (pour que ce soit cohérent visuellement même si plat)
            x_start = int((start_idx / float(n_frames - 1)) * (region_width - 1))
            x_end = int((end_idx / float(n_frames - 1)) * (region_width - 1))

            ctx.set_line_width(1.5)
            # START
            ctx.move_to(x0 + x_start + 0.5, top)
            ctx.line_to(x0 + x_start + 0.5, bottom)
            # END
            ctx.move_to(x0 + x_end + 0.5, top)
            ctx.line_to(x0 + x_end + 0.5, bottom)
            ctx.stroke()

            ctx.restore()
            return

        # 2e passage : tracé des deux courbes (haut et bas) → onde symétrique
        # Haut
        first_amp_norm = amplitudes[0] / max_amp
        y_top0 = center_y - first_amp_norm * half_h
        ctx.move_to(x0 + 0.5, y_top0)
        for x in range(1, region_width):
            amp_norm = amplitudes[x] / max_amp
            y_top = center_y - amp_norm * half_h
            ctx.line_to(x0 + x + 0.5, y_top)
        ctx.stroke()

        # Bas
        first_amp_norm = amplitudes[0] / max_amp
        y_bot0 = center_y + first_amp_norm * half_h
        ctx.move_to(x0 + 0.5, y_bot0)
        for x in range(1, region_width):
            amp_norm = amplitudes[x] / max_amp
            y_bot = center_y + amp_norm * half_h
            ctx.line_to(x0 + x + 0.5, y_bot)
        ctx.stroke()

        # Barres START / END
        x_start = int((start_idx / float(n_frames - 1)) * (region_width - 1))
        x_end = int((end_idx / float(n_frames - 1)) * (region_width - 1))

        ctx.set_line_width(1.5)
        # START
        ctx.move_to(x0 + x_start + 0.5, top)
        ctx.line_to(x0 + x_start + 0.5, bottom)
        # END
        ctx.move_to(x0 + x_end + 0.5, top)
        ctx.line_to(x0 + x_end + 0.5, bottom)
        ctx.stroke()

        ctx.restore()


    def update_display(self, ctx, w, h):

        session = getattr(self.app, "session_mode", None)

        if (
            not self.app.is_mode_active(self.app.settings_mode)
            and not (
                session is not None
                and self.app.is_mode_active(session)
                and getattr(session, "clip_view_active", False)
            )
        ):

            # If settings mode is active, don't draw the upper parts of the screen because settings page will
            # "cover them"

            # Draw MIDI CCs section names
            section_names = self.get_current_track_midi_cc_sections()[0:8]
            if section_names:
                height = 20
                for i, section_name in enumerate(section_names):
                    show_text(ctx, i, 0, section_name, background_color=definitions.RED)
                    
                    is_selected = False
                    selected_section, _ = self.get_currently_selected_midi_cc_section_and_page()
                    if selected_section == section_name:
                        is_selected = True

                    current_track_color = self.get_current_track_color_helper()
                    if is_selected:
                        background_color = current_track_color
                        font_color = definitions.BLACK
                    else:
                        background_color = definitions.BLACK
                        font_color = current_track_color
                    show_text(ctx, i, 0, section_name, height=height,
                              font_color=font_color, background_color=background_color)

            # Draw MIDI CC controls
            if self.active_midi_control_ccs:
                instrument = self.get_current_track_instrument_short_name_helper()
                selected_section, _ = self.get_currently_selected_midi_cc_section_and_page()

                sampler_wave_drawn = False

                # --- CAS SPECIAL : SAMPLER + section "Param" ---
                if instrument == "SAMPLER" and selected_section == "Param":
                    try:
                        # On détermine la note à partir du premier contrôle de la page
                        first_control = self.active_midi_control_ccs[0]
                        label = first_control.name  # ex: "SMP36 ATTACK"
                        parts = label.split(" ")
                        note = None
                        if parts and parts[0].startswith("SMP"):
                            try:
                                note = int(parts[0].replace("SMP", ""))
                            except ValueError:
                                note = None

                        if note is not None:
                            self._draw_sampler_waveform(ctx, note)
                            sampler_wave_drawn = True

                    except Exception:
                        # En cas d'erreur, on ignore silencieusement et on garde le drawing normal
                        sampler_wave_drawn = False

                # Ensuite : dessiner les contrôles (sauf les 4 premiers si waveform sampler affichée)
                for i in range(0, min(len(self.active_midi_control_ccs), 8)):
                    # Si on a dessiné l'onde pour le sampler, on supprime les 4 premiers knobs visuels
                    if sampler_wave_drawn and i < 4:
                        continue
                    try:
                        self.active_midi_control_ccs[i].draw(ctx, i)
                    except IndexError:
                        continue

    
    def on_button_pressed(self, button_name):
        if  button_name in self.midi_cc_button_names:
            current_track_sections = self.get_current_track_midi_cc_sections()
            n_sections = len(current_track_sections)
            idx = self.midi_cc_button_names.index(button_name)
            if idx < n_sections:
                new_section = current_track_sections[idx]
                self.update_current_section_page(new_section=new_section, new_page=0)
            return True

        elif button_name in [push2_python.constants.BUTTON_PAGE_LEFT, push2_python.constants.BUTTON_PAGE_RIGHT]:
            show_prev, show_next = self.get_should_show_midi_cc_next_prev_pages_for_section()
            _, current_page = self.get_currently_selected_midi_cc_section_and_page()
            if button_name == push2_python.constants.BUTTON_PAGE_LEFT and show_prev:
                self.update_current_section_page(new_page=current_page - 1)
            elif button_name == push2_python.constants.BUTTON_PAGE_RIGHT and show_next:
                self.update_current_section_page(new_page=current_page + 1)
            return True


    def on_encoder_rotated(self, encoder_name, increment):
        # ---------------------------------------------------
        # CLIP VIEW (SessionMode) : scroll via encodeurs
        # ---------------------------------------------------
        session = getattr(self.app, "session_mode", None)

        if (
            session is not None
            and self.app.is_mode_active(session)
            and session.clip_view_active
            and session.selected_clip is not None
        ):
            # Track1 → scroll vertical
            if encoder_name == push2_python.constants.ENCODER_TRACK1_ENCODER:
                session.clip_view_note_min = max(
                    0, min(127 - 12, session.clip_view_note_min + increment)
                )
                self.app.display_render_needed = True
                return True

            # Track2 → scroll horizontal
            if encoder_name == push2_python.constants.ENCODER_TRACK2_ENCODER:
                steps = getattr(session, "steps_per_measure", 16)
                session.clip_view_start_step = max(
                    0, session.clip_view_start_step + increment * steps
                )
                self.app.display_render_needed = True
                return True

            # Track3 → sélection note
            if encoder_name == push2_python.constants.ENCODER_TRACK3_ENCODER:
                session.clip_view_select_event(1 if increment > 0 else -1)
                self.app.display_render_needed = True
                return True

            # Track4 → déplacement temporel
            if encoder_name == push2_python.constants.ENCODER_TRACK4_ENCODER:
                session.clip_view_move_selected_in_time(increment)
                self.app.display_render_needed = True
                return True

            # Track5 → déplacement pitch
            if encoder_name == push2_python.constants.ENCODER_TRACK5_ENCODER:
                session.clip_view_move_selected_in_pitch(increment)
                self.app.display_render_needed = True
                return True




        try:
            encoder_num = [
                push2_python.constants.ENCODER_TRACK1_ENCODER,
                push2_python.constants.ENCODER_TRACK2_ENCODER,
                push2_python.constants.ENCODER_TRACK3_ENCODER,
                push2_python.constants.ENCODER_TRACK4_ENCODER,
                push2_python.constants.ENCODER_TRACK5_ENCODER,
                push2_python.constants.ENCODER_TRACK6_ENCODER,
                push2_python.constants.ENCODER_TRACK7_ENCODER,
                push2_python.constants.ENCODER_TRACK8_ENCODER,
            ].index(encoder_name)

            # Pas de contrôles actifs → rien à faire
            if not self.active_midi_control_ccs:
                return True

            control = self.active_midi_control_ccs[encoder_num]
            if control is None:
                return True

            # Met à jour la valeur (0–127) et envoie le CC (pour les instruments normaux)
            control.update_value(increment)

            # --- LOGIQUE SPÉCIALE POUR LE SAMPLER ---
            instrument = self.get_current_track_instrument_short_name_helper()
            if instrument != "SAMPLER":
                # Pour tous les autres instruments, on reste dans le comportement normal
                return True

            # À partir d'ici : on intercepte les CC pour piloter le sampler interne
            label = control.name           # ex: "SMP36 VOL", "SMP40 ATTACK", "SMP42 START", etc.
            parts = label.split(" ")
            if not parts:
                return True

            # On attend des labels du type "SMP36 XXX"
            if not parts[0].startswith("SMP"):
                return True

            try:
                note = int(parts[0].replace("SMP", ""))   # "SMP36" -> 36
            except ValueError:
                return True

            # Normalisation 0.0 → 1.0
            val_norm = control.value / 127.0

            # Si pas de 2e mot, on considère que c'est un volume
            param = parts[1] if len(parts) >= 2 else "VOL"

            # --- Mapping paramètre → méthodes du Sampler ---
            if param == "VOL":
                # Page "VOLUMES 36–43", labels: "SMP36 VOL", etc.
                self.app.sampler.set_sample_volume(note, val_norm)
                return True

            elif param == "ATTACK":
                # 0–0.200s (200 ms) par sample
                self.app.sampler.set_sample_attack(note, val_norm * 0.200)
                return True

            elif param == "RELEASE":
                # 0–0.600s (600 ms) par sample
                self.app.sampler.set_sample_release(note, val_norm * 0.600)
                return True

            elif param == "START":
                # Trim start en pourcentage 0.0–1.0
                self.app.sampler.set_sample_trim_start(note, val_norm)
                return True

            elif param == "END":
                # Trim end en pourcentage 0.0–1.0
                self.app.sampler.set_sample_trim_end(note, val_norm)
                return True

            elif param.startswith("PARAM"):
                # Réservé pour usage futur → on consomme quand même l’encodeur
                return True

        except ValueError:
            # Encoder pas dans la liste (ex: Tempo Encoder déjà géré ailleurs)
            pass

        # On renvoie toujours True : ce mode consomme l’encodeur quand il est actif
        return True


    # -------------------------------------------------------------
    # SAMPLER : sélection automatique SMPxx → affiche page Param
    # -------------------------------------------------------------
    def select_sample(self, note):
        """
        Force l'affichage de la page Param correspondant à SMPxx.
        Ex : note 36 → SMP36 START/ATTACK/RELEASE/END
        """

        instrument = self.get_current_track_instrument_short_name_helper()
        if instrument != "SAMPLER":
            return

        section = "Param"
        controls = self.instrument_midi_control_ccs.get("SAMPLER", [])
        if not controls:
            return

        # ---- 1) Tous les contrôles de la section Param (ordre local) ----
        section_controls = [c for c in controls if c.section == section]
        if not section_controls:
            return

        # ---- 2) Contrôles pour ce sample SMPxx dans cette section ----
        prefix = f"SMP{note} "
        sample_controls = [c for c in section_controls
                           if c.name.startswith(prefix)]

        if not sample_controls:
            print("[SAMPLER] select_sample: aucun contrôle Param trouvé pour", note)
            return

        # ---- 3) Index local dans la section Param ----
        first_control = sample_controls[0]
        try:
            local_index = section_controls.index(first_control)
        except ValueError:
            return

        # ---- 4) Page = index local // 8 (8 contrôles par page) ----
        page = local_index // 8

        # ---- 5) Mise à jour interne ----
        self.current_selected_section_and_page["SAMPLER"] = [section, page]
        self.active_midi_control_ccs = self.get_midi_cc_controls_for_current_track_section_and_page()

        # ---- 6) Rafraîchissement Push ----
        self.app.buttons_need_update = True
        self.app.display_render_needed = True

    def draw_clip_grid(self, ctx, clip_length, clip_events, playhead_step):
        """
        Affiche une mini-grille 16 pas représentant tout le clip.
        - clip_length : longueur totale du clip (steps)
        - clip_events : clip.data
        - playhead_step : position courante dans le clip
        """

        if clip_length <= 0:
            return

        grid_cols = 16

        display_w = push2_python.constants.DISPLAY_LINE_PIXELS
        display_h = push2_python.constants.DISPLAY_N_LINES

        # zone droite du display
        x0 = display_w // 2
        x1 = display_w
        y0 = display_h - 40
        height = 10

        col_width = (x1 - x0) / grid_cols

        ctx.save()

        # fond
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(x0, y0, x1 - x0, height)
        ctx.fill()

        # présence de notes
        for ev in clip_events:
            start = ev.get("start")
            if start is None:
                continue

            col = int((start / float(clip_length)) * grid_cols)
            col = max(0, min(grid_cols - 1, col))

            r, g, b = definitions.get_color_rgb_float(definitions.GRAY_LIGHT)
            ctx.set_source_rgb(r, g, b)
            ctx.rectangle(
                x0 + col * col_width,
                y0,
                col_width - 1,
                height
            )
            ctx.fill()

        # playhead
        play_col = int((playhead_step / float(clip_length)) * grid_cols)
        play_col = max(0, min(grid_cols - 1, play_col))

        r, g, b = definitions.get_color_rgb_float(definitions.BLUE)
        ctx.set_source_rgb(r, g, b)
        ctx.rectangle(
            x0 + play_col * col_width,
            y0,
            col_width - 1,
            height
        )
        ctx.fill()

        ctx.restore()
