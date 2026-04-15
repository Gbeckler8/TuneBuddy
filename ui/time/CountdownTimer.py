from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from ui.info.StatusBar import StatusBar


class CountdownTimer(QObject):
    """A simple countdown timer that emits a signal when finished
    TODO: make it aligned to the metronome
    """
    finished = pyqtSignal()

    def __init__(self, status_bar: StatusBar, duration: float=2.0):
        super().__init__()
        self.duration: float = duration
        self.t: float = duration
        self.status_bar = status_bar # reference to parent status bar to update msgs
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_timeout)

    def start(self):
        self.timer.start(100) # update every 100 ms

    def _on_timeout(self):
        self.t -= 0.100 # decrease by 100 ms
        self.status_bar.update_status(f"Starting in (s): {self.t:.1f}")
        if self.t <= 0:
            self.timer.stop()
            self.finished.emit()
            self.status_bar.update_status("Recording...")