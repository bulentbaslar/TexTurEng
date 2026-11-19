import httpx
import numpy as np
import pytest

from textureng import cleanup
from textureng.audio import SAMPLE_RATE, load_wav, to_wav_bytes
from textureng.config import Config
from textureng.context import AppInfo, resolve_profile
from textureng.history import History
from textureng.hotkey import HotkeyState, parse_combo
from textureng.pipeline import run_pipeline
from textureng.stt.base import Transcript


# ---- context ---------------------------------------------------------------
@pytest.mark.parametrize(
    "process,title,expected",
    [
        ("outlook.exe", "Inbox - Outlook", "email"),
        ("OUTLOOK.EXE", "", "email"),
        ("slack.exe", "general - Slack", "chat"),
        ("code.exe", "main.py - Visual Studio Code", "code"),
        ("windowsterminal.exe", "PowerShell", "code"),
        ("winword.exe", "Slack notes.docx - Word", "document"),
        ("chrome.exe", "Inbox (3) - someone@gmail.com - Gmail - Google Chrome", "email"),
        ("msedge.exe", "WhatsApp - Microsoft Edge", "chat"),
        ("chrome.exe", "Untitled document - Google Docs - Google Chrome", "document"),
        ("chrome.exe", "Weather forecast - Google Chrome", "default"),
        ("notepad.exe", "gmail password.txt - Notepad", "default"),
        ("", "", "default"),
    ],
)
def test_resolve_profile(cfg, process, title, expected):
    assert resolve_profile(AppInfo(process.lower(), title), cfg["profiles"], cfg["browsers"]) == expected


# ---- hotkeys ---------------------------------------------------------------
def make_state():
    return HotkeyState(parse_combo("ctrl+win"), parse_combo("Ctrl + Win + Space"), parse_combo("escape"))


def test_parse_combo_aliases():
    assert parse_combo("Control+Cmd") == {"ctrl", "win"}
    assert parse_combo("") == frozenset()


def test_push_to_talk():
    s = make_state()
    assert s.press("ctrl") is None
    assert s.press("win") == "start"
    assert s.press("win") is None  # auto-repeat
    assert s.release("ctrl") == "stop"
    assert s.release("win") is None


def test_hands_free_latch_and_stop():
    s = make_state()
    s.press("ctrl")
    assert s.press("win") == "start"
    assert s.press("space") is None           # latches
    for key in ("space", "win", "ctrl"):
        assert s.release(key) is None         # keeps recording
    assert s.recording
    s.press("ctrl"); s.press("win")
    assert s.press("space") == "stop"
    assert not s.recording


def test_escape_cancels_and_blocks_until_release():
    s = make_state()
    s.press("ctrl"); s.press("win")
    assert s.press("esc") == "cancel"
    assert s.release("esc") is None
    assert s.release("win") is None           # no stop after a cancel
    assert s.release("ctrl") is None
    s.press("ctrl")
    assert s.press("win") == "start"          # works again


def test_other_shortcut_cancels_hold():
    s = make_state()
    s.press("ctrl"); s.press("win")
    assert s.press("left") == "cancel"        # Ctrl+Win+Left switches desktops


def test_extra_modifier_does_not_start():
    s = make_state()
    s.press("shift"); s.press("ctrl")
    assert s.press("win") is None


# ---- cleanup ---------------------------------------------------------------
def test_build_messages(cfg):
    messages = cleanup.build_messages("um hello", cfg["profiles"]["email"], "tr", ["Ayşe", "Textureng"])
    system = messages[0]["content"]
    assert "Turkish" in system and "Email" in system and "Ayşe, Textureng" in system
    assert messages[1]["content"] == "<transcript>um hello</transcript>"


def test_polish_uses_model_output(cfg, monkeypatch):
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: '"Hello there."')
    result = cleanup.polish("um hello there", cfg["profiles"]["default"], "en", cfg)
    assert result.text == "Hello there." and result.used_llm and not result.warning


def test_polish_falls_back_when_ollama_is_down(cfg, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cleanup, "_post_chat", boom)
    result = cleanup.polish("um hello there", cfg["profiles"]["default"], "en", cfg)
    assert result.text == "um hello there" and not result.used_llm and "Ollama" in result.warning


def test_polish_rejects_an_answer_instead_of_cleanup(cfg, monkeypatch):
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "Sure! Here is a poem.\n" + "roses are red " * 30)
    result = cleanup.polish("write me a poem", cfg["profiles"]["default"], "en", cfg)
    assert result.text == "write me a poem" and result.warning


