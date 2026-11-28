import threading
from pathlib import Path

import numpy as np
import pytest

from textureng import transcribe_file as tf
from textureng.audio import load_wav
from textureng.transcribe_file import Segment

ASSET = Path(__file__).parent / "assets" / "english.wav"
SR = tf.SAMPLE_RATE


# ---- SRT and TXT formatting --------------------------------------------------------
def test_srt_time():
    assert tf.srt_time(0) == "00:00:00,000"
    assert tf.srt_time(62.3456) == "00:01:02,346"
    assert tf.srt_time(3723.5) == "01:02:03,500"


def test_srt_numbering_and_layout():
    srt = tf.to_srt([Segment(0.0, 2.5, "Merhaba.", "tr"), Segment(3.0, 5.0, "Hello there.", "en")])
    assert srt == (
        "1\n00:00:00,000 --> 00:00:02,500\nMerhaba.\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nHello there.\n"
    )


def test_long_segment_is_split_into_short_cues():
    text = " ".join(["word"] * 60)              # far more than 2 lines of 42 characters
    cues = tf.subtitle_cues([Segment(10.0, 40.0, text, "en")])
    assert len(cues) > 1
    for start, end, cue in cues:
        lines = cue.split("\n")
        assert len(lines) <= 2 and all(len(line) <= 42 for line in lines)
        assert 10.0 <= start < end <= 40.0 + 1e-6
    assert cues[0][0] == 10.0 and abs(cues[-1][1] - 40.0) < 1e-6
    assert all(cues[i][1] == pytest.approx(cues[i + 1][0]) for i in range(len(cues) - 1))
    assert sum(len(c[2].split()) for c in cues) == 60


def test_txt_paragraphs_after_pauses():
    segments = [Segment(0, 2, "One.", "en"), Segment(2.5, 4, "Two.", "en"), Segment(7, 8, "Üç.", "tr")]
    assert tf.to_txt(segments) == "One. Two.\n\nÜç.\n"
    assert tf.to_txt([]) == ""


def test_never_overwrites(tmp_path):
    source = tmp_path / "talk.m4a"
    assert tf.free_output_path(source, ".txt") == tmp_path / "talk.txt"
    (tmp_path / "talk.txt").write_text("mine")
    (tmp_path / "talk (2).txt").write_text("mine too")
    assert tf.free_output_path(source, ".txt") == tmp_path / "talk (3).txt"


# ---- grouping speech into chunks ----------------------------------------------------
def test_group_regions():
    regions = [(0, 10), (12, 20), (100, 110), (111, 300)]
    assert tf.group_regions(regions, max_len=50, max_gap=5) == [(0, 20), (100, 110), (111, 300)]
    assert tf.group_regions(regions, max_len=1000, max_gap=float("inf")) == [(0, 300)]
    assert tf.group_regions([], 10, 1) == []


# ---- transcribing with fake engines -------------------------------------------------
class FakeLocal:
    """Speaks Turkish in the first half of the audio and English in the second."""

    def __init__(self):
        self.calls = []

    def pick_language(self, piece, candidates):
        return "tr" if piece.mean() > 0 else "en"

    def transcribe_chunk(self, piece, language, terms=None):
        self.calls.append(language)
        return [(0.0, len(piece) / SR, "Merhaba dünya." if language == "tr" else "Hello world.")]


def two_speech_parts():
    audio = np.zeros(SR * 20, np.float32)
    audio[SR * 1:SR * 4] = 0.3       # "Turkish" speech (positive mean)
    audio[SR * 12:SR * 15] = -0.3    # "English" speech
    return audio


def fake_regions(audio):
    return [(SR * 1, SR * 4), (SR * 12, SR * 15)]


def test_each_chunk_gets_its_own_language(monkeypatch):
    monkeypatch.setattr(tf, "speech_regions", fake_regions)
    steps = []
    segments = tf.transcribe_audio(two_speech_parts(), FakeLocal(), "auto", progress=steps.append)
    assert [(s.text, s.language) for s in segments] == [("Merhaba dünya.", "tr"), ("Hello world.", "en")]
    assert segments[0].start == pytest.approx(1.0) and segments[1].start == pytest.approx(12.0)
    assert steps[-1] == 1.0 and steps == sorted(steps)


def test_fixed_language_is_used_everywhere(monkeypatch):
    monkeypatch.setattr(tf, "speech_regions", fake_regions)
    engine = FakeLocal()
    tf.transcribe_audio(two_speech_parts(), engine, "en")
    assert engine.calls == ["en", "en"]


def test_silence_phrase_is_dropped(monkeypatch):
    class SaysThankYou(FakeLocal):
        def transcribe_chunk(self, piece, language, terms=None):
            return [(0.0, len(piece) / SR, "Thank you.")]

    audio = np.zeros(SR * 5, np.float32) + 0.001       # near silence
    monkeypatch.setattr(tf, "speech_regions", lambda a: [(0, len(a))])
    assert tf.transcribe_audio(audio, SaysThankYou(), "en") == []


