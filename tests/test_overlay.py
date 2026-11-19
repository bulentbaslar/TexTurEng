import pytest
from PySide6.QtWidgets import QApplication

from textureng.ui import overlay


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_box_colours():
    assert overlay.box_colors("listening", False) == overlay.DICTATE_COLORS     # red: Ctrl+Win
    assert overlay.box_colors("listening", True) == overlay.TRANSLATE_COLORS    # orange: Ctrl+Win+Alt
    assert overlay.box_colors("processing", True) == overlay.TRANSLATE_COLORS
    assert overlay.box_colors("error", True) == overlay.ERROR_COLORS


@pytest.mark.parametrize("level,lit", [(0.0, 0), (0.05, 0), (0.1, 1), (0.3, 2), (0.5, 3), (1.0, 3)])
def test_waves_follow_the_voice(level, lit):
    assert overlay.lit_waves(level) == lit


def test_box_is_centred_and_level_falls_back_gently(qapp):
    class Recorder:
        level = 0.8

    box = overlay.Overlay(Recorder())
    box.show_mode("listening", translate=True)
    screen = QApplication.screenAt(box.geometry().center()) or QApplication.primaryScreen()
    centre = screen.availableGeometry().center()
    assert abs(box.geometry().center().x() - centre.x()) <= 1
    assert abs(box.geometry().center().y() - centre.y()) <= 1
    box._tick()
    assert box.level == pytest.approx(0.8)
    Recorder.level = 0.0
    box._tick()
    assert 0.6 < box.level < 0.8          # does not drop to silence at once
    box.set_translate(False)
    assert not box.translate
    box.dismiss()
    assert not box.isVisible()
