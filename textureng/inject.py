"""Put text into the focused window: clipboard paste (default) or simulated typing.

Runs on the GUI thread because it uses the Qt clipboard. The previous clipboard
content is restored after the paste."""
from __future__ import annotations

import logging

from PySide6.QtCore import QMimeData, QObject, QTimer
from PySide6.QtGui import QGuiApplication

from .hotkey import modifiers_down

log = logging.getLogger(__name__)

# Keeps dictated text out of Windows clipboard history (Win+V) and cloud sync.
_EXCLUDE_FORMATS = (
    'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"',
    'application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"',
    'application/x-qt-windows-mime;value="CanUploadToCloudClipboard"',
)
PASTE_DELAY_MS = 60
RESTORE_DELAY_MS = 450


def _copy_mime(source: QMimeData | None) -> QMimeData | None:
    if source is None or not source.formats():
        return None
    copy = QMimeData()
    for fmt in source.formats():
        copy.setData(fmt, source.data(fmt))
    return copy


class Injector(QObject):
    def __init__(self):
        super().__init__()
        self._saved: QMimeData | None = None
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore)

    def inject(self, text: str, method: str = "paste") -> None:
        if not text:
            return
        self._wait_for_modifiers(text, method, tries=75)

    def _wait_for_modifiers(self, text: str, method: str, tries: int) -> None:
        # A held Ctrl/Win/Alt would turn the paste into some other shortcut.
        if tries > 0 and modifiers_down():
            QTimer.singleShot(20, lambda: self._wait_for_modifiers(text, method, tries - 1))
            return
        if method == "type":
            self._type(text)
        else:
            self._paste(text)

    def _type(self, text: str) -> None:
        from pynput.keyboard import Controller

        try:
            Controller().type(text)
        except Exception:
            log.exception("Typing failed; falling back to paste")
            self._paste(text)

    def _paste(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if not self._restore_timer.isActive():  # otherwise keep the older saved content
            self._saved = _copy_mime(clipboard.mimeData())
        self._restore_timer.stop()
        mime = QMimeData()
        mime.setText(text)
        for fmt in _EXCLUDE_FORMATS:
            mime.setData(fmt, b"\x00\x00\x00\x00")
        clipboard.setMimeData(mime)
        QTimer.singleShot(PASTE_DELAY_MS, self._send_paste)
        self._restore_timer.start(RESTORE_DELAY_MS)

    def _send_paste(self) -> None:
        from pynput.keyboard import Controller, Key

        keyboard = Controller()
        with keyboard.pressed(Key.ctrl):
            keyboard.press("v")
            keyboard.release("v")

    def _restore(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if self._saved is not None:
            clipboard.setMimeData(self._saved)
        else:
            clipboard.clear()
        self._saved = None
