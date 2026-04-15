from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QDoubleSpinBox,  QGroupBox, QCheckBox, QFrame, QDialog, QPushButton
)
import logging
from app_logic.midi.ScoreData import ScoreData
from app_logic.NoteData import NoteData


class ClipperPanel(QWidget):
    """The ClipperPanel allows users to clip the active MIDI content
    to the specified start/end time. Allows users to only focus on certain
    sections of the MIDI for playback, practice, and analysis."""

    clip_triggered = pyqtSignal() 

    def __init__(self):
        super().__init__()

        self._layout = QVBoxLayout()
        self.setLayout(self._layout)

        # important data structures
        self.score_data: ScoreData = None

        self.init_ui()

    def load_score(self, score_data: ScoreData):
        """Load the score data into the clipper panel, and update ranges."""
        self.score_data = score_data

        # change the start/end input ranges
        # rk: score_data.get_length probably doesnt exist
        score_length_sec = score_data.get_length()
        self.start_input.setRange(0.0, score_length_sec)
        self.end_input.setRange(0.0, score_length_sec)
        self.end_input.setValue(score_length_sec)

    def init_ui(self):
        """Initialize the UI components of the ClipperPanel."""
        # start time input
        self.start_label = QLabel("Start time:")
        self.start_input = QDoubleSpinBox()
        self.start_input.setRange(0.0, 10000.0)
        self.start_input.setSingleStep(0.1)
        self.start_input.setSuffix(" sec")
        # layouts
        self.start_layout = QHBoxLayout()
        self.start_layout.addWidget(self.start_label)
        self.start_layout.addWidget(self.start_input)
        self._layout.addLayout(self.start_layout)

        # end time input
        self.end_label = QLabel("End time:")
        self.end_input = QDoubleSpinBox()
        self.end_input.setRange(0.0, 10000.0)
        self.end_input.setSingleStep(0.1)
        self.end_input.setSuffix(" sec")
        # layouts
        self.end_layout = QHBoxLayout()
        self.end_layout.addWidget(self.end_label)
        self.end_layout.addWidget(self.end_input)
        self._layout.addLayout(self.end_layout)

        # add clip and reset buttons
        self.clip_button = QPushButton("Clip")
        self.clip_button.clicked.connect(self.handle_clip)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.handle_reset)
        # layouts
        self.button_layout = QHBoxLayout()
        self.button_layout.addWidget(self.clip_button)
        self.button_layout.addWidget(self.reset_button)
        self._layout.addLayout(self.button_layout)

        self._layout.addStretch()

    def handle_clip(self):
        """Handle the clip button click event."""
        start_time = self.start_input.value()
        end_time = self.end_input.value()

        if start_time >= end_time:
            logging.warning("Start time must be less than end time.")
            return
        if self.score_data is None:
            logging.warning("Must load score data before clipping.")
            return
        
        logging.info(f"Clipping score from {start_time} sec to {end_time} sec.")
        notes = self.score_data.note_data.read(start_time=start_time, end_time=end_time)
        
        # create new notedata with clipped notes
        data = {}
        for n in notes:
            data[n.start_time] = n
        # load in clipped data into a new notedata
        note_data_clipped = NoteData()
        note_data_clipped.data = data
        note_data_clipped.times = sorted(data.keys())
        
        self.score_data.note_data = note_data_clipped # update the working note_data
        self.clip_triggered.emit() # used to update slider bounds / plot

    def handle_reset(self):
        """Handle the reset button click event."""
        if self.score_data is None:
            logging.warning("Must load score data before resetting.")
            return
        
        logging.info("Resetting score to full data.")
        self.score_data.note_data = self.score_data.note_data_full
        self.clip_triggered.emit()


class ClipperDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clip Utility")
        self.setMinimumWidth(300)

        self.clipper_panel = ClipperPanel()
        self.layout = QVBoxLayout()
        self.layout.addWidget(self.clipper_panel)
        self.setLayout(self.layout)