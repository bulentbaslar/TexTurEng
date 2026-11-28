"""Transcribe recordings (.m4a, .mp3, .wav, video files...) into .txt and .srt files.

How it works:
1. The file is decoded to 16 kHz mono with PyAV (through faster-whisper), so no extra
   converter is needed.
2. Speech is found with faster-whisper's voice-activity detector and grouped into
   chunks of up to 25 s, split at pauses.
3. Local engine: each chunk gets its own language (the better of Turkish and English
   when the setting is Auto), so recordings that switch between the languages come out
   right; the chunk is then transcribed in that language.
   Cloud engine: chunks of up to 10 minutes are sent to the service, which detects the
   language once per chunk.
4. The verbatim text goes to name.txt (new paragraph after a pause) and, if wanted,
   name.srt subtitles. Existing files are never overwritten.

No Qt in here, so it can be unit-tested; the window is ui/transcribe_window.py."""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
LOCAL_CHUNK_S = 25.0        # Whisper reads at most 30 s at a time
LOCAL_JOIN_GAP_S = 1.0      # pauses shorter than this stay inside one chunk
CLOUD_CHUNK_S = 600.0       # 10 min of 16-bit 16 kHz WAV is ~19 MB, under the 25 MB upload limit
PARAGRAPH_PAUSE_S = 2.0
SRT_LINE_WIDTH = 42
SRT_MAX_LINES = 2

AUDIO_EXTENSIONS = [
    ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".amr", ".3gp",
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv",
]


class TranscribeError(Exception):
    """A readable reason why a file could not be transcribed."""


class Cancelled(Exception):
    pass


@dataclass
class Segment:
    start: float    # seconds from the start of the recording
    end: float
    text: str
    language: str


# ---- reading the file -------------------------------------------------------------
def load_media(path: str | Path) -> np.ndarray:
    """The sound of an audio or video file as 16 kHz mono float32."""
    from faster_whisper import decode_audio

    path = Path(path)
    if not path.is_file():
        raise TranscribeError("The file was not found")
    try:
        audio = decode_audio(str(path), sampling_rate=SAMPLE_RATE)
    except Exception as exc:
        raise TranscribeError(
            "Could not read sound from this file (it may be damaged, or not an audio or video file)"
        ) from exc
    if not len(audio):
        raise TranscribeError("The file contains no sound")
    return np.asarray(audio, dtype=np.float32)


# ---- finding speech ---------------------------------------------------------------
def speech_regions(audio: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) sample positions of the speech in the audio."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(min_silence_duration_ms=500, speech_pad_ms=200, max_speech_duration_s=LOCAL_CHUNK_S)
    return [(int(t["start"]), int(t["end"])) for t in get_speech_timestamps(audio, options)]


def group_regions(regions: list[tuple[int, int]], max_len: int, max_gap: float) -> list[tuple[int, int]]:
    """Join neighbouring speech regions into chunks of at most max_len samples,
    starting a new chunk at any pause longer than max_gap samples."""
    chunks: list[tuple[int, int]] = []
    for start, end in regions:
        if chunks and start - chunks[-1][1] <= max_gap and end - chunks[-1][0] <= max_len:
            chunks[-1] = (chunks[-1][0], end)
        else:
            chunks.append((start, end))
    return chunks


def _is_silence_artifact(text: str, piece: np.ndarray) -> bool:
    """Whisper's typical "Thank you." for near-silent audio (see pipeline.py)."""
    from .pipeline import QUIET_PEAK, SILENCE_PHRASES

    if text.strip().lower() not in SILENCE_PHRASES:
        return False
    return not len(piece) or float(np.max(np.abs(piece))) < QUIET_PEAK


# ---- transcribing -----------------------------------------------------------------
def transcribe_audio(
    audio: np.ndarray,
    transcriber,
    language: str = "auto",
    candidates: list[str] | None = None,
    terms: list[str] | None = None,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Segment]:
    """Segments with times from the start of the recording. language: "auto", "en" or "tr".
    Works with LocalTranscriber (transcribe_chunk) and CloudTranscriber (transcribe_timed)."""
    candidates = candidates or ["en", "tr"]
    local = hasattr(transcriber, "transcribe_chunk")
    if local:
        chunks = group_regions(speech_regions(audio), int(LOCAL_CHUNK_S * SAMPLE_RATE), LOCAL_JOIN_GAP_S * SAMPLE_RATE)
    else:
        chunks = group_regions(speech_regions(audio), int(CLOUD_CHUNK_S * SAMPLE_RATE), math.inf)
    total = len(audio)
    segments: list[Segment] = []
    for start, end in chunks:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        piece = audio[start:end]
        offset = start / SAMPLE_RATE
        if local:
            if language in ("en", "tr"):
                lang = language
            else:
                lang = candidates[0] if len(candidates) == 1 else transcriber.pick_language(piece, candidates)
            parts = transcriber.transcribe_chunk(piece, lang, terms)
        else:
            parts, lang = transcriber.transcribe_timed(piece, language, terms)
        for part_start, part_end, text in parts:
            a = max(0, int(part_start * SAMPLE_RATE))
            b = min(len(piece), max(a + 1, int(part_end * SAMPLE_RATE)))
            if not text or _is_silence_artifact(text, piece[a:b]):
                continue
            seg_start = offset + max(0.0, part_start)
            seg_end = min(offset + part_end, end / SAMPLE_RATE)
            segments.append(Segment(seg_start, max(seg_end, seg_start + 0.3), text, lang))
        if progress is not None:
            progress(min(1.0, end / total) if total else 1.0)
    if progress is not None:
        progress(1.0)
    return segments


# ---- writing .txt and .srt ----------------------------------------------------------
def to_txt(segments: list[Segment]) -> str:
    """Verbatim text; a blank line between paragraphs after pauses of 2 s or more."""
    out = ""
    previous: Segment | None = None
    for seg in segments:
        if previous is None:
            out = seg.text
        elif seg.start - previous.end >= PARAGRAPH_PAUSE_S:
            out += "\n\n" + seg.text
        else:
            out += " " + seg.text
        previous = seg
    return out + "\n" if out else ""


def srt_time(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_words(words: list[str], width: int = SRT_LINE_WIDTH) -> list[str]:
    lines: list[str] = []
    for word in words:
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def subtitle_cues(segments: list[Segment]) -> list[tuple[float, float, str]]:
    """(start, end, text) cues of at most 2 lines of 42 characters. Longer segments are
    split into several cues, sharing the segment's time by number of words."""
    cues: list[tuple[float, float, str]] = []
    for seg in segments:
        words = seg.text.split()
        if not words:
            continue
        lines = wrap_words(words)
        groups = [lines[i:i + SRT_MAX_LINES] for i in range(0, len(lines), SRT_MAX_LINES)]
        duration = max(seg.end - seg.start, 0.3)
        done = 0
        for group in groups:
            count = sum(len(line.split()) for line in group)
            start = seg.start + duration * done / len(words)
            done += count
            end = seg.start + duration * done / len(words)
            cues.append((start, end, "\n".join(group)))
    return cues


def to_srt(segments: list[Segment]) -> str:
    blocks = [
        f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n"
        for i, (start, end, text) in enumerate(subtitle_cues(segments), 1)
    ]
    return "\n".join(blocks)


def free_output_path(source: Path, extension: str) -> Path:
    """name.txt next to the recording, or name (2).txt etc. if that exists."""
    candidate = source.with_suffix(extension)
    number = 2
    while candidate.exists():
        candidate = source.with_name(f"{source.stem} ({number}){extension}")
        number += 1
    return candidate


def _write(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".part")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


@dataclass
class FileResult:
    txt_path: Path
    srt_path: Path | None
    duration: float      # seconds of audio
    segments: int
    languages: list[str]


def transcribe_file(
    path: str | Path,
    transcriber,
    language: str = "auto",
    make_srt: bool = True,
    terms: list[str] | None = None,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> FileResult:
    """Transcribe one recording and write the .txt (and .srt) next to it.
    Nothing is written when it fails or is cancelled."""
    source = Path(path)
    started = time.perf_counter()
    audio = load_media(source)
    segments = transcribe_audio(audio, transcriber, language, terms=terms, progress=progress, cancel=cancel)
    if not segments:
        raise TranscribeError("No speech was found in this recording")
    txt_path = free_output_path(source, ".txt")
    _write(txt_path, to_txt(segments))
    srt_path = None
    if make_srt:
        srt_path = free_output_path(source, ".srt")
        _write(srt_path, to_srt(segments))
    languages = sorted({s.language for s in segments if s.language})
    duration = len(audio) / SAMPLE_RATE
    # File names and text stay out of the log (see SECURITY.md).
    log.info("file transcribed (%s, %.0fs audio, %d segments, languages %s) in %.1fs",
             source.suffix.lower(), duration, len(segments), "+".join(languages) or "?",
             time.perf_counter() - started)
    return FileResult(txt_path, srt_path, duration, len(segments), languages)
