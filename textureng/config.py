"""Settings stored as JSON in %APPDATA%\\Textureng (override with TEXTURENG_HOME)."""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

APP_NAME = "TexTurEng"  # shown to people; folders stay "Textureng"
log = logging.getLogger(__name__)


def app_dir() -> Path:
    base = os.environ.get("TEXTURENG_HOME")
    path = Path(base) if base else Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


# Order matters: the first profile whose rule matches wins. "default" is the fallback.
DEFAULT_PROFILES: dict[str, dict] = {
    "email": {
        "name": "Email",
        "processes": ["outlook.exe", "olk.exe", "thunderbird.exe", "hxoutlook.exe"],
        "titles": ["gmail", "outlook", "proton mail", "yahoo mail", "yandex mail"],
        "style": (
            "Professional email. Complete, well-formed sentences. Split into short "
            "paragraphs separated by a blank line. If the speaker says a greeting or a "
            "sign-off, put it on its own line. Do not invent a greeting, a sign-off or a name."
        ),
    },
    "chat": {
        "name": "Chat",
        "processes": [
            "slack.exe", "teams.exe", "ms-teams.exe", "discord.exe", "whatsapp.exe",
            "whatsapp.root.exe", "telegram.exe", "signal.exe",
        ],
        "titles": ["whatsapp", "slack", "discord", "telegram", "messenger", "microsoft teams"],
        "style": (
            "Casual chat message. Keep it short and conversational, keep the speaker's "
            "informal tone. A single short sentence gets no trailing period. No greeting "
            "or sign-off unless spoken."
        ),
    },
    "code": {
        "name": "Code / terminal",
        "processes": [
            "code.exe", "cursor.exe", "windsurf.exe", "windowsterminal.exe", "cmd.exe",
            "powershell.exe", "pwsh.exe", "pycharm64.exe", "idea64.exe", "devenv.exe",
            "sublime_text.exe", "notepad++.exe", "claude.exe",
        ],
        "titles": ["github", "gitlab", "stack overflow"],
        "style": (
            "Technical writing for a code editor, terminal or AI coding assistant. Keep "
            "technical terms, file names, commands and identifiers exactly as spoken and "
            "write them in their usual code spelling (for example camelCase, snake_case, "
            "file.py). Rewrite as little as possible; be concise and direct."
        ),
    },
    "document": {
        "name": "Document / notes",
        "processes": ["winword.exe", "notion.exe", "obsidian.exe", "onenote.exe", "wordpad.exe"],
        "titles": ["google docs", "notion", "word", "confluence"],
        "style": (
            "Clean written prose for a document. Full sentences and sensible paragraphs. "
            "When the speaker enumerates items (first, second, third / bir, iki, üç), "
            "always write an introductory line ending with a colon and then one item per "
            "line, each starting with '- '."
        ),
    },
    "default": {
        "name": "Default",
        "processes": [],
        "titles": [],
        "style": "Neutral, clear writing. Keep the speaker's tone.",
    },
}

DEFAULTS: dict = {
    "hotkey_ptt": "ctrl+win",
    "hotkey_toggle": "ctrl+win+space",
    "hotkey_cancel": "esc",
    # Not ctrl+alt: on Turkish keyboards AltGr (for @ and similar) sends Ctrl+Alt.
    "hotkey_translate": "ctrl+win+alt",
    "translate_mode": False,     # tray switch: translate every dictation
    "translate_target": "auto",  # auto (the other language) | en | tr
    "selection_translate": True,  # Ctrl+C twice on selected text shows a translation popup
    "tts_engine": "auto",         # auto (natural voice if installed) | neural | windows
    "tts_voice_en": "en_US-ljspeech-medium",
    "tts_voice_tr": "tr_TR-fahrettin-medium",
    "tts_speed": 1.0,
    "tts_auto_read": False,       # read each popup translation aloud automatically
    "read_selection_button": True,  # show a 🔊 button after selecting text anywhere
    "transcribe_language": "auto",  # audio files: auto (Turkish/English, mixed) | tr | en
    "transcribe_srt": True,         # audio files: also write .srt subtitles
    "speech_format": "mp3",         # text to audio file: mp3 | m4a | wav
    "mic_device": "",            # device name; empty = system default
    "language": "auto",          # auto | en | tr
    "languages": ["en", "tr"],   # candidates when language is "auto"
    "stt_engine": "local",       # local | cloud
    "local_model": "large-v3-turbo",
    "local_device": "auto",      # auto | cuda | cpu
    "cloud_base_url": "https://api.groq.com/openai/v1",
    "cloud_model": "whisper-large-v3-turbo",
    "cleanup_enabled": True,
    "cleanup_provider": "ollama",  # ollama (local) | cloud (same endpoint and key as cloud speech)
    "cloud_cleanup_model": "qwen/qwen3.8-27b",
    "ollama_url": "http://127.0.0.1:11434",  # not "localhost": its IPv6 lookup adds ~2 s per call on Windows
    "ollama_model": "gemma3:12b",
    "ollama_timeout": 20,
    "inject_method": "paste",    # paste | type
    "type_apps": [],             # process names that get typed text instead of a paste
    "append_space": True,
    "history_enabled": True,
    "dictionary": [],
    "browsers": [
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
        "vivaldi.exe", "arc.exe",
    ],
    "profiles": DEFAULT_PROFILES,
}


# Cloud cleanup models the provider has retired; saved settings naming one get the
# current default instead, so an update fixes "model not available" by itself.
RETIRED_CLOUD_CLEANUP_MODELS = {"llama-3.3-70b-versatile"}


def _merge(defaults: dict, saved: dict) -> dict:
    out = copy.deepcopy(defaults)
    for key, value in saved.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "config.json"
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.existed = self.path.exists()  # False on the very first start
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = _merge(DEFAULTS, saved)
            if self.data.get("cloud_cleanup_model") in RETIRED_CLOUD_CLEANUP_MODELS:
                log.info("cloud cleanup model %s is retired; using %s",
                         self.data["cloud_cleanup_model"], DEFAULTS["cloud_cleanup_model"])
                self.data["cloud_cleanup_model"] = DEFAULTS["cloud_cleanup_model"]
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s (%s); using defaults", self.path, exc)

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def __getitem__(self, key: str):
        return self.data[key]

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value

    def get(self, key: str, default=None):
        return self.data.get(key, default)
