"""Turn text into an audio file (.mp3, .m4a or .wav) with the read-aloud voices.

- The text is split into paragraphs and sentences. Each sentence is read by the
  Turkish or the English voice depending on its language (short sentences follow their
  paragraph), so mixed texts sound right.
- Short pauses go between sentences, longer ones between paragraphs.
- The voices are the same as for 🔊 (tts.py): natural Piper voices when installed,
  otherwise the Windows voices.
- Files are encoded with PyAV, which is already installed for audio-file transcription.

No Qt in here, so it can be unit-tested; the window is ui/speech_window.py."""
from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .cleanup import looks_turkish
from .tts import NeuralEngine, WindowsEngine, make_synthesizer, split_text

log = logging.getLogger(__name__)

OUTPUT_RATE = 22050             # the natural voices' own rate
SENTENCE_PAUSE_S = 0.35
PARAGRAPH_PAUSE_S = 0.8
MAX_SENTENCE_CHARS = 300        # longer "sentences" are cut at word boundaries
MAX_TEXT_CHARS = 200_000        # about 3-4 hours of speech
FORMATS = {"mp3": ".mp3", "m4a": ".m4a", "wav": ".wav"}
TEXT_EXTENSIONS = [".txt", ".md"]


class SpeechError(Exception):
    """A readable reason why no audio file could be made."""


class Cancelled(Exception):
    pass


@dataclass
class Part:
    text: str
    language: str           # "en" or "tr"
    pause_after: float      # seconds of silence after this sentence


