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

    def enqueue(self, kind: str, key: str, payload: dict[str, Any]) -> None:
        """Queue the newest state for one key. Due at once, even after a failure."""
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO erp_outbox (kind, key, payload, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(kind, key) DO UPDATE SET
                       payload=excluded.payload, status='pending', attempts=0,
                       last_error=NULL, next_attempt_at=0""",
                (kind, key, _dump(payload), self._clock()),
            )

    def due(self, limit: int = 50) -> list[OutboxMessage]:
        """Oldest first: a truck waiting since this morning goes before one typed now."""
        with self._lock:
            rows = self._db.execute(
                """SELECT kind, key, payload, attempts, last_error FROM erp_outbox
                   WHERE status != 'sent' AND next_attempt_at <= ?
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
            )
            for row in rows
        ]

    def mark_sent(self, message: OutboxMessage) -> None:
        """Done — but only if this is still the payload that was sent.

        The console can queue newer state while the older one is on the wire;
        marking that row sent would drop the newer state for good.
        """
        with self._lock, self._db:
            self._db.execute(
                """UPDATE erp_outbox SET status='sent', last_error=NULL
                   WHERE kind=? AND key=? AND payload=?""",
                (message.kind, message.key, _dump(message.payload)),
            )

    def mark_error(self, message: OutboxMessage, error: str) -> None:
        """Keep it, with the reason, and try again after the backoff."""
        attempts = message.attempts + 1
        backoff = min(_BACKOFF_BASE_S * 2 ** (attempts - 1), _BACKOFF_MAX_S)
        with self._lock, self._db:
            self._db.execute(
                """UPDATE erp_outbox
                   SET status='error', attempts=?, last_error=?, next_attempt_at=?
                   WHERE kind=? AND key=?""",
                (attempts, error[:_ERROR_CHARS], self._clock() + backoff, message.kind, message.key),
            )


def _dump(payload: dict[str, Any]) -> str:
    """Sorted keys: the stored text is compared when marking a message sent."""
    return json.dumps(payload, sort_keys=True)
