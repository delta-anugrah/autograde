from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS outbox_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL UNIQUE,
    machine_id  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL NOT NULL DEFAULT 0,
    last_error  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_outbox_status_retry
    ON outbox_events (status, next_retry_at);
"""

_MAX_RETRIES = 50
_BACKOFF_BASE = 5    # retry cepat untuk startup race condition; exponential ke max 600s
_BACKOFF_MAX  = 600


class OutboxStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, self._db:
            # Durability eksplisit (jangan andalkan default implementasi):
            # - WAL: lebih tahan korupsi saat power-loss + baca/tulis tidak saling blok.
            # - synchronous=FULL: fsync tiap commit → transaksi yang sudah commit
            #   selamat dari mati listrik. Outbox write rate rendah, biaya fsync ringan.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)

    def add_event(self, event_id: str, machine_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO outbox_events (event_id, machine_id, payload) VALUES (?, ?, ?)",
                (event_id, machine_id, json.dumps(payload)),
            )

    def get_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                """SELECT id, event_id, payload, retry_count
                   FROM outbox_events
                   WHERE status = 'pending' AND next_retry_at <= ?
                   ORDER BY retry_count ASC, id ASC LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_delivered(self, row_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM outbox_events WHERE id = ?", (row_id,))

    def mark_failed_attempt(self, row_id: int, error: str) -> None:
        with self._lock, self._db:
            row = self._db.execute("SELECT retry_count FROM outbox_events WHERE id = ?", (row_id,)).fetchone()
            if not row:
                return
            retry = row["retry_count"] + 1
            backoff = min(_BACKOFF_BASE * (2 ** (retry - 1)), _BACKOFF_MAX)
            next_retry = time.time() + backoff
            new_status = "failed" if retry >= _MAX_RETRIES else "pending"
            self._db.execute(
                "UPDATE outbox_events SET retry_count=?, next_retry_at=?, last_error=?, status=? WHERE id=?",
                (retry, next_retry, error[:500], new_status, row_id),
            )

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) as n FROM outbox_events WHERE status='pending'").fetchone()
        return row["n"] if row else 0
