# controller/sequencer_controller.py

import definitions


class SequencerController:
    """
    Interprète les notes envoyées par RhythmicMode pour contrôler le séquenceur interne.
    Convertit le pitch (0-127) en actions logiques :
    - Sélection de pad
    - Toggle de step dans la grille
    - Navigation / pages
    - Actions globales
    """

    def __init__(self, app, sequencer_model, sequencer_window):
        self.app = app
        self.model = sequencer_model      # ton modèle : steps, resolution, patterns
        self.window = sequencer_window    # ton UI du séquenceur

        self.selected_pad = None          # ex: "kick", "snare", etc.
        self.pad_map = {}                 # pitch → instrument
        self.step_range_start = None      # pitch minimal des steps
        self.step_range_end = None        # pitch max des steps
        self.pad_to_push2 = {}     # pad_name → (row, col) sur Push 2
        self.step_to_push2 = {}    # step_index → (row, col) sur Push 2

        # Tu définis ces mappings plus tard selon ta matrice rythmique
        self._init_default_mapping()

    # -------------------------------------------------------------------------
    # INITIALISATION DU MAPPING
    # -------------------------------------------------------------------------
    def _init_default_mapping(self):
        """
        Définition des pads et steps, et mapping vers Push 2.
        """
        # Pads (pitch → pad_name)
        self.pad_map = {
            36: "kick",
            37: "snare",
            38: "closed_hh",
            39: "open_hh",
        }

        # Steps
        self.step_range_start = 64
        self.step_range_end = 64 + 15  # 16 steps : 64 → 79

        # Mapping pad_name → (row, col) Push 2
        # Exemple : pads sur la rangée 4
        self.pad_to_push2 = {
            "kick": (4, 0),
            "snare": (4, 1),
            "closed_hh": (4, 2),
            "open_hh": (4, 3),
        }

        # Mapping step_index → (row, col) Push 2
        # 16 steps répartis sur 2 lignes
        for i in range(16):
            if i < 8:
                self.step_to_push2[i] = (5, i)       # rangée 5, colonnes 0-7
            else:
                self.step_to_push2[i] = (6, i - 8)  # rangée 6, colonnes 0-7


    # -------------------------------------------------------------------------
    # FONCTION PRINCIPALE
    # -------------------------------------------------------------------------
    def handle_rhythmic_input(self, pitch, is_note_on=True):
        """
        Fonction appelée depuis RhythmicMode à chaque pad / note envoyé.
        """
        # 1. Ignore si ce n'est pas un note_on
        if not is_note_on:
            return

        # 2. D'abord : instrument selection
        if pitch in self.pad_map:
            return self._select_pad(self.pad_map[pitch])

        # 3. Ensuite : gestion des steps
        if self.step_range_start <= pitch <= self.step_range_end:
            step_index = pitch - self.step_range_start
            return self._toggle_step(step_index)

        # 4. Sinon : peut être une fonction globale (shift, mute…)
        return self._global_action(pitch)

    # -------------------------------------------------------------------------
    # SÉLECTION DE PAD
    # -------------------------------------------------------------------------
    def _select_pad(self, pad_name):
        if pad_name not in self.pad_to_push2:
            print(f"[SEQ] Pad inconnu : {pad_name}")
            return

        # Trouver l’index correspondant pour window.selected_pad
        idx = list(self.pad_map.values()).index(pad_name)
        self.window.selected_pad = idx
        print(f"[SEQ] Pad sélectionné : {pad_name} (index {idx})")

        # UI
        self.window.update_pad_display()
        self.window.update_steps_display()

        # Feedback Push
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # TOGGLE D’UN STEP
    # -------------------------------------------------------------------------
    def _toggle_step(self, step_index):
        pad = self.window.selected_pad
        if pad is None:
            print("[SEQ] Aucun pad sélectionné → ignore l’appui.")
            return

        print(f"[SEQ] Toggle step {step_index} pour pad {pad}")

        # Basculer le step
        self.window.toggle_step(step_index)

        # Mise à jour visuelle
        self.window.update_steps_display()

        # Feedback Push
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # FEEDBACK PUSH2
    # -------------------------------------------------------------------------
    def update_push_feedback(self):
        if not self.app.push:
            return

        # Préparer matrice 8x8 pour Push
        pad_matrix = [[definitions.BLACK for _ in range(8)] for _ in range(8)]

        # --- Allumer pad sélectionné ---
        selected_pad_idx = self.window.selected_pad
        selected_pad_name = list(self.pad_map.values())[selected_pad_idx]
        if selected_pad_name in self.pad_to_push2:
            row, col = self.pad_to_push2[selected_pad_name]
            pad_matrix[row][col] = definitions.NOTE_ON_COLOR

        # --- Allumer steps ---
        steps = self.window.steps[selected_pad_idx]
        for step_idx, step_on in enumerate(steps):
            if step_idx in self.step_to_push2:
                row, col = self.step_to_push2[step_idx]
                pad_matrix[row][col] = definitions.NOTE_ON_COLOR if step_on else definitions.BLACK

        # Envoyer la matrice complète à Push 2
        self.app.push.pads.set_pads_color(pad_matrix)

    # -------------------------------------------------------------------------
    # ACTIONS GLOBALES
    # -------------------------------------------------------------------------
    def _global_action(self, pitch):
        """
        Ici tu mets des actions non-step, non-pad :
        - changement de page
        - Start/Stop
        - Clear
        - Duplicate
        """
        print(f"[SEQ] Action globale non définie pour pitch {pitch}")
