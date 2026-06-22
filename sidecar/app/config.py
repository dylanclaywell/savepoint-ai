"""Global, sticky application settings backed by ``app.db`` (SQLite).

These persist across all workspaces and chats — the selected chat model, the
embedding model, generation params, and the system prompt. Per-game data
(documents, KB, conversations) lives in separate per-workspace DBs (M2+).

The data directory is supplied by the Tauri host via ``--data-dir`` so dev and
release both write to the right place; we fall back to ``~/.savepoint-ai``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Settings keys + defaults. No default *model* — that is chosen at runtime from
# whatever the user has installed (sticky once set). The system prompt is fully
# user-owned; empty until the user (or a future M5 starter) fills it.
DEFAULTS: dict[str, Any] = {
    "chat_model": None,
    "embed_model": None,
    "system_prompt": "",
    "gen_params": {},  # e.g. {"temperature": 0.7}
    "active_workspace": None,  # id of the active per-game workspace
}


class Settings:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "app.db"
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3's `with con:` commits but never closes; close explicitly so
        # the app.db handle isn't held open (matters on Windows).
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS app_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def get_all(self) -> dict[str, Any]:
        """Return all settings, falling back to defaults for unset keys."""
        out = dict(DEFAULTS)
        with self._connect() as con:
            for key, value in con.execute("SELECT key, value FROM app_settings"):
                out[key] = json.loads(value)
        return out

    def get(self, key: str) -> Any:
        return self.get_all().get(key)

    def set_many(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Upsert the given keys (ignores unknown keys), return full settings."""
        with self._connect() as con:
            for key, value in updates.items():
                if key not in DEFAULTS:
                    continue
                con.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
        return self.get_all()
