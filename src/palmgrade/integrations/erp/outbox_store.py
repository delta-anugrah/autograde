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
import logging
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
    -- Why it is waiting, one of JENIS_GAGAL (NULL on rows from an older build).
    error_kind      TEXT,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    -- Moves on at every enqueue: a send marks its row done only if nothing newer
    -- was queued while it was on the wire (see `mark_sent`).
    version         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS idx_erp_outbox_due ON erp_outbox (status, next_attempt_at);
"""

logger = logging.getLogger(__name__)

#: Every status this table ever holds.
STATUS_SEMUA = ("pending", "error", "sent")
#: What `due()` reads. `IN (...)`, not `!= 'sent'`, so idx_erp_outbox_due is used on a
#: table that is never trimmed; a status added to STATUS_SEMUA must be added here too
#: or its rows are never sent (pinned by test_erp_outbox_store.py).
STATUS_BELUM_TERKIRIM = ("pending", "error")

# Contract §5: drained every 30 s, backing off to an hour while AutoERP is down.
#: Why a row is waiting, set by its worker at `mark_error` and worded by the Status tab
#: (user decision 2026-10-01: outside the Log tab no raw error text; `last_error` keeps
#: the text for the Log tab and curl). The worker knows the failure's type, the text
#: alone would have to be parsed.
GAGAL_TAK_TERJANGKAU = "tak_terjangkau"   # no usable answer: network, timeout, gateway
GAGAL_KUNCI_DITOLAK = "kunci_ditolak"     # the destination refused this PC's key (401/403)
GAGAL_DITOLAK = "ditolak"                 # the destination refused this message's content
GAGAL_TUJUAN = "galat_tujuan"             # the destination crashed on this message
GAGAL_KONSOL = "galat_konsol"             # our own side: bookkeeping, unknown kind, bad payload
JENIS_GAGAL = (GAGAL_TAK_TERJANGKAU, GAGAL_KUNCI_DITOLAK, GAGAL_DITOLAK, GAGAL_TUJUAN, GAGAL_KONSOL)

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
            _add_error_kind_column(self._db)

    def enqueue(self, kind: str, key: str, payload: dict[str, Any]) -> None:
        """Queue the newest state for one key. Due at once, even after a failure."""
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO erp_outbox (kind, key, payload, created_at, version)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(kind, key) DO UPDATE SET
                       payload=excluded.payload, status='pending', attempts=0,
                       last_error=NULL, error_kind=NULL, next_attempt_at=0,
                       version=erp_outbox.version + 1""",
                (kind, key, _dump(payload), self._clock()),
            )

    def due(self, limit: int = 50) -> list[OutboxMessage]:
        """Oldest first: a truck waiting since this morning goes before one typed now.

        A row whose payload no longer parses is set aside as `error` for the full
        hour, with the reason support reads in Antrean ERP, instead of raising:
        one unreadable row used to stop the whole queue every 30 s. A requeue of
        the same key replaces the payload and makes it due again.
        """
        tanda = ", ".join("?" * len(STATUS_BELUM_TERKIRIM))
        with self._lock, self._db:
            rows = self._db.execute(
                f"""SELECT kind, key, payload, attempts, last_error, version FROM erp_outbox
                   WHERE status IN ({tanda}) AND next_attempt_at <= ?
                   ORDER BY created_at, rowid LIMIT ?""",
                (*STATUS_BELUM_TERKIRIM, self._clock(), limit),
            ).fetchall()
            pesan = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except ValueError as exc:
                    self._sisihkan_rusak(row, f"payload tidak terbaca: {exc}")
                    continue
                pesan.append(
                    OutboxMessage(
                        kind=row["kind"],
                        key=row["key"],
                        payload=payload,
                        attempts=row["attempts"],
                        last_error=row["last_error"],
                        version=row["version"],
                    )
                )
        return pesan

    def _sisihkan_rusak(self, row: sqlite3.Row, alasan: str) -> None:
        """Dipanggil di dalam kunci dan transaksi `due()`."""
        self._db.execute(
            """UPDATE erp_outbox SET status='error', attempts=attempts + 1, last_error=?,
               error_kind=?, next_attempt_at=? WHERE kind=? AND key=? AND version=?""",
            (
                alasan[:_ERROR_CHARS], GAGAL_KONSOL, self._clock() + _BACKOFF_MAX_S,
                row["kind"], row["key"], row["version"],
            ),
        )
        logger.error("Antrean AutoERP: %s %s disisihkan, %s", row["kind"], row["key"], alasan)

    def mark_sent(self, message: OutboxMessage) -> None:
        """Done, but only if nothing was queued for this key since it was read.

        The console can queue newer state while the older one is on the wire;
        marking that row sent would drop the newer state for good. The generation
        decides, not the payload: a requeue can carry the very same text (the R2
        page's is always `{"assignment_id": X}`) and still mean "build it again".
        """
        with self._lock, self._db:
            self._db.execute(
                """UPDATE erp_outbox SET status='sent', last_error=NULL, error_kind=NULL
                   WHERE kind=? AND key=? AND version=?""",
                (message.kind, message.key, message.version),
            )

    def mark_error(self, message: OutboxMessage, error: str, *, jenis: str | None = None) -> None:
        """Keep it, with the reason (`error` for the Log tab, `jenis` from JENIS_GAGAL for
        the screen), and try again after the backoff.

        Skipped when newer state was queued meanwhile: that one was never tried,
        so it stays due at once with no failure on it.
        """
        attempts = message.attempts + 1
        backoff = min(_BACKOFF_BASE_S * 2 ** (attempts - 1), _BACKOFF_MAX_S)
        with self._lock, self._db:
            self._db.execute(
                """UPDATE erp_outbox
                   SET status='error', attempts=?, last_error=?, error_kind=?, next_attempt_at=?
                   WHERE kind=? AND key=? AND version=?""",
                (
                    attempts, error[:_ERROR_CHARS], jenis, self._clock() + backoff,
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
                """SELECT kind, key, last_error, error_kind, attempts, next_attempt_at FROM erp_outbox
                   WHERE status='error' ORDER BY next_attempt_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "key": row["key"],
                "last_error": row["last_error"],
                "error_kind": row["error_kind"],
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


def _add_error_kind_column(db: sqlite3.Connection) -> None:
    """Same pattern as `_add_version_column`: an older file gains the column with NULL
    (the screen then writes its generic sentence), an older build ignores it."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(erp_outbox)")}
    if "error_kind" not in columns:
        db.execute("ALTER TABLE erp_outbox ADD COLUMN error_kind TEXT")


def _dump(payload: dict[str, Any]) -> str:
    """Sorted keys: the same state is always stored as the same text."""
    return json.dumps(payload, sort_keys=True)
