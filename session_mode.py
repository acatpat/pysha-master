import definitions
import push2_python.constants
from melodic_mode import MelodicMode


class Clip:
    STATE_EMPTY = 0
    STATE_PLAYING = 1
    STATE_RECORDING = 2
    STATE_QUEUED = 3
    STATE_QUEUED_RECORD = 4
    STATE_WAIT_END_RECORD = 5  # stop à la prochaine mesure pendant rec

    def __init__(self):
        self.state = Clip.STATE_EMPTY
        self.data = []              # liste d'évènements: {note, velocity, start, end}
        self.length = 0             # longueur du clip en "steps clip"
        self.last_step_notes = []   # optionnel (non utilisé pour l'instant)

        # Enregistrement
        self.record_start_step = None  # step global au début REC
        self.record_stop_measure = None

        # Lecture
        self.playhead_step = 0        # position courante dans le clip (0..length-1)
        self.stop_after_end = False   # si True → s'arrête à la fin du clip



    def clear(self):
        self.data = []
        self.state = Clip.STATE_EMPTY
        self.length = 0
        self.last_step_notes = []
        self.record_start_step = None
        self.playhead_step = 0
        self.stop_after_end = False


class ClipMatrix:
    def __init__(self, rows=8, cols=8):
        self.rows = rows
        self.cols = cols
        self.clips = [[Clip() for _ in range(cols)] for _ in range(rows)]

    def get_clip(self, row, col):
        return self.clips[row][col]

    def to_color_matrix(self):
        matrix = []
        for r in range(self.rows):
            row_colors = []
            for c in range(self.cols):
                clip = self.clips[r][c]

                if clip.state == Clip.STATE_RECORDING:
                    color = definitions.RED
                elif clip.state == Clip.STATE_PLAYING:
                    color = definitions.GREEN
                elif clip.state == Clip.STATE_QUEUED:
                    color = definitions.YELLOW
                elif clip.state == Clip.STATE_QUEUED_RECORD:
                    color = definitions.ORANGE
                elif clip.state == Clip.STATE_WAIT_END_RECORD:
                    color = definitions.RED
                else:
                    color = definitions.GRAY_DARK

                row_colors.append(color)

            matrix.append(row_colors)
        return matrix


