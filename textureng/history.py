"""SQLite log of dictations (raw and polished)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .config import app_dir


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "history.db"
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS dictation ("
                "id INTEGER PRIMARY KEY, ts REAL, app TEXT, profile TEXT, language TEXT, raw TEXT, text TEXT)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(dictation)")}
            if "translated_to" not in columns:  # databases from before translation existed
                db.execute("ALTER TABLE dictation ADD COLUMN translated_to TEXT DEFAULT ''")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def add(self, app: str, profile: str, language: str, raw: str, text: str, translated_to: str = "") -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO dictation (ts, app, profile, language, raw, text, translated_to) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), app, profile, language, raw, text, translated_to),
            )

    def recent(self, limit: int = 200) -> list[tuple]:
        """Rows of (ts, app, profile, language, raw, text, translated_to), newest first."""
        with self._connect() as db:
            return db.execute(
                "SELECT ts, app, profile, language, raw, text, COALESCE(translated_to, '') "
                "FROM dictation ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def clear(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM dictation")