def test_cancel(monkeypatch):
    monkeypatch.setattr(tf, "speech_regions", fake_regions)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(tf.Cancelled):
        tf.transcribe_audio(two_speech_parts(), FakeLocal(), "auto", cancel=cancel)


class FakeCloud:
    def __init__(self):
        self.lengths = []

    def transcribe_timed(self, piece, language="auto", terms=None):
        self.lengths.append(len(piece) / SR)
        return [(0.5, 2.0, "Bir."), (2.0, 3.0, "İki.")], "tr"


def test_cloud_chunks_and_time_offsets(monkeypatch):
    minute = 60 * SR
    regions = [(i * minute, i * minute + 20 * SR) for i in range(25)]      # 25 min of talk
    monkeypatch.setattr(tf, "speech_regions", lambda a: regions)
    engine = FakeCloud()
    audio = np.zeros(26 * minute, np.float32)
    segments = tf.transcribe_audio(audio, engine, "auto")
    assert len(engine.lengths) == 3 and max(engine.lengths) <= tf.CLOUD_CHUNK_S
    starts = [s.start for s in segments if s.text == "Bir."]
    assert starts[0] == pytest.approx(0.5) and starts[1] > 9 * 60    # second chunk shifted
    assert {s.language for s in segments} == {"tr"}


# ---- whole files -------------------------------------------------------------------------
def write_m4a(samples, path):
    import av

    container = av.open(str(path), "w")
    stream = container.add_stream("aac", rate=SR)
    stream.layout = "mono"
    frame = av.AudioFrame.from_ndarray(
        (np.clip(samples, -1, 1) * 32767).astype(np.int16).reshape(1, -1), format="s16", layout="mono")
    frame.rate = SR
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()


def test_load_m4a(tmp_path):
    original = load_wav(ASSET)
    path = tmp_path / "speech.m4a"
    write_m4a(original, path)
    decoded = tf.load_media(path)
    assert abs(len(decoded) - len(original)) < SR * 0.2           # same length within 0.2 s
    assert float(np.max(np.abs(decoded))) > 0.1                    # sound survived


def test_unreadable_files(tmp_path):
    with pytest.raises(tf.TranscribeError, match="not found"):
        tf.load_media(tmp_path / "missing.m4a")
    bad = tmp_path / "notes.m4a"
    bad.write_text("this is not audio")
    with pytest.raises(tf.TranscribeError, match="Could not read"):
        tf.load_media(bad)


def test_transcribe_file_writes_txt_and_srt(tmp_path, monkeypatch):
    source = tmp_path / "meeting.m4a"
    write_m4a(two_speech_parts(), source)
    monkeypatch.setattr(tf, "speech_regions", fake_regions)
    result = tf.transcribe_file(source, FakeLocal(), "auto", make_srt=True)
    assert result.txt_path == tmp_path / "meeting.txt" and result.srt_path == tmp_path / "meeting.srt"
    assert result.txt_path.read_text(encoding="utf-8") == "Merhaba dünya.\n\nHello world.\n"
    assert result.srt_path.read_text(encoding="utf-8").startswith("1\n00:00:01,000 --> ")
    assert result.languages == ["en", "tr"] and result.segments == 2
    again = tf.transcribe_file(source, FakeLocal(), "auto", make_srt=False)
    assert again.txt_path.name == "meeting (2).txt" and again.srt_path is None


def test_window_clear_list_keeps_files(tmp_path, monkeypatch, cfg):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from textureng.ui.transcribe_window import TranscribeWindow

    source = tmp_path / "meeting.m4a"
    write_m4a(two_speech_parts(), source)
    monkeypatch.setattr(tf, "speech_regions", fake_regions)
    window = TranscribeWindow(cfg, lambda: FakeLocal())
    window.add_files([str(source)])
    window.start()
    window._running = True
    window.clear_list()                       # refused while running
    assert window.table.rowCount() == 1
    import time
    deadline = time.time() + 30
    while window.job and window.table.item(0, 1).text().startswith(("Waiting", "Transcribing")) and time.time() < deadline:
        app.processEvents(); time.sleep(0.02)
    for _ in range(20):
        app.processEvents(); time.sleep(0.02)
    assert window.table.item(0, 1).text().startswith("Done")
    window.clear_list()
    assert window.table.rowCount() == 0 and window.progress.value() == 0
    assert (tmp_path / "meeting.txt").exists() and (tmp_path / "meeting.srt").exists()
    window.shutdown()


def test_nothing_written_when_cancelled_or_silent(tmp_path, monkeypatch):
    source = tmp_path / "quiet.m4a"
    write_m4a(np.zeros(SR * 3, np.float32), source)
    monkeypatch.setattr(tf, "speech_regions", lambda a: [])
    with pytest.raises(tf.TranscribeError, match="No speech"):
        tf.transcribe_file(source, FakeLocal(), "auto")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["quiet.m4a"]
