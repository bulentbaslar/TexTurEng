import httpx
import pytest

from textureng import cleanup
from textureng.hotkey import DoubleCopyDetector, key_name


def test_ctrl_c_is_read_as_c():
    class Key:  # what pynput reports for C while Ctrl is held on Windows
        vk, char = 0x43, "\x03"

    assert key_name(Key()) == "c"


# ---- language guess and direction ------------------------------------------
@pytest.mark.parametrize(
    "text,turkish",
    [
        ("Yarınki toplantıya katılabilir misiniz?", True),
        ("Bu raporu ve ekleri bir an önce gönder", True),
        ("bu rapor ve ekler icin bir dakika", True),          # no Turkish letters, common words
        ("Please send the updated manual by Friday.", False),
        ("The aircraft is due for its C-check in May.", False),
        ("Müller GmbH", True),                                # short text with ü
        ("", False),
    ],
)
def test_looks_turkish(text, turkish):
    assert cleanup.looks_turkish(text) is turkish


@pytest.mark.parametrize(
    "setting,text,expected",
    [
        ("auto", "Yarın görüşürüz", ("tr", "en")),
        ("auto", "See you tomorrow", ("en", "tr")),
        ("en", "Yarın görüşürüz", ("tr", "en")),
        ("en", "See you tomorrow", ("en", "tr")),   # already English: flip to Turkish
        ("tr", "See you tomorrow", ("en", "tr")),
        ("tr", "Yarın görüşürüz", ("tr", "en")),
    ],
)
def test_selection_direction(setting, text, expected):
    assert cleanup.selection_direction(text, setting) == expected


# ---- translate_text -----------------------------------------------------------
def test_translate_text_prompt_and_result(cfg, monkeypatch):
    cfg["dictionary"] = ["Textureng"]
    seen = {}

    def fake(url, model, messages, timeout):
        seen["system"], seen["user"] = messages[0]["content"], messages[1]["content"]
        return "<text>See you tomorrow at three.</text>"

    monkeypatch.setattr(cleanup, "_post_chat", fake)
    result = cleanup.translate_text("  Yarın saat üçte görüşürüz.  ", cfg)
    assert (result.text, result.source, result.target, result.error) == ("See you tomorrow at three.", "tr", "en", "")
    assert "translate it into English" in seen["system"] and "never answer" in seen["system"]
    assert "Textureng" in seen["system"]
    assert seen["user"] == "<text>Yarın saat üçte görüşürüz.</text>"


def test_translate_text_runs_when_cleanup_is_off(cfg, monkeypatch):
    cfg["cleanup_enabled"] = False
    monkeypatch.setattr(cleanup, "_post_chat", lambda *a, **k: "Merhaba")
    assert cleanup.translate_text("Hello", cfg).text == "Merhaba"


def test_translate_text_reports_errors(cfg, monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cleanup, "_post_chat", down)
    result = cleanup.translate_text("Hello there", cfg)
    assert result.text == "" and "Ollama translation is not running" in result.error


def test_translate_text_cloud_without_key(cfg, monkeypatch):
    cfg["cleanup_provider"] = "cloud"
    monkeypatch.setattr(cleanup, "_cloud_key", lambda: "")
    assert "No cloud API key" in cleanup.translate_text("Hello", cfg).error


def test_translate_text_truncates_long_selections(cfg, monkeypatch):
    sent = {}

    def fake(url, model, messages, timeout):
        sent["user"], sent["timeout"] = messages[1]["content"], timeout
        return "çeviri"

    monkeypatch.setattr(cleanup, "_post_chat", fake)
    result = cleanup.translate_text("word " * 2000, cfg)
    assert result.truncated and len(sent["user"]) <= cleanup.MAX_SELECTION_CHARS + len("<text></text>")
    assert sent["timeout"] > cfg["ollama_timeout"]   # long text gets more time


def test_translate_text_empty(cfg):
    assert cleanup.translate_text("   ", cfg).error


# ---- Ctrl+C twice ---------------------------------------------------------------
def test_double_copy_detector():
    d = DoubleCopyDetector(window=0.5)
    assert not d.copy_pressed(10.0)
    assert d.copy_pressed(10.3)          # second copy within half a second
    assert not d.copy_pressed(10.4)      # starts a new pair after triggering
    assert not d.copy_pressed(11.5)      # too slow: counts as a new first press
    assert d.copy_pressed(11.9)
    d.copy_pressed(20.0); d.reset()
    assert not d.copy_pressed(20.2)      # another key in between resets
