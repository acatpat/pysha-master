# ui/synth_window.py
import os
import json
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt

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

        self._build_ui()
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

        # garder l'ordre stable — mettre à jour combo seulement si changé
        self._instruments = instruments
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(self._instruments)
        self.combo.blockSignals(False)

        # garder sélection si possible
        if self._selected_instrument in self._instruments:
            self.set_selected_instrument(self._selected_instrument)
        elif self._instruments:
            # par défaut, ne pas forcer la sélection — mais afficher premier si rien choisi
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
        # émettre signal (autres composants s'abonnent)
        try:
            self.instrument_changed.emit(text)
        except Exception:
            pass

    def set_selected_instrument(self, short_name):
        """Appelé depuis l'extérieur pour synchroniser la fenêtre (push ou code)."""
        if short_name is None:
            return
        if short_name not in self._instruments:
            # essayer de raffraîchir la liste
            self.refresh_instrument_list()
        if short_name in self._instruments:
            idx = self._instruments.index(short_name)
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(idx)
            self.combo.blockSignals(False)
            self._on_combo_changed(short_name)
        else:
            # afficher sans sélectionner si inconnu
            self.current_label.setText(f"Current: {short_name} (missing)")

    def get_instrument_list(self):
        return list(self._instruments)

    # --------------------
    # Méthode utilitaire pour être appelée par le handler push lower-row
    # --------------------
    def handle_lower_row_button(self, index):
        """
        index: 0..N-1 correspondant à la position du bouton dans la lower row.
        On mappe index -> instrument short_name si possible, sinon on ignore.
        """
        if index < 0 or index >= len(self._instruments):
            return None
        chosen = self._instruments[index]
        self.set_selected_instrument(chosen)
        return chosen

    def set_current_instrument(self, short_name):
        idx = self.combo.findText(short_name)
        if idx != -1:
            block = self.combo.blockSignals(True)
            self.combo.setCurrentIndex(idx)
            self.combo.blockSignals(block)
