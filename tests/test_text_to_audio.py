import threading
import time

import numpy as np
import pytest

from textureng import text_to_audio as ta
from textureng.transcribe_file import load_media


# ---- sentences, languages, pauses --------------------------------------------------
def test_plan_speech_languages_and_pauses():
    text = ("Merhaba, bugünkü toplantıya hoş geldiniz. Today we review the schedule.\n\n"
            "Raporu cuma gününe kadar göndereceğim. OK.")
    parts = ta.plan_speech(text)
    assert [(p.language, p.text) for p in parts] == [
        ("tr", "Merhaba, bugünkü toplantıya hoş geldiniz."),
        ("en", "Today we review the schedule."),
        ("tr", "Raporu cuma gününe kadar göndereceğim."),
        ("tr", "OK."),                                     # short sentence follows its paragraph
    ]
    assert [p.pause_after for p in parts] == [ta.SENTENCE_PAUSE_S, ta.PARAGRAPH_PAUSE_S, ta.SENTENCE_PAUSE_S, 0.0]


def test_plan_speech_lines_and_long_sentences():
    parts = ta.plan_speech("First line without a full stop\nSecond line")
    assert [p.text for p in parts] == ["First line without a full stop", "Second line"]
    long_sentence = " ".join(["word"] * 200)
    pieces = ta.plan_speech(long_sentence)
    assert len(pieces) > 1 and all(len(p.text) <= ta.MAX_SENTENCE_CHARS for p in pieces)
    assert ta.plan_speech("   \n\n  ") == []


