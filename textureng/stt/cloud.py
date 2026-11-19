"""Cloud speech-to-text through an OpenAI-compatible /audio/transcriptions endpoint
(Groq by default). The API key lives in Windows Credential Manager, not in config."""
from __future__ import annotations

import logging

import httpx

from ..audio import to_wav_bytes
from .base import Transcript

log = logging.getLogger(__name__)
KEYRING_SERVICE = "Textureng"
KEYRING_USER = "cloud_stt_api_key"
_LANG_NAMES = {"english": "en", "turkish": "tr"}


def get_api_key() -> str:
    import keyring

    return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""


def set_api_key(value: str) -> None:
    import keyring

    if value:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, value)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass


class CloudTranscriber:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"cloud:{model}"
        self._key = ""

    def load(self) -> None:
        self._key = get_api_key()
        if not self._key:
            raise RuntimeError("No cloud API key saved. Add one in Settings > Speech.")

    def transcribe(self, audio, language="auto", candidates=None, terms=None) -> Transcript:
        if not self._key:
            self.load()
        data = {"model": self.model, "response_format": "verbose_json"}
        if language != "auto":
            data["language"] = language
        elif candidates and len(candidates) == 1:
            data["language"] = candidates[0]
        if terms:
            data["prompt"] = ", ".join(terms)
        response = httpx.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._key}"},
            data=data,
            files={"file": ("speech.wav", to_wav_bytes(audio), "audio/wav")},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        lang = str(body.get("language") or data.get("language") or "").lower()
        return Transcript(text=str(body.get("text", "")).strip(), language=_LANG_NAMES.get(lang, lang))
