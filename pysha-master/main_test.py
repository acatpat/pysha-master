# main_test.py
import sys
from PyQt6.QtWidgets import QApplication
from ui.sequencer_window import SequencerWindow

app = QApplication(sys.argv)
w = SequencerWindow()
w.show()
sys.exit(app.exec())
