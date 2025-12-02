import os
import json
import time
import threading
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt
import mido

import definitions


class SynthWindow(QWidget):
    instrument_changed = pyqtSignal(str)  # short_name (sans .json)

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Synth / Instruments")
        self.setMinimumSize(360, 120)

        self._instruments = []
        self._selected_instrument = None
        self.instrument_midi_ports = {}  # {instr: {"in": str, "out": mido.Output}}

        self._build_ui()

        # remplir les combos MIDI IN/OUT une seule fois
        self.combo_in.addItems(mido.get_input_names())
        self.combo_out.addItems(mido.get_output_names())

        # connecter signaux
        self.combo_in.currentIndexChanged.connect(self.on_midi_in_changed)
        self.combo_out.currentIndexChanged.connect(self.on_midi_out_changed)

        # remplir la liste d’instruments
        self.refresh_instrument_list()

    # --------------------
    # UI
    # --------------------
    def _build_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        header = QLabel("Instrument definitions")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        midi_row = QHBoxLayout()
        layout.addLayout(midi_row)
        self.combo_in = QComboBox()
        self.combo_out = QComboBox()
        midi_row.addWidget(QLabel("MIDI IN"))
        midi_row.addWidget(self.combo_in)
        midi_row.addWidget(QLabel("MIDI OUT"))
        midi_row.addWidget(self.combo_out)

        row = QHBoxLayout()
        layout.addLayout(row)
        self.combo = QComboBox()
        self.combo.currentTextChanged.connect(self._on_combo_changed)
        row.addWidget(self.combo)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_instrument_list)
        row.addWidget(self.refresh_btn)

        self.current_label = QLabel("Current: -")
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.current_label)

    # --------------------
    # Instrument list
    # --------------------
    def refresh_instrument_list(self):
        folder = getattr(definitions, 'INSTRUMENT_DEFINITION_FOLDER', None)
        instruments = []
        if folder and os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith('.json'):
                    instruments.append(fn[:-5])
        self._instruments = instruments

        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(self._instruments)
        self.combo.blockSignals(False)

        if self._selected_instrument in self._instruments:
            self.set_selected_instrument(self._selected_instrument)
        elif self._instruments:
            self.combo.setCurrentIndex(0)
            self._on_combo_changed(self.combo.currentText())

    # --------------------
    # Sélection instrument
    # --------------------
    def _on_combo_changed(self, text):
        if not text:
            return
        self._selected_instrument = text
        self.current_label.setText(f"Current: {text}")

        # mettre à jour la sélection des ports
        self.refresh_instrument_ports_ui(text)

        try:
            self.instrument_changed.emit(text)
        except Exception:
            pass

    def set_selected_instrument(self, short_name):
        if short_name is None:
            return
        if short_name not in self._instruments:
            self.refresh_instrument_list()
        if short_name in self._instruments:
            idx = self._instruments.index(short_name)
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(idx)
            self.combo.blockSignals(False)
            self._on_combo_changed(short_name)
        else:
            self.current_label.setText(f"Current: {short_name} (missing)")

    def get_instrument_list(self):
        return list(self._instruments)

    def handle_lower_row_button(self, index):
        if index < 0 or index >= len(self._instruments):
            return None
        chosen = self._instruments[index]
        self.set_selected_instrument(chosen)
        return chosen

    # --------------------
    # Ports MIDI
    # --------------------
    def refresh_instrument_ports_ui(self, instr):
        ports = self.instrument_midi_ports.get(instr, {})
        in_port = ports.get("in")
        if in_port and self.combo_in.findText(in_port) != -1:
            self.combo_in.setCurrentText(in_port)
        out_port = ports.get("out")
        out_name = getattr(out_port, "name", None) if out_port else None
        if out_name and self.combo_out.findText(out_name) != -1:
            self.combo_out.setCurrentText(out_name)

    def on_midi_in_changed(self, index):
        instr_name = self.combo.currentText()
        port_name = self.combo_in.currentText()
        if instr_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instr_name] = {"in": "", "out": None}
        self.instrument_midi_ports[instr_name]["in"] = port_name
        print(f"[MIDI] IN port for {instr_name} set to {port_name}")

    def on_midi_out_changed(self, index):
        instr_name = self.combo.currentText()
        port_name = self.combo_out.currentText()
        if instr_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instr_name] = {"in": "", "out": None}

        # fermer l’ancien port
        old_port = self.instrument_midi_ports[instr_name].get("out")
        if old_port:
            try:
                old_port.close()
            except Exception:
                pass

        # ouvrir le nouveau port avec retry
        midi_out_port = None
        for attempt in range(2):
            try:
                midi_out_port = mido.open_output(port_name)
                print(f"[MIDI] OUT port for {instr_name} opened: {port_name}")
                break
            except IOError:
                print(f"[MIDI] Attempt {attempt+1} failed to open OUT port {port_name} for {instr_name}")
                time.sleep(0.5)

        self.instrument_midi_ports[instr_name]["out"] = midi_out_port

        # mise à jour pour le séquenceur
        if hasattr(self, "sequencer_controller") and self.sequencer_controller:
            self.sequencer_controller.update_output_port(instr_name, midi_out_port)
    # --------------------
    # Compatibilité app.py
    # --------------------
    def set_current_instrument(self, short_name):
        self.set_selected_instrument(short_name)
