from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Transcript:
    text: str
    language: str  # ISO code such as "en" or "tr"; "" when unknown


class Transcriber(Protocol):
    name: str

    def load(self) -> None:
        """Prepare the engine (load the model, check the key). May be slow."""

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "auto",
        candidates: list[str] | None = None,
        terms: list[str] | None = None,
    ) -> Transcript:
        """audio: 16 kHz mono float32. language: "auto" or an ISO code.
        candidates: languages to choose between in auto mode. terms: spelling hints."""
