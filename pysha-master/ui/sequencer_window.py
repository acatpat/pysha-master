# ui/sequencer_window.py

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QDial, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot


class SequencerWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Séquenceur 16 Pads – 64 Steps (Vue minimale)")
        self.setMinimumSize(900, 500)

        # Séquence
        self.selected_pad = 0
        self.steps = [[False] * 32 for _ in range(16)]
        self.current_step = 0

        # Tempo par défaut
        self.tempo_bpm = 120

        # Résolution (steps par beat)
        # 1/16 par défaut = 4 steps par beat
        self.steps_per_beat = 4

        # Timer de lecture
        self.timer = QTimer()
        # Clock interne désactivée (gérée par Synths_Midi)
        # self.timer.timeout.connect(self.advance_step)


        # Dans __init__ ou via setter
        self.sequencer_target = None  # sera assigné depuis l'extérieur



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
            btn.clicked.connect(lambda checked, s=steps: self.set_resolution(s))
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

        # ⬅️ CORRECTION : inversion propre de l'état du bouton
        current = self.play_button.isChecked()
        self.play_button.setChecked(not current)

        # maintenant toggle_play agit correctement
        self.toggle_play()


    def toggle_play(self):
        if self.play_button.isChecked():
            self.play_button.setText("Stop")

            # Désactivation de l’ancienne clock interne (QTimer)
            # interval = int(60000 / self.tempo_bpm / self.steps_per_beat)
            # self.timer.start(interval)

            # Clock globale (Synths_Midi)
            self.app.start_clock()

        else:
            self.play_button.setText("Play")

            # self.timer.stop()  # désactivé, clock externe uniquement

            self.reset_step_highlight()
            self.app.stop_clock()


    def set_tempo(self, bpm):
        self.tempo_bpm = bpm
        self.tempo_label.setText(f"{bpm} BPM")
        if self.timer.isActive():
            interval = int(60000 / bpm / self.steps_per_beat)
            self.timer.start(interval)

    @pyqtSlot(int)
    def set_resolution_slot(self, steps_per_beat):
        print(f"[SEQ UI] set_resolution_slot called with {steps_per_beat}")
        self.set_resolution(steps_per_beat)

    def set_resolution(self, steps_per_beat):
        print(f"[SEQ UI] set_resolution: {steps_per_beat}")
        self.steps_per_beat = steps_per_beat

        # Mise à jour visuelle des boutons
        for btn, steps in self.reso_buttons:
            btn.setChecked(steps == steps_per_beat)

        if self.timer.isActive():
            interval = int(60000 / self.tempo_bpm / self.steps_per_beat)
            self.timer.start(interval)


    def advance_step(self):
        self.highlight_step(self.current_step, False)
        
        # nombre de steps = longueur d'un pad
        num_steps = len(self.steps[self.selected_pad])
        self.current_step = (self.current_step + 1) % num_steps
        
        self.highlight_step(self.current_step, True)

        # Jouer les notes actives pour ce step
        if self.sequencer_target:
            for pad_index, pad_steps in enumerate(self.steps):
                if pad_steps[self.current_step]:
                    self.sequencer_target.play_step(pad_index, self.current_step)


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
    # Logique Steps / Pads
    # -------------------------------------------------------------
    def select_pad(self, pad_index):
        self.selected_pad = pad_index
        self.update_pad_display()
        self.update_steps_display()

    def update_pad_display(self):
        for i, b in enumerate(self.pad_buttons):
            b.setChecked(i == self.selected_pad)

    def toggle_step(self, step_index):
        pad = self.selected_pad
        self.steps[pad][step_index] = not self.steps[pad][step_index]
        self.update_steps_display()

        if self.sequencer_target:
            self.sequencer_target.set_step_state(pad, step_index, self.steps[pad][step_index])


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
