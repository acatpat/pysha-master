import definitions
import push2_python.constants
from melodic_mode import MelodicMode

# ============================================================================
# SESSION MODE (Playtime-like)
# ============================================================================
# Structure vide, conforme à la charte :
# - aucune simplification
# - aucune logique modifiée dans les autres modes
# - uniquement la base nécessaire
# - tout le futur code SessionMode restera ici
# ============================================================================


class Clip:
    """
    Un clip MIDI avec 4 états:
    - empty
    - playing
    - recording
    - queued (attente démarrage)
    """
    STATE_EMPTY = 0
    STATE_PLAYING = 1
    STATE_RECORDING = 2
    STATE_QUEUED = 3

    def __init__(self):
        self.state = Clip.STATE_EMPTY
        self.data = []    # placeholder pour notes, steps ou events
        self.length = 16  # par défaut

    def clear(self):
        self.data = []
        self.state = Clip.STATE_EMPTY
        self.last_step_notes = []


    def set_playing(self):
        self.state = Clip.STATE_PLAYING

    def set_recording(self):
        self.state = Clip.STATE_RECORDING

    def set_queued(self):
        self.state = Clip.STATE_QUEUED

    def set_empty(self):
        self.state = Clip.STATE_EMPTY



class ClipMatrix:
    """
    Matrice 8x8 de clips, comme Ableton / Playtime.
    Aucune logique encore — structure vide conforme à la charte.
    """
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
                else:
                    color = definitions.GRAY_DARK  # EMPTY visible
                row_colors.append(color)

            matrix.append(row_colors)
        return matrix



class SessionMode(MelodicMode):

    """
    Nouveau mode “Session” (Playtime-like).
    Implémentation vide, étape par étape.
    Aucun impact sur les autres modes.
    """

    def __init__(self, app, settings=None):
        super().__init__(app, settings=settings)
        self.clips = ClipMatrix(8, 8)
        self.current_page = 0  # pour expansion future (banques)

        self.shift_is_held = False


    # -----------------------------------------------------------
    # ACTIVATION / DÉSACTIVATION
    # -----------------------------------------------------------


    def activate(self):
        super().activate()
        # Forcer l’update complet du feedback Push2
        if hasattr(self.app, 'sequencer_controller'):
            self.app.sequencer_controller.update_push_feedback()

    def deactivate(self):
        super().deactivate()
        # Forcer update des pads à la sortie du mode
        self.app.pads_need_update = True
        self.app.buttons_need_update = True
    # -----------------------------------------------------------
    # UPDATE PADS / BUTTONS
    # -----------------------------------------------------------
    def update_pads(self):
        try:
            color_matrix = self.clips.to_color_matrix()
            self.push.pads.set_pads_color(color_matrix)
        except Exception:
            pass



    def update_buttons(self):
        """
        Placeholder — on pourra associer transport, rec, etc.
        Pour l’instant, rien n’est modifié.
        """
        pass

    def clear_buttons(self):
        """
        Éteint les boutons utilisés par ce mode.
        """
        # Aucun bouton défini pour l’instant
        pass

    # -----------------------------------------------------------
    # GESTION DES PADS PUSH2
    # -----------------------------------------------------------
    def on_pad_pressed(self, pad_n, pad_ij, velocity):
        """
        Gestion clip par pad :
        - TAP = PLAY / STOP
        - SHIFT + TAP = RECORD / STOP-REC / CLEAR
        """
        if velocity == 0:
            return False  # ignore "note off"

        # On récupère l'état SHIFT AVANT de l'utiliser
        shift_down = getattr(self, "shift_is_held", False)

        # DEBUG SHIFT
        if shift_down:
            print("SHIFT détecté !")
        else:
            print("SHIFT pas détecté.")

        row, col = pad_ij
        clip = self.clips.get_clip(row, col)

        # -----------------------------
        # MODE SHIFT : RECORD / CLEAR
        # -----------------------------
        if shift_down:

            if clip.state == Clip.STATE_RECORDING:
                clip.state = Clip.STATE_PLAYING

            elif clip.state == Clip.STATE_PLAYING:
                clip.state = Clip.STATE_EMPTY

            else:
                clip.state = Clip.STATE_RECORDING

            self.app.pads_need_update = True
            return True

        # -----------------------------
        # MODE NORMAL : PLAY / STOP
        # -----------------------------
        if clip.state == Clip.STATE_EMPTY:
            clip.state = Clip.STATE_QUEUED

        elif clip.state == Clip.STATE_PLAYING:
            clip.state = Clip.STATE_EMPTY

        elif clip.state == Clip.STATE_QUEUED:
            clip.state = Clip.STATE_PLAYING

        elif clip.state == Clip.STATE_RECORDING:
            clip.state = Clip.STATE_EMPTY  # stop rec

        self.app.pads_need_update = True
        return True

    # -----------------------------------------------------------
    # GESTION DES BOUTONS PUSH2
    # -----------------------------------------------------------
    def on_button_pressed(self, button_name):
        """
        Placeholder : aucun bouton encore mappé.
        """
        return False

    def get_recording_clip(self):
        """
        Retourne le clip en train d’enregistrer, ou None.
        (Il ne peut y en avoir qu’un à la fois car tu enregistres pad par pad.)
        """
        for r in range(8):
            for c in range(8):
                clip = self.clips.get_clip(r, c)
                if clip.state == Clip.STATE_RECORDING:
                    return clip
        return None

    def on_midi_in(self, msg, source=None):
        
        """
        Reçoit toutes les notes MIDI pendant l'enregistrement
        (Seuls les clips RECORDING enregistrent).
        """
        # Filtrer note_on uniquement
        if msg.type != "note_on" or msg.velocity == 0:
            return False

        # Trouver le clip en enregistrement
        clip = self.get_recording_clip()
        if clip is None:
            return False

        # Récupérer le step courant du sequencer
        try:
            current_step = getattr(self.app.sequencer_window, "current_step", -1)
        except:
            current_step = -1

        # Corriger si le step n’a pas encore démarré
        if current_step < 0:
            current_step = 0

        # Ajouter dans les données du clip
        clip.data.append({
            "note": msg.note,
            "velocity": msg.velocity,
            "step": current_step
        })
        print("RECORD:", msg.note, current_step)


        return True

    def on_button_pressed(self, button_name):
        if button_name == "Shift":
            self.shift_is_held = True
            return True
        return False

    def on_button_released(self, button_name):
        if button_name == "Shift":
            self.shift_is_held = False
            return True
        return False
