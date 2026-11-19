"""First-run setup, shown on PCs without a usable GPU.

Speech recognition and AI cleanup are chosen separately; each can run in the
cloud or on this PC. Everything can be changed later in Settings."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from .. import cleanup
from ..config import APP_NAME
from .settings import _combo, set_startup

log = logging.getLogger(__name__)
LAPTOP_OLLAMA_MODEL = "gemma3:4b"  # small enough to be usable without a big GPU


def has_local_gpu() -> bool:
    """True when CUDA speech recognition can work: a compatible GPU and the CUDA
    libraries (which the laptop installer does not include)."""
    try:
        import ctranslate2
        import nvidia  # noqa: F401  (cuBLAS / cuDNN wheels)

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def apply_choices(cfg, speech: str, cleanup_choice: str, ollama_model: str = "") -> None:
    """speech: cloud | local.  cleanup_choice: cloud | ollama | off."""
    cfg["stt_engine"] = speech
    if speech == "local":  # no GPU here: a small model on the CPU
        cfg["local_model"] = "small"
        cfg["local_device"] = "cpu"
    cfg["cleanup_enabled"] = cleanup_choice != "off"
    if cleanup_choice in ("cloud", "ollama"):
        cfg["cleanup_provider"] = cleanup_choice
    if cleanup_choice == "ollama" and ollama_model:
        cfg["ollama_model"] = ollama_model


class WelcomeDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setMinimumWidth(560)
        installed = cleanup.list_ollama_models(cfg["ollama_url"])
        ollama_found = installed is not None

        intro = QLabel(
            f"<b>{APP_NAME} turns your speech into polished text in any app.</b><br><br>"
            "It has two steps, and each can run in the cloud or on this PC:<br>"
            "&bull; <b>Speech recognition</b> turns your voice into text.<br>"
            "&bull; <b>Cleanup</b> removes filler words, fixes grammar and formats the text.<br><br>"
            "Cloud is fastest on a PC without a compatible graphics card, but sends your audio "
            "or text to the service and needs an API key "
            '(free at <a href="https://console.groq.com/keys">console.groq.com/keys</a>).'
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setOpenExternalLinks(True)

        form = QFormLayout()
        self.speech = _combo(
            [("cloud", "Cloud (fast)"), ("local", "On this PC (private, a few seconds per dictation)")], "cloud"
        )
        form.addRow("Speech recognition", self.speech)
        ollama_label = "Ollama on this PC (private)" + ("" if ollama_found else " (Ollama not detected)")
        self.cleanup = _combo(
            [("cloud", "Cloud (fast)"), ("ollama", ollama_label), ("off", "Off (paste what was heard)")],
            "ollama" if ollama_found else "cloud",
        )
        form.addRow("Cleanup", self.cleanup)
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.ollama_model.addItems(installed or [])
        self.ollama_model.setCurrentText(
            cfg["ollama_model"] if installed and cfg["ollama_model"] in installed
            else (installed[0] if installed else LAPTOP_OLLAMA_MODEL)
        )
        form.addRow("Ollama model", self.ollama_model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("gsk_…  (only needed for a Cloud choice above)")
        form.addRow("Cloud API key", self.key)
        self.language = _combo(
            [("auto", "Auto (English / Turkish)"), ("en", "English"), ("tr", "Türkçe")], cfg["language"]
        )
        form.addRow("Language", self.language)
        self.startup = QCheckBox("Start with Windows")
        self.startup.setChecked(True)
        form.addRow("", self.startup)

        self.note = QLabel()
        self.note.setWordWrap(True)
        hint = QLabel(
            f"Then hold <b>{cfg['hotkey_ptt']}</b> in any app, speak, and release. "
            f"Hold <b>{cfg['hotkey_translate']}</b> instead to translate English ⇄ Turkish. "
            "All of this can be changed later from the tray icon."
        )
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Start")
        buttons.accepted.connect(self._finish)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.note)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._installed = installed or []
        self.speech.currentIndexChanged.connect(self._update)
        self.cleanup.currentIndexChanged.connect(self._update)
        self.ollama_model.currentTextChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        uses_ollama = self.cleanup.currentData() == "ollama"
        uses_cloud = "cloud" in (self.speech.currentData(), self.cleanup.currentData())
        self.ollama_model.setEnabled(uses_ollama)
        self.key.setEnabled(uses_cloud)
        notes = []
        model = self.ollama_model.currentText().strip()
        if uses_ollama and model not in self._installed:
            notes.append(f"Ollama model “{model}” is not installed yet. In a terminal run:  ollama pull {model}")
        if self.speech.currentData() == "local":
            notes.append("The speech model (about 500 MB) downloads on first start.")
        self.note.setText("\n".join(notes))
        self.note.setVisible(bool(notes))

    def _finish(self) -> None:
        apply_choices(
            self.cfg, self.speech.currentData(), self.cleanup.currentData(), self.ollama_model.currentText().strip()
        )
        self.cfg["language"] = self.language.currentData()
        try:
            if self.key.text().strip():
                from ..stt.cloud import set_api_key

                set_api_key(self.key.text().strip())
            if self.startup.isChecked():
                set_startup(True)
        except Exception:
            log.exception("Saving the API key or startup entry failed")
        self.accept()


def first_run(cfg) -> None:
    """Choose sensible defaults for this hardware and save the first config."""
    if not has_local_gpu():
        apply_choices(cfg, "cloud", "cloud")
        WelcomeDialog(cfg).exec()
    cfg.save()
