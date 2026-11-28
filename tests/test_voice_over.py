import time

import numpy as np
import pytest

from textureng import text_to_audio as ta
from textureng.transcribe_file import Segment, load_media, to_srt

RATE = ta.OUTPUT_RATE


# ---- reading .srt -----------------------------------------------------------------
def test_parse_srt_standard_and_messy():
    srt = (
        "﻿1\r\n00:00:02,000 --> 00:00:05,500\r\nWelcome to the\r\n<i>training.</i>\r\n\r\n"
        "2\n00:00:08.000 --> 00:00:11,000\n{\\an8}Yağ seviyesini kontrol edin.\n\n"
        "00:01:00,5 --> 00:01:02,000\nNo number here.\n\n"
        "4\n00:01:05,000 --> 00:01:06,000\n\n"            # empty text: skipped
    )
    cues = ta.parse_srt(srt)
    assert [(c.start, c.end, c.text) for c in cues] == [
        (2.0, 5.5, "Welcome to the training."),
        (8.0, 11.0, "Yağ seviyesini kontrol edin."),
        (60.5, 62.0, "No number here."),
    ]
    assert ta.parse_srt("just some text") == []


def test_parse_srt_reads_our_own_subtitles():
    segments = [Segment(1.0, 3.0, "Merhaba dünya.", "tr"), Segment(4.0, 6.5, "Hello world.", "en")]
    cues = ta.parse_srt(to_srt(segments))
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 3.0, "Merhaba dünya."), (4.0, 6.5, "Hello world.")]


# ---- timing --------------------------------------------------------------------------
class TimedVoices:
    """Speech takes 0.1 s per character at speed 1.0 (faster at higher speeds)."""

    def __init__(self):
        self.calls = []

    def __call__(self, text, lang, speed=1.0):
        self.calls.append((lang, round(speed, 2)))
        seconds = len(text) * 0.1 / speed
        return np.full(int(seconds * RATE), 0.2, np.float32), RATE


def starts(audio):
    """Start times (s) of sound after silence."""
    on = np.abs(audio) > 0.01
    edges = np.flatnonzero(on[1:] & ~on[:-1]) + 1
    return ([0.0] if on[0] else []) + [e / RATE for e in edges]


def test_lines_start_at_their_times():
    cues = [ta.Cue(1.0, 2.0, "Hello."), ta.Cue(5.0, 6.0, "Merhaba.")]     # 0.6 s and 0.8 s of speech
    audio, faster, late, langs = ta.voice_over(cues, TimedVoices())
    assert starts(audio) == pytest.approx([1.0, 5.0], abs=0.01)
    assert faster == 0 and late == []
    assert len(audio) / RATE == pytest.approx(6.0, abs=0.01)                 # as long as the subtitles


def test_long_line_is_read_faster_to_fit():
    voices = TimedVoices()
    cues = [ta.Cue(0.0, 2.0, "x" * 25), ta.Cue(2.2, 3.0, "Next.")]         # 2.5 s of speech, 2.2 s room
    audio, faster, late, _ = ta.voice_over(cues, voices)
    assert faster == 1 and late == []
    assert 1.0 < voices.calls[1][1] <= ta.MAX_SPEEDUP                        # re-read faster
    assert starts(audio)[1] == pytest.approx(2.2, abs=0.01)                  # next line still on time


def test_line_that_cannot_fit_delays_the_next_one():
    cues = [ta.Cue(0.0, 1.0, "x" * 40), ta.Cue(1.0, 2.0, "Next line.")]     # 4 s of speech, 1 s room
    audio, faster, late, _ = ta.voice_over(cues, TimedVoices())
    first_length = 40 * 0.1 / ta.MAX_SPEEDUP
    assert starts(audio)[0] == 0.0
    assert late == [(2, round(first_length - 1.0, 1))]                      # line 2 starts late, no overlap
    assert float(np.max(np.abs(audio))) <= 0.99


def test_languages_per_line():
    cues = [ta.Cue(0, 1, "Yağ seviyesini kontrol edin lütfen."), ta.Cue(2, 3, "Check the oil level please."),
            ta.Cue(4, 5, "Tamam."), ta.Cue(6, 7, "Hello there."), ta.Cue(8, 9, "Boeing 737.")]
    voices = TimedVoices()
    _, _, _, langs = ta.voice_over(cues, voices)
    # short lines: known short words decide; "Boeing 737." follows the line before it
    first_reads = [lang for lang, speed in voices.calls if speed == 1.0]   # re-reads to fit are faster
    assert first_reads == ["tr", "en", "tr", "en", "en"]
    assert langs == ["en", "tr"]


@pytest.mark.parametrize("text,previous,expected", [
    ("Evet.", "en", "tr"), ("Güzel!", "en", "tr"), ("Thank you.", "tr", "en"), ("OK.", "tr", "en"),
    ("A320.", "tr", "tr"), ("Bu bir deneme cümlesidir.", "en", "tr"), ("This is a test.", "tr", "en"),
])
def test_line_language(text, previous, expected):
    assert ta.line_language(text, previous) == expected


# ---- whole file ------------------------------------------------------------------------
def test_create_voice_over_file(tmp_path):
    srt = tmp_path / "v1.2 training.srt"
    srt.write_text(to_srt([Segment(1.0, 2.5, "Hello there.", "en"), Segment(4.0, 6.0, "Merhaba arkadaşlar.", "tr")]),
                   encoding="utf-8")
    out = ta.voice_over_path(srt, ".mp3")
    assert out.name == "v1.2 training voice-over.mp3"
    result = ta.create_voice_over_file(srt, out, "mp3", TimedVoices())
    assert result.lines == 2 and result.languages == ["en", "tr"] and out.exists()
    assert abs(len(load_media(out)) / 16000 - result.duration) < 0.15
    assert ta.voice_over_path(srt, ".mp3").name == "v1.2 training voice-over (2).mp3"
    bad = tmp_path / "empty.srt"
    bad.write_text("nothing", encoding="utf-8")
    with pytest.raises(ta.SpeechError, match="No subtitles"):
        ta.create_voice_over_file(bad, tmp_path / "x.mp3", "mp3", TimedVoices())


def test_window_subtitles_tab(tmp_path, monkeypatch, cfg):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from textureng.ui import speech_window

    monkeypatch.setattr(ta, "VoiceSet", lambda *a, **k: TimedVoices())
    srt = tmp_path / "talk.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:02,000\nHello there.\n", encoding="utf-8")
    txt = tmp_path / "note.txt"
    txt.write_text("Just a note.", encoding="utf-8")
    window = speech_window.SpeechWindow(cfg)
    window.add_files([str(txt), str(srt)])               # routed to the right tabs
    assert window.files.table.rowCount() == 1 and window.srts.table.rowCount() == 1
    assert window.tabs.currentIndex() == speech_window.TAB_SRT
    assert window.create_button.text() == "Create voice-over" and not window.listen_button.isVisible()
    window.create()
    deadline = time.time() + 30
    while window.running and time.time() < deadline:
        app.processEvents(); time.sleep(0.02)
    app.processEvents()
    assert window.srts.table.item(0, 1).text().startswith("Done")
    assert (tmp_path / "talk voice-over.mp3").exists()
    assert window.files.table.item(0, 1).text() == "Waiting"   # other tab untouched
    window.srts.clear()
    assert window.srts.table.rowCount() == 0 and (tmp_path / "talk voice-over.mp3").exists()
    window.shutdown()
