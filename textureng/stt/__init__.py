from __future__ import annotations

from .base import Transcriber, Transcript


def make_transcriber(cfg) -> Transcriber:
    if cfg["stt_engine"] == "cloud":
        from .cloud import CloudTranscriber

        return CloudTranscriber(cfg["cloud_base_url"], cfg["cloud_model"])
    from .local import LocalTranscriber

    return LocalTranscriber(cfg["local_model"], cfg["local_device"])


__all__ = ["Transcriber", "Transcript", "make_transcriber"]
