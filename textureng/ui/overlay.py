"""Floating pill at the bottom of the screen. Never takes focus or mouse input."""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

BARS = 22
WIDTH, HEIGHT = 176, 44
TRANSLATE_COLOR = QColor(245, 165, 36)  # amber: this dictation will be translated


class Overlay(QWidget):
    def __init__(self, recorder):
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
            | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(WIDTH, HEIGHT)
        self.recorder = recorder
        self.mode = "hidden"  # hidden | listening | processing | error
        self.translate = False  # amber colouring while a translation is recorded / processed
        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

    def set_translate(self, on: bool) -> None:
        self.translate = on
        self.update()

    def show_mode(self, mode: str, translate: bool = False) -> None:
        self._hide_timer.stop()
        self.mode = mode
        self.translate = translate
        if mode == "listening":
            self.levels.extend([0.0] * BARS)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - WIDTH // 2, area.bottom() - HEIGHT - 28)
        self.show()
        self._timer.start()
        if mode == "error":
            self._hide_timer.start(1600)

    def dismiss(self) -> None:
        self.mode = "hidden"
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        if self.mode == "listening":
            self.levels.append(self.recorder.level)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, WIDTH - 2, HEIGHT - 2)
        painter.setPen(QColor(255, 255, 255, 40))
        painter.setBrush(QColor(18, 18, 22, 235))
        painter.drawRoundedRect(rect, HEIGHT / 2, HEIGHT / 2)
        painter.setPen(Qt.NoPen)
        mid = HEIGHT / 2
        if self.mode == "listening":
            painter.setBrush(TRANSLATE_COLOR if self.translate else QColor(255, 255, 255))
            step = (WIDTH - 48) / BARS
            for i, level in enumerate(self.levels):
                h = 3 + min(1.0, level) ** 0.6 * 24
                painter.drawRoundedRect(QRectF(24 + i * step, mid - h / 2, 3, h), 1.5, 1.5)
        elif self.mode == "processing":
            phase = time.monotonic() * 5
            for i in range(3):
                alpha = int(110 + 145 * (0.5 + 0.5 * math.sin(phase - i * 0.9)))
                base = TRANSLATE_COLOR if self.translate else QColor(140, 170, 255)
                painter.setBrush(QColor(base.red(), base.green(), base.blue(), alpha))
                painter.drawEllipse(QRectF(WIDTH / 2 - 21 + i * 16, mid - 5, 10, 10))
        elif self.mode == "error":
            painter.setBrush(QColor(255, 95, 95))
            painter.drawRoundedRect(QRectF(WIDTH / 2 - 30, mid - 2, 60, 4), 2, 2)
        painter.end()
