"""Manifest SQLite untuk batch upload R2 + API cloud (spec 2026-07-10 §3.1).

State machine per item:
    pending ──PUT R2 ok──▶ image_uploaded ──POST API ok──▶ done ──retensi──▶ dihapus
       │ (item tanpa gambar: langsung POST → done)
       └─ input cacat ──▶ poisoned (di-skip, file TIDAK pernah dihapus)

Beda kontrak dgn outbox lama: TANPA retry cap & TANPA TTL — item nunggu di
disk selamanya sampai terkirim (syarat "tahan outage berapa pun").
Durability: WAL + synchronous=FULL, sama persis dgn outbox_store.py.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS upload_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key      TEXT NOT NULL UNIQUE,
    event_id      TEXT,
    image_path    TEXT,
    r2_key        TEXT,
    status        TEXT DEFAULT 'pending',
    retry_count   INTEGER DEFAULT 0,
    next_retry_at REAL DEFAULT 0,
    last_error    TEXT,
    discovered_at REAL,
    uploaded_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_upload_status ON upload_items (status, next_retry_at);
"""

_BACKOFF_BASE = 5
_BACKOFF_MAX = 600


class UploadManifest:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)

    def has_item(self, item_key: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM upload_items WHERE item_key = ?", (item_key,)
            ).fetchone()
        return row is not None

    def upsert_item(
        self, item_key: str, event_id: str, image_path: str | None, r2_key: str | None
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO upload_items "
                "(item_key, event_id, image_path, r2_key, discovered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (item_key, event_id, image_path, r2_key, time.time()),
            )

    def get_uploadable(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT id, item_key, event_id, image_path, r2_key, status, retry_count
                   FROM upload_items
                   WHERE status IN ('pending', 'image_uploaded') AND next_retry_at <= ?
                   ORDER BY discovered_at ASC LIMIT ?""",
                (time.time(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_image_uploaded(self, item_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE upload_items SET status='image_uploaded', last_error=NULL WHERE id=?",
                (item_id,),
            )

    def mark_done(self, item_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE upload_items SET status='done', uploaded_at=?, last_error=NULL WHERE id=?",
                (time.time(), item_id),
            )

    def mark_poisoned(self, item_id: int, error: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE upload_items SET status='poisoned', last_error=? WHERE id=?",
                (error[:500], item_id),
            )

    def requeue(self, item_id: int, error: str) -> None:
        # TANPA batas retry — status tidak berubah, hanya backoff yang maju.
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT retry_count FROM upload_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                return
            retry = row["retry_count"] + 1
            backoff = min(_BACKOFF_BASE * (2 ** (retry - 1)), _BACKOFF_MAX)
            self._db.execute(
                "UPDATE upload_items SET retry_count=?, next_retry_at=?, last_error=? WHERE id=?",
                (retry, time.time() + backoff, error[:500], item_id),
            )

    def get_expired_done(self, cutoff: float) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, item_key, image_path FROM upload_items "
                "WHERE status='done' AND uploaded_at < ?",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_oldest_done(self, limit: int) -> list[dict[str, Any]]:
        """Item `done` tertua duluan — bahan bakar pembersihan darurat saat disk menipis.

        Hanya `done`, sama seperti `get_expired_done`: statusnya berarti gambar
        sudah mendarat di R2 DAN API cloud sudah menjawab 2xx. Menyapu status
        lain berarti menghapus satu-satunya salinan yang ada.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT id, item_key, image_path FROM upload_items "
                "WHERE status='done' ORDER BY uploaded_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_item(self, item_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM upload_items WHERE id=?", (item_id,))

    def counts(self) -> dict[str, int]:
        base = {"pending": 0, "image_uploaded": 0, "done": 0, "poisoned": 0}
        with self._lock:
            rows = self._db.execute(
                "SELECT status, COUNT(*) AS n FROM upload_items GROUP BY status"
            ).fetchall()
        base.update({r["status"]: r["n"] for r in rows})
        return base
