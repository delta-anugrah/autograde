"""Messages waiting for AutoERP, on the mill's own disk (contract §5).

The queue lives at the edge because that is where the outage is: a factory PC
loses power and its uplink, and a truck typed during either must still reach
AutoERP afterwards. Durability follows `integrations/outbox/outbox_store.py`
(WAL + synchronous=FULL + one lock).

One row per (kind, key), always holding the newest state. AutoERP's handlers are
upserts that replace the sections they carry, so an older payload is never worth
sending once a newer one exists.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS erp_outbox (
    kind            TEXT NOT NULL,
    key             TEXT NOT NULL,
    payload         TEXT NOT NULL,
    -- pending = never tried · error = tried, waiting out its backoff · sent = done
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    -- Moves on at every enqueue: a send marks its row done only if nothing newer
    -- was queued while it was on the wire (see `mark_sent`).
    version         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS idx_erp_outbox_due ON erp_outbox (status, next_attempt_at);
"""

# Contract §5: drained every 30 s, backing off to an hour while AutoERP is down.
_BACKOFF_BASE_S = 30
_BACKOFF_MAX_S = 3600
_ERROR_CHARS = 500


@dataclass(frozen=True)
class OutboxMessage:
    kind: str
    key: str
    payload: dict[str, Any]
    attempts: int
    last_error: str | None
    # The row's generation when it was read; 0 on rows written by an older build.
    version: int = 0


class ErpOutboxStore:
    def __init__(self, db_path: Path, *, clock: Callable[[], float] = time.time) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)
            _add_version_column(self._db)

    def enqueue(self, kind: str, key: str, payload: dict[str, Any]) -> None:
        """Queue the newest state for one key. Due at once, even after a failure."""
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO erp_outbox (kind, key, payload, created_at, version)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(kind, key) DO UPDATE SET
                       payload=excluded.payload, status='pending', attempts=0,
                       last_error=NULL, next_attempt_at=0, version=erp_outbox.version + 1""",
                (kind, key, _dump(payload), self._clock()),
            )

    def due(self, limit: int = 50) -> list[OutboxMessage]:
        """Oldest first: a truck waiting since this morning goes before one typed now."""
        # IN, not `!= 'sent'`: the same rows (status is only ever pending/error/sent),
        # but this form can use idx_erp_outbox_due on a table that is never trimmed.
        with self._lock:
            rows = self._db.execute(
                """SELECT kind, key, payload, attempts, last_error, version FROM erp_outbox
                   WHERE status IN ('pending', 'error') AND next_attempt_at <= ?
                   ORDER BY created_at, rowid LIMIT ?""",
                (self._clock(), limit),
            ).fetchall()
        return [
            OutboxMessage(
                kind=row["kind"],
                key=row["key"],
                payload=json.loads(row["payload"]),
                attempts=row["attempts"],
                last_error=row["last_error"],
                version=row["version"],
            )
            for row in rows
        ]

    def mark_sent(self, message: OutboxMessage) -> None:
        """Done, but only if nothing was queued for this key since it was read.

        The console can queue newer state while the older one is on the wire;
        marking that row sent would drop the newer state for good. The generation
        decides, not the payload: a requeue can carry the very same text (the R2
        page's is always `{"assignment_id": X}`) and still mean "build it again".
        """
        with self._lock, self._db:
            self._db.execute(
                """UPDATE erp_outbox SET status='sent', last_error=NULL
                   WHERE kind=? AND key=? AND version=?""",
                (message.kind, message.key, message.version),
            )

    def mark_error(self, message: OutboxMessage, error: str) -> None:
        """Keep it, with the reason, and try again after the backoff.

        Skipped when newer state was queued meanwhile: that one was never tried,
        so it stays due at once with no failure on it.
        """
        attempts = message.attempts + 1
        backoff = min(_BACKOFF_BASE_S * 2 ** (attempts - 1), _BACKOFF_MAX_S)
        with self._lock, self._db:
            self._db.execute(
                """UPDATE erp_outbox
                   SET status='error', attempts=?, last_error=?, next_attempt_at=?
                   WHERE kind=? AND key=? AND version=?""",
                (
                    attempts, error[:_ERROR_CHARS], self._clock() + backoff,
                    message.kind, message.key, message.version,
                ),
            )

    def hapus_semua(self) -> int:
        """Danger Zone: kosongkan antrean, terkirim atau belum. Kembalikan jumlahnya.

        Pemanggil yang memutuskan boleh atau tidak (`domain/bahaya.py`): kiriman
        `pending` saat AutoERP disetel menolak penghapusan lebih dulu.
        """
        with self._lock, self._db:
            return self._db.execute("DELETE FROM erp_outbox").rowcount

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM erp_outbox WHERE status='pending'"
            ).fetchone()
        return row["n"]

    def failed_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM erp_outbox WHERE status='error'"
            ).fetchone()
        return row["n"]

    def failed_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        """Rows waiting out their backoff, newest failure first — what support reads."""
        with self._lock:
            rows = self._db.execute(
                """SELECT kind, key, last_error, attempts, next_attempt_at FROM erp_outbox
                   WHERE status='error' ORDER BY next_attempt_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "key": row["key"],
                "last_error": row["last_error"],
                "attempts": row["attempts"],
                "next_attempt_at": row["next_attempt_at"],
            }
            for row in rows
        ]

    def requeue_failed(self) -> int:
        """Move every `error` row back to `pending`, due at once. Returns how many moved.

        `attempts` is deliberately left alone: a row old enough to matter is
        already near the hour ceiling, so keeping the count only ever shortens
        its next backoff, never lengthens it. Resetting to 0 would also let
        this button re-hammer a still-down AutoERP at 30s/1m/2m again, and
        would erase the one signal support has for "stuck forever" (a 417 on
        a bad field) versus "just a blip" (a network timeout).
        """
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE erp_outbox SET status='pending', next_attempt_at=0
                   WHERE status='error'"""
            )
        return cur.rowcount


def _add_version_column(db: sqlite3.Connection) -> None:
    """In place on an outbox written by an older build: its rows start at 0 and keep
    working, and an older build opened on the file later simply ignores the column."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(erp_outbox)")}
    if "version" not in columns:
        db.execute("ALTER TABLE erp_outbox ADD COLUMN version INTEGER NOT NULL DEFAULT 0")


def _dump(payload: dict[str, Any]) -> str:
    """Sorted keys: the same state is always stored as the same text."""
    return json.dumps(payload, sort_keys=True)
