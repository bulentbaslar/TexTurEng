"""Text-to-speech for the translation popup.

Two engines:
- "neural": natural Piper voices run by sherpa-onnx, fully offline. Each voice is
  downloaded once (about 65 MB) into %APPDATA%\\Textureng\\voices.
- "windows": the voices built into Windows (through the Windows Runtime).

With engine "auto" the neural voice is used when sherpa-onnx is installed and the
voice can be loaded; otherwise the Windows voice for that language is used."""
from __future__ import annotations

import io
import logging
import re
import tarfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from .config import app_dir

log = logging.getLogger(__name__)

DOWNLOAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-{voice}.tar.bz2"


@dataclass(frozen=True)
class Voice:
    id: str        # Piper voice name, e.g. "tr_TR-fettah-medium"
    label: str
    licence: str


NEURAL_VOICES: dict[str, list[Voice]] = {
    "en": [
        Voice("en_US-ljspeech-medium", "LJ (US English, female)", "public domain recordings"),
        Voice("en_US-lessac-medium", "Lessac (US English, female)", "Blizzard 2013 licence, check before commercial use"),
        Voice("en_US-ryan-medium", "Ryan (US English, male)", "CC BY-NC-SA 4.0, non-commercial"),
    ],
    "tr": [
        Voice("tr_TR-fahrettin-medium", "Fahrettin (Turkish, male)", "recordings licence not published"),
        Voice("tr_TR-dfki-medium", "DFKI (Turkish, male)", "CC BY-NC-SA 4.0, non-commercial"),
        Voice("tr_TR-fettah-medium", "Fettah (Turkish, male)", "CC0 recordings"),
    ],
}
DEFAULT_VOICES = {"en": "en_US-ljspeech-medium", "tr": "tr_TR-fahrettin-medium"}
LANGUAGE_NAMES = {"en": "English", "tr": "Turkish"}


class SpeechError(Exception):
    """A readable reason why the text could not be spoken."""


def neural_available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:
        return False
    return True


def voice_for(cfg, lang: str) -> str:
    chosen = cfg.get(f"tts_voice_{lang}", "")
    known = {v.id for v in NEURAL_VOICES.get(lang, [])}
    return chosen if chosen in known else DEFAULT_VOICES.get(lang, "")