# ---- planning: sentences, languages and pauses ----------------------------------------
def _sentences(paragraph: str) -> list[str]:
    pieces = []
    for line in paragraph.splitlines():
        for sentence in re.split(r"(?<=[.!?…])\s+", line.strip()):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > MAX_SENTENCE_CHARS:
                pieces.extend(split_text(sentence, limit=MAX_SENTENCE_CHARS // 2))
            else:
                pieces.append(sentence)
    return pieces


def plan_speech(text: str) -> list[Part]:
    """Sentences with their language and the pause that follows each."""
    parts: list[Part] = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        sentences = _sentences(paragraph)
        if not sentences:
            continue
        paragraph_lang = "tr" if looks_turkish(paragraph) else "en"
        for i, sentence in enumerate(sentences):
            if len(sentence.split()) >= 3:
                lang = "tr" if looks_turkish(sentence) else "en"
            else:
                lang = paragraph_lang        # "OK." or "Evet." follow their paragraph
            pause = PARAGRAPH_PAUSE_S if i == len(sentences) - 1 else SENTENCE_PAUSE_S
            parts.append(Part(sentence, lang, pause))
    if parts:
        parts[-1].pause_after = 0.0
    return parts


# ---- rendering ---------------------------------------------------------------------------
def resample(samples: np.ndarray, rate: int, target: int = OUTPUT_RATE) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if rate == target or not len(samples):
        return samples
    count = max(1, int(round(len(samples) * target / rate)))
    return np.interp(np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples).astype(np.float32)


class VoiceSet:
    """The English and Turkish voices for one job (own engines, so a running job does
    not interfere with the 🔊 buttons)."""

    def __init__(self, cfg, speed: float | None = None, status=None, stop: threading.Event | None = None):
        self.cfg, self.speed, self.status, self.stop = cfg, speed, status, stop
        self.neural, self.windows = NeuralEngine(), WindowsEngine()
        self._synth: dict[str, Callable] = {}

    def __call__(self, text: str, lang: str, speed: float | None = None) -> tuple[np.ndarray, int]:
        """Speak text in lang; speed overrides the job's speed (used to fit subtitle slots)."""
        speed = round(float(speed if speed is not None else (self.speed or self.cfg.get("tts_speed", 1.0))), 3)
        key = (lang, speed)
        if key not in self._synth:
            self._synth[key] = make_synthesizer(
                self.cfg, lang, self.neural, self.windows, self.status, self.stop, speed)
        return self._synth[key](text)


def render(parts: list[Part], voices: Callable[[str, str], tuple[np.ndarray, int]],
           progress: Callable[[float], None] | None = None,
           cancel: threading.Event | None = None) -> np.ndarray:
    """All parts read one after another, with pauses, as one array at OUTPUT_RATE."""
    chunks: list[np.ndarray] = []
    total = sum(len(p.text) for p in parts) or 1
    done = 0
    for part in parts:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        samples, rate = voices(part.text, part.language)
        chunks.append(resample(samples, rate))
        if part.pause_after:
            chunks.append(np.zeros(int(part.pause_after * OUTPUT_RATE), np.float32))
        done += len(part.text)
        if progress is not None:
            progress(done / total)
    if not chunks:
        return np.zeros(0, np.float32)
    audio = np.concatenate(chunks)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.99:            # never clip
        audio = audio * (0.99 / peak)
    return audio


# ---- saving ----------------------------------------------------------------------------------
def write_audio(samples: np.ndarray, path: Path, fmt: str, rate: int = OUTPUT_RATE) -> None:
    """Save mono float samples as mp3, m4a or wav. Written to a temporary name first,
    so a failed or cancelled save leaves nothing behind."""
    path = Path(path)
    temp = path.with_name(path.name + ".part")
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    try:
        if fmt == "wav":
            with wave.open(str(temp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm.tobytes())
        else:
            import av

            container = av.open(str(temp), "w", format="mp3" if fmt == "mp3" else "mp4")
            stream = container.add_stream("mp3" if fmt == "mp3" else "aac", rate=rate)
            stream.layout = "mono"
            stream.bit_rate = 128_000
            frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
            frame.rate = rate
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
            container.close()
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def read_text_file(path: str | Path) -> str:
    """Text of a .txt file: UTF-8, or the Windows Turkish code page for older files."""
    path = Path(path)
    if not path.is_file():
        raise SpeechError("The file was not found")
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def free_output_path(base: Path, extension: str) -> Path:
    """base.mp3, or base (2).mp3 etc. if that exists."""
    candidate = base.with_suffix(extension)
    number = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.stem} ({number}){extension}")
        number += 1
    return candidate


@dataclass
class SpeechResult:
    path: Path
    duration: float     # seconds of audio
    sentences: int
    languages: list[str]


def create_speech_file(
    text: str,
    out_path: str | Path,
    fmt: str,
    voices: Callable[[str, str], tuple[np.ndarray, int]],
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> SpeechResult:
    if fmt not in FORMATS:
        raise SpeechError(f"Unknown audio format: {fmt}")
    if len(text) > MAX_TEXT_CHARS:
        raise SpeechError(f"The text is too long (more than {MAX_TEXT_CHARS:,} characters); split it into parts")
    parts = plan_speech(text)
    if not parts:
        raise SpeechError("There is no text to read")
    started = time.perf_counter()
    audio = render(parts, voices, progress, cancel)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    out_path = Path(out_path)
    write_audio(audio, out_path, fmt)
    languages = sorted({p.language for p in parts})
    duration = len(audio) / OUTPUT_RATE
    # File names and text stay out of the log (see SECURITY.md).
    log.info("speech file created (.%s, %.0fs audio, %d sentences, languages %s) in %.1fs",
             fmt, duration, len(parts), "+".join(languages), time.perf_counter() - started)
    return SpeechResult(out_path, duration, len(parts), languages)


# ---- voice-over from subtitles (.srt) ----------------------------------------------------
MAX_SPEEDUP = 1.3           # a line may be read up to 30 % faster to fit its time
LATE_REPORT_S = 0.3         # lines starting later than this are listed in the result
_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"


_SHORT_TR = {"tamam", "evet", "hayır", "peki", "merhaba", "selam", "yok", "var", "teşekkürler",
             "teşekkür", "sağol", "sağolun", "günaydın", "iyi", "güzel", "lütfen", "efendim", "tabii", "olur"}
_SHORT_EN = {"the", "to", "you", "is", "are", "we", "it", "this", "that", "there", "here",
             "hello", "hi", "yes", "no", "ok", "okay", "thanks", "thank", "please", "and", "of", "in", "good",
             "great", "right", "sure", "sorry", "bye", "welcome", "well", "now", "let's", "what", "why", "how"}


def line_language(text: str, previous: str) -> str:
    """Language of one subtitle line. Longer lines are judged on their own; short ones
    by common short words and Turkish letters, else they follow the previous line."""
    if len(text.split()) >= 3:
        return "tr" if looks_turkish(text) else "en"
    words = set(re.findall(r"[a-zçğıöşü']+", text.lower()))
    if any(ch in "çğıöşüÇĞİÖŞÜ" for ch in text) or words & _SHORT_TR:
        return "tr"
    if words & _SHORT_EN:
        return "en"
    return previous


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _seconds(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[Cue]:
    """Subtitle cues from .srt text. Tolerates missing numbers, '.' instead of ',',
    and formatting tags such as <i>…</i> or {\\an8}."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")):
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        for i, line in enumerate(lines):
            match = re.match(_TIME + r"\s*-->\s*" + _TIME, line)
            if match:
                g = match.groups()
                words = " ".join(lines[i + 1:])
                words = re.sub(r"<[^>]+>|\{[^}]*\}", "", words).strip()
                if words:
                    cues.append(Cue(_seconds(*g[:4]), _seconds(*g[4:]), words))
                break
    return sorted(cues, key=lambda c: c.start)


@dataclass
class VoiceOverResult:
    path: Path
    duration: float
    lines: int
    faster: int                       # lines read faster than normal to fit
    late: list[tuple[int, float]]     # (line number, seconds late) for lines that did not fit
    languages: list[str]


def voice_over(cues: list[Cue], voices, speed: float = 1.0,
               progress: Callable[[float], None] | None = None,
               cancel: threading.Event | None = None) -> tuple[np.ndarray, int, list[tuple[int, float]], list[str]]:
    """Speak each cue at its start time. A line longer than the time until the next line
    is read faster (up to MAX_SPEEDUP); if it still does not fit, the following lines
    start a little later instead of overlapping. Returns (audio, lines read faster,
    late lines, languages)."""
    placed: list[tuple[int, np.ndarray]] = []   # (start sample, samples)
    cursor = 0.0
    faster = 0
    late: list[tuple[int, float]] = []
    languages: set[str] = set()
    previous_lang = "tr" if looks_turkish(" ".join(c.text for c in cues)) else "en"
    for number, cue in enumerate(cues, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        lang = line_language(cue.text, previous_lang)
        previous_lang = lang
        languages.add(lang)
        start = max(cue.start, cursor)
        next_start = cues[number].start if number < len(cues) else math.inf
        room = max(0.1, next_start - start)
        samples, rate = voices(cue.text, lang, speed)
        samples = resample(samples, rate)
        length = len(samples) / OUTPUT_RATE
        if length > room:
            factor = min(MAX_SPEEDUP, length / room * 1.03)
            samples, rate = voices(cue.text, lang, speed * factor)
            samples = resample(samples, rate)
            length = len(samples) / OUTPUT_RATE
            faster += 1
        if start - cue.start > LATE_REPORT_S:
            late.append((number, round(start - cue.start, 1)))
        placed.append((int(start * OUTPUT_RATE), samples))
        cursor = start + length
        if progress is not None:
            progress(number / len(cues))
    total = max([s + len(a) for s, a in placed] + [int(cues[-1].end * OUTPUT_RATE)]) if cues else 0
    audio = np.zeros(total, np.float32)
    for start_sample, samples in placed:
        audio[start_sample:start_sample + len(samples)] += samples
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    return audio, faster, late, sorted(languages)


def create_voice_over_file(srt_path: str | Path, out_path: str | Path, fmt: str, voices,
                           speed: float = 1.0, progress=None, cancel=None) -> VoiceOverResult:
    if fmt not in FORMATS:
        raise SpeechError(f"Unknown audio format: {fmt}")
    cues = parse_srt(read_text_file(srt_path))
    if not cues:
        raise SpeechError("No subtitles found in this file (is it an .srt file?)")
    started = time.perf_counter()
    audio, faster, late, languages = voice_over(cues, voices, speed, progress, cancel)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    out_path = Path(out_path)
    write_audio(audio, out_path, fmt)
    duration = len(audio) / OUTPUT_RATE
    log.info("voice-over created (.%s, %.0fs audio, %d lines, %d faster, %d late, languages %s) in %.1fs",
             fmt, duration, len(cues), faster, len(late), "+".join(languages), time.perf_counter() - started)
    return VoiceOverResult(out_path, duration, len(cues), faster, late, languages)


def voice_over_path(srt_path: Path, extension: str) -> Path:
    """talk.srt -> "talk voice-over.mp3" next to it (or "(2)" etc. if taken). Built by
    name, not with_suffix, so dots in names like "v1.2 talk.srt" are kept."""
    candidate = srt_path.with_name(f"{srt_path.stem} voice-over{extension}")
    number = 2
    while candidate.exists():
        candidate = srt_path.with_name(f"{srt_path.stem} voice-over ({number}){extension}")
        number += 1
    return candidate


def preview_audio(text: str, voices, max_chars: int = 300) -> np.ndarray:
    """The first sentence or two, for the window's Listen button."""
    parts, used = [], 0
    for part in plan_speech(text):
        parts.append(part)
        used += len(part.text)
        if used >= max_chars:
            break
    if parts:
        parts[-1].pause_after = 0.0
    return render(parts, voices)
