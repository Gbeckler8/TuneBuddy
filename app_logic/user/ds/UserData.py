import numpy as np

from app_logic.user.ds.AudioData import AudioData
from app_logic.user.ds.PitchData import PitchData, Pitch
from app_logic.NoteData import NoteData
from app_logic.user.ds.Buffer import Buffer
from algorithms.Config import Config

class UserData:
    def __init__(self, pitch_detector, note_detector):
        """the user data. requires reference to pitch and note detectors"""
        # essential data variables
        self.config = pitch_detector.config
        self.audio_data = AudioData()
        self.pitch_data = PitchData(self.config)
        self.note_data = NoteData()

        # queue data structures for real time pitch + note detection + correction
        self.a2p_queue = Buffer(pitch_detector.SR) #audio-to-pitches
        self.p2n_queue = Buffer(sr=pitch_detector.SR/pitch_detector.HOP_SIZE) #pitches-to-notes
        self.n2c_queue = None #notes-to-corrections

        # algorithms
        self.pitch_detector = pitch_detector
        self.note_detector = note_detector

    def on_pitches_detected(self, pitches):
        self.pitch_data.data = pitches

    def load_audio(self, audio_filepath: str):
        """load in a pre-recorded audio file from a filepath
        also computes pitches on the entire file"""
        self.audio_data.load_data(audio_filepath)
        self.detect_pitches()
        self.detect_notes()

    def detect_pitches(self):
        """run pitch detection on the current audio data"""
        self.pitch_data.data = self.pitch_detector.detect_pitches(self.audio_data.data)

    def detect_notes(self):
        """run note detection on the current pitch data"""
        self.note_data = self.note_detector.detect_notes(self.pitch_data)

    def write_data(self, indata: np.ndarray, start_time: float):
        """write indata to the audio_data at the given start_time
        and append to our queue for pitch processing
        """
        self.audio_data.write_data(indata, start_time)
        self.a2p_queue.push(indata)

    def write_pitch_data(self, indata: list[Pitch], start_time: float):
        """write indata to the pitch_data at the given start_time
        and append to our queue for note processing
        """
        self.pitch_data.write(indata, start_time)
        self.p2n_queue.push(indata)