class SessionMode(MelodicMode):

    def __init__(self, app, settings=None):
        super().__init__(app, settings=settings)

        self.clips = ClipMatrix(8, 8)
        self.current_page = 0
        self.shift_is_held = False

        # Compteur global de steps séquenceur (indépendant de current_step 0..31)
        self.global_step = 0
        self.steps_per_measure = 16  # valeur par défaut, mise à jour par on_sequencer_step


        # --- Nouveaux états pour Duplicate / Delete / Quantize ---
        self.duplicate_is_held = False
        self.delete_is_held = False
        self.quantize_is_held = False
        self.duplicate_source = None  # (row, col) du clip source à dupliquer
        self.selected_clip = None   # (scene, track)
        self.select_pressed = False
        self.clip_view_active = False

    # ----------------------------------------------------------------------
    #  UTILITAIRE : ALL NOTES OFF POUR UNE PISTE (colonne)
    # ----------------------------------------------------------------------
    def _send_all_notes_off_for_track(self, track_col):
        """
        Envoie note_off 0–127 sur l’instrument de la colonne donnée.
        Utilisé pour sécuriser l’arrêt des clips.
        """
        try:
            tsm = self.app.track_selection_mode
            tracks = getattr(tsm, "tracks_info", [])
            if track_col < 0 or track_col >= len(tracks):
                return

            instr = tracks[track_col].get("instrument_short_name")
            if not instr:
                return

            for n in range(128):
                self.app.synths_midi.send_note_off(instr, n, velocity=0)

            print(f"[SESSION] ALL NOTES OFF sent for instrument '{instr}'")
        except Exception as e:
            print(f"[SESSION] ERROR ALL NOTES OFF: {e}")

    # -----------------------------------------------------------
    # ACTIVATION / DÉSACTIVATION
    # -----------------------------------------------------------
    def activate(self):
        super().activate()
        self.update_pads()
        self.update_buttons()

    def deactivate(self):

        # Éteindre les boutons en quittant le mode
        push = self.push
        push.buttons.set_button_color("Delete", definitions.BLACK)
        push.buttons.set_button_color("Duplicate", definitions.BLACK)
        push.buttons.set_button_color("Quantize", definitions.BLACK)
        push.buttons.set_button_color("Stop", definitions.BLACK)
        push.buttons.set_button_color("Select", definitions.BLACK)
        push.buttons.set_button_color("Clip", definitions.BLACK)

        super().deactivate()
        self.app.pads_need_update = True
        self.app.buttons_need_update = True

    # -----------------------------------------------------------
    # UPDATE PADS
    # -----------------------------------------------------------
    def update_pads(self):
        if not self.app.is_mode_active(self):
            return

        push = self.push
        tsm = self.app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", None)

        if not tracks or len(tracks) < 8:
            track_color = definitions.GRAY_DARK
            tracks = [{} for _ in range(8)]

        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                if 0 <= c < len(tracks):
                    track_color = tracks[c].get("color", definitions.GRAY_DARK)
                else:
                    track_color = definitions.GRAY_DARK

                if clip.state == Clip.STATE_EMPTY and len(clip.data) > 0:
                    color = track_color
                    anim = None
                elif clip.state == Clip.STATE_EMPTY:
                    color = definitions.GRAY_DARK
                    anim = None
                elif clip.state == Clip.STATE_QUEUED:
                    color = definitions.YELLOW
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF
                elif clip.state == Clip.STATE_QUEUED_RECORD:
                    color = definitions.ORANGE
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF
                elif clip.state == Clip.STATE_RECORDING:
                    color = definitions.RED
                    anim = push2_python.constants.ANIMATION_PULSING_QUARTER
                elif clip.state == Clip.STATE_WAIT_END_RECORD:
                    color = definitions.RED
                    anim = push2_python.constants.ANIMATION_BLINKING_HALF
                elif clip.state == Clip.STATE_PLAYING:
                    color = track_color
                    anim = push2_python.constants.ANIMATION_PULSING_HALF
                else:
                    color = definitions.GRAY_DARK
                    anim = None

                if anim is None:
                    anim = push2_python.constants.ANIMATION_STATIC

                push.pads.set_pad_color((r, c), color, anim)

    def update_buttons(self):
        push = self.push

        # Toujours allumés en mode Session
        push.buttons.set_button_color("Delete", definitions.WHITE)
        push.buttons.set_button_color("Duplicate", definitions.WHITE)
        push.buttons.set_button_color("Quantize", definitions.WHITE)
        push.buttons.set_button_color("Stop", definitions.WHITE)
        push.buttons.set_button_color("Select", definitions.WHITE)
        push.buttons.set_button_color("Clip", definitions.WHITE)

    # -----------------------------------------------------------
    #  STEP CALLBACK (PLAYBACK / RECORD)
    # -----------------------------------------------------------
    def on_sequencer_step(self, current_step, is_measure_start, num_steps):
        """
        Appelé à chaque step par SequencerController.
        Ici on utilise un compteur global (self.global_step)
        pour gérer des clips plus longs que la boucle du séquenceur (32 steps).
        """
        # Avance du step global
        self.global_step += 1
        self.steps_per_measure = num_steps

        app = self.app
        tsm = app.track_selection_mode
        tracks = getattr(tsm, "tracks_info", [])

        # -----------------------------
        # 1) DÉMARRER / ARRÊTER ENREGISTREMENT (quantisé à la mesure)
        # -----------------------------
        changed_states = False

        if is_measure_start:
            current_measure = self.global_step // num_steps

            for r in range(8):
                for c in range(8):
                    clip = self.clips.get_clip(r, c)

                    # -------------------------
                    # START RECORD
                    # -------------------------
                    if clip.state == Clip.STATE_QUEUED_RECORD:
                        clip.state = Clip.STATE_RECORDING
                        clip.data = []
                        clip.length = 0
                        clip.record_start_step = self.global_step
                        clip.record_stop_measure = None
                        clip.playhead_step = 0
                        clip.stop_after_end = False

                        print(
                            f"[SESSION] START RECORDING ({r},{c}) "
                            f"at global_step={self.global_step}"
                        )
                        self.app.pads_need_update = True

                    # -------------------------
                    # STOP RECORD (mesure cible)
                    # -------------------------
                    if (
                        clip.state == Clip.STATE_WAIT_END_RECORD
                        and clip.record_stop_measure == current_measure
                    ):
                        start_measure = clip.record_start_step // num_steps
                        recorded_measures = current_measure - start_measure
                        if recorded_measures < 1:
                            recorded_measures = 1

                        clip.length = recorded_measures * num_steps
                        clip.state = Clip.STATE_QUEUED
                        clip.playhead_step = 0
                        clip.stop_after_end = False
                        clip.record_stop_measure = None

                        print(
                            f"[SESSION] STOP RECORD ({r},{c}) "
                            f"→ length={clip.length} steps "
                            f"({recorded_measures} bars)"
                        )

                        self._send_all_notes_off_for_track(c)
                        self.app.pads_need_update = True




        if changed_states:
            app.pads_need_update = True

        # -----------------------------
        # 2) PLAYBACK : NOTE OFF / NOTE ON + gestion de la fin de clip
        # -----------------------------
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)

                if clip.state != Clip.STATE_PLAYING:
                    continue

                # Clip sans longueur → rien à faire
                if clip.length <= 0:
                    continue

                step_in_clip = clip.playhead_step

                # NOTE OFF au step courant
                for ev in clip.data:
                    if ev.get("end") == step_in_clip:
                        try:
                            if c < len(tracks):
                                instr = tracks[c]["instrument_short_name"]
                                note = ev["note"]
                                print(f"[SESSION-PLAY] NOTE_OFF instr={instr} note={note} clip_step={step_in_clip}")
                                app.synths_midi.send_note_off(instr, note)
                        except Exception as e:
                            print(f"[SESSION-PLAY] NOTE_OFF ERROR: {e}")

                # NOTE ON au step courant
                for ev in clip.data:
                    if ev.get("start") == step_in_clip:
                        try:
                            if c < len(tracks):
                                instr = tracks[c]["instrument_short_name"]
                                note = ev["note"]
                                vel = ev.get("velocity", 100)
                                print(f"[SESSION-PLAY] NOTE_ON instr={instr} note={note} vel={vel} clip_step={step_in_clip}")
                                app.synths_midi.send_note_on(instr, note, vel)
                        except Exception as e:
                            print(f"[SESSION-PLAY] NOTE_ON ERROR: {e}")

                # Avance du playhead dans le clip
                clip.playhead_step += 1

                if clip.playhead_step >= clip.length:
                    # Fin de clip atteinte
                    if clip.stop_after_end:
                        # STOP demandé → on arrête ici
                        print(f"[SESSION] Clip end reached → STOP ({r},{c})")
                        # Sécurité : all notes off
                        self._send_all_notes_off_for_track(c)
                        clip.state = Clip.STATE_EMPTY
                        clip.playhead_step = 0
                        clip.stop_after_end = False
                        app.pads_need_update = True
                    else:
                        # Loop par défaut
                        clip.playhead_step = 0

        # -----------------------------
        # 3) QUEUED → PLAYING AU DÉBUT DE MESURE
        # -----------------------------
        if is_measure_start:
            changed = False
            for r in range(8):
                for c in range(8):
                    clip = self.clips.get_clip(r, c)
                    if clip.state == Clip.STATE_QUEUED and clip.length > 0:
                        clip.state = Clip.STATE_PLAYING
                        clip.playhead_step = 0
                        clip.stop_after_end = False
                        print(f"[SESSION] Clip ({r},{c}) → PLAYING at measure start (global_step={self.global_step})")
                        changed = True
            if changed:
                app.pads_need_update = True

    # -----------------------------------------------------------
    # QUANTISATION
    # -----------------------------------------------------------
    def _quantize_clip_to_sixteenth(self, clip):
        """
        Quantise les événements du clip sur une grille de 1/16.
        Ici on suppose qu'1 step de clip = 1/16.
        """
        if clip is None:
            return
        if clip.length <= 0 or not clip.data:
            return

        grid = 1  # 1 step = 1/16

        def q(v):
            return int(round(v / grid)) * grid

        max_end = 0
        for ev in clip.data:
            start = ev.get("start")
            end = ev.get("end")

            if start is not None:
                ev["start"] = q(start)

            if end is not None:
                ev["end"] = q(end)
                # Sécurité : éviter end < start
                if ev["end"] < ev["start"]:
                    ev["end"] = ev["start"] + 1
                if ev["end"] > max_end:
                    max_end = ev["end"]

        if max_end > 0:
            # On s'assure que la longueur est au moins jusqu'à la dernière note
            clip.length = max(clip.length, max_end)


    # -----------------------------------------------------------
    # GESTION PADS
    # -----------------------------------------------------------
    def on_pad_pressed(self, pad_n, pad_ij, velocity):
        row, col = pad_ij
        # --- SELECT + PAD → sélection clip ---
        if self.select_pressed:
            self.select_clip(row, col)
            return

        if velocity == 0:
            return False


        clip = self.clips.get_clip(row, col)

        # ---------------------------------------------------
        # 1) DELETE + pad → efface le clip
        # ---------------------------------------------------
        if self.delete_is_held:
            if len(clip.data) > 0 or clip.length > 0 or clip.state != Clip.STATE_EMPTY:
                clip.clear()
                print(f"[SESSION] Clip ({row},{col}) deleted via Delete+Pad")
                self.app.pads_need_update = True
                return True
            else:
                # Rien à supprimer
                print(f"[SESSION] Delete+Pad ({row},{col}) → clip already empty")
                return True

        # ---------------------------------------------------
        # 2) DUPLICATE maintenu :
        #    - premier pad = source
        #    - deuxième pad (vide) = destination
        # ---------------------------------------------------
        if self.duplicate_is_held:
            # Sélection de la source
            if self.duplicate_source is None:
                if len(clip.data) > 0 and clip.length > 0:
                    self.duplicate_source = (row, col)
                    print(f"[SESSION] Duplicate source selected at ({row},{col})")
                else:
                    print(f"[SESSION] Duplicate source at ({row},{col}) ignored (empty clip)")
                return True
            else:
                # On a déjà une source : ce pad devient la destination
                src_r, src_c = self.duplicate_source
                src_clip = self.clips.get_clip(src_r, src_c)

                # Empêcher la duplication vers un clip non vide
                if len(src_clip.data) == 0 or src_clip.length <= 0:
                    print("[SESSION] Duplicate: source has no data, abort")
                    return True

                if len(clip.data) > 0 or clip.length > 0 or clip.state != Clip.STATE_EMPTY:
                    print(f"[SESSION] Duplicate: destination ({row},{col}) is not empty, abort")
                    return True

                # Copie des données
                clip.clear()
                clip.data = [dict(ev) for ev in src_clip.data]
                clip.length = src_clip.length
                clip.state = Clip.STATE_EMPTY
                clip.playhead_step = 0
                clip.stop_after_end = False
                clip.record_start_step = None

                print(f"[SESSION] Clip ({src_r},{src_c}) duplicated to ({row},{col})")
                self.app.pads_need_update = True
                return True

        # ---------------------------------------------------
        # 3) QUANTIZE maintenu : quantisation du clip à 1/16
        # ---------------------------------------------------
        if self.quantize_is_held:
            if len(clip.data) > 0 and clip.length > 0:
                self._quantize_clip_to_sixteenth(clip)
                print(f"[SESSION] Quantize 1/16 applied to clip ({row},{col})")
                # Pas de changement d'état de lecture, seulement les données
                return True
            else:
                print(f"[SESSION] Quantize ignored on empty clip ({row},{col})")
                return True

        # ---------------------------------------------------
        # 4) COMPORTEMENT EXISTANT (PLAY / REC) inchangé
        # ---------------------------------------------------

        # --- Clip AVEC données : PLAY / STOP À LA FIN ---
        if len(clip.data) > 0 and clip.length > 0:
            if clip.state == Clip.STATE_PLAYING:
                # Demande un STOP à la fin du clip
                clip.stop_after_end = True
                print(f"[SESSION] Pad ({row},{col}) → STOP AT END requested")
            else:
                # (Re)lancer le clip, quantisé à la prochaine mesure
                clip.state = Clip.STATE_QUEUED
                clip.playhead_step = 0
                clip.stop_after_end = False
                print(f"[SESSION] Pad ({row},{col}) → QUEUED (play at next measure)")

            self.app.pads_need_update = True
            return True

        # --- Clip vide : programmation enregistrement à prochaine mesure ---
        if clip.state == Clip.STATE_EMPTY and len(clip.data) == 0:
            clip.state = Clip.STATE_QUEUED_RECORD
            clip.record_start_step = None
            clip.playhead_step = 0
            clip.stop_after_end = False
            print(f"[SESSION] Pad ({row},{col}) → QUEUED_RECORD (rec at next measure)")
            self.app.pads_need_update = True
            return True

        # --- Pendant RECORDING : demander arrêt à prochaine mesure ---
        if clip.state == Clip.STATE_RECORDING:
            steps_per_measure = getattr(self, "steps_per_measure", 16)
            clip.record_stop_measure = self.global_step // steps_per_measure + 1
            clip.state = Clip.STATE_WAIT_END_RECORD
            print(
                f"[SESSION] STOP REC requested → will stop at measure {clip.record_stop_measure}"
            )
            self.app.pads_need_update = True


        return False


    # -----------------------------------------------------------
    # MIDI ENREGISTREMENT
    # -----------------------------------------------------------
    def get_recording_clip(self):
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_RECORDING:
                    return clip
        return None


    def on_midi_in(self, msg, source=None):

        """
        Enregistrement des notes en steps RELATIFS au début du clip :
        - start = global_step - record_start_step
        - end   = idem
        """
        clip = self.get_recording_clip()
        if clip is None:
            return False

        if msg.type not in ("note_on", "note_off"):
            return False

        # Step du sequencer en valeur globale
        current_global = self.global_step
        if clip.record_start_step is None:
            # sécurité : si jamais pas initialisé (ne devrait pas arriver)
            clip.record_start_step = current_global

        clip_step = current_global - clip.record_start_step
        if clip_step < 0:
            clip_step = 0

        # NOTE ON (velocity > 0)
        if msg.type == "note_on" and msg.velocity > 0:
            ev = {
                "note": msg.note,
                "velocity": msg.velocity,
                "start": clip_step,
                "end": None,
            }
            clip.data.append(ev)
            print(f"[SESSION-REC] NOTE_ON note={msg.note} vel={msg.velocity} clip_step={clip_step}")
            return True

        # NOTE OFF (note_off ou note_on vel=0)
        if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            for ev in reversed(clip.data):
                if ev.get("note") == msg.note and ev.get("end") is None:
                    ev["end"] = clip_step
                    print(f"[SESSION-REC] NOTE_OFF note={msg.note} clip_step={clip_step}")
                    break
            return True


        return False

    def select_clip(self, scene, track):
        """
        Sélectionne un clip sans déclencher d'action (UI only).
        """
        self.selected_clip = (scene, track)

        # Miroir global (pour display Push plus tard)
        self.app.selected_clip = self.selected_clip

        # Forcer le refresh visuel des pads
        self.app.pads_need_update = True


    # -----------------------------------------------------------
    # BOUTONS (Shift, Duplicate, Delete, Quantize)
    # -----------------------------------------------------------
    def on_button_pressed(self, button_name):
        print(f"[SESSION] on_button_pressed: {button_name}")
        if button_name == "Shift":
            self.shift_is_held = True
            return True

        if button_name == "Duplicate":
            self.duplicate_is_held = True
            self.duplicate_source = None
            print("[SESSION] Duplicate button held")
            return True

        if button_name == "Delete":
            self.delete_is_held = True
            print("[SESSION] Delete button held")
            return True

        if button_name == "Quantize":
            self.quantize_is_held = True
            print("[SESSION] Quantize button held")
            return True

        if button_name == "Select":
            self.select_pressed = True
            return True

        if button_name == "Clip":
            # Activer la vue Clip uniquement si un clip est sélectionné
            if self.selected_clip is not None:
                self.clip_view_active = True
                self.app.clip_view_active = True  # miroir global (display plus tard)
                print(f"[SESSION] Clip View ON for clip {self.selected_clip}")
                return True
            return False

        if button_name == "Session":
            self.clip_view_active = False
            self.app.clip_view_active = False
            print("[SESSION] Clip View OFF → back to Session")
            return False

        if button_name == "Browse":

            scene, track = self.selected_clip
            clip = self.clips.get_clip(scene, track)


            self.export_clip_to_midi(
                clip,
                filename=f"clip_{scene}_{track}.mid",
                track_col=track
            )

            return True



        return False

    def on_button_released(self, button_name):
        if button_name == "Shift":
            self.shift_is_held = False
            return True

        if button_name == "Duplicate":
            self.duplicate_is_held = False
            self.duplicate_source = None
            print("[SESSION] Duplicate button released")
            return True

        if button_name == "Delete":
            self.delete_is_held = False
            print("[SESSION] Delete button released")
            return True
        
        if button_name == "Select":
            self.select_pressed = False
            return True

        if button_name == "Quantize":
            self.quantize_is_held = False
            print("[SESSION] Quantize button released")
            return True

        return False

    # -----------------------------------------------------------
    # AFFICHAGE PUSH 2 : barre d’avancement de mesure
    # -----------------------------------------------------------
    def update_display(self, ctx, w, h):
        """
        Étend l'affichage du SessionMode (hérité de MelodicMode)
        et ajoute une barre d’avancement de la mesure.
        """
        # --- 1) Rendu normal du MelodicMode ---
        super().update_display(ctx, w, h)

        # --- 2) Afficher la barre seulement si SessionMode est actif ---
        if not self.app.is_mode_active(self):
            return

        # --- 3) Récupération du séquenceur ---
        seq = getattr(self.app, "sequencer_controller", None)
        if seq is None:
            return

        current_step = getattr(seq, "current_step", 0)

        # --- 4) Calcul du nombre de steps par mesure ---
        # Priorité 1 : un attribut direct (si existe)
        steps_per_measure = getattr(seq, "steps_per_measure", None)

        # Priorité 2 : steps_per_beat * beats_per_measure
        if steps_per_measure is None:
            steps_per_beat = getattr(seq, "steps_per_beat", None)
            beats_per_measure = getattr(seq, "beats_per_measure", None)
            if steps_per_beat is not None and beats_per_measure is not None:
                steps_per_measure = steps_per_beat * beats_per_measure

        # Fallback : 16 steps par mesure (classique Push)
        if steps_per_measure is None:
            steps_per_measure = 16

        # -------------------------------------------------------
        # CLIP VIEW : grille du clip sélectionné
        # -------------------------------------------------------
        if getattr(self, "clip_view_active", False) and self.selected_clip is not None:
            scene, track = self.selected_clip
            clip = self.clips.get_clip(scene, track)

            if clip.length <= 0:
                return

            mcc = getattr(self.app, "midi_cc_mode", None)
            if mcc is None:
                return

            mcc.draw_clip_grid(
                ctx,
                clip.length,
                clip.data,
                clip.playhead_step
            )
            return



        # -------------------------------------------------------
        # CLIP VIEW (V1) : barre d’avancement du clip sélectionné
        # -------------------------------------------------------
        if getattr(self, "clip_view_active", False) and self.selected_clip is not None:
            row, col = self.selected_clip
            clip = self.clips.get_clip(row, col)

            # Clip valide ?
            if clip.length > 0:
                mcc = getattr(self.app, "midi_cc_mode", None)
                if mcc is not None:
                    # playhead_step est déjà relatif au clip
                    step_in_clip = clip.playhead_step % clip.length
                    mcc.draw_measure_progress(
                        ctx,
                        step_in_clip,
                        clip.length
                    )
                # -----------------------------
                # MINI GRID 16 STEPS (CLIP VIEW)
                # -----------------------------
                grid_cols = 16
                grid = [0] * grid_cols

                # Marquer les steps contenant des notes
                for ev in clip.data:
                    start = ev.get("start")
                    end = ev.get("end")
                    if start is None:
                        continue

                    if end is None:
                        end = start + 1

                    for s in range(start, end):
                        col = int(s * grid_cols / clip.length)
                        col = max(0, min(grid_cols - 1, col))
                        grid[col] = 1

                # Position du playhead
                play_col = int(step_in_clip * grid_cols / clip.length)
                play_col = max(0, min(grid_cols - 1, play_col))

                # -----------------------------
                # DESSIN
                # -----------------------------
                display_w = push2_python.constants.DISPLAY_LINE_PIXELS
                display_h = push2_python.constants.DISPLAY_N_LINES

                x0 = display_w // 2   # moitié droite de l'écran
                y0 = display_h - 40
                cell_w = (display_w // 2) / grid_cols
                cell_h = 8

                ctx.save()

                for i in range(grid_cols):
                    if i == play_col:
                        ctx.set_source_rgb(0.2, 0.6, 1.0)   # playhead (bleu)
                    elif grid[i]:
                        ctx.set_source_rgb(0.8, 0.8, 0.8)   # note présente
                    else:
                        ctx.set_source_rgb(0.15, 0.15, 0.15)  # vide

                    ctx.rectangle(
                        x0 + i * cell_w,
                        y0,
                        cell_w - 1,
                        cell_h
                    )
                    ctx.fill()

                ctx.restore()


                return


        # -------------------------------------------------------
        # SESSION VIEW : barre d’avancement de la mesure
        # -------------------------------------------------------
        mcc = getattr(self.app, "midi_cc_mode", None)
        if mcc is not None:
            step_in_measure = current_step % steps_per_measure
            mcc.draw_measure_progress(
                ctx,
                step_in_measure,
                steps_per_measure
            )

    def export_clip_to_midi(self, clip, filename, track_col=0):
        """
        Exporte un clip SessionMode vers un fichier MIDI standard.
        Ouvrable dans Reaper / Ableton / Bitwig.
        """

        if clip is None or clip.length <= 0 or not clip.data:
            print("[SESSION] Export MIDI aborted: empty clip")
            return

        import os

        # --- dossier d’export fixe ---
        export_dir = os.path.join(os.getcwd(), "midi_exports")
        os.makedirs(export_dir, exist_ok=True)

        # --- nom de fichier automatique si non fourni ---
        if not filename:
            filename = "clip.mid"

        # --- chemin absolu ---
        filename = os.path.join(export_dir, filename)


        import mido

        # --- paramètres MIDI ---
        ticks_per_beat = 480
        steps_per_beat = 4          # 1/16 → 4 steps par noire
        ticks_per_step = ticks_per_beat // steps_per_beat

        bpm = getattr(self.app.synths_midi, "bpm", 120)
        tempo = mido.bpm2tempo(bpm)

        mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
        track = mido.MidiTrack()
        mid.tracks.append(track)

        # --- tempo ---
        track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))

        # --- collect events ---
        events = []

        for ev in clip.data:
            note = ev["note"]
            vel = ev.get("velocity", 100)
            start = ev.get("start", 0)
            end = ev.get("end", start + 1)

            start_tick = int(start * ticks_per_step)
            end_tick = int(end * ticks_per_step)

            events.append((start_tick, "on", note, vel))
            events.append((end_tick, "off", note, 0))

        # --- trier par temps ---
        events.sort(key=lambda e: e[0])

        # --- écrire avec delta-times ---
        last_tick = 0
        for tick, etype, note, vel in events:
            delta = tick - last_tick
            last_tick = tick

            if etype == "on":
                track.append(
                    mido.Message(
                        "note_on",
                        note=int(note),
                        velocity=int(vel),
                        time=delta
                    )
                )
            else:
                track.append(
                    mido.Message(
                        "note_off",
                        note=int(note),
                        velocity=0,
                        time=delta
                    )
                )

        # --- forcer la longueur exacte du clip ---
        total_clip_ticks = clip.length * ticks_per_step

        remaining = total_clip_ticks - last_tick
        if remaining < 0:
            remaining = 0

        # --- fin de piste ---
        track.append(mido.MetaMessage("end_of_track", time=remaining))


        # --- sauvegarde ---
        import os
        print("[SESSION] MIDI export path:", os.path.abspath(filename))

        mid.save(filename)
        print(f"[SESSION] Clip exported to MIDI → {filename}")
