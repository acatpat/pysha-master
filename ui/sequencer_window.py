# ui/sequencer_window.py

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QDial, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSlot


class SequencerWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Séquenceur 16 Pads – 64 Steps (Vue minimale)")
        self.setMinimumSize(900, 500)

        # Séquence
        self.selected_pad = 0
        self.steps = [[False] * 32 for _ in range(16)]
        self.current_step = 0

        # Instrument fixe du séquenceur (indépendant de SynthWindow)
        self.sequencer_output_instrument = "DDRM"


        # Tempo par défaut
        self.tempo_bpm = 120

        # Résolution (steps par beat)
        # 1/16 par défaut = 4 steps par beat
        self.steps_per_beat = 4

        # Références externes (raccordées depuis app.py)
        self.sequencer_target = None  # sera assigné depuis l'extérieur
        # self.app sera typiquement assigné depuis PyshaApp : window.app = self

        self.build_ui()

    # -------------------------------------------------------------
    # UI
    # -------------------------------------------------------------
    def build_ui(self):
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        #
        # --- Contrôles de transport ---
        #
        controls = QHBoxLayout()
        main_layout.addLayout(controls)

        # Bouton Play
        self.play_button = QPushButton("Play")
        self.play_button.setCheckable(True)
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setFixedWidth(80)
        controls.addWidget(self.play_button)

        # Dial Tempo
        tempo_box = QVBoxLayout()
        controls.addLayout(tempo_box)

        self.tempo_label = QLabel(f"{self.tempo_bpm} BPM")
        self.tempo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tempo_box.addWidget(self.tempo_label)

        self.tempo_dial = QDial()
        self.tempo_dial.setRange(40, 240)
        self.tempo_dial.setValue(self.tempo_bpm)
        self.tempo_dial.valueChanged.connect(self.set_tempo)
        tempo_box.addWidget(self.tempo_dial)

        # --- PRESETS ---
        preset_layout = QHBoxLayout()
        main_layout.addLayout(preset_layout)

        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(200)
        preset_layout.addWidget(self.preset_combo)

        self.btn_preset_save = QPushButton("Save Preset")
        self.btn_preset_save.clicked.connect(self.on_save_preset)
        preset_layout.addWidget(self.btn_preset_save)

        self.btn_preset_load = QPushButton("Load Preset")
        self.btn_preset_load.clicked.connect(self.on_load_preset)
        preset_layout.addWidget(self.btn_preset_load)

        # ----- Séquenceur → Instrument -----
        seq_instr_layout = QHBoxLayout()
        main_layout.addLayout(seq_instr_layout)

        self.seq_instr_label = QLabel("Séquenceur → Instrument :", self)
        seq_instr_layout.addWidget(self.seq_instr_label)

        self.seq_instr_combo = QComboBox(self)
        self.seq_instr_combo.addItems(["DDRM", "PRO800", "MINITAUR", "KIJIMI", "OCTATRACK", "SOURCE"])
        self.seq_instr_combo.setCurrentText(self.sequencer_output_instrument)

        self.seq_instr_combo.currentTextChanged.connect(self.on_seq_output_instrument_changed)
        seq_instr_layout.addWidget(self.seq_instr_combo)


        #
        # --- Sélecteur de résolution ---
        #
        resolution_layout = QHBoxLayout()
        controls.addLayout(resolution_layout)

        self.reso_buttons = []

        def add_reso(label, steps):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(50)
            # Pour l'instant, on garde l'appel direct à set_resolution (UI).
            btn.clicked.connect(lambda checked, s=steps: self.on_resolution_button(s))
            self.reso_buttons.append((btn, steps))
            resolution_layout.addWidget(btn)

        add_reso("1/4", 1)
        add_reso("1/8", 2)
        add_reso("1/16", 4)
        add_reso("1/32", 8)

        # Sélection visuelle par défaut
        for btn, steps in self.reso_buttons:
            btn.setChecked(steps == self.steps_per_beat)

        #
        # --- STEPS ---
        #
        self.steps_grid = QGridLayout()
        main_layout.addLayout(self.steps_grid)

        self.step_buttons = []
        for i in range(32):
            b = QPushButton(str(i + 1))
            b.setCheckable(True)
            b.setFixedSize(40, 40)
            # On garde l'appel vers toggle_step, qui sera maintenant un simple wrapper vers le controller
            b.clicked.connect(lambda checked, idx=i: self.toggle_step(idx))
            self.step_buttons.append(b)
            self.steps_grid.addWidget(b, i // 16, i % 16)

        #
        # --- 16 PADS ---
        #
        pads_layout = QGridLayout()
        main_layout.addLayout(pads_layout)

        self.pad_buttons = []
        for i in range(16):
            b = QPushButton(f"Pad {i+1}")
            b.setCheckable(True)
            b.setFixedSize(70, 70)
            # La sélection de pad reste une logique purement UI
            b.clicked.connect(lambda checked, idx=i: self.select_pad(idx))
            self.pad_buttons.append(b)
            pads_layout.addWidget(b, i // 4, i % 4)

        self.update_pad_display()
        self.update_steps_display()

    # -------------------------------------------------------------
    # Lecture du séquenceur
    # -------------------------------------------------------------
    @pyqtSlot()
    def toggle_play_slot(self):
        print("[SEQ UI] toggle_play_slot called (thread-safe)")

        # Inversion propre de l'état du bouton
        current = self.play_button.isChecked()
        self.play_button.setChecked(not current)

        # maintenant toggle_play agit correctement
        self.toggle_play()



    def toggle_play(self):
        if self.play_button.isChecked():
            self.play_button.setText("Stop")
            # Clock globale (Synths_Midi)
            if hasattr(self, "app"):
                self.app.synths_midi.start_clock()
        else:
            self.play_button.setText("Play")
            self.reset_step_highlight()
            if hasattr(self, "app"):
                self.app.synths_midi.stop_clock()

    def set_tempo(self, bpm):
        """
        Appelée par le QDial.
        UI + notification vers le SequencerController,
        qui lui-même met à jour Synths_Midi.bpm.
        """
        self.tempo_bpm = bpm
        self.tempo_label.setText(f"{bpm} BPM")

        if hasattr(self, "app") and hasattr(self.app, "sequencer_controller"):
            try:
                self.app.sequencer_controller.set_tempo(bpm)
            except Exception:
                pass

    @pyqtSlot(int)
    def set_resolution_slot(self, steps_per_beat):
        print(f"[SEQ UI] set_resolution_slot called with {steps_per_beat}")
        self.set_resolution(steps_per_beat)

    def set_resolution(self, steps_per_beat):
        """
        Mise à jour purement visuelle de la résolution dans la fenêtre.
        La logique de timing (ticks_per_step) est gérée dans SequencerController._set_resolution.
        """
        print(f"[SEQ UI] set_resolution: {steps_per_beat}")
        self.steps_per_beat = steps_per_beat

        # Mise à jour visuelle des boutons
        for btn, steps in self.reso_buttons:
            btn.setChecked(steps == steps_per_beat)

    def on_resolution_button(self, steps_per_beat):
        """
        UI → Controller : bouton de résolution pressé
        1) UI met à jour l'affichage (SéquenceWindow.set_resolution)
        2) Controller reçoit la vraie résolution via _set_resolution
        """
        # 1. Mise à jour visuelle
        self.set_resolution(steps_per_beat)

        # 2. Envoi de la résolution au contrôleur (logique de timing)
        if hasattr(self, "app") and hasattr(self.app, "sequencer_controller"):
            try:
                self.app.sequencer_controller._set_resolution(steps_per_beat)
            except Exception:
                pass


    # -------------------------------------------------------------
    # Ces deux fonctions ne portent plus la logique de séquenceur :
    # elles délèguent maintenant au SequencerController.
    # -------------------------------------------------------------
    def advance_step(self):
        """
        Compatibilité : si quelqu'un appelle encore SequencerWindow.advance_step(),
        on route vers SequencerController.advance_step().
        """
        if hasattr(self, "app") and hasattr(self.app, "sequencer_controller"):
            try:
                self.app.sequencer_controller.advance_step()
            except Exception:
                pass

    def toggle_step(self, step_index):
        """
        Compatibilité : route le toggle d'un step vers SequencerController._toggle_step().
        La logique de steps (model, sequencer_target, Push) est dans le controller.
        """
        if hasattr(self, "app") and hasattr(self.app, "sequencer_controller"):
            try:
                self.app.sequencer_controller._toggle_step(step_index)
            except Exception:
                pass

    # -------------------------------------------------------------
    # UI highlight
    # -------------------------------------------------------------
    def highlight_step(self, step, on):
        b = self.step_buttons[step]
        if on:
            b.setStyleSheet("background-color: yellow;")
        else:
            b.setStyleSheet("")

    def reset_step_highlight(self):
        for b in self.step_buttons:
            b.setStyleSheet("")
        self.current_step = 0

    # -------------------------------------------------------------
    # Logique Steps / Pads (UI uniquement)
    # -------------------------------------------------------------
    def select_pad(self, pad_index):
        self.selected_pad = pad_index
        self.update_pad_display()
        self.update_steps_display()

    def update_pad_display(self):
        for i, b in enumerate(self.pad_buttons):
            b.setChecked(i == self.selected_pad)

    def update_steps_display(self):
        pad = self.selected_pad
        for i, b in enumerate(self.step_buttons):
            b.setChecked(self.steps[pad][i])

    # ui/sequencer_window.py (ajouter à SequencerWindow)
    def highlight_pad(self, pad_name):
        """
        Met en évidence le pad sélectionné par le controller.
        Ici pad_name = "kick", "snare", etc.
        """
        name_to_index = {
            "kick": 0,
            "snare": 1,
            "closed_hh": 2,
            "open_hh": 3
            # compléter selon ton pad_map
        }
        idx = name_to_index.get(pad_name)
        if idx is not None:
            self.select_pad(idx)

    def update_step_leds(self):
        """
        Mise à jour visuelle des steps.
        Appelée par le controller après un toggle_step.
        """
        self.update_steps_display()

    # -------------------------------------------------------------
    # PRESETS
    # -------------------------------------------------------------
    def refresh_preset_list(self):
        if not hasattr(self, "app") or not hasattr(self.app, "list_presets"):
            return
        import os
        self.preset_combo.clear()
        presets = self.app.list_presets()
        for p in presets:
            name = os.path.basename(p)
            self.preset_combo.addItem(name, p)

    def on_save_preset(self):
        if not hasattr(self, "app") or not hasattr(self.app, "save_preset_auto"):
            return
        filename = self.app.save_preset_auto()
        self.refresh_preset_list()

        import os
        base = os.path.basename(filename)
        idx = self.preset_combo.findText(base)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def on_load_preset(self):
        if not hasattr(self.app, "synth_window") or self.app.synth_window is None:
            print("[PRESET] synth_window not ready yet -> skipping load")
            return

        idx = self.preset_combo.currentIndex()
        if idx < 0:
            return

        filepath = self.preset_combo.itemData(idx)
        if filepath and hasattr(self.app, "load_preset"):
            self.app.load_preset(filepath)
            self.update_steps_display()

    def on_seq_output_instrument_changed(self, instr_name):
        self.sequencer_output_instrument = instr_name
        print(f"[SEQ] Séquenceur → instrument fixé à : {instr_name}")
