"""Find out which app the user is dictating into and pick a writing profile for it."""
from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class AppInfo:
    process: str = ""  # lower-case executable name, e.g. "outlook.exe"
    title: str = ""


def get_foreground_app() -> AppInfo:
    if sys.platform != "win32":
        return AppInfo()
    try:
        import psutil

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return AppInfo()
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            process = psutil.Process(pid.value).name().lower()
        except Exception:
            process = ""
        return AppInfo(process=process, title=buffer.value)
    except Exception:
        log.exception("Could not read the foreground window")
        return AppInfo()


def resolve_profile(app: AppInfo, profiles: dict, browsers: list[str]) -> str:
    """Process name decides first. Window titles are only consulted for browsers,
    so a Word file called "Slack notes" is still treated as a document."""
    process = app.process.lower()
    for key, profile in profiles.items():
        if process and process in (p.lower() for p in profile.get("processes", [])):
            return key
    if process in (b.lower() for b in browsers):
        title = app.title.lower()
        for key, profile in profiles.items():
            if any(word.lower() in title for word in profile.get("titles", []) if word):
                return key
    return "default"
