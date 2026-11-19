"""Local speech-to-text with faster-whisper."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

from .base import Transcript

log = logging.getLogger(__name__)
_dll_dirs_added = False


def _add_cuda_dll_dirs() -> None:
    """Make the cuBLAS/cuDNN DLLs from the nvidia-* pip packages loadable."""
    global _dll_dirs_added
    if _dll_dirs_added or os.name != "nt":
        return
    _dll_dirs_added = True
    try:
        import nvidia  # namespace package created by nvidia-*-cu12 wheels
    except ImportError:
        return
    for root in list(nvidia.__path__):
        for sub in ("cublas", "cudnn"):
            bin_dir = Path(root) / sub / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


class LocalTranscriber:
    def __init__(self, model_name: str = "large-v3-turbo", device: str = "auto"):
        self.model_name = model_name
        self.device = device
        self.name = f"local:{model_name}"
        self.model = None
        self.active_device = ""

    def load(self) -> None:
        if self.model is not None:
            return
        _add_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        attempts = []
        if self.device in ("auto", "cuda"):
            attempts.append(("cuda", "float16"))
        if self.device in ("auto", "cpu"):
            attempts.append(("cpu", "int8"))
        last_error: Exception | None = None
        for device, compute in attempts:
            try:
                model = WhisperModel(self.model_name, device=device, compute_type=compute)
                # A tiny run proves the CUDA libraries really load, not just the weights.
                list(model.transcribe(np.zeros(8000, dtype=np.float32), language="en")[0])
                self.model, self.active_device = model, device
                log.info("Whisper %s loaded on %s (%s)", self.model_name, device, compute)
                return
            except Exception as exc:  # missing CUDA DLLs, no GPU, out of memory...
                last_error = exc
                log.warning("Whisper on %s failed: %s", device, exc)
        raise RuntimeError(f"Could not load Whisper model {self.model_name}: {last_error}")

    def _pick_language(self, audio: np.ndarray, candidates: list[str]) -> str | None:
        """Choose only among the candidate languages; avoids stray misdetections."""
        try:
            _, _, probs = self.model.detect_language(audio)
        except Exception as exc:
            log.debug("detect_language unavailable (%s); letting Whisper decide", exc)
            return None
        scores = dict(probs)
        best = max(candidates, key=lambda code: scores.get(code, 0.0))
        log.debug("Language scores: %s", {c: round(scores.get(c, 0.0), 3) for c in candidates})
        return best

    def transcribe(self, audio, language="auto", candidates=None, terms=None) -> Transcript:
        self.load()
        lang = None if language == "auto" else language
        if lang is None and candidates:
            lang = candidates[0] if len(candidates) == 1 else self._pick_language(audio, candidates)
        segments, info = self.model.transcribe(
            audio,
            language=lang,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=", ".join(terms) if terms else None,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return Transcript(text=text, language=lang or getattr(info, "language", "") or "")
