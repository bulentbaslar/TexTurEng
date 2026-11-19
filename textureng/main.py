"""GUI entry point: tray app that wires hotkeys, recorder, pipeline and injection."""
from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QLockFile, QObject, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import cleanup
from .audio import SAMPLE_RATE, Recorder
from .config import APP_NAME, Config, app_dir
from .context import AppInfo, get_foreground_app
from .history import History
from .hotkey import HotkeyManager
from .inject import Injector
from .pipeline import PipelineWorker, Result
from .selection import SelectionWatcher, copy_selection
from .tts import Speaker
from .ui.speak_bubble import SpeakBubble
from .ui.history_window import HistoryWindow
from .ui.overlay import Overlay
from .ui.settings import SettingsWindow
from .ui.translation_popup import TranslationPopup
from .ui.tray import Tray

log = logging.getLogger(__name__)
MIN_SECONDS = 0.35  # shorter recordings are treated as an accidental tap


def setup_logging() -> None:
    handler = RotatingFileHandler(app_dir() / "textureng.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler] + ([logging.StreamHandler()] if sys.stderr else []),
    )
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class Controller(QObject):
    requestProcess = Signal(object, object, bool)
    requestTextTranslation = Signal(str, int)
    requestPrepare = Signal()

    def __init__(self, app: QApplication, cfg: Config):
        super().__init__()
        self.app, self.cfg = app, cfg
        self.recorder = Recorder(cfg["mic_device"])
        self.overlay = Overlay(self.recorder)
        self.history = History()
        self.injector = Injector()
        self.popup = TranslationPopup()
        self.popup.replaceRequested.connect(self.replace_selection)
        self.speaker = Speaker(cfg)
        self._speech_owner = "popup"  # which window started the current speech
        self.popup.speakRequested.connect(lambda text, lang: self._speak(text, lang, "popup"))
        self.popup.stopRequested.connect(self.speaker.stop)
        self.speaker.started.connect(lambda: self._speech_ui().set_speaking(True))
        self.speaker.finished.connect(lambda: self._speech_ui().set_speaking(False))
        self.speaker.status.connect(self.on_speech_status)
        self.speaker.failed.connect(self.on_speech_failed)

        # 🔊 button next to selected text in any app
        self.bubble = SpeakBubble()
        self.bubble.speakClicked.connect(self.read_selection_aloud)
        self.bubble.stopClicked.connect(self.speaker.stop)
        self.watcher = SelectionWatcher()
        self.watcher.enabled = bool(cfg["read_selection_button"])
        self.watcher.maybeSelected.connect(self.on_maybe_selected)
        self.watcher.mousePressed.connect(self.on_mouse_pressed)
        self.watcher.start()
        self._popup_request = 0
        self.target = AppInfo()
        self.busy = False
        self.translating = False  # the current recording will be translated
        self._key_version = 0
        self._engine_signature = self._signature()
        self._windows: dict[str, object] = {}

        self.tray = Tray(cfg)
        self.tray.engineChosen.connect(self.choose_engine)
        self.tray.cleanupChosen.connect(self.choose_cleanup)
        self.tray.translateToggled.connect(self.set_translate_mode)
        self.tray.pauseToggled.connect(self.set_paused)
        self.tray.settingsRequested.connect(self.open_settings)
        self.tray.historyRequested.connect(self.open_history)
        self.tray.quitRequested.connect(self.quit)
        self.tray.show()

        self.thread = QThread()
        self.worker = PipelineWorker(cfg)
        self.worker.moveToThread(self.thread)
        self.requestProcess.connect(self.worker.process)
        self.requestPrepare.connect(self.worker.prepare)
        self.requestTextTranslation.connect(self.worker.translate_selection)
        self.worker.textTranslated.connect(self.on_text_translated)
        self.worker.finished.connect(self.on_result)
        self.worker.failed.connect(self.on_failed)
        self.worker.status.connect(self.on_status)
        self.thread.start()
        self.requestPrepare.emit()

        self.hotkeys = HotkeyManager(cfg)
        self.hotkeys.started.connect(self.start_recording)
        self.hotkeys.translateOn.connect(self.switch_to_translation)
        self.hotkeys.doubleCopy.connect(self.translate_selection)
        self.hotkeys.stopped.connect(self.stop_recording)
        self.hotkeys.cancelled.connect(self.cancel_recording)
        self.hotkeys.start()

    def _signature(self) -> tuple:
        c = self.cfg
        return (c["stt_engine"], c["local_model"], c["local_device"], c["cloud_base_url"],
                c["cloud_model"], c["cleanup_enabled"], c["ollama_url"], c["ollama_model"],
                c["cleanup_provider"], c["cloud_cleanup_model"], self._key_version)

    # ---- recording --------------------------------------------------------
    def start_recording(self, translate: bool = False) -> None:
        if self.busy:
            self.hotkeys.force_stop()
            return
        self.target = get_foreground_app()
        self.translating = bool(translate or self.cfg["translate_mode"])
        try:
            self.recorder.start()
        except Exception as exc:
            log.exception("Could not open the microphone")
            self.hotkeys.force_stop()
            self.overlay.show_mode("error")
            self.tray.warn(f"Microphone problem: {exc}")
            return
        self.tray.set_state("listening")
        self.overlay.show_mode("listening", translate=self.translating)

    def switch_to_translation(self) -> None:
        if self.recorder.recording:
            self.translating = True
            self.overlay.set_translate(True)

    def stop_recording(self) -> None:
        if not self.recorder.recording:
            return
        audio = self.recorder.stop()
        self.tray.set_state("idle")
        if len(audio) < MIN_SECONDS * SAMPLE_RATE:
            self.overlay.dismiss()
            return
        self.busy = True
        self.overlay.show_mode("processing", translate=self.translating)
        self.requestProcess.emit(audio, self.target, self.translating)

    def cancel_recording(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()
        self.tray.set_state("idle")
        self.overlay.dismiss()

    # ---- translating selected text (Ctrl+C twice) -------------------------
    def translate_selection(self) -> None:
        # The second Ctrl+C is still being handled by the other app; read the
        # clipboard once its copy has landed.
        QTimer.singleShot(150, self._translate_clipboard)

    def _translate_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        self._popup_request += 1
        if not text:
            self.popup.show_loading("", "")
            self.popup.direction.setText("Translate selection")
            self.popup.show_error("No text found. Select some text, then press Ctrl+C twice.")
            return
        source, target = cleanup.selection_direction(text, self.cfg["translate_target"])
        self.popup.show_loading(source, target)
        self.requestTextTranslation.emit(text, self._popup_request)

    def on_text_translated(self, result, request_id: int) -> None:
        log.info("selection translated %s->%s (%d chars)%s", result.source, result.target,
                 len(result.text), f" error: {result.error}" if result.error else "")
        if request_id != self._popup_request or not self.popup.isVisible():
            return  # the popup was closed or a newer selection was sent
        if result.error:
            self.popup.show_error(f"Could not translate: {result.error}.")
            return
        note = "Only the first 4,000 characters were translated." if result.truncated else ""
        self.popup.show_result(result.text, note)
        if self.cfg["tts_auto_read"]:
            self.popup.speak()

    # ---- reading aloud -------------------------------------------------------
    def _speech_ui(self):
        return self.bubble if self._speech_owner == "bubble" else self.popup

    def _speak(self, text: str, lang: str, owner: str) -> None:
        if self.speaker.speaking:
            self._speech_ui().set_speaking(False)
        self._speech_owner = owner
        self.speaker.speak(text, lang)

    def on_speech_status(self, text: str) -> None:
        if self._speech_owner == "bubble":
            self.bubble.set_message(text)
        else:
            self.popup.set_note(text)

    def on_speech_failed(self, message: str) -> None:
        log.warning("Speech failed: %s", message)
        if self._speech_owner == "popup" and self.popup.isVisible():
            self.popup.set_note(message)
        else:
            self.bubble.set_message("")
            self.bubble.dismiss()
            self.tray.warn(message)

    def on_maybe_selected(self) -> None:
        if (not self.hotkeys.enabled or self.recorder.recording or self.bubble.speaking
                or self.popup.contains_cursor() or self.bubble.contains_cursor()):
            return
        self.bubble.show_near_cursor()

    def on_mouse_pressed(self) -> None:
        if self.bubble.isVisible() and not self.bubble.contains_cursor():
            self.bubble.dismiss()

    def read_selection_aloud(self) -> None:
        self.hotkeys.ignore_copy_until = time.monotonic() + 1.0  # our Ctrl+C is not a "Ctrl+C twice"
        text = copy_selection()
        if not text:
            self.bubble.set_message("No text selected", seconds=2)
            return
        lang = "tr" if cleanup.looks_turkish(text) else "en"
        log.info("reading selection aloud (%s, %d chars)", lang, len(text))
        self._speak(text[: cleanup.MAX_SELECTION_CHARS], lang, "bubble")

    def replace_selection(self, text: str) -> None:
        self.injector.inject(text, self.cfg["inject_method"])

    # ---- results ----------------------------------------------------------
    def on_result(self, result: Result) -> None:
        self.busy = False
        self.overlay.dismiss()
        if not result.text:
            return
        method = "type" if result.app.process in self.cfg["type_apps"] else self.cfg["inject_method"]
        text = result.text + (" " if self.cfg["append_space"] else "")
        self.injector.inject(text, method)
        if result.warning:
            self.tray.warn(result.warning)
        if self.cfg["history_enabled"]:
            try:
                self.history.add(
                    result.app.process, result.profile, result.language, result.raw, result.text,
                    translated_to=result.translated_to,
                )
            except Exception:
                log.exception("Could not save history")

    def on_failed(self, message: str) -> None:
        self.busy = False
        self.overlay.show_mode("error")
        self.tray.warn(f"Dictation failed: {message}")

    def on_status(self, text: str) -> None:
        self.tray.set_status(text)
        if text not in ("Ready", "Loading speech model…"):
            self.tray.warn(text)

    # ---- tray actions -----------------------------------------------------
    def choose_engine(self, engine: str) -> None:
        if engine != self.cfg["stt_engine"]:
            self.cfg["stt_engine"] = engine
            self.cfg.save()
            self.apply_settings()

    def choose_cleanup(self, choice: str) -> None:
        self.cfg["cleanup_enabled"] = choice != "off"
        if choice != "off":
            self.cfg["cleanup_provider"] = choice
        self.cfg.save()
        self.apply_settings()

    def set_translate_mode(self, on: bool) -> None:
        self.cfg["translate_mode"] = on
        self.cfg.save()

    def set_paused(self, paused: bool) -> None:
        self.hotkeys.enabled = not paused
        if paused:
            self.popup.dismiss()
            self.bubble.dismiss()
            self.speaker.stop()
            self.cancel_recording()
            self.hotkeys.force_stop()
        self.tray.set_state("paused" if paused else "idle")

    def apply_settings(self) -> None:
        self.recorder.device_name = self.cfg["mic_device"]
        self.hotkeys.reload(self.cfg)
        self.watcher.enabled = bool(self.cfg["read_selection_button"])
        self.tray.refresh(self.cfg)
        if self._signature() != self._engine_signature:
            self._engine_signature = self._signature()
            self.requestPrepare.emit()

    def open_settings(self) -> None:
        window = SettingsWindow(self.cfg)
        window.saved.connect(self.apply_settings)
        window.keyChanged.connect(self._on_key_changed)
        self._show("settings", window)

    def _on_key_changed(self) -> None:
        self._key_version += 1  # makes apply_settings reload the engines with the new key

    def open_history(self) -> None:
        self._show("history", HistoryWindow(self.history))

    def _show(self, name: str, window) -> None:
        old = self._windows.get(name)
        if old is not None:
            old.close()
        self._windows[name] = window
        window.show()
        window.raise_()
        window.activateWindow()

    def quit(self) -> None:
        self.speaker.stop()
        self.watcher.stop()
        self.hotkeys.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self.thread.quit()
        self.thread.wait(3000)
        self.tray.hide()
        self.app.quit()


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(app_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running (see the system tray).")
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "No system tray is available.")
        return 1

    from .migrate import migrate_from_voxpolish

    migrate_from_voxpolish()  # settings, history, key and startup entry from the old name
    cfg = Config()
    if not cfg.existed:
        from .ui.welcome import first_run

        first_run(cfg)
    controller = Controller(app, cfg)
    app.aboutToQuit.connect(lock.unlock)
    log.info("%s started", APP_NAME)
    code = app.exec()
    del controller
    return code


if __name__ == "__main__":
    sys.exit(main())
