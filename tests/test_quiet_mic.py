import numpy as np

from textureng import cleanup, pipeline
from textureng.audio import SAMPLE_RATE
from textureng.context import AppInfo
from textureng.stt.base import Transcript


class Hears:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def load(self):
        pass

    def transcribe(self, audio, language="auto", candidates=None, terms=None):
        return Transcript(self.text, "en")


def silence(level=0.001):
    return (np.random.default_rng(0).standard_normal(SAMPLE_RATE * 2) * level).astype(np.float32)


def test_thank_you_from_silence_is_not_pasted(cfg, monkeypatch):
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "Thank you.")
    result = pipeline.run_pipeline(silence(), AppInfo("notepad.exe", ""), cfg, Hears("Thank you."))
    assert result.text == "" and result.warning == pipeline.MIC_TOO_QUIET


def test_silence_with_nothing_heard_warns(cfg):
    result = pipeline.run_pipeline(silence(), AppInfo("notepad.exe", ""), cfg, Hears(""))
    assert result.text == "" and result.warning == pipeline.MIC_TOO_QUIET


def test_real_thank_you_is_kept(cfg, monkeypatch):
    loud = (np.sin(np.linspace(0, 2000, SAMPLE_RATE * 2)) * 0.3).astype(np.float32)
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "Thank you.")
    result = pipeline.run_pipeline(loud, AppInfo("notepad.exe", ""), cfg, Hears("Thank you."))
    assert result.text == "Thank you." and not result.warning


def test_quiet_but_real_words_are_kept(cfg, monkeypatch):
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "See you tomorrow.")
    result = pipeline.run_pipeline(silence(), AppInfo("notepad.exe", ""), cfg, Hears("see you tomorrow"))
    assert result.text == "See you tomorrow."


def test_audio_levels():
    assert pipeline.audio_levels(np.zeros(0, np.float32)) == (0.0, 0.0)
    peak, rms = pipeline.audio_levels(np.array([0.5, -0.5], np.float32))
    assert peak == 0.5 and abs(rms - 0.5) < 1e-6
