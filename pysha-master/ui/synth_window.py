# ui/synth_window.py
import os
import json
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt
import mido

import definitions

class SynthWindow(QWidget):
    """
    Petite fenêtre pour sélectionner une 'instrument_definition' (fichiers JSON).
    - liste les fichiers présents dans definitions.INSTRUMENT_DEFINITION_FOLDER
    - permet de sélectionner un instrument
    - émet instrument_changed(str) quand la sélection change
    - peut être pilotée depuis le Push (lower row buttons)
    """

    instrument_changed = pyqtSignal(str)  # short_name (sans .json)

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Synth / Instruments")
        self.setMinimumSize(360, 120)

        self._instruments = []  # liste de short names (strings)
        self._selected_instrument = None

        # ports MIDI associés aux instruments
        self.instrument_midi_ports = {}  # { "DDRM": {"in": "...", "out": "..."} }

        # construit l’UI (combo instrument)
        self._build_ui()

        # remplir les combos MIDI IN/OUT (créés dans _build_ui)
        self.combo_in.addItems(mido.get_input_names())
        self.combo_out.addItems(mido.get_output_names())

        # connecter signaux
        self.combo_in.currentIndexChanged.connect(self.on_midi_in_changed)
        self.combo_out.currentIndexChanged.connect(self.on_midi_out_changed)

        # remplir la liste d’instruments JSON
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

        # ---- AJOUT DES COMBOS MIDI IN/OUT ----
        midi_row = QHBoxLayout()
        layout.addLayout(midi_row)

        self.combo_in = QComboBox()
        self.combo_out = QComboBox()
        midi_row.addWidget(QLabel("MIDI IN"))
        midi_row.addWidget(self.combo_in)
        midi_row.addWidget(QLabel("MIDI OUT"))
        midi_row.addWidget(self.combo_out)
        # --------------------------------------

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
    # Disk / list handling
    # --------------------
    def refresh_instrument_list(self):
        """Lit le dossier definitions.INSTRUMENT_DEFINITION_FOLDER et remplit le combo."""
        folder = getattr(definitions, 'INSTRUMENT_DEFINITION_FOLDER', None)
        instruments = []
        if folder and os.path.isdir(folder):
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith('.json'):
                    short = fn[:-5]  # enlever .json
                    instruments.append(short)

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
    # Sélection / API publique
    # --------------------
    def _on_combo_changed(self, text):
        if not text:
            return
        self._selected_instrument = text
        self.current_label.setText(f"Current: {text}")

        # charger les ports MIDI si connus
        if text in self.instrument_midi_ports:
            current_in = self.instrument_midi_ports[text].get("in", "")
            current_out = self.instrument_midi_ports[text].get("out", "")

            idx_in = self.combo_in.findText(current_in)
            if idx_in != -1:
                self.combo_in.setCurrentIndex(idx_in)

            idx_out = self.combo_out.findText(current_out)
            if idx_out != -1:
                self.combo_out.setCurrentIndex(idx_out)

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

    # --------------------
    # Pour Push lower-row
    # --------------------
    def handle_lower_row_button(self, index):
        if index < 0 or index >= len(self._instruments):
            return None
        chosen = self._instruments[index]
        self.set_selected_instrument(chosen)
        return chosen

    # --------------------
    # Ports MIDI par instrument
    # --------------------
    def on_midi_in_changed(self, index):
        short_name = self.combo.currentText()
        port = self.combo_in.currentText()

        if short_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[short_name] = {"in": "", "out": ""}

        self.instrument_midi_ports[short_name]["in"] = port

    def on_midi_out_changed(self, index):
        short_name = self.combo.currentText()
        port = self.combo_out.currentText()

        if short_name not in self.instrument_midi_ports:
            self.instrument_midi_ports[short_name] = {"in": "", "out": ""}

        self.instrument_midi_ports[short_name]["out"] = port

    def set_current_instrument(self, short_name):
        """
        Méthode requise par app.py : redirige simplement vers set_selected_instrument.
        """
        self.set_selected_instrument(short_name)
