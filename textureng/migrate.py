"""One-time move of settings from the app's earlier folder name.

Copies settings and history from %APPDATA%\\VoxPolish, copies the saved cloud API key
in Windows Credential Manager, and replaces the old "Start with Windows" entry.
The old folder and key are left in place, so nothing is lost if something goes wrong."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)
OLD_NAME = "VoxPolish"
COPIED_FILES = ("config.json", "history.db")


def migrate_files(old_dir: Path, new_dir: Path) -> list[str]:
    """Copy settings and history unless the new folder already has settings."""
    if (new_dir / "config.json").exists() or not (old_dir / "config.json").exists():
        return []
    new_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in COPIED_FILES:
        if (old_dir / name).exists():
            shutil.copy2(old_dir / name, new_dir / name)
            copied.append(name)
    return copied


def migrate_api_key(new_service: str, user: str) -> bool:
    import keyring

    if keyring.get_password(new_service, user):
        return False
    old = keyring.get_password(OLD_NAME, user)
    if not old:
        return False
    keyring.set_password(new_service, user, old)
    return True


def migrate_startup_entry() -> bool:
    """If VoxPolish started with Windows, make Textureng do so instead."""
    import winreg

    from .ui.settings import RUN_KEY, set_startup

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            winreg.QueryValueEx(key, OLD_NAME)
            winreg.DeleteValue(key, OLD_NAME)
    except OSError:
        return False
    set_startup(True)
    return True


def migrate_from_voxpolish() -> None:
    """Run at start-up. Skipped when TEXTURENG_HOME points elsewhere (tests)."""
    if os.environ.get("TEXTURENG_HOME") or os.name != "nt":
        return
    from .config import app_dir
    from .stt.cloud import KEYRING_SERVICE, KEYRING_USER

    appdata = Path(os.environ.get("APPDATA", str(Path.home())))
    steps = {
        "files": lambda: migrate_files(appdata / OLD_NAME, app_dir()),
        "api key": lambda: migrate_api_key(KEYRING_SERVICE, KEYRING_USER),
        "startup": migrate_startup_entry,
    }
    for name, step in steps.items():
        try:
            result = step()
            if result:
                log.info("Carried over from %s: %s %s", OLD_NAME, name, result if result is not True else "")
        except Exception:
            log.exception("Carrying over %s from %s failed", name, OLD_NAME)
