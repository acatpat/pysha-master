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
        self.instrument_midi_ports = {}  # {instr: {"in": str, "out": str}}

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
        in_port_name = ports.get("in")
        if in_port_name and self.combo_in.findText(in_port_name) != -1:
            self.combo_in.setCurrentText(in_port_name)

        out_port_name = ports.get("out")
        if out_port_name and self.combo_out.findText(out_port_name) != -1:
            self.combo_out.setCurrentText(out_port_name)

    # --------------------
    # Mise à jour depuis SettingsMode
    # --------------------
    def update_port_from_external_change(self, instr, in_name=None, out_name=None):
        """
        Appelée depuis SettingsMode lorsqu'un port MIDI change.
        Met à jour le dictionnaire et rafraîchit l'affichage.
        """
        if instr not in self.instrument_midi_ports:
            self.instrument_midi_ports[instr] = {"in": None, "out": None}

        if in_name is not None:
            self.instrument_midi_ports[instr]["in"] = in_name
        if out_name is not None:
            self.instrument_midi_ports[instr]["out"] = out_name

        # Si l’instrument affiché est celui qui a changé,
        # on met à jour visuellement les QComboBox.
        if instr == self._selected_instrument:
            self.refresh_instrument_ports_ui(instr)


    def on_midi_in_changed(self, index):
        instr_name = self.combo.currentText()
        port_name = self.combo_in.currentText()

        if instr_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instr_name] = {"in": "", "out": ""}

        # On stocke uniquement le NOM du port dans la fenêtre
        self.instrument_midi_ports[instr_name]["in"] = port_name
        print(f"[MIDI] IN port for {instr_name} set to {port_name}")

        # Informer Synths_Midi pour qu’il ouvre/ferme les ports réels
        if self.app is not None and hasattr(self.app, "synths_midi"):
            current_out = self.instrument_midi_ports[instr_name].get("out") or None
            try:
                self.app.synths_midi.assign_instrument_ports(
                    instrument_name=instr_name,
                    in_name=port_name,
                    out_name=current_out,
                )
            except Exception as e:
                print(f"[MIDI] Error assigning IN port for {instr_name} in Synths_Midi:", e)


    def on_midi_out_changed(self, index):
        instr_name = self.combo.currentText()
        port_name = self.combo_out.currentText()

        if instr_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[instr_name] = {"in": "", "out": ""}

        # Dans la fenêtre, on stocke uniquement le NOM du port
        self.instrument_midi_ports[instr_name]["out"] = port_name
        print(f"[MIDI] OUT port for {instr_name} set to {port_name}")

        # Informer Synths_Midi pour qu’il ouvre/ferme le port réel
        if self.app is not None and hasattr(self.app, "synths_midi"):
            current_in = self.instrument_midi_ports[instr_name].get("in") or None
            try:
                self.app.synths_midi.assign_instrument_ports(
                    instrument_name=instr_name,
                    in_name=current_in,
                    out_name=port_name,
                )
            except Exception as e:
                print(f"[MIDI] Error assigning OUT port for {instr_name} in Synths_Midi:", e)

        # L’appel à sequencer_controller.update_output_port reste optionnel ;
        # on le laisse pour compatibilité, mais il ne reçoit plus d’objet port.
        if hasattr(self, "sequencer_controller") and self.sequencer_controller:
            try:
                self.sequencer_controller.update_output_port(instr_name, port_name)
            except Exception:
                pass

    # --------------------
    # Compatibilité app.py
    # --------------------
    def set_current_instrument(self, short_name):
        self.set_selected_instrument(short_name)
