import io
import tarfile
import threading
import wave

import numpy as np
import pytest

from textureng import tts


# ---- choosing voices and splitting text -------------------------------------
def test_voice_for_defaults_and_unknown_values(cfg):
    assert tts.voice_for(cfg, "en") == "en_US-ljspeech-medium"
    assert tts.voice_for(cfg, "tr") == "tr_TR-fahrettin-medium"
    cfg["tts_voice_tr"] = "tr_TR-fettah-medium"
    assert tts.voice_for(cfg, "tr") == "tr_TR-fettah-medium"
    cfg["tts_voice_tr"] = "something-else"
    assert tts.voice_for(cfg, "tr") == "tr_TR-fahrettin-medium"
    assert tts.voice_for(cfg, "de") == ""


def test_every_default_voice_is_listed():
    for lang, voice in tts.DEFAULT_VOICES.items():
        assert voice in {v.id for v in tts.NEURAL_VOICES[lang]}


def test_split_text_keeps_sentences_and_paragraphs():
    text = "Hello there. How are you?\n\nSecond paragraph here!"
    assert tts.split_text(text, limit=20) == ["Hello there.", "How are you?", "Second paragraph here!"]
    assert tts.split_text("Short one. Another.", limit=300) == ["Short one. Another."]
    long_sentence = "word " * 400
    pieces = tts.split_text(long_sentence, limit=100)
    assert all(len(p) <= 200 for p in pieces) and " ".join(pieces).split() == long_sentence.split()
    assert tts.split_text("  \n \n ") == []


def test_wav_to_samples():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.array([0, 16384, -16384], dtype="<i2")).tobytes())
    samples, rate = tts.wav_to_samples(buffer.getvalue())
    assert rate == 16000 and np.allclose(samples, [0, 0.5, -0.5])


# ---- downloading voices ----------------------------------------------------------
def make_archive(path, members):
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_unpack_voice(tmp_path):
    archive = tmp_path / "v.tar.bz2"
    make_archive(archive, {
        "vits-piper-tr_TR-fettah-medium/tokens.txt": b"a 1",
        "vits-piper-tr_TR-fettah-medium/tr_TR-fettah-medium.onnx": b"model",
    })
    tts.unpack_voice(archive, tmp_path)
    assert (tmp_path / "vits-piper-tr_TR-fettah-medium" / "tokens.txt").exists()


def test_unpack_voice_refuses_paths_outside_the_folder(tmp_path):
    archive = tmp_path / "bad.tar.bz2"
    make_archive(archive, {"../escaped.txt": b"x"})
    with pytest.raises(tarfile.TarError):
        tts.unpack_voice(archive, tmp_path / "voices")
    assert not (tmp_path / "escaped.txt").exists()


def test_is_downloaded(isolated_home):
    assert not tts.is_downloaded("tr_TR-fettah-medium")
    folder = tts.voice_path("tr_TR-fettah-medium")
    folder.mkdir(parents=True)
    (folder / "tokens.txt").write_text("a 1")
    (folder / "tr_TR-fettah-medium.onnx").write_bytes(b"m")
    assert tts.is_downloaded("tr_TR-fettah-medium")


# ---- the speaker ------------------------------------------------------------------
class FakeEngine:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def synthesize(self, text, *args):
        if self.fail:
            raise tts.SpeechError("no voice")
        self.calls.append((text,) + args)
        return np.zeros(100, dtype=np.float32), 22050


def make_speaker(cfg, monkeypatch, neural=True):
    played = []
    speaker = tts.Speaker(cfg, player=lambda samples, rate, stop: played.append(rate))
    speaker.windows = FakeEngine()
    monkeypatch.setattr(tts, "neural_available", lambda: neural)
    monkeypatch.setattr(tts, "is_downloaded", lambda voice: True)
    monkeypatch.setattr(speaker.neural, "_load", lambda voice: None)
    monkeypatch.setattr(speaker.neural, "synthesize", lambda text, voice, speed: (np.zeros(10, np.float32), 22050))
    events = []
    for name in ("started", "finished", "status", "failed"):
        getattr(speaker, name).connect(lambda *a, n=name: events.append((n,) + a))
    return speaker, played, events


def test_engine_choice(cfg, monkeypatch):
    speaker, _, _ = make_speaker(cfg, monkeypatch, neural=True)
    assert speaker.engine_for("tr") == "neural"
    cfg["tts_engine"] = "windows"
    assert speaker.engine_for("tr") == "windows"
    cfg["tts_engine"] = "auto"
    monkeypatch.setattr(tts, "neural_available", lambda: False)
    assert speaker.engine_for("tr") == "windows"
    assert speaker.engine_for("de") == "windows"


def test_speaks_each_sentence_with_the_neural_voice(cfg, monkeypatch):
    speaker, played, events = make_speaker(cfg, monkeypatch)
    speaker._run("Bir. İki. Üç.", "tr", threading.Event())
    assert played == [22050]   # short text: one piece
    assert events[0] == ("started",) and events[-1] == ("finished",)
    assert not speaker.windows.calls


def test_falls_back_to_windows_voice(cfg, monkeypatch):
    speaker, played, events = make_speaker(cfg, monkeypatch)

    def broken(voice):
        raise RuntimeError("model file damaged")

    monkeypatch.setattr(speaker.neural, "_load", broken)
    cfg["tts_speed"] = 1.15
    speaker._run("Merhaba", "tr", threading.Event())
    assert speaker.windows.calls == [("Merhaba", "tr", 1.15)] and played
    assert not [e for e in events if e[0] == "failed"]


def test_reports_when_no_voice_is_available(cfg, monkeypatch):
    speaker, played, events = make_speaker(cfg, monkeypatch, neural=False)
    speaker.windows = FakeEngine(fail=True)
    speaker._run("Merhaba", "tr", threading.Event())
    assert ("failed", "no voice") in events and not played


def test_stop_before_playing(cfg, monkeypatch):
    speaker, played, events = make_speaker(cfg, monkeypatch)
    stop = threading.Event()
    stop.set()
    speaker._run("One. Two.", "en", stop)
    assert not played and not [e for e in events if e[0] == "failed"]


def test_download_progress_is_reported(cfg, monkeypatch):
    speaker, played, events = make_speaker(cfg, monkeypatch)
    monkeypatch.setattr(tts, "is_downloaded", lambda voice: False)
    monkeypatch.setattr(tts, "download_voice", lambda voice, progress: progress(0.5))
    speaker._run("Merhaba", "tr", threading.Event())
    assert ("status", "Downloading the Turkish voice… 50%") in events and played
