"""Per-game workspaces and the documents inside them.

Layout (see PLAN.md): a shared ``app.db`` holds the workspace registry; each
game gets its own ``workspaces/<slug>.db`` holding that game's documents (and,
from M3, chunks + embeddings + conversations). Keeping each game in its own
file is what lets one game reference another's knowledge base later via SQLite
``ATTACH``.

M2 scope: workspaces + document CRUD + the ``in_kb`` flag. The vector tables
are created in M3, once an embedding model (and thus a dimension) is chosen.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import sqlite_vec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "workspace"


class Workspaces:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.app_db = data_dir / "app.db"
        self.ws_dir = data_dir / "workspaces"
        self.ws_dir.mkdir(parents=True, exist_ok=True)
        self._init_registry()

    # ---- registry (app.db) ------------------------------------------------
    #
    # NOTE: sqlite3's `with con:` only commits the transaction — it does NOT
    # close the connection. On Windows a leaked open handle keeps a file lock
    # (so deleting a workspace DB fails). These context managers commit AND
    # close.

    @contextmanager
    def _registry(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.app_db)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_registry(self) -> None:
        with self._registry() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS workspaces ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL, "
                "slug TEXT NOT NULL UNIQUE, "
                "created_at TEXT NOT NULL)"
            )

    def list(self) -> list[dict[str, Any]]:
        with self._registry() as con:
            rows = con.execute(
                "SELECT id, name, slug, created_at FROM workspaces ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, ws_id: int) -> dict[str, Any] | None:
        with self._registry() as con:
            row = con.execute(
                "SELECT id, name, slug, created_at FROM workspaces WHERE id = ?",
                (ws_id,),
            ).fetchone()
        return dict(row) if row else None

    def create(self, name: str) -> dict[str, Any]:
        base = _slugify(name)
        existing = {w["slug"] for w in self.list()}
        slug = base
        i = 2
        while slug in existing:
            slug = f"{base}-{i}"
            i += 1
        with self._registry() as con:
            cur = con.execute(
                "INSERT INTO workspaces (name, slug, created_at) VALUES (?, ?, ?)",
                (name.strip() or "Untitled game", slug, _now()),
            )
            ws_id = cur.lastrowid
        # The per-game DB file + schema are created lazily on first connect.
        return self.get(ws_id)  # type: ignore[return-value]

    def rename(self, ws_id: int, name: str) -> dict[str, Any] | None:
        # Only the display name changes; the slug (and thus the .db filename)
        # stays put so we never have to move the file.
        with self._registry() as con:
            con.execute(
                "UPDATE workspaces SET name = ? WHERE id = ?",
                (name.strip() or "Untitled game", ws_id),
            )
        return self.get(ws_id)

    def delete(self, ws_id: int) -> None:
        ws = self.get(ws_id)
        if ws is None:
            return
        with self._registry() as con:
            con.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
        # Drop the per-game DB file (connections are closed per-op above).
        path = self._db_path(ws["slug"])
        if path.exists():
            path.unlink()

    # ---- per-workspace DB -------------------------------------------------

    def _db_path(self, slug: str) -> Path:
        return self.ws_dir / f"{slug}.db"

    # Per-game schema. Applied on every connect (CREATE IF NOT EXISTS) so games
    # created before a table existed pick it up. chunks / chunk_embeddings
    # (vec0) land in M3.
    _SCHEMA = (
        "CREATE TABLE IF NOT EXISTS documents ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT NOT NULL, "
        "body_markdown TEXT NOT NULL DEFAULT '', "
        "source TEXT NOT NULL DEFAULT 'manual', "  # manual | ai
        "in_kb INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS conversations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id INTEGER NOT NULL "
        "REFERENCES conversations(id) ON DELETE CASCADE, "
        "role TEXT NOT NULL, "
        "content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)",
        # KB chunks. The vec0 embedding table is created lazily (its dimension
        # depends on the chosen embedding model) — see ensure_vec_table.
        "CREATE TABLE IF NOT EXISTS chunks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, "
        "ordinal INTEGER NOT NULL, "
        "text TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS kb_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    )

    @contextmanager
    def _connect(self, ws_id: int) -> Iterator[sqlite3.Connection]:
        ws = self.get(ws_id)
        if ws is None:
            raise KeyError(f"no workspace {ws_id}")
        con = sqlite3.connect(self._db_path(ws["slug"]))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        for stmt in self._SCHEMA:
            con.execute(stmt)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _vec_exists(con: sqlite3.Connection) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'chunk_embeddings'"
        ).fetchone()
        return row is not None

    # ---- documents --------------------------------------------------------

    def list_documents(self, ws_id: int) -> list[dict[str, Any]]:
        with self._connect(ws_id) as con:
            rows = con.execute(
                "SELECT id, title, source, in_kb, created_at, updated_at "
                "FROM documents ORDER BY updated_at DESC"
            ).fetchall()
        return [self._doc(r) for r in rows]

    def get_document(self, ws_id: int, doc_id: int) -> dict[str, Any] | None:
        with self._connect(ws_id) as con:
            row = con.execute(
                "SELECT id, title, body_markdown, source, in_kb, created_at, updated_at "
                "FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
        return self._doc(row) if row else None

    def create_document(
        self,
        ws_id: int,
        title: str,
        body: str = "",
        source: str = "manual",
        in_kb: bool = True,
    ) -> dict[str, Any]:
        ts = _now()
        with self._connect(ws_id) as con:
            cur = con.execute(
                "INSERT INTO documents "
                "(title, body_markdown, source, in_kb, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title.strip() or "Untitled", body, source, int(in_kb), ts, ts),
            )
            doc_id = cur.lastrowid
        return self.get_document(ws_id, doc_id)  # type: ignore[return-value]

    def update_document(
        self, ws_id: int, doc_id: int, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"title", "body_markdown", "in_kb"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return self.get_document(ws_id, doc_id)
        sets["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._connect(ws_id) as con:
            con.execute(
                f"UPDATE documents SET {cols} WHERE id = ?",
                (*sets.values(), doc_id),
            )
        return self.get_document(ws_id, doc_id)

    def delete_document(self, ws_id: int, doc_id: int) -> None:
        with self._connect(ws_id) as con:
            con.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    # ---- conversations ----------------------------------------------------

    def list_conversations(self, ws_id: int) -> list[dict[str, Any]]:
        with self._connect(ws_id) as con:
            rows = con.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, "
                "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) "
                "AS message_count "
                "FROM conversations c ORDER BY c.updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_conversation(self, ws_id: int, title: str = "") -> dict[str, Any]:
        ts = _now()
        with self._connect(ws_id) as con:
            cur = con.execute(
                "INSERT INTO conversations (title, created_at, updated_at) "
                "VALUES (?, ?, ?)",
                (title.strip(), ts, ts),
            )
            conv_id = cur.lastrowid
        return self.get_conversation(ws_id, conv_id)  # type: ignore[return-value]

    def get_conversation(self, ws_id: int, conv_id: int) -> dict[str, Any] | None:
        with self._connect(ws_id) as con:
            row = con.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
            if row is None:
                return None
            msgs = con.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id",
                (conv_id,),
            ).fetchall()
        conv = dict(row)
        conv["messages"] = [dict(m) for m in msgs]
        return conv

    def add_message(
        self, ws_id: int, conv_id: int, role: str, content: str
    ) -> dict[str, Any]:
        ts = _now()
        with self._connect(ws_id) as con:
            con.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (conv_id, role, content, ts),
            )
            con.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, conv_id)
            )
            # Name an untitled conversation after its first user turn.
            if role == "user":
                cur = con.execute(
                    "SELECT title FROM conversations WHERE id = ?", (conv_id,)
                ).fetchone()
                if cur and not (cur["title"] or "").strip():
                    title = " ".join(content.split())[:60]
                    con.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (title or "Untitled", conv_id),
                    )
        return {"role": role, "content": content, "created_at": ts}

    def delete_conversation(self, ws_id: int, conv_id: int) -> None:
        with self._connect(ws_id) as con:
            con.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    # ---- knowledge base (chunks + vec0 embeddings) ------------------------

    def ensure_vec_table(self, ws_id: int, dim: int) -> bool:
        """Ensure the vec0 table matches `dim`. Returns True if it had to (re)build
        — in which case existing chunks were cleared and callers must re-embed."""
        with self._connect(ws_id) as con:
            stored = con.execute(
                "SELECT value FROM kb_meta WHERE key = 'embed_dim'"
            ).fetchone()
            stored_dim = int(stored["value"]) if stored else None
            if self._vec_exists(con) and stored_dim == dim:
                return False
            if self._vec_exists(con):
                con.execute("DROP TABLE chunk_embeddings")
                con.execute("DELETE FROM chunks")
            con.execute(
                f"CREATE VIRTUAL TABLE chunk_embeddings USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
            )
            con.execute(
                "INSERT INTO kb_meta (key, value) VALUES ('embed_dim', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(dim),),
            )
            return True

    def index_document(
        self, ws_id: int, doc_id: int, chunks: list[str], embeddings: list[list[float]]
    ) -> None:
        with self._connect(ws_id) as con:
            self._clear_doc_chunks(con, doc_id)
            for ordinal, (text, emb) in enumerate(zip(chunks, embeddings)):
                cur = con.execute(
                    "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, ?, ?)",
                    (doc_id, ordinal, text),
                )
                con.execute(
                    "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)",
                    (cur.lastrowid, sqlite_vec.serialize_float32(emb)),
                )

    def unindex_document(self, ws_id: int, doc_id: int) -> None:
        with self._connect(ws_id) as con:
            self._clear_doc_chunks(con, doc_id)

    @staticmethod
    def _clear_doc_chunks(con: sqlite3.Connection, doc_id: int) -> None:
        ids = [
            r["id"]
            for r in con.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (doc_id,)
            ).fetchall()
        ]
        if ids and Workspaces._vec_exists(con):
            con.executemany(
                "DELETE FROM chunk_embeddings WHERE chunk_id = ?", [(i,) for i in ids]
            )
        con.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))

    def search(
        self, ws_id: int, query_embedding: list[float], k: int = 5
    ) -> list[dict[str, Any]]:
        with self._connect(ws_id) as con:
            if not self._vec_exists(con):
                return []
            rows = con.execute(
                "WITH knn AS ("
                "  SELECT chunk_id, distance FROM chunk_embeddings "
                "  WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
                ") "
                "SELECT c.document_id, d.title, c.text, knn.distance "
                "FROM knn JOIN chunks c ON c.id = knn.chunk_id "
                "JOIN documents d ON d.id = c.document_id "
                "ORDER BY knn.distance",
                (sqlite_vec.serialize_float32(query_embedding), k),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _doc(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["in_kb"] = bool(d.get("in_kb", 0))
        return d
