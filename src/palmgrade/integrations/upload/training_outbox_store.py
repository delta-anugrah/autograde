"""Training photos waiting for the nexio inbox, on the mill's own disk (nexio spec §6.2).

Its own file, not `erp_outbox.db`: R2 being down must not hold AutoERP messages, and
a backlog of thousands of photos must not slow the ERP queue. Durability follows
`integrations/erp/outbox_store.py` (WAL + synchronous=FULL + one lock).

One row per bunch, keyed by `event_id`. Unlike the ERP outbox a row never changes
once queued: the photo and its manifest are facts, so a redelivered event is ignored
rather than requeued, and a sent photo is never sent again.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..erp.outbox_store import GAGAL_KONSOL

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS training_outbox (
    event_id        TEXT PRIMARY KEY,
    line_code       TEXT NOT NULL,
    photo_path      TEXT NOT NULL,
    manifest        TEXT NOT NULL,
    -- pending = never tried · error = waiting out its backoff · sent = done · gone = photo no longer there
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    error_kind      TEXT,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    done_at         REAL
);
CREATE INDEX IF NOT EXISTS idx_training_outbox_due ON training_outbox (status, next_attempt_at);
"""

STATUS_BELUM_TERKIRIM = ("pending", "error")
STATUS_SELESAI = ("sent", "gone")

_BACKOFF_BASE_S = 30
_BACKOFF_MAX_S = 3600
_ERROR_CHARS = 500
#: A row whose stored manifest no longer parses: our own side, retried at the backoff ceiling.
MANIFEST_UNREADABLE = "manifest unreadable"
#: Sent and gone rows are kept a week for support, then deleted: 10,000 rows a day.
KEEP_DONE_S = 7 * 86400


@dataclass(frozen=True)
class TrainingPackage:
    event_id: str
    line_code: str
    photo_path: str
    manifest: dict[str, Any]
    attempts: int


class TrainingOutboxStore:
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
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def enqueue(self, event_id: str, line_code: str, photo_path: str, manifest: dict[str, Any]) -> bool:
        """Queue one package. False when this bunch is already queued or done."""
        with self._lock, self._db:
            cur = self._db.execute(
                """INSERT OR IGNORE INTO training_outbox (event_id, line_code, photo_path, manifest, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, line_code, photo_path, json.dumps(manifest, ensure_ascii=False), self._clock()),
            )
            return cur.rowcount == 1

    def due(self, limit: int) -> list[TrainingPackage]:
        """Oldest first, so a backlog leaves in the order it was graded.

        A row whose manifest no longer parses is set aside (status error, an hour's wait)
        instead of raising: being oldest, it would otherwise head every batch and stall the queue.
        """
        tanda = ", ".join("?" * len(STATUS_BELUM_TERKIRIM))
        paket: list[TrainingPackage] = []
        with self._lock, self._db:
            rows = self._db.execute(
                f"""SELECT event_id, line_code, photo_path, manifest, attempts FROM training_outbox
                    WHERE status IN ({tanda}) AND next_attempt_at <= ?
                    ORDER BY created_at, rowid LIMIT ?""",
                (*STATUS_BELUM_TERKIRIM, self._clock(), limit),
            ).fetchall()
            for r in rows:
                manifest = _baca_manifest(r["manifest"])
                if manifest is None:
                    self._sisihkan_rusak(r["event_id"], r["line_code"])
                    continue
                paket.append(TrainingPackage(r["event_id"], r["line_code"], r["photo_path"], manifest, r["attempts"]))
        return paket

    def _sisihkan_rusak(self, event_id: str, line_code: str) -> None:
        """Called inside the lock and transaction of `due()`."""
        self._db.execute(
            """UPDATE training_outbox SET status='error', attempts=attempts + 1, last_error=?, error_kind=?,
                   next_attempt_at=? WHERE event_id=?""",
            (MANIFEST_UNREADABLE, GAGAL_KONSOL, self._clock() + _BACKOFF_MAX_S, event_id),
        )
        logger.error("Training outbox: %s (%s) set aside, %s", event_id, line_code, MANIFEST_UNREADABLE)

    def mark_sent(self, event_id: str) -> None:
        self._close(event_id, "sent", None)

    def mark_gone(self, event_id: str, reason: str) -> None:
        self._close(event_id, "gone", reason)

    def _close(self, event_id: str, status: str, reason: str | None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE training_outbox SET status=?, last_error=?, error_kind=NULL, done_at=? WHERE event_id=?",
                (status, reason[:_ERROR_CHARS] if reason else None, self._clock(), event_id),
            )

    def mark_error(self, event_id: str, error: str, *, jenis: str) -> None:
        """Back off one row only; the worker carries on with the next one.

        Only a row still waiting is touched: a sent or gone row is never brought back.
        """
        tanda = ", ".join("?" * len(STATUS_BELUM_TERKIRIM))
        with self._lock, self._db:
            row = self._db.execute(
                f"SELECT attempts FROM training_outbox WHERE event_id=? AND status IN ({tanda})",
                (event_id, *STATUS_BELUM_TERKIRIM),
            ).fetchone()
            if row is None:
                return
            attempts = row["attempts"] + 1
            delay = min(_BACKOFF_BASE_S * 2 ** (attempts - 1), _BACKOFF_MAX_S)
            self._db.execute(
                f"""UPDATE training_outbox SET status='error', attempts=?, last_error=?, error_kind=?,
                       next_attempt_at=? WHERE event_id=? AND status IN ({tanda})""",
                (attempts, error[:_ERROR_CHARS], jenis, self._clock() + delay, event_id, *STATUS_BELUM_TERKIRIM),
            )

    def pending_count(self) -> int:
        """Never tried yet. Rows waiting out a backoff are `failed_count`, like ErpOutboxStore."""
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM training_outbox WHERE status='pending'").fetchone()[0]

    def failed_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM training_outbox WHERE status='error'").fetchone()[0]

    def failed_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        """Same row shape and order as ErpOutboxStore.failed_rows (newest failure first)."""
        with self._lock:
            rows = self._db.execute(
                """SELECT line_code AS kind, event_id AS key, last_error, error_kind, attempts, next_attempt_at
                   FROM training_outbox WHERE status='error' ORDER BY next_attempt_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def last_sent_at(self) -> float | None:
        with self._lock:
            return self._db.execute("SELECT MAX(done_at) FROM training_outbox WHERE status='sent'").fetchone()[0]

    def prune(self, now: float | None = None) -> int:
        cutoff = (self._clock() if now is None else now) - KEEP_DONE_S
        tanda = ", ".join("?" * len(STATUS_SELESAI))
        with self._lock, self._db:
            return self._db.execute(
                f"DELETE FROM training_outbox WHERE status IN ({tanda}) AND done_at < ?", (*STATUS_SELESAI, cutoff)
            ).rowcount

    def hapus_semua(self) -> int:
        """Danger Zone: the photos themselves are being deleted, so are their packages."""
        with self._lock, self._db:
            return self._db.execute("DELETE FROM training_outbox").rowcount


def _baca_manifest(teks: str) -> dict[str, Any] | None:
    """The stored manifest, or None when it is not a JSON object (a damaged row)."""
    try:
        manifest = json.loads(teks)
    except (ValueError, TypeError):
        return None
    return manifest if isinstance(manifest, dict) else None
