import sqlite3

import numpy as np
import pytest

from textureng import cleanup
from textureng.audio import SAMPLE_RATE
from textureng.context import AppInfo
from textureng.history import History
from textureng.hotkey import HotkeyState, parse_combo
from textureng.pipeline import run_pipeline, translation_target
from textureng.stt.base import Transcript


# ---- hotkeys ---------------------------------------------------------------
def make_state():
    return HotkeyState(
        parse_combo("ctrl+win"), parse_combo("ctrl+win+space"), parse_combo("esc"), parse_combo("ctrl+win+alt")
    )


def test_alt_during_hold_switches_to_translation():
    s = make_state()
    s.press("ctrl")
    assert s.press("win") == "start"
    assert s.press("alt") == "translate"
    assert s.press("alt") is None            # auto-repeat
    assert s.release("alt") is None          # still holding ctrl+win: keep recording
    assert s.recording and s.translating
    assert s.release("win") == "stop"


def test_translate_combo_pressed_first():
    s = make_state()
    s.press("alt"); s.press("ctrl")
    assert s.press("win") == "start_translate"
    assert s.translating
    assert s.release("ctrl") == "stop"


def test_altgr_does_not_start_anything():
    s = make_state()                         # AltGr on a Turkish keyboard = Ctrl+Alt
    assert s.press("ctrl") is None
    assert s.press("alt") is None
    assert s.release("alt") is None and s.release("ctrl") is None
    assert not s.recording


def test_normal_hold_is_not_translated():
    s = make_state()
    s.press("ctrl"); s.press("win")
    assert not s.translating
    assert s.release("ctrl") == "stop"


def test_translate_in_hands_free_mode():
    s = make_state()
    s.press("ctrl"); s.press("win"); s.press("space")   # latch hands-free
    for key in ("space", "win", "ctrl"):
        s.release(key)
    s.press("ctrl"); s.press("win")
    assert s.press("alt") == "translate"
    assert s.recording


def test_cancel_during_translation_then_new_start():
    s = make_state()
    s.press("alt"); s.press("ctrl"); s.press("win")
    assert s.press("esc") == "cancel"
    for key in ("esc", "alt", "ctrl", "win"):
        assert s.release(key) is None
    s.press("ctrl")
    assert s.press("win") == "start" and not s.translating


# ---- prompt and cleanup -----------------------------------------------------
def test_translation_prompt(cfg):
    system = cleanup.build_messages("ee merhaba", cfg["profiles"]["email"], "tr", [], target="en")[0]["content"]
    assert "Translate into English" in system and "The transcript is in Turkish" in system
    assert "Never translate" not in system
    assert "I can join the meeting tomorrow at three" in system      # tr -> en example
    assert "Bütçeyi" not in system                                    # no en -> tr example


def test_normal_prompt_still_keeps_language(cfg):
    system = cleanup.build_messages("um hi", cfg["profiles"]["chat"], "en", [])[0]["content"]
    assert "Never translate" in system and "Translate into" not in system


def test_translation_runs_even_when_cleanup_is_off(cfg, monkeypatch):
    cfg["cleanup_enabled"] = False
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "Merhaba, nasılsın?")
    result = cleanup.polish("um hi how are you", cfg["profiles"]["default"], "en", cfg, target="tr")
    assert result.text == "Merhaba, nasılsın?" and result.used_llm


def test_translation_to_same_language_is_plain_cleanup(cfg, monkeypatch):
    seen = {}

    def fake(url, model, messages, timeout):
        seen["system"] = messages[0]["content"]
        return "Hi, how are you?"

    monkeypatch.setattr(cleanup, "_post_chat", fake)
    cleanup.polish("um hi how are you", cfg["profiles"]["default"], "en", cfg, target="en")
    assert "Never translate" in seen["system"]


def test_translation_failure_pastes_original(cfg, monkeypatch):
    import httpx

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cleanup, "_post_chat", down)
    result = cleanup.polish("um hi", cfg["profiles"]["default"], "en", cfg, target="tr")
    assert result.text == "um hi" and "untranslated" in result.warning


def test_longer_turkish_translation_is_accepted(cfg, monkeypatch):
    raw = "send the manual by friday"
    longer = "Lütfen bakım el kitabının güncel sürümünü cuma gününe kadar bana gönderir misiniz?"
    assert cleanup.is_suspicious(longer, raw)  # the normal cleanup limit would reject it
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: longer)
    assert cleanup.polish(raw, cfg["profiles"]["default"], "en", cfg, target="tr").used_llm


# ---- pipeline ---------------------------------------------------------------
@pytest.mark.parametrize(
    "setting,spoken,expected",
    [("auto", "en", "tr"), ("auto", "tr", "en"), ("auto", "", "en"), ("en", "en", "en"), ("tr", "en", "tr")],
)
def test_translation_target(cfg, setting, spoken, expected):
    cfg["translate_target"] = setting
    assert translation_target(cfg, spoken) == expected


class FakeTranscriber:
    name = "fake"

    def load(self):
        pass

    def transcribe(self, audio, language="auto", candidates=None, terms=None):
        return Transcript("ee yarın görüşelim", "tr")


def test_pipeline_translates(cfg, monkeypatch):
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "See you tomorrow")
    audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
    result = run_pipeline(audio, AppInfo("slack.exe", ""), cfg, FakeTranscriber(), translate=True)
    assert result.text == "See you tomorrow" and result.translated_to == "en" and result.raw == "ee yarın görüşelim"
    plain = run_pipeline(audio, AppInfo("slack.exe", ""), cfg, FakeTranscriber())
    assert plain.translated_to == ""


# ---- history ----------------------------------------------------------------
def test_history_upgrades_old_database(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE dictation (id INTEGER PRIMARY KEY, ts REAL, app TEXT, profile TEXT, "
                   "language TEXT, raw TEXT, text TEXT)")
        db.execute("INSERT INTO dictation (ts, app, profile, language, raw, text) VALUES (1, 'a', 'chat', 'en', 'r', 't')")
    history = History(path)
    history.add("outlook.exe", "email", "tr", "merhaba", "Hello", translated_to="en")
    rows = history.recent()
    assert rows[0][6] == "en" and rows[1][6] == ""
