# controller/sequencer_controller.py

import definitions

class SequencerController:
    """
    Contrôle le séquenceur interne et envoie le feedback sur Push 2.
    """

    def __init__(self, app, sequencer_model, sequencer_window):
        self.app = app
        self.model = sequencer_model
        self.window = sequencer_window

        # Initialisations des attributs
        self.pad_map = {}               # pitch → pad_name
        self.step_range_start = None
        self.step_range_end = None
        self.pad_to_push2 = {}          # pitch MIDI → (row, col) sur Push 2
        self.step_to_push2 = {}         # step_index → (row, col) sur Push 2
        self.step_pitch_to_index = {}   # pitch MIDI → step_index

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
            40: "pad5",
            41: "pad6",
            42: "pad7",
            43: "pad8",
            44: "pad9",
            45: "pad10",
            46: "pad11",
            47: "pad12",
            48: "pad13",
            49: "pad14",
            50: "pad15",
            51: "pad16",
        }

        # Steps
        step_rows = [
            [64, 65, 66, 67, 96, 97, 98, 99],
            [60, 61, 62, 63, 92, 93, 94, 95],
            [56, 57, 58, 59, 88, 89, 90, 91],
            [52, 53, 54, 55, 84, 85, 86, 87]
        ]
        self.step_range_start = min(min(row) for row in step_rows)
        self.step_range_end = max(max(row) for row in step_rows)

        # Mapping step_index → position Push 2 (row, col) et pitch → step_index
        for row_idx, row_notes in enumerate(step_rows):
            for col_idx, pitch in enumerate(row_notes):
                step_index = row_idx * 8 + col_idx
                self.step_to_push2[step_index] = (row_idx, col_idx)
                self.step_pitch_to_index[pitch] = step_index

        # Mapping pad MIDI → position Push 2 (row, col)
        pad_midi_notes = list(range(36, 52))  # 16 pads
        for idx, pitch in enumerate(pad_midi_notes):
            row = 4 + (idx // 8)   # rangée 4 et 5
            col = idx % 8
            self.pad_to_push2[pitch] = (row, col)

    # -------------------------------------------------------------------------
    # FONCTION PRINCIPALE
    # -------------------------------------------------------------------------
    def handle_rhythmic_input(self, pitch, is_note_on=True):
        if not is_note_on:
            return

        # 1. Sélection pad
        if pitch in self.pad_map:
            return self._select_pad(self.pad_map[pitch])

        # 2. Toggle step
        if pitch in self.step_pitch_to_index:
            step_index = self.step_pitch_to_index[pitch]
            return self._toggle_step(step_index)

        # 3. Actions globales
        return self._global_action(pitch)

    # -------------------------------------------------------------------------
    # SÉLECTION DE PAD
    # -------------------------------------------------------------------------
    def _select_pad(self, pad_name):
        # Pitch MIDI du pad
        pitch = [p for p, name in self.pad_map.items() if name == pad_name][0]
        # Index dans window.selected_pad
        self.window.selected_pad = list(self.pad_map.keys()).index(pitch)

        # Feedback Push 2
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # TOGGLE D’UN STEP
    # -------------------------------------------------------------------------
    def _toggle_step(self, step_index):
        pad_idx = self.window.selected_pad
        self.window.toggle_step(step_index)

        # Feedback Push 2
        self.update_push_feedback()

    # -------------------------------------------------------------------------
    # FEEDBACK PUSH 2
    # -------------------------------------------------------------------------
    def update_push_feedback(self):
        if not self.app.push:
            return

        # Matrice 8x8
        pad_matrix = [[definitions.BLACK for _ in range(8)] for _ in range(8)]

        # --- Allumer le pad sélectionné ---
        selected_pad_idx = self.window.selected_pad
        selected_pitch = list(self.pad_map.keys())[selected_pad_idx]
        row, col = self.pad_to_push2[selected_pitch]
        pad_matrix[row][col] = definitions.NOTE_ON_COLOR

        # --- Allumer les steps ---
        steps = self.window.steps[selected_pad_idx]
        for step_index, step_on in enumerate(steps):
            if step_index in self.step_to_push2 and step_on:
                step_row, step_col = self.step_to_push2[step_index]
                pad_matrix[step_row][step_col] = definitions.NOTE_ON_COLOR

        # Envoyer la matrice complète à Push 2
        self.app.push.pads.set_pads_color(pad_matrix)

    # -------------------------------------------------------------------------
    # ACTIONS GLOBALES
    # -------------------------------------------------------------------------
    def _global_action(self, pitch):
        print(f"[SEQ] Action globale non définie pour pitch {pitch}")
