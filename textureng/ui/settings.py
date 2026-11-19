"""Settings window."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import APP_NAME

log = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):  # installed build: the exe is the app
        return f'"{sys.executable}"'
    launcher = Path(__file__).resolve().parents[2] / "run.pyw"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{launcher}"'


def startup_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass


def _combo(options: list[tuple[str, str]], current: str) -> QComboBox:
    box = QComboBox()
    for value, label in options:
        box.addItem(label, value)
    index = box.findData(current)
    box.setCurrentIndex(index if index >= 0 else 0)
    return box


class SettingsWindow(QDialog):
    saved = Signal()
    keyChanged = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(f"{APP_NAME} settings")
        self.resize(620, 560)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._speech_tab(), "Speech")
        tabs.addTab(self._cleanup_tab(), "Cleanup")
        tabs.addTab(self._voice_tab(), "Voice")
        tabs.addTab(self._profiles_tab(), "App styles")
        tabs.addTab(self._dictionary_tab(), "Dictionary")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        from .. import __author__, __version__

        credit = QLabel(f"{APP_NAME} {__version__} · by {__author__} · MIT License")
        credit.setStyleSheet("color: gray;")
        footer = QHBoxLayout()
        footer.addWidget(credit)
        footer.addStretch()
        footer.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(footer)

    # ---- tabs -------------------------------------------------------------
    def _general_tab(self) -> QWidget:
        cfg = self.cfg
        page = QWidget()
        form = QFormLayout(page)
        self.ptt = QLineEdit(cfg["hotkey_ptt"])
        self.toggle = QLineEdit(cfg["hotkey_toggle"])
        self.cancel = QLineEdit(cfg["hotkey_cancel"])
        self.translate_hk = QLineEdit(cfg["hotkey_translate"])
        form.addRow("Hold to talk", self.ptt)
        form.addRow("Hold to translate", self.translate_hk)
        form.addRow("Hands-free on/off", self.toggle)
        form.addRow("Cancel", self.cancel)
        form.addRow("", QLabel("Write keys joined by +, for example ctrl+win, alt+shift+d, f9."))

        self.mic = QComboBox()
        self.mic.addItem("System default", "")
        try:
            from ..audio import list_input_devices

            for name in list_input_devices():
                self.mic.addItem(name, name)
        except Exception:
            log.exception("Could not list microphones")
        index = self.mic.findData(cfg["mic_device"])
        self.mic.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Microphone", self.mic)

        self.language = _combo(
            [("auto", "Auto (English / Turkish)"), ("en", "English"), ("tr", "Türkçe")], cfg["language"]
        )
        form.addRow("Language", self.language)
        self.translate_target = _combo(
            [("auto", "The other language (English ⇄ Turkish)"), ("en", "Always English"), ("tr", "Always Turkish")],
            cfg["translate_target"],
        )
        form.addRow("Translate into", self.translate_target)
        self.selection_translate = QCheckBox("Translate selected text: select it anywhere and press Ctrl+C twice")
        self.selection_translate.setChecked(cfg["selection_translate"])
        form.addRow("", self.selection_translate)
        self.inject = _combo(
            [("paste", "Paste (fast, restores clipboard)"), ("type", "Type characters")], cfg["inject_method"]
        )
        form.addRow("Insert text by", self.inject)
        self.type_apps = QLineEdit(", ".join(cfg["type_apps"]))
        self.type_apps.setPlaceholderText("e.g. putty.exe, mstsc.exe")
        form.addRow("Always type in", self.type_apps)
        self.append_space = QCheckBox("Add a space after each dictation")
        self.append_space.setChecked(cfg["append_space"])
        form.addRow("", self.append_space)
        self.history = QCheckBox("Keep a history of dictations on this PC")
        self.history.setChecked(cfg["history_enabled"])
        form.addRow("", self.history)
        self.startup = QCheckBox("Start with Windows")
        self.startup.setChecked(startup_enabled())
        form.addRow("", self.startup)
        return page

    def _speech_tab(self) -> QWidget:
        cfg = self.cfg
        page = QWidget()
        form = QFormLayout(page)
        self.engine = _combo([("local", "Local (Whisper on this PC)"), ("cloud", "Cloud API")], cfg["stt_engine"])
        form.addRow("Engine", self.engine)
        self.local_model = QComboBox()
        self.local_model.setEditable(True)
        self.local_model.addItems(["large-v3-turbo", "large-v3", "medium", "small", "base"])
        self.local_model.setCurrentText(cfg["local_model"])
        form.addRow("Local model", self.local_model)
        self.local_device = _combo(
            [("auto", "Auto (GPU if available)"), ("cuda", "GPU (CUDA)"), ("cpu", "CPU")], cfg["local_device"]
        )
        form.addRow("Run on", self.local_device)
        self.cloud_url = QLineEdit(cfg["cloud_base_url"])
        form.addRow("Cloud base URL", self.cloud_url)
        self.cloud_model = QLineEdit(cfg["cloud_model"])
        form.addRow("Cloud model", self.cloud_model)
        self.cloud_key = QLineEdit()
        self.cloud_key.setEchoMode(QLineEdit.Password)
        self.cloud_key.setPlaceholderText("Leave empty to keep the saved key")
        form.addRow("Cloud API key", self.cloud_key)
        form.addRow("", QLabel("The key is stored in Windows Credential Manager and is used for\n"
                               "both cloud speech and cloud cleanup.\n"
                               "Any OpenAI-compatible transcription endpoint works (Groq, OpenAI)."))
        return page

    def _cleanup_tab(self) -> QWidget:
        cfg = self.cfg
        page = QWidget()
        form = QFormLayout(page)
        self.cleanup_enabled = QCheckBox("Polish text with AI (remove fillers, fix grammar, format)")
        self.cleanup_enabled.setChecked(cfg["cleanup_enabled"])
        form.addRow("", self.cleanup_enabled)
        self.cleanup_provider = _combo(
            [("ollama", "Local (Ollama on this PC)"), ("cloud", "Cloud API")], cfg["cleanup_provider"]
        )
        form.addRow("Run cleanup on", self.cleanup_provider)
        self.ollama_url = QLineEdit(cfg["ollama_url"])
        form.addRow("Ollama address", self.ollama_url)
        from ..cleanup import list_ollama_models

        installed = list_ollama_models(cfg["ollama_url"])
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.ollama_model.addItems(installed or [])
        self.ollama_model.setCurrentText(cfg["ollama_model"])
        form.addRow("Ollama model", self.ollama_model)
        form.addRow("", QLabel(
            "The list shows the models installed in Ollama on this PC."
            if installed is not None else "Ollama is not running on this PC right now."
        ))
        self.cloud_cleanup_model = QLineEdit(cfg["cloud_cleanup_model"])
        form.addRow("Cloud model", self.cloud_cleanup_model)
        form.addRow("", QLabel("Cloud cleanup uses the base URL and API key from the Speech tab.\n"
                               "When the cleanup service is not reachable the raw transcript is pasted."))
        return page

    def _voice_tab(self) -> QWidget:
        from ..tts import NEURAL_VOICES, neural_available, voice_for

        cfg = self.cfg
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("", QLabel("The 🔊 button in the translation popup reads the translation aloud."))
        has_neural = neural_available()
        self.tts_engine = _combo(
            [("auto", "Natural voice (downloaded once, works offline)"), ("windows", "Windows voice")],
            cfg["tts_engine"] if has_neural else "windows",
        )
        self.tts_engine.setEnabled(has_neural)
        form.addRow("Voice type", self.tts_engine)
        self.tts_voices = {}
        for lang, label in (("en", "English voice"), ("tr", "Turkish voice")):
            box = _combo([(v.id, v.label) for v in NEURAL_VOICES[lang]], voice_for(cfg, lang))
            box.setEnabled(has_neural)
            for i, voice in enumerate(NEURAL_VOICES[lang]):
                box.setItemData(i, f"Licence: {voice.licence}", Qt.ToolTipRole)
            form.addRow(label, box)
            self.tts_voices[lang] = box
        self.tts_speed = _combo(
            [(0.8, "Slower"), (0.9, "A little slower"), (1.0, "Normal"), (1.15, "A little faster"), (1.3, "Faster")],
            cfg["tts_speed"],
        )
        form.addRow("Speed", self.tts_speed)
        self.tts_auto_read = QCheckBox("Read every popup translation aloud automatically")
        self.tts_auto_read.setChecked(cfg["tts_auto_read"])
        form.addRow("", self.tts_auto_read)
        self.read_selection_button = QCheckBox("Show a 🔊 button when you select text in any app, to read it aloud")
        self.read_selection_button.setChecked(cfg["read_selection_button"])
        form.addRow("", self.read_selection_button)
        note = (
            "Natural voices download about 65 MB per language the first time they are used."
            if has_neural
            else "Natural voices are not included in this version; the voices built into Windows are used.\n"
                 "For Turkish, add a Turkish voice in Windows Settings > Time & language > Speech."
        )
        form.addRow("", QLabel(note))
        return page

    def _profiles_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("How text is written in each kind of app. Programs are matched by .exe name."))
        self.profile_fields = {}
        for key, profile in self.cfg["profiles"].items():
            layout.addWidget(QLabel(f"<b>{profile.get('name', key)}</b>"))
            processes = None
            if key != "default":
                processes = QLineEdit(", ".join(profile.get("processes", [])))
                layout.addWidget(processes)
            style = QPlainTextEdit(profile.get("style", ""))
            style.setFixedHeight(58)
            layout.addWidget(style)
            self.profile_fields[key] = (processes, style)
        return page

    def _dictionary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Names and terms to spell exactly, one per line."))
        self.dictionary = QPlainTextEdit("\n".join(self.cfg["dictionary"]))
        layout.addWidget(self.dictionary)
        return page

    # ---- save -------------------------------------------------------------
    @staticmethod
    def _split(text: str) -> list[str]:
        return [part.strip().lower() for part in text.split(",") if part.strip()]

    def _save(self) -> None:
        cfg = self.cfg
        cfg["hotkey_ptt"] = self.ptt.text().strip().lower() or "ctrl+win"
        cfg["hotkey_toggle"] = self.toggle.text().strip().lower()
        cfg["hotkey_cancel"] = self.cancel.text().strip().lower()
        cfg["hotkey_translate"] = self.translate_hk.text().strip().lower()
        cfg["translate_target"] = self.translate_target.currentData()
        cfg["selection_translate"] = self.selection_translate.isChecked()
        if self.tts_engine.isEnabled():
            cfg["tts_engine"] = self.tts_engine.currentData()
            for lang, box in self.tts_voices.items():
                cfg[f"tts_voice_{lang}"] = box.currentData()
        cfg["tts_speed"] = self.tts_speed.currentData()
        cfg["tts_auto_read"] = self.tts_auto_read.isChecked()
        cfg["read_selection_button"] = self.read_selection_button.isChecked()
        cfg["mic_device"] = self.mic.currentData()
        cfg["language"] = self.language.currentData()
        cfg["inject_method"] = self.inject.currentData()
        cfg["type_apps"] = self._split(self.type_apps.text())
        cfg["append_space"] = self.append_space.isChecked()
        cfg["history_enabled"] = self.history.isChecked()
        cfg["stt_engine"] = self.engine.currentData()
        cfg["local_model"] = self.local_model.currentText().strip() or "large-v3-turbo"
        cfg["local_device"] = self.local_device.currentData()
        cfg["cloud_base_url"] = self.cloud_url.text().strip()
        cfg["cloud_model"] = self.cloud_model.text().strip()
        cfg["cleanup_enabled"] = self.cleanup_enabled.isChecked()
        cfg["cleanup_provider"] = self.cleanup_provider.currentData()
        cfg["cloud_cleanup_model"] = self.cloud_cleanup_model.text().strip()
        cfg["ollama_url"] = self.ollama_url.text().strip()
        cfg["ollama_model"] = self.ollama_model.currentText().strip()
        for key, (processes, style) in self.profile_fields.items():
            if processes is not None:
                cfg["profiles"][key]["processes"] = self._split(processes.text())
            cfg["profiles"][key]["style"] = style.toPlainText().strip()
        cfg["dictionary"] = [line.strip() for line in self.dictionary.toPlainText().splitlines() if line.strip()]
        cfg.save()
        try:
            if self.cloud_key.text().strip():
                from ..stt.cloud import set_api_key

                set_api_key(self.cloud_key.text().strip())
                self.keyChanged.emit()
            if self.startup.isChecked() != startup_enabled():
                set_startup(self.startup.isChecked())
        except Exception:
            log.exception("Saving the API key or startup entry failed")
        self.saved.emit()
        self.accept()
