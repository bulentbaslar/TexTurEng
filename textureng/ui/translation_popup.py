"""Popup next to the mouse that shows the translation of the selected text.

It never takes keyboard focus, so the text stays selected in the other app and
"Replace" can paste the translation over it. It closes on a click outside it,
on Esc, or with its close button."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

NAMES = {"en": "English", "tr": "Turkish"}
MAX_WIDTH, MAX_TEXT_HEIGHT = 460, 320
_VK_LBUTTON, _VK_RBUTTON, _VK_ESCAPE = 0x01, 0x02, 0x1B

STYLE = """
#card { background: #18181c; border: 1px solid rgba(255,255,255,0.14); border-radius: 12px; }
QLabel { color: #f4f4f5; font-size: 10.5pt; }
#direction { color: #f5a524; font-size: 9pt; font-weight: 600; }
#note { color: #a1a1aa; font-size: 8.5pt; }
#body { background: transparent; }
QScrollArea { background: transparent; border: none; }
QPushButton { color: #f4f4f5; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12);
              border-radius: 6px; padding: 4px 12px; font-size: 9pt; }
QPushButton:hover { background: rgba(255,255,255,0.16); }
#primary { background: #f5a524; color: #18181c; border: none; font-weight: 600; }
#primary:hover { background: #f7b84d; }
QPushButton:disabled, #primary:disabled { color: #71717a; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); }
#speak { padding: 4px 8px; font-size: 10pt; }
#close { background: transparent; border: none; padding: 0 4px; font-size: 11pt; color: #a1a1aa; }
#close:hover { color: #f4f4f5; }
"""


def _key_down(vk: int) -> bool:
    return sys.platform == "win32" and bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class TranslationPopup(QWidget):
    replaceRequested = Signal(str)  # paste this over the selection
    speakRequested = Signal(str, str)  # text, language code
    stopRequested = Signal()
    closed = Signal()

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self.translation = ""
        self.target = ""
        self.speaking = False

        card = QFrame(objectName="card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self.direction = QLabel(objectName="direction")
        close = QPushButton("✕", objectName="close")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        header = QHBoxLayout()
        header.addWidget(self.direction)
        header.addStretch()
        header.addWidget(close)

        self.body = QLabel(objectName="body")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.PlainText)
        self.body.setMaximumWidth(MAX_WIDTH - 32)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.body)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setStyleSheet("background: transparent;")

        self.note = QLabel(objectName="note")
        self.note.setWordWrap(True)

        self.speak_button = QPushButton("🔊", objectName="speak")
        self.speak_button.setToolTip("Read the translation aloud")
        self.speak_button.clicked.connect(self._toggle_speech)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self._copy)
        self.replace_button = QPushButton("Replace selection", objectName="primary")
        self.replace_button.clicked.connect(self._replace)
        for button in (self.speak_button, self.copy_button, self.replace_button):
            button.setCursor(Qt.PointingHandCursor)
        buttons = QHBoxLayout()
        buttons.addWidget(self.note, 1)
        buttons.addWidget(self.speak_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.replace_button)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.scroll)
        layout.addLayout(buttons)

        self._watch = QTimer(self)
        self._watch.setInterval(40)
        self._watch.timeout.connect(self._check_outside_click)
        self._anchor = QPoint()
        self._grace = 0

    # ---- states -----------------------------------------------------------
    def show_loading(self, source: str, target: str) -> None:
        self._anchor = QCursor.pos()
        self.translation = ""
        self.target = target
        self.direction.setText(f"{NAMES.get(source, source)} → {NAMES.get(target, target)}")
        self.body.setText("Translating…")
        self.note.setText("")
        self._set_buttons(False)
        self._present()

    def show_result(self, text: str, note: str = "") -> None:
        self.translation = text
        self.body.setText(text)
        self.note.setText(note)
        self._set_buttons(True)
        self._present()

    def show_error(self, message: str) -> None:
        self.translation = ""
        self.body.setText(message)
        self.note.setText("")
        self._set_buttons(False)
        self._present()

    def dismiss(self) -> None:
        self._watch.stop()
        if self.speaking:
            self.stopRequested.emit()
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def set_speaking(self, speaking: bool) -> None:
        self.speaking = speaking
        self.speak_button.setText("■" if speaking else "🔊")
        self.speak_button.setToolTip("Stop reading" if speaking else "Read the translation aloud")

    def contains_cursor(self) -> bool:
        return self.isVisible() and self.frameGeometry().contains(QCursor.pos())

    def set_note(self, text: str) -> None:
        self.note.setText(text)

    def speak(self) -> None:
        if self.translation and not self.speaking:
            self.speakRequested.emit(self.translation, self.target)

    # ---- internals --------------------------------------------------------
    def _set_buttons(self, enabled: bool) -> None:
        for button in (self.speak_button, self.copy_button, self.replace_button):
            button.setEnabled(enabled)

    def _toggle_speech(self) -> None:
        if self.speaking:
            self.stopRequested.emit()
        else:
            self.speak()

    def _present(self) -> None:
        self.body.adjustSize()
        text_height = min(MAX_TEXT_HEIGHT, max(24, self.body.heightForWidth(MAX_WIDTH - 32)))
        self.scroll.setFixedHeight(text_height + 4)
        self.setFixedWidth(MAX_WIDTH if len(self.body.text()) > 50 else 380)
        self.adjustSize()
        self._place()
        if not self.isVisible():
            self._grace = 3  # ignore the mouse button state for the first few checks
            self.show()
        self.raise_()
        self._watch.start()

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(self._anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x, y = self._anchor.x() + 12, self._anchor.y() + 18
        if x + self.width() > area.right():
            x = area.right() - self.width() - 8
        if y + self.height() > area.bottom():
            y = self._anchor.y() - self.height() - 12  # above the cursor instead
        self.move(max(area.left() + 8, x), max(area.top() + 8, y))

    def _check_outside_click(self) -> None:
        if self._grace:
            self._grace -= 1
            return
        if _key_down(_VK_ESCAPE):
            self.dismiss()
            return
        if (_key_down(_VK_LBUTTON) or _key_down(_VK_RBUTTON)) and not self.frameGeometry().contains(QCursor.pos()):
            self.dismiss()

    def _copy(self) -> None:
        if self.translation:
            QGuiApplication.clipboard().setText(self.translation)
            self.note.setText("Copied")

    def _replace(self) -> None:
        if self.translation:
            text = self.translation
            self.dismiss()
            self.replaceRequested.emit(text)
