"""Listening indicator: a rounded box in the middle of the screen with a white
microphone and sound waves on both sides that follow your voice.

Red while dictating (Ctrl+Win), orange while dictating to translate (Ctrl+Win+Alt).
It never takes focus or mouse input."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

BOX = 150          # size of the coloured box
MARGIN = 12        # room for the soft shadow around it
SIZE = BOX + 2 * MARGIN
WAVES = 3          # arcs on each side of the microphone

# (top, bottom) colours of the box
DICTATE_COLORS = (QColor(242, 51, 63), QColor(196, 18, 31))     # red
TRANSLATE_COLORS = (QColor(255, 166, 43), QColor(240, 118, 0))   # orange
ERROR_COLORS = (QColor(113, 113, 122), QColor(63, 63, 70))       # grey
TRANSLATE_COLOR = TRANSLATE_COLORS[1]  # kept for other modules


def box_colors(mode: str, translate: bool) -> tuple[QColor, QColor]:
    if mode == "error":
        return ERROR_COLORS
    return TRANSLATE_COLORS if translate else DICTATE_COLORS


def lit_waves(level: float) -> int:
    """How many arcs on each side light up for a microphone level of 0..1."""
    return sum(level >= 0.06 + i * 0.2 for i in range(WAVES))


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
        self.setFixedSize(SIZE, SIZE)
        self.recorder = recorder
        self.mode = "hidden"     # hidden | listening | processing | error
        self.translate = False   # orange box while a translation is recorded / processed
        self.level = 0.0         # smoothed microphone level
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
            self.level = 0.0
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        center = screen.availableGeometry().center()
        self.move(center.x() - SIZE // 2, center.y() - SIZE // 2)
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
            # rise at once with the voice, fall back gently
            self.level = max(float(self.recorder.level), self.level * 0.82)
        self.update()

    # ---- drawing -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(MARGIN, MARGIN, BOX, BOX)
        radius = BOX * 0.22

        # soft shadow
        p.setPen(Qt.NoPen)
        for i in range(MARGIN, 0, -3):
            p.setBrush(QColor(0, 0, 0, 10))
            p.drawRoundedRect(box.adjusted(-i / 2, -i / 2 + 3, i / 2, i / 2 + 3), radius + i / 2, radius + i / 2)

        top, bottom = box_colors(self.mode, self.translate)
        gradient = QLinearGradient(box.topLeft(), box.bottomLeft())
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, bottom)
        p.setBrush(gradient)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawRoundedRect(box, radius, radius)

        cx = box.center().x()
        head_y = box.center().y() - 16      # centre of the microphone head
        self._draw_waves(p, cx, head_y)
        self._draw_microphone(p, cx, head_y)
        p.end()

    def _wave_alphas(self) -> list[int]:
        if self.mode == "listening":
            lit = lit_waves(self.level)
            return [255 if i < lit else 70 for i in range(WAVES)]
        if self.mode == "processing":  # waves travel outwards while the text is prepared
            phase = time.monotonic() * 6
            return [int(70 + 185 * max(0.0, math.sin(phase - i * 0.9))) for i in range(WAVES)]
        return [70] * WAVES

    def _draw_waves(self, p: QPainter, cx: float, cy: float) -> None:
        for i, alpha in enumerate(self._wave_alphas()):
            r = 34 + i * 13
            pen = QPen(QColor(255, 255, 255, alpha), 5.5)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            p.drawArc(rect, -40 * 16, 80 * 16)    # right side
            p.drawArc(rect, 140 * 16, 80 * 16)    # left side

    def _draw_microphone(self, p: QPainter, cx: float, cy: float) -> None:
        white = QColor(255, 255, 255)
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(cx - 13, cy - 26, 26, 50), 13, 13)        # head
        pen = QPen(white, 5.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - 22, cy - 6, 44, 44), 180 * 16, 180 * 16)    # cradle
        p.drawLine(QPointF(cx, cy + 38), QPointF(cx, cy + 50))            # stand
        p.drawLine(QPointF(cx, cy + 50), QPointF(cx - 15, cy + 58))       # feet
        p.drawLine(QPointF(cx, cy + 50), QPointF(cx + 15, cy + 58))
