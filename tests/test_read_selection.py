import pytest
from PySide6.QtWidgets import QApplication

from textureng import selection
from textureng.selection import GestureDetector

WIN = (1, 0, 0, 800, 600)  # (window handle, left, top, right, bottom)


@pytest.fixture(scope="module")
def qapp():
    """A Qt app; whatever was on the real clipboard is put back afterwards."""
    app = QApplication.instance() or QApplication([])
    saved = selection._copy_mime(QApplication.clipboard().mimeData())
    yield app
    if saved is not None:
        QApplication.clipboard().setMimeData(saved)
    else:
        QApplication.clipboard().clear()


# ---- which mouse gestures count as selecting text ----------------------------
def test_drag_across_text_counts():
    d = GestureDetector()
    d.press(100, 100, 0.0, WIN)
    assert d.release(180, 104, 0.4, WIN)


def test_plain_click_does_not_count():
    d = GestureDetector()
    d.press(100, 100, 0.0, WIN)
    assert not d.release(102, 101, 0.1, WIN)


def test_double_click_on_a_word_counts():
    d = GestureDetector()
    d.press(100, 100, 0.0, WIN); assert not d.release(100, 100, 0.05, WIN)
    d.press(101, 100, 0.2, WIN); assert d.release(101, 100, 0.25, WIN)
    d.press(101, 100, 0.4, WIN); assert not d.release(101, 100, 0.45, WIN)  # a new pair starts


def test_slow_or_distant_second_click_does_not_count():
    d = GestureDetector()
    d.press(100, 100, 0.0, WIN); d.release(100, 100, 0.05, WIN)
    d.press(100, 100, 1.0, WIN); assert not d.release(100, 100, 1.05, WIN)   # too slow
    d.press(300, 100, 1.2, WIN); assert not d.release(300, 100, 1.25, WIN)   # elsewhere


def test_moving_a_window_does_not_count():
    d = GestureDetector()
    d.press(100, 10, 0.0, WIN)
    assert not d.release(400, 200, 0.5, (1, 300, 190, 1100, 790))  # the window moved with the mouse


def test_release_without_press():
    assert not GestureDetector().release(5, 5, 0.0, WIN)


# ---- copying the selection keeps the user's clipboard -----------------------------
class FakeKeyboard:
    def __init__(self, on_copy):
        self.on_copy = on_copy

    def pressed(self, key):
        import contextlib
        return contextlib.nullcontext()

    def press(self, key):
        if key == "c":
            self.on_copy()

    def release(self, key):
        pass


def put_on_clipboard(text):
    """Put text on the real Windows clipboard. Another program (clipboard history,
    cloud clipboard, a clipboard manager) may hold it open for a moment, so retry;
    skip the test if it stays busy instead of failing the install."""
    import time
    from PySide6.QtCore import QCoreApplication

    for _ in range(25):
        QApplication.clipboard().setText(text)
        QCoreApplication.processEvents()
        if QApplication.clipboard().text() == text:
            return
        time.sleep(0.1)
    pytest.skip("the Windows clipboard is busy (held by another program)")


def clipboard_text_soon(expected, wait=2.0):
    """Read the clipboard, giving a busy clipboard a moment to become readable."""
    import time
    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + wait
    while True:
        QCoreApplication.processEvents()
        text = QApplication.clipboard().text()
        if text == expected or time.monotonic() > deadline:
            return text
        time.sleep(0.1)


def install_fakes(monkeypatch, copies_text):
    import pynput.keyboard

    state = {"seq": 1}

    def on_copy():
        if copies_text is not None:
            QApplication.clipboard().setText(copies_text)
            state["seq"] += 1

    monkeypatch.setattr(pynput.keyboard, "Controller", lambda: FakeKeyboard(on_copy))
    monkeypatch.setattr(selection, "_clipboard_sequence", lambda: state["seq"])


def test_copy_selection_returns_text_and_restores_clipboard(qapp, monkeypatch):
    put_on_clipboard("what the user had copied before")
    install_fakes(monkeypatch, "  Merhaba dünya  ")
    assert selection.copy_selection(timeout=0.3) == "Merhaba dünya"
    assert clipboard_text_soon("what the user had copied before") == "what the user had copied before"


def test_copy_selection_with_nothing_selected(qapp, monkeypatch):
    put_on_clipboard("unchanged")
    install_fakes(monkeypatch, None)
    assert selection.copy_selection(timeout=0.2) == ""
    assert clipboard_text_soon("unchanged") == "unchanged"


# ---- the floating button ------------------------------------------------------------
def test_bubble_states(qapp):
    from textureng.ui.speak_bubble import SpeakBubble

    b = SpeakBubble()
    clicks = []
    b.speakClicked.connect(lambda: clicks.append("speak"))
    b.stopClicked.connect(lambda: clicks.append("stop"))
    b.show_near_cursor()
    assert b.isVisible() and b.button.text() == "🔊"
    b.button.click()
    b.set_speaking(True)
    assert b.button.text() == "■"
    b.dismiss()
    assert b.isVisible()          # stays while reading so it can be stopped
    b.button.click()
    b.set_speaking(False)
    assert not b.isVisible() and clicks == ["speak", "stop"]
    b.show_near_cursor(); b.set_message("No text selected", seconds=2)
    assert b.label.isVisible()
    b.dismiss()
    assert not b.isVisible()