def test_cloud_cleanup(cfg, monkeypatch):
    cfg["cleanup_provider"] = "cloud"
    seen = {}

    def fake_cloud(base_url, key, model, messages, timeout):
        seen.update(base_url=base_url, key=key, model=model)
        return "Hello there."

    monkeypatch.setattr(cleanup, "_cloud_key", lambda: "test-key")
    monkeypatch.setattr(cleanup, "_post_cloud_chat", fake_cloud)
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: pytest.fail("Ollama must not be used"))
    result = cleanup.polish("um hello there", cfg["profiles"]["default"], "en", cfg)
    assert result.text == "Hello there." and result.used_llm
    assert seen == {"base_url": cfg["cloud_base_url"], "key": "test-key", "model": cfg["cloud_cleanup_model"]}


def test_cloud_cleanup_without_key_or_with_bad_key(cfg, monkeypatch):
    cfg["cleanup_provider"] = "cloud"
    monkeypatch.setattr(cleanup, "_cloud_key", lambda: "")
    result = cleanup.polish("um hello", cfg["profiles"]["default"], "en", cfg)
    assert result.text == "um hello" and "API key" in result.warning

    def rejected(*a, **k):
        request = httpx.Request("POST", "https://example.invalid")
        raise httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request))

    monkeypatch.setattr(cleanup, "_cloud_key", lambda: "bad")
    monkeypatch.setattr(cleanup, "_post_cloud_chat", rejected)
    result = cleanup.polish("um hello", cfg["profiles"]["default"], "en", cfg)
    assert result.text == "um hello" and "API key rejected" in result.warning


def test_first_run_modes(cfg):
    from textureng.ui.welcome import apply_choices

    apply_choices(cfg, "cloud", "cloud")
    assert cfg["stt_engine"] == "cloud" and cfg["cleanup_provider"] == "cloud" and cfg["cleanup_enabled"]
    apply_choices(cfg, "cloud", "ollama", "gemma3:4b")   # cloud speech + Ollama on the laptop
    assert (cfg["stt_engine"], cfg["cleanup_provider"], cfg["ollama_model"]) == ("cloud", "ollama", "gemma3:4b")
    apply_choices(cfg, "local", "off")
    assert (cfg["stt_engine"], cfg["local_model"], cfg["local_device"]) == ("local", "small", "cpu")
    assert not cfg["cleanup_enabled"] and cfg["cleanup_provider"] == "ollama"


def test_list_ollama_models_unreachable():
    assert cleanup.list_ollama_models("http://127.0.0.1:9") is None


def test_polish_disabled(cfg, monkeypatch):
    cfg["cleanup_enabled"] = False
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: pytest.fail("should not be called"))
    assert cleanup.polish(" raw text ", cfg["profiles"]["default"], "en", cfg).text == "raw text"


# ---- pipeline, audio, config, history ---------------------------------------
class FakeTranscriber:
    name = "fake"

    def load(self):
        pass

    def transcribe(self, audio, language="auto", candidates=None, terms=None):
        self.seen = (language, candidates, terms)
        return Transcript("ee yarın görüşelim", "tr")


def test_run_pipeline(cfg, monkeypatch):
    captured = {}

    def fake_post(url, model, messages, timeout):
        captured["system"] = messages[0]["content"]
        return "Yarın görüşelim"

    monkeypatch.setattr(cleanup, "_post_chat", fake_post)
    fake = FakeTranscriber()
    result = run_pipeline(np.zeros(SAMPLE_RATE, dtype=np.float32), AppInfo("slack.exe", "x"), cfg, fake)
    assert result.profile == "chat" and result.text == "Yarın görüşelim" and result.raw == "ee yarın görüşelim"
    assert fake.seen[0] == "auto" and fake.seen[1] == ["en", "tr"]
    assert "Chat" in captured["system"] and "Turkish" in captured["system"]


def test_wav_round_trip(tmp_path):
    tone = (0.5 * np.sin(np.linspace(0, 440 * 2 * np.pi, SAMPLE_RATE))).astype(np.float32)
    path = tmp_path / "tone.wav"
    path.write_bytes(to_wav_bytes(tone))
    loaded = load_wav(path)
    assert len(loaded) == SAMPLE_RATE and np.allclose(loaded, tone, atol=1e-3)


def test_config_persists_and_merges_new_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"ollama_model": "other:1b", "profiles": {"chat": {"style": "mine"}}}', encoding="utf-8")
    cfg = Config(path)
    assert cfg["ollama_model"] == "other:1b"
    assert cfg["profiles"]["chat"]["style"] == "mine"
    assert "slack.exe" in cfg["profiles"]["chat"]["processes"]   # default kept
    assert cfg["hotkey_ptt"] == "ctrl+win"
    cfg["language"] = "tr"
    cfg.save()
    assert Config(path)["language"] == "tr"


def test_history(tmp_path):
    history = History(tmp_path / "h.db")
    history.add("slack.exe", "chat", "en", "um hi", "Hi")
    history.add("code.exe", "code", "en", "raw", "Polished")
    rows = history.recent()
    assert [r[5] for r in rows] == ["Polished", "Hi"]
    history.clear()
    assert history.recent() == []