# ---- rendering ---------------------------------------------------------------------
class FakeVoices:
    """English at 16 kHz (like the Windows voices), Turkish at 22.05 kHz (like Piper)."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, lang):
        self.calls.append(lang)
        rate = 16000 if lang == "en" else 22050
        return np.full(rate // 2, 0.5 if lang == "en" else -0.5, np.float32), rate   # 0.5 s each


def test_render_resamples_and_adds_pauses():
    parts = [ta.Part("Hello.", "en", 0.35), ta.Part("Merhaba.", "tr", 0.0)]
    steps = []
    audio = ta.render(parts, FakeVoices(), progress=steps.append)
    expected = 0.5 + 0.35 + 0.5
    assert len(audio) / ta.OUTPUT_RATE == pytest.approx(expected, abs=0.01)
    assert steps[-1] == 1.0
    assert float(np.max(np.abs(audio))) <= 0.99


def test_render_cancel():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ta.Cancelled):
        ta.render([ta.Part("Hello.", "en", 0)], FakeVoices(), cancel=cancel)


# ---- saving -----------------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["mp3", "m4a", "wav"])
def test_create_speech_file_formats(tmp_path, fmt):
    out = tmp_path / f"speech{ta.FORMATS[fmt]}"
    voices = FakeVoices()
    result = ta.create_speech_file("Hello there friends. Merhaba arkadaşlar nasılsınız.", out, fmt, voices)
    assert result.path == out and out.exists() and not (tmp_path / (out.name + ".part")).exists()
    assert voices.calls == ["en", "tr"] and result.languages == ["en", "tr"]
    decoded = load_media(out)
    assert abs(len(decoded) / 16000 - result.duration) < 0.15


def test_errors(tmp_path):
    with pytest.raises(ta.SpeechError, match="no text"):
        ta.create_speech_file("   ", tmp_path / "x.mp3", "mp3", FakeVoices())
    with pytest.raises(ta.SpeechError, match="format"):
        ta.create_speech_file("Hi.", tmp_path / "x.ogg", "ogg", FakeVoices())
    with pytest.raises(ta.SpeechError, match="too long"):
        ta.create_speech_file("a" * (ta.MAX_TEXT_CHARS + 1), tmp_path / "x.mp3", "mp3", FakeVoices())
    cancel = threading.Event(); cancel.set()
    with pytest.raises(ta.Cancelled):
        ta.create_speech_file("Hello.", tmp_path / "y.mp3", "mp3", FakeVoices(), cancel=cancel)
    assert list(tmp_path.iterdir()) == []                  # nothing written


def test_read_text_file_encodings(tmp_path):
    utf8 = tmp_path / "a.txt"; utf8.write_text("Güneş ışığı", encoding="utf-8-sig")
    old = tmp_path / "b.txt"; old.write_bytes("Güneş ışığı".encode("cp1254"))
    assert ta.read_text_file(utf8) == "Güneş ışığı"
    assert ta.read_text_file(old) == "Güneş ışığı"
    with pytest.raises(ta.SpeechError, match="not found"):
        ta.read_text_file(tmp_path / "missing.txt")


def test_free_output_path(tmp_path):
    (tmp_path / "notes.mp3").write_bytes(b"x")
    assert ta.free_output_path(tmp_path / "notes.txt", ".mp3") == tmp_path / "notes (2).mp3"
    assert ta.free_output_path(tmp_path / "other.txt", ".mp3") == tmp_path / "other.mp3"


# ---- the window ---------------------------------------------------------------------
def test_window_converts_text_files(tmp_path, monkeypatch, cfg):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from textureng.ui import speech_window

    monkeypatch.setattr(ta, "VoiceSet", lambda *a, **k: FakeVoices())
    source = tmp_path / "letter.txt"
    source.write_text("Merhaba. Bu bir deneme mektubudur.\n\nThis is a test letter.", encoding="utf-8")
    window = speech_window.SpeechWindow(cfg)
    window.add_files([str(source), str(source)])           # duplicate ignored
    assert window.table.rowCount() == 1 and window.tabs.currentIndex() == 1
    window.create()
    deadline = time.time() + 30
    while window.running and time.time() < deadline:
        app.processEvents(); time.sleep(0.02)
    app.processEvents()
    assert window.table.item(0, 1).text().startswith("Done")
    assert (tmp_path / "letter.mp3").exists()
    window.clear_list()
    assert window.table.rowCount() == 0 and (tmp_path / "letter.mp3").exists()
    window.shutdown()


def test_window_clear_text(tmp_path, monkeypatch, cfg):
    from PySide6.QtWidgets import QApplication, QFileDialog

    app = QApplication.instance() or QApplication([])
    from textureng.ui import speech_window

    monkeypatch.setattr(ta, "VoiceSet", lambda *a, **k: FakeVoices())
    target = tmp_path / "pasted.mp3"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    window = speech_window.SpeechWindow(cfg)
    assert not window.clear_text_button.isEnabled()          # nothing to clear yet
    window.text.setPlainText("Hello there. Merhaba.")
    assert window.clear_text_button.isEnabled()
    window.create()
    deadline = time.time() + 30
    while window.running and time.time() < deadline:
        app.processEvents(); time.sleep(0.02)
    app.processEvents()
    assert window.text_result.text().startswith("Saved:") and target.exists()
    window.clear_text()
    assert window.text.toPlainText() == "" and window.text_result.text() == ""
    assert not window.open_audio.isVisible() and not window.clear_text_button.isEnabled()
    assert target.exists()                                   # the saved file is kept
    window.shutdown()


def test_voice_summary_licence_note(cfg, monkeypatch):
    from textureng import tts
    from textureng.ui.speech_window import voice_summary

    monkeypatch.setattr(tts, "neural_available", lambda: True)
    cfg["tts_voice_tr"] = "tr_TR-fahrettin-medium"
    text, note = voice_summary(cfg)
    assert "Fahrettin" in text and "Fahrettin" in note
    cfg["tts_voice_tr"] = "tr_TR-fettah-medium"
    assert voice_summary(cfg)[1] == ""                     # CC0 + public domain: no note
    cfg["tts_engine"] = "windows"
    assert "Windows voice" in voice_summary(cfg)[0]
