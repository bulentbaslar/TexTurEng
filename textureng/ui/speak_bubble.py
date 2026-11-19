"""Small round 🔊 button shown next to the mouse after text is selected.

It never takes focus (so the selection stays active in the other app), hides after
a few seconds or on a click elsewhere, and turns into ■ while reading."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

STYLE = """
QWidget#bubble { background: #18181c; border: 1px solid rgba(255,255,255,0.22); border-radius: 19px; }
QPushButton { color: #f4f4f5; background: transparent; border: none; font-size: 15pt; }
QPushButton:hover { background: rgba(245,165,36,0.30); border-radius: 15px; }
QLabel { color: #e4e4e7; font-size: 9.5pt; padding-right: 10px; }
"""
SHOW_SECONDS = 3.5


class SpeakBubble(QWidget):
    speakClicked = Signal()
    stopClicked = Signal()

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self.speaking = False

        inner = QWidget(objectName="bubble")
        self.button = QPushButton("🔊")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setFixedSize(38, 32)
        self.button.setToolTip("Read the selected text aloud")
        self.button.clicked.connect(self._clicked)
        self.label = QLabel()
        self.label.hide()
        row = QHBoxLayout(inner)
        row.setContentsMargins(3, 2, 3, 2)
        row.setSpacing(0)
        row.addWidget(self.button)
        row.addWidget(self.label)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(inner)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._timeout)

    def show_near_cursor(self) -> None:
        self.set_speaking(False)
        self.set_message("")
        self._place(QCursor.pos())
        self.show()
        self.raise_()
        self._hide_timer.start(int(SHOW_SECONDS * 1000))

    def contains_cursor(self) -> bool:
        return self.isVisible() and self.frameGeometry().contains(QCursor.pos())

    def set_speaking(self, speaking: bool) -> None:
        self.speaking = speaking
        self.button.setText("■" if speaking else "🔊")
        self.button.setToolTip("Stop reading" if speaking else "Read the selected text aloud")
        if speaking:
            self._hide_timer.stop()
        elif self.isVisible() and not self.label.text():
            self.hide()

    def set_message(self, text: str, seconds: float = 0) -> None:
        self.label.setText(text)
        self.label.setVisible(bool(text))
        self.adjustSize()
        if text and seconds:
            self._hide_timer.start(int(seconds * 1000))

    def dismiss(self) -> None:
        if not self.speaking:
            self._hide_timer.stop()
            self.hide()

    def _timeout(self) -> None:
        if not self.speaking:
            self.label.setText("")
            self.hide()

    def _clicked(self) -> None:
        if self.speaking:
            self.stopClicked.emit()
        else:
            self._hide_timer.stop()
            self.speakClicked.emit()

    def _place(self, anchor: QPoint) -> None:
        self.adjustSize()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x, y = anchor.x() + 10, anchor.y() - self.height() - 10  # above-right of the cursor
        if y < area.top() + 4:
            y = anchor.y() + 18
        x = min(x, area.right() - self.width() - 4)
        self.move(max(area.left() + 4, x), y)
