"""System tray icon and menu."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import APP_NAME


def make_icon(color: str = "#5b7cfa") -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 16, 16)
    p.setBrush(QColor("white"))
    p.drawRoundedRect(QRectF(25, 12, 14, 26), 7, 7)       # microphone body
    pen = QPen(QColor("white"), 4)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(17, 18, 30, 28), 180 * 16, 180 * 16)  # cradle
    p.drawLine(32, 46, 32, 53)
    p.drawLine(24, 53, 40, 53)
    p.end()
    return QIcon(pixmap)


def about_text() -> str:
    from .. import REPO_URL, __author__, __license__, __version__

    link = f'<br><a href="{REPO_URL}">{REPO_URL}</a>' if REPO_URL else ""
    return (
        f"<b>{APP_NAME} {__version__}</b><br>"
        "AI dictation and English ⇄ Turkish translation for Windows.<br><br>"
        f"Created by <b>{__author__}</b><br>"
        f"Released under the {__license__} License.{link}<br><br>"
        "Built with faster-whisper, Ollama and PySide6."
    )


def show_about() -> None:
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox()
    box.setWindowTitle(f"About {APP_NAME}")
    box.setIconPixmap(make_icon().pixmap(64, 64))
    box.setTextFormat(Qt.RichText)
    box.setText(about_text())
    box.exec()


class Tray(QSystemTrayIcon):
    engineChosen = Signal(str)
    cleanupChosen = Signal(str)
    translateToggled = Signal(bool)
    pauseToggled = Signal(bool)
    settingsRequested = Signal()
    historyRequested = Signal()
    quitRequested = Signal()

    def __init__(self, cfg):
        super().__init__(make_icon())
        self._icons = {"idle": make_icon(), "listening": make_icon("#e5484d"), "paused": make_icon("#8b8d98")}
        menu = QMenu()
        self.status_action = menu.addAction("Starting…")
        self.status_action.setEnabled(False)
        self.hint_action = menu.addAction("")
        self.hint_action.setEnabled(False)
        self.translate_hint_action = menu.addAction("")
        self.translate_hint_action.setEnabled(False)
        menu.addSeparator()

        engine_menu = menu.addMenu("Speech engine")
        group = QActionGroup(engine_menu)
        self.engine_actions = {}
        for key, label in (("local", "Local (Whisper on this PC)"), ("cloud", "Cloud API")):
            action = QAction(label, engine_menu, checkable=True)
            action.triggered.connect(lambda _checked, k=key: self.engineChosen.emit(k))
            group.addAction(action)
            engine_menu.addAction(action)
            self.engine_actions[key] = action

        cleanup_menu = menu.addMenu("Cleanup")
        cleanup_group = QActionGroup(cleanup_menu)
        self.cleanup_actions = {}
        for key, label in (("ollama", "Local (Ollama on this PC)"), ("cloud", "Cloud API"), ("off", "Off")):
            action = QAction(label, cleanup_menu, checkable=True)
            action.triggered.connect(lambda _checked, k=key: self.cleanupChosen.emit(k))
            cleanup_group.addAction(action)
            cleanup_menu.addAction(action)
            self.cleanup_actions[key] = action

        self.translate_action = menu.addAction("Translate mode (every dictation)")
        self.translate_action.setCheckable(True)
        self.translate_action.toggled.connect(self.translateToggled)

        self.pause_action = menu.addAction("Pause dictation")
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(self.pauseToggled)
        menu.addSeparator()
        menu.addAction("History…").triggered.connect(self.historyRequested)
        menu.addAction("Settings…").triggered.connect(self.settingsRequested)
        menu.addAction(f"About {APP_NAME}…").triggered.connect(show_about)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self.quitRequested)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.refresh(cfg)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.settingsRequested.emit()

    def refresh(self, cfg) -> None:
        self.engine_actions.get(cfg["stt_engine"], self.engine_actions["local"]).setChecked(True)
        current = cfg["cleanup_provider"] if cfg["cleanup_enabled"] else "off"
        self.cleanup_actions.get(current, self.cleanup_actions["ollama"]).setChecked(True)
        self.translate_action.blockSignals(True)
        self.translate_action.setChecked(bool(cfg["translate_mode"]))
        self.translate_action.blockSignals(False)
        target = {"en": "English", "tr": "Turkish"}.get(cfg["translate_target"], "the other language")
        selection = " · Ctrl+C twice on selected text" if cfg["selection_translate"] else ""
        self.translate_hint_action.setText(f"Hold {cfg['hotkey_translate']} to translate into {target}{selection}")
        self.hint_action.setText(f"Hold {cfg['hotkey_ptt']} to dictate · {cfg['hotkey_toggle']} hands-free")

    def set_status(self, text: str) -> None:
        self.status_action.setText(text)
        self.setToolTip(f"{APP_NAME}: {text}")

    def set_state(self, state: str) -> None:
        self.setIcon(self._icons.get(state, self._icons["idle"]))

    def warn(self, text: str) -> None:
        self.showMessage(APP_NAME, text, QSystemTrayIcon.Warning, 4000)
