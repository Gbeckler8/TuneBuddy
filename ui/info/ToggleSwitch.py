from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QPainter, QColor

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None, text=""):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor) # hover cursor (signals interactivity)
        self.setFixedSize(46, 26) # x,y dim
        self.setText(text)

    def sizeHint(self):
        return QSize(46, 26)

    def paintEvent(self, event):
        """Internal custom overrided method to paint the generic checkbox
        to look more like a toggle switch ;)"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        margin = 2
        track_rect = QRectF(margin, margin, rect.width() - 2 * margin, rect.height() - 2 * margin)

        # track color
        if self.isChecked():
            track_color = QColor("#3daee9")
        else:
            track_color = QColor("#777777")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, track_rect.height() / 2, track_rect.height() / 2)

        # knob
        knob_d = track_rect.height() - 4
        y = track_rect.y() + 2
        if self.isChecked():
            x = track_rect.right() - knob_d - 2
        else:
            x = track_rect.x() + 2

        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(x, y, knob_d, knob_d))