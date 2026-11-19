"""The dictation pipeline: audio -> transcript -> profile -> polished text.

run_pipeline() is plain Python (used by the CLI and tests); PipelineWorker
wraps it for the GUI and lives on a background QThread."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal, Slot

from . import cleanup
from .audio import SAMPLE_RATE
from .context import AppInfo, resolve_profile
from .stt import make_transcriber

log = logging.getLogger(__name__)


@dataclass
class Result:
    text: str = ""
    raw: str = ""
    language: str = ""
    profile: str = "default"
    app: AppInfo = field(default_factory=AppInfo)
    warning: str = ""
    used_llm: bool = False
    stt_seconds: float = 0.0
    cleanup_seconds: float = 0.0
    translated_to: str = ""  # ISO code when the text was translated, else ""


def translation_target(cfg, spoken: str) -> str:
    """Language to translate into. "auto" means the other one of English/Turkish."""
    target = cfg["translate_target"]
    if target in ("en", "tr"):
        return target
    return "tr" if spoken == "en" else "en"


def run_pipeline(
    audio, app: AppInfo, cfg, transcriber, profile_key: str | None = None, translate: bool = False
) -> Result:
    t0 = time.perf_counter()
    transcript = transcriber.transcribe(
        audio, language=cfg["language"], candidates=list(cfg["languages"]), terms=list(cfg["dictionary"])
    )
    t1 = time.perf_counter()
    key = profile_key or resolve_profile(app, cfg["profiles"], cfg["browsers"])
    profile = cfg["profiles"].get(key) or cfg["profiles"]["default"]
    target = translation_target(cfg, transcript.language) if translate else ""
    polished = cleanup.polish(transcript.text, profile, transcript.language, cfg, target=target)
    t2 = time.perf_counter()
    translated = target if (polished.used_llm and target and target != transcript.language) else ""
    result = Result(
        text=polished.text, raw=transcript.text, language=transcript.language, profile=key, app=app,
        warning=polished.warning, used_llm=polished.used_llm, stt_seconds=t1 - t0, cleanup_seconds=t2 - t1,
        translated_to=translated,
    )
    log.info(
        "audio %.1fs | stt %.2fs | cleanup %.2fs | lang=%s%s profile=%s app=%s",
        len(audio) / SAMPLE_RATE, result.stt_seconds, result.cleanup_seconds,
        result.language, f"->{translated}" if translated else "", key, app.process,
    )
    return result


class PipelineWorker(QObject):
    finished = Signal(object)  # Result
    textTranslated = Signal(object, int)  # cleanup.TextTranslation, request id
    failed = Signal(str)
    status = Signal(str)       # human-readable readiness / warning line

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.transcriber = None

    @Slot()
    def prepare(self) -> None:
        """(Re)load the speech engine and warm up the cleanup model."""
        self.status.emit("Loading speech model…")
        try:
            self.transcriber = make_transcriber(self.cfg)
            self.transcriber.load()
        except Exception as exc:
            log.exception("Speech engine failed to load")
            self.transcriber = None
            self.status.emit(f"Speech engine problem: {exc}")
            return
        problem = cleanup.warm_up(self.cfg)
        self.status.emit(problem or "Ready")

    @Slot(str, int)
    def translate_selection(self, text: str, request_id: int) -> None:
        self.textTranslated.emit(cleanup.translate_text(text, self.cfg), request_id)

    @Slot(object, object, bool)
    def process(self, audio, app, translate: bool = False) -> None:
        try:
            if self.transcriber is None:
                self.transcriber = make_transcriber(self.cfg)
                self.transcriber.load()
            self.finished.emit(run_pipeline(audio, app, self.cfg, self.transcriber, translate=translate))
        except Exception as exc:
            log.exception("Dictation failed")
            self.failed.emit(str(exc))