def split_text(text: str, limit: int = 300) -> list[str]:
    """Sentence-sized pieces, so speech starts quickly and can be stopped in between."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        current = ""
        for sentence in re.split(r"(?<=[.!?…])\s+", paragraph):
            if current and len(current) + len(sentence) + 1 > limit:
                pieces.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
    # A single very long sentence still gets cut at word boundaries.
    out: list[str] = []
    for piece in pieces:
        while len(piece) > limit * 2:
            cut = piece.rfind(" ", 0, limit * 2)
            cut = cut if cut > 0 else limit * 2
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            out.append(piece)
    return out


def wav_to_samples(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SpeechError(f"Unexpected Windows voice format ({width * 8}-bit)")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


# ---- neural voices --------------------------------------------------------------
def voices_dir() -> Path:
    path = app_dir() / "voices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voice_path(voice_id: str) -> Path:
    return voices_dir() / f"vits-piper-{voice_id}"


def is_downloaded(voice_id: str) -> bool:
    folder = voice_path(voice_id)
    return (folder / "tokens.txt").exists() and any(folder.glob("*.onnx"))


def download_voice(voice_id: str, progress=None) -> Path:
    """Download and unpack a voice; progress(fraction) is called while downloading."""
    import httpx

    target = voice_path(voice_id)
    if is_downloaded(voice_id):
        return target
    archive = voices_dir() / f"{voice_id}.tar.bz2.part"
    try:
        with httpx.stream("GET", DOWNLOAD_URL.format(voice=voice_id), follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with open(archive, "wb") as handle:
                for chunk in response.iter_bytes(1 << 16):
                    handle.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
        unpack_voice(archive, voices_dir())
    except httpx.HTTPError as exc:
        raise SpeechError(f"Could not download the voice ({exc.__class__.__name__})") from exc
    finally:
        archive.unlink(missing_ok=True)
    if not is_downloaded(voice_id):
        raise SpeechError("The downloaded voice is incomplete")
    return target


def unpack_voice(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(destination, filter="data")  # refuses paths outside destination


class NeuralEngine:
    def __init__(self):
        self._loaded: dict[str, object] = {}
        self._lock = threading.Lock()

    def _load(self, voice_id: str):
        import sherpa_onnx

        with self._lock:
            if voice_id not in self._loaded:
                folder = voice_path(voice_id)
                model = next(folder.glob("*.onnx"))
                config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=str(model), lexicon="", tokens=str(folder / "tokens.txt"),
                            data_dir=str(folder / "espeak-ng-data"),
                        ),
                        provider="cpu",
                        num_threads=2,
                    ),
                    max_num_sentences=1,
                )
                self._loaded[voice_id] = sherpa_onnx.OfflineTts(config)
            return self._loaded[voice_id]

    def synthesize(self, text: str, voice_id: str, speed: float) -> tuple[np.ndarray, int]:
        audio = self._load(voice_id).generate(text, sid=0, speed=speed)
        samples = np.asarray(audio.samples, dtype=np.float32)
        if not len(samples):
            raise SpeechError("The voice produced no sound")
        return samples, audio.sample_rate


# ---- Windows voices ---------------------------------------------------------------
class WindowsEngine:
    @staticmethod
    def available_languages() -> set[str]:
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer

            return {v.language.split("-")[0].lower() for v in SpeechSynthesizer.all_voices}
        except Exception:
            return set()

    def synthesize(self, text: str, lang: str, speed: float) -> tuple[np.ndarray, int]:
        import asyncio

        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer
            from winrt.windows.storage.streams import DataReader
        except Exception as exc:
            raise SpeechError("Windows voices are not available") from exc
        voices = [v for v in SpeechSynthesizer.all_voices if v.language.lower().startswith(lang)]
        if not voices:
            name = LANGUAGE_NAMES.get(lang, lang)
            raise SpeechError(
                f"No {name} voice is installed in Windows. Add one in Windows Settings > "
                f"Time & language > Speech > Add voices"
            )

        async def run() -> bytes:
            synth = SpeechSynthesizer()
            synth.voice = voices[0]
            synth.options.speaking_rate = max(0.5, min(3.0, speed))
            stream = await synth.synthesize_text_to_stream_async(text)
            reader = DataReader(stream.get_input_stream_at(0))
            await reader.load_async(stream.size)
            data = bytearray(stream.size)
            reader.read_bytes(data)
            return bytes(data)

        return wav_to_samples(asyncio.run(run()))


# ---- choosing the voice for a language ------------------------------------------------
def engine_for(cfg, lang: str) -> str:
    """"neural" or "windows", following the setting and what is installed."""
    choice = cfg.get("tts_engine", "auto")
    if choice == "windows" or not neural_available() or not voice_for(cfg, lang):
        return "windows"
    return "neural"


def make_synthesizer(cfg, lang: str, neural: NeuralEngine, windows: WindowsEngine,
                     status=None, stop: threading.Event | None = None, speed: float | None = None):
    """A function text -> (samples, rate) for one language: the natural voice (downloaded
    once if needed) when available, otherwise the Windows voice. status(msg) reports
    downloads; "" clears the message."""
    status = status or (lambda message: None)
    speed = float(cfg.get("tts_speed", 1.0) if speed is None else speed)
    if engine_for(cfg, lang) == "neural":
        voice_id = voice_for(cfg, lang)
        try:
            if not is_downloaded(voice_id):
                name = LANGUAGE_NAMES.get(lang, lang)
                status(f"Downloading the {name} voice (one time only)…")
                download_voice(voice_id, lambda f: status(f"Downloading the {name} voice… {int(f * 100)}%"))
                status("")
            neural._load(voice_id)
            return lambda piece: neural.synthesize(piece, voice_id, speed)
        except Exception as exc:
            if stop is not None and stop.is_set():
                raise
            log.warning("Natural voice unavailable (%s); using the Windows voice", exc)
            status("")
    return lambda piece: windows.synthesize(piece, lang, speed)


# ---- the speaker used by the app ----------------------------------------------------
def _play(samples: np.ndarray, rate: int, stop: threading.Event) -> None:
    import sounddevice as sd

    sd.play(samples, rate)
    duration = len(samples) / rate
    waited = 0.0
    while waited < duration + 0.3:
        if stop.wait(0.05):
            sd.stop()
            return
        waited += 0.05
    sd.wait()


class Speaker(QObject):
    """Speaks text in a background thread. Signals are delivered on the GUI thread."""

    started = Signal()
    finished = Signal()
    status = Signal(str)   # e.g. "Downloading the Turkish voice… 40%"
    failed = Signal(str)

    def __init__(self, cfg, player=_play):
        super().__init__()
        self.cfg = cfg
        self.neural = NeuralEngine()
        self.windows = WindowsEngine()
        self._player = player
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def speaking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def speak(self, text: str, lang: str) -> None:
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(text, lang, self._stop), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def engine_for(self, lang: str) -> str:
        return engine_for(self.cfg, lang)

    def _synthesizer(self, lang: str, stop: threading.Event):
        return make_synthesizer(self.cfg, lang, self.neural, self.windows, self.status.emit, stop)

    def _run(self, text: str, lang: str, stop: threading.Event) -> None:
        self.started.emit()
        try:
            synthesize = self._synthesizer(lang, stop)
            for piece in split_text(text):
                if stop.is_set():
                    break
                samples, rate = synthesize(piece)
                if stop.is_set():
                    break
                self._player(samples, rate, stop)
        except Exception as exc:
            if not stop.is_set():  # a stop request is not an error
                if not isinstance(exc, SpeechError):
                    log.exception("Speaking failed")
                    exc = SpeechError(f"Could not play the voice ({exc})")
                self.failed.emit(str(exc))
        finally:
            self.finished.emit()
