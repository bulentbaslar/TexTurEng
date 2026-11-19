"""Global hotkeys: hold-to-talk, a hands-free toggle, and cancel.

HotkeyState is the pure state machine (unit tested); HotkeyManager feeds it
from a pynput keyboard listener and re-emits its events as Qt signals."""
from __future__ import annotations

import ctypes
import logging
import sys
import time

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

_ALIASES = {
    "control": "ctrl", "cmd": "win", "windows": "win", "super": "win", "meta": "win",
    "escape": "esc", "option": "alt", "spacebar": "space", "return": "enter",
}
_MODIFIER_VKS = {
    "ctrl": (0xA2, 0xA3), "win": (0x5B, 0x5C), "alt": (0xA4, 0xA5), "shift": (0xA0, 0xA1),
}


def parse_combo(text: str) -> frozenset[str]:
    keys = set()
    for part in (text or "").lower().replace(" ", "").split("+"):
        if part:
            keys.add(_ALIASES.get(part, part))
    return frozenset(keys)


class HotkeyState:
    """press()/release() return one of:
    "start"            begin a normal dictation
    "start_translate"  begin a dictation that will be translated
    "translate"        switch the current recording to translation
    "stop", "cancel" or None.

    The translate combo normally contains the push-to-talk keys (ctrl+win+alt vs
    ctrl+win), so pressing the extra key during a hold switches to translation."""

    def __init__(
        self,
        ptt: frozenset[str],
        toggle: frozenset[str],
        cancel: frozenset[str],
        translate: frozenset[str] = frozenset(),
    ):
        self.ptt, self.toggle, self.cancel, self.translate = ptt, toggle, cancel, translate
        self.pressed: set[str] = set()
        self.recording = False
        self.latched = False      # hands-free: keeps recording after keys are released
        self.blocked = False      # after a cancel, until the hold keys are let go
        self.translating = False
        self.hold: frozenset[str] = frozenset()  # keys that must stay down while talking

    def _begin(self, hold: frozenset[str], latched: bool, translating: bool) -> None:
        self.recording, self.latched, self.translating, self.hold = True, latched, translating, hold

    def press(self, key: str) -> str | None:
        if key in self.pressed:
            return None  # keyboard auto-repeat
        self.pressed.add(key)
        if self.recording:
            if self.cancel and self.cancel <= self.pressed:
                return self._cancel()
            if self.toggle and self.pressed == self.toggle:
                if self.latched:
                    self.recording = self.latched = False
                    return "stop"
                self.latched = True
                return None
            if self.translate and self.pressed == self.translate:
                if self.translating:
                    return None
                self.translating = True
                return "translate"
            # Another key during a hold means a different shortcut (e.g. Ctrl+Win+Left).
            if not self.latched and key not in (self.hold | self.toggle | self.translate):
                return self._cancel()
            return None
        if self.blocked:
            return None
        if self.toggle and self.pressed == self.toggle:
            self._begin(self.toggle, latched=True, translating=False)
            return "start"
        if self.translate and self.pressed == self.translate:
            # Letting go of only the extra key (Alt) keeps the recording going.
            hold = self.ptt if self.ptt and self.ptt <= self.translate else self.translate
            self._begin(hold, latched=False, translating=True)
            return "start_translate"
        if self.ptt and self.pressed == self.ptt:
            self._begin(self.ptt, latched=False, translating=False)
            return "start"
        return None

    def release(self, key: str) -> str | None:
        self.pressed.discard(key)
        if self.blocked and not (self.pressed & (self.ptt | self.translate)):
            self.blocked = False
        if self.recording and not self.latched and not (self.hold <= self.pressed):
            self.recording = False
            return "stop"
        return None

    def _cancel(self) -> str:
        self.recording = self.latched = False
        self.blocked = bool(self.pressed & (self.ptt | self.translate))
        return "cancel"

    def reset(self) -> None:
        self.pressed.clear()
        self.recording = self.latched = self.blocked = self.translating = False


class DoubleCopyDetector:
    """Detects Ctrl+C pressed twice quickly (the trigger for translating selected text)."""

    def __init__(self, window: float = 0.5):
        self.window = window
        self._last: float | None = None

    def copy_pressed(self, now: float) -> bool:
        if self._last is not None and now - self._last <= self.window:
            self._last = None
            return True
        self._last = now
        return False

    def reset(self) -> None:
        self._last = None


def key_name(key) -> str:
    """Canonical name for a pynput key: ctrl, win, alt, shift, space, esc, a, 1, f5..."""
    name = getattr(key, "name", None)
    if name:  # pynput.keyboard.Key
        base = name.split("_")[0]
        if base == "cmd":
            return "win"
        if base in ("ctrl", "alt", "shift"):
            return base
        return name
    vk = getattr(key, "vk", None)
    if vk and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
        return chr(vk).lower()
    char = getattr(key, "char", None)
    return char.lower() if char else f"vk{vk}"


def modifiers_down() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vks in _MODIFIER_VKS.values() for vk in vks)


class HotkeyManager(QObject):
    started = Signal(bool)   # True when the dictation should be translated
    translateOn = Signal()   # the current recording switched to translation
    doubleCopy = Signal()    # Ctrl+C pressed twice: translate the selected text
    stopped = Signal()
    cancelled = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.enabled = True
        self.double_copy_enabled = True
        self._double_copy = DoubleCopyDetector()
        self.ignore_copy_until = 0.0  # set while the app itself presses Ctrl+C
        self._listener = None
        self.state = HotkeyState(frozenset(), frozenset(), frozenset())
        self.reload(cfg)

    def reload(self, cfg) -> None:
        self.state = HotkeyState(
            parse_combo(cfg["hotkey_ptt"]),
            parse_combo(cfg["hotkey_toggle"]),
            parse_combo(cfg["hotkey_cancel"]),
            parse_combo(cfg["hotkey_translate"]),
        )
        self.double_copy_enabled = bool(cfg["selection_translate"])

    def start(self) -> None:
        from pynput import keyboard

        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def force_stop(self) -> None:
        """Called when recording ends for another reason (error, pause)."""
        self.state.reset()

    def _emit(self, event: str | None) -> None:
        if event in ("start", "start_translate"):
            self.started.emit(event == "start_translate")
        elif event == "translate":
            self.translateOn.emit()
        elif event == "stop":
            self.stopped.emit()
        elif event == "cancel":
            self.cancelled.emit()

    def _prune_stale(self, current: str) -> None:
        """Drop modifiers whose key-up we missed (lock screen, UAC prompt)."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        for name, vks in _MODIFIER_VKS.items():
            if name != current and name in self.state.pressed:
                if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
                    self._emit(self.state.release(name))

    def _on_press(self, key) -> None:
        try:
            name = key_name(key)
            self._prune_stale(name)
            fresh = name not in self.state.pressed  # not keyboard auto-repeat
            if not self.enabled and not self.state.recording:
                self.state.pressed.add(name)
                return
            self._emit(self.state.press(name))
            if fresh and name == "c" and self.double_copy_enabled and not self.state.recording:
                if self.state.pressed == {"ctrl", "c"}:  # plain Ctrl+C, no Shift/Alt/Win
                    if time.monotonic() < self.ignore_copy_until:
                        self._double_copy.reset()
                    elif self._double_copy.copy_pressed(time.monotonic()):
                        self.doubleCopy.emit()
                else:
                    self._double_copy.reset()
        except Exception:
            log.exception("Hotkey press handling failed")

    def _on_release(self, key) -> None:
        try:
            self._emit(self.state.release(key_name(key)))
        except Exception:
            log.exception("Hotkey release handling failed")
