"""Microphone capture: 16 kHz mono float32, with a live level for the overlay."""
from __future__ import annotations

import logging
import threading
import wave
from io import BytesIO
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
log = logging.getLogger(__name__)


def list_input_devices() -> list[str]:
    """Names of input devices on the default host API (avoids duplicates)."""
    import sounddevice as sd

    try:
        default_in = sd.default.device[0]
        hostapi = sd.query_devices(default_in)["hostapi"] if default_in is not None and default_in >= 0 else 0
    except Exception:
        hostapi = 0
    names = []
    for dev in sd.query_devices():
        if dev["max_input_channels"] > 0 and dev["hostapi"] == hostapi and dev["name"] not in names:
            names.append(dev["name"])
    return names


def _device_index(name: str):
    if not name:
        return None
    import sounddevice as sd

    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and dev["name"] == name:
            return index
    log.warning("Microphone %r not found; using the system default", name)
    return None


class Recorder:
    def __init__(self, device_name: str = ""):
        self.device_name = device_name
        self.level = 0.0  # 0..1, read by the overlay
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd

        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
        self.level = 0.0
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=_device_index(self.device_name),
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:
        chunk = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(chunk)
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        self.level = min(1.0, rms * 12.0)

    def stop(self) -> np.ndarray:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("Closing the microphone stream failed")
        self.level = 0.0
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)


def to_wav_bytes(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def load_wav(path: str | Path) -> np.ndarray:
    """Read a PCM WAV file as 16 kHz mono float32."""
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width} bytes")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(data):
        target = int(round(len(data) * SAMPLE_RATE / rate))
        data = np.interp(
            np.linspace(0, len(data) - 1, target), np.arange(len(data)), data
        ).astype(np.float32)
    return data
