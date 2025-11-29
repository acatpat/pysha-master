# controller/sequencer_controller.py

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

        # Tu définis ces mappings plus tard selon ta matrice rythmique
        self._init_default_mapping()

    # -------------------------------------------------------------------------
    # INITIALISATION DU MAPPING
    # -------------------------------------------------------------------------
    def _init_default_mapping(self):
        """
        Mapping de base. Tu pourras l'ajuster selon ta Rhythmic Grid.
        L’idée : séparer "pads d'instrument" et "steps".
        """

        # Exemple minimal : pads = row 8 de RhythmicMode
        self.pad_map = {
            36: "kick",
            37: "snare",
            38: "closed_hh",
            39: "open_hh",
        }

        # Steps correspondraient à la partie haute
        self.step_range_start = 64
        self.step_range_end = 64 + 15  # 16 steps : 64 → 79

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
        # Convertir pad_name en index
        name_to_index = {
            "kick": 0,
            "snare": 1,
            "closed_hh": 2,
            "open_hh": 3
            # compléter si nécessaire
        }
        idx = name_to_index.get(pad_name)
        if idx is None:
            print(f"[SEQ] Pad inconnu : {pad_name}")
            return

        self.window.selected_pad = idx
        print(f"[SEQ] Pad sélectionné : {pad_name} (index {idx})")

        # UI
        self.window.update_pad_display()
        self.window.update_steps_display()

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
