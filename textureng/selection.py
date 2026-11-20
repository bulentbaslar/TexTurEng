"""Read selected text aloud from any app.

Windows has no "text was selected" event, so SelectionWatcher watches the mouse:
a drag across text, or a double-click on a word, probably selected something. The
app then shows a small 🔊 button next to the cursor. Clicking it copies the
selection with Ctrl+C, reads the text, and puts the previous clipboard back."""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QMimeData, QObject, Signal
from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)

DRAG_MIN_PIXELS = 12        # shorter movements are ordinary clicks
DOUBLE_CLICK_SECONDS = 0.45
DOUBLE_CLICK_PIXELS = 6


@dataclass
class Press:
    x: int
    y: int
    t: float
    window_rect: tuple | None  # foreground window position when the button went down


def foreground_rect() -> tuple | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    rect = wintypes.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (hwnd, rect.left, rect.top, rect.right, rect.bottom)


class GestureDetector:
    """Decides whether a left-button press/release looked like selecting text."""

    def __init__(self):
        self._press: Press | None = None
        self._last_click: Press | None = None

    def press(self, x: int, y: int, t: float, window_rect: tuple | None) -> None:
        self._press = Press(x, y, t, window_rect)

    def release(self, x: int, y: int, t: float, window_rect: tuple | None) -> bool:
        press, self._press = self._press, None
        if press is None:
            return False
        if press.window_rect != window_rect:
            self._last_click = None
            return False  # the window moved or resized: a title-bar drag, not a selection
        moved = abs(x - press.x) + abs(y - press.y)
        if moved >= DRAG_MIN_PIXELS:
            self._last_click = None
            return True   # drag-select
        last, self._last_click = self._last_click, Press(x, y, t, window_rect)
        if last and t - last.t <= DOUBLE_CLICK_SECONDS and abs(x - last.x) + abs(y - last.y) <= DOUBLE_CLICK_PIXELS:
            self._last_click = None
            return True   # double-click selects a word
        return False


class SelectionWatcher(QObject):
    """Global mouse listener. Signals arrive on the GUI thread."""

    maybeSelected = Signal()   # left button released after a selection gesture
    mousePressed = Signal()    # any button pressed anywhere

    def __init__(self):
        super().__init__()
        self.enabled = True
        self.detector = GestureDetector()
        self._listener = None

    def start(self) -> None:
        from pynput import mouse

        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x, y, button, pressed) -> None:
        try:
            from pynput.mouse import Button

            if pressed:
                self.mousePressed.emit()
            if button != Button.left or not self.enabled:
                return
            if pressed:
                self.detector.press(x, y, time.monotonic(), foreground_rect())
            elif self.detector.release(x, y, time.monotonic(), foreground_rect()):
                self.maybeSelected.emit()
        except Exception:
            log.exception("Mouse handling failed")


# ---- copying the selection without losing the clipboard -------------------------
def _clipboard_sequence() -> int:
    if sys.platform != "win32":
        return 0
    return int(ctypes.windll.user32.GetClipboardSequenceNumber())


def _copy_mime(source: QMimeData | None) -> QMimeData | None:
    if source is None or not source.formats():
        return None
    copy = QMimeData()
    for fmt in source.formats():
        copy.setData(fmt, source.data(fmt))
    return copy


def copy_selection(timeout: float = 0.6) -> str:
    """Press Ctrl+C in the focused app, read the copied text, restore the clipboard.
    Returns "" when nothing was copied (nothing selected)."""
    from PySide6.QtCore import QCoreApplication
    from pynput.keyboard import Controller, Key

    clipboard = QGuiApplication.clipboard()
    saved = _copy_mime(clipboard.mimeData())
    before = _clipboard_sequence()
    keyboard = Controller()
    with keyboard.pressed(Key.ctrl):
        keyboard.press("c")
        keyboard.release("c")
    deadline = time.monotonic() + timeout
    while _clipboard_sequence() == before and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    if _clipboard_sequence() == before:
        return ""
    time.sleep(0.03)  # let the other app finish writing every format
    QCoreApplication.processEvents()
    text = clipboard.text().strip()
    if saved is not None:
        _restore_clipboard(saved)
    return text


def _restore_clipboard(saved: QMimeData, attempts: int = 20) -> None:
    """Put saved clipboard contents back. Right after a copy, Windows clipboard
    history or a clipboard manager may hold the clipboard open, so setting it can
    fail; check and retry for up to about two seconds."""
    from PySide6.QtCore import QCoreApplication

    clipboard = QGuiApplication.clipboard()
    for _ in range(attempts):
        clipboard.setMimeData(_copy_mime(saved))  # Qt takes ownership: give it a copy
        QCoreApplication.processEvents()
        current = clipboard.mimeData()
        if current is not None and current.formats() and current.text() == saved.text():
            return
        time.sleep(0.1)
    log.warning("could not restore the clipboard (another program kept it open)")
