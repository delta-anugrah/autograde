"""ERROR/WARNING history that survives a restart, for the support Log screen.

Its own SQLite file, not a table in `console.db`: the writer is a logging
handler callable from any thread, and sharing one lock with the queries that
serve the operator screen would let an error flood slow that screen down.
Same conventions as the other stores — WAL, `synchronous=FULL`, one lock.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..domain.log_line import JawabanLog, KursorLine
from . import log_serap_line
from .log_serap_line import HasilSerap, TambahGalat

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS event_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at     REAL NOT NULL,
    level         TEXT NOT NULL,
    source        TEXT NOT NULL,
    message       TEXT NOT NULL,
    detail        TEXT,
    fingerprint   TEXT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1,
    last_seen_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_log_logged_at ON event_log (logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_fingerprint ON event_log (fingerprint, last_seen_at DESC);
"""

# Renamed from `log_kejadian` (Indonesian) after the rest of the schema had
# already moved to English. `CREATE TABLE IF NOT EXISTS` leaves an existing
# table alone, so without this pass a developer machine with an old-named
# table would end up with two tables and lose its log history.
_OLD_TABLE = "log_kejadian"
_RENAMED_COLUMNS = (
    ("waktu", "logged_at"),
    ("sumber", "source"),
    ("pesan", "message"),
    ("sidik", "fingerprint"),
    ("jumlah", "count"),
    ("terakhir_at", "last_seen_at"),
)

# Identical messages inside this window are counted, not stacked. Long enough
# to absorb a per-second error flood, short enough that tomorrow's copy of the
# same event still reads as its own event.
MERGE_WINDOW_S = 60.0

_DAY_S = 86400.0


class LogStore:
    def __init__(self, db_path: Path, *, retention_days: int = 180) -> None:
        self._retention_s = retention_days * _DAY_S
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            # Before `_CREATE_SQL`: its indexes name the English columns, so on a
            # database written before the rename they would be created against
            # columns that do not exist yet.
            self._rename_indonesian_table()
            self._db.executescript(_CREATE_SQL)
            # Batch 3.2: kolom `line_code`/`asal` + kursor tarikan log line, di tempat.
            log_serap_line.pasang_skema_line(self._db)

    def _rename_indonesian_table(self) -> None:
        """Carry a database written before `log_kejadian` became `event_log`.

        Same shape as `ConsoleStore._rename_indonesian_columns`: rename the
        table, then rename each column that still has its old name, so
        existing rows and their history survive instead of being orphaned
        under the new table name.
        """
        table_exists = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_OLD_TABLE,)
        ).fetchone()
        if not table_exists:
            return
        self._db.execute(f"ALTER TABLE {_OLD_TABLE} RENAME TO event_log")
        columns = {r["name"] for r in self._db.execute("PRAGMA table_info(event_log)")}
        for old, new in _RENAMED_COLUMNS:
            if old in columns and new not in columns:
                self._db.execute(f"ALTER TABLE event_log RENAME COLUMN {old} TO {new}")

    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None:
        """Record one event, or bump the counter if it is a duplicate within the merge window."""
        fingerprint = _fingerprint(level, source, message)
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT id FROM event_log"
                " WHERE fingerprint = ? AND last_seen_at >= ?"
                " ORDER BY last_seen_at DESC LIMIT 1",
                (fingerprint, now - MERGE_WINDOW_S),
            ).fetchone()
            if row is not None:
                self._db.execute(
                    "UPDATE event_log SET count = count + 1, last_seen_at = ?"
                    " WHERE id = ?",
                    (now, row["id"]),
                )
                return
            self._db.execute(
                "INSERT INTO event_log"
                " (logged_at, level, source, message, detail, fingerprint, count, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (now, level, source, message, detail, fingerprint, now),
            )

    def read(
        self, *, level: str | None, search: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        """One page, newest first, plus `total` across the whole filtered set.

        `total` comes from its own SQL COUNT, never `len(items)` — the last
        page would otherwise report a wrong count and pagination breaks.
        """
        conditions, args = [], []
        if level:
            conditions.append("level = ?")
            args.append(level)
        if search:
            conditions.append("(message LIKE ? OR source LIKE ? OR line_code LIKE ?)")
            args.extend([f"%{search}%"] * 3)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._lock:
            total = self._db.execute(
                f"SELECT COUNT(*) AS n FROM event_log{where}", args
            ).fetchone()["n"]
            rows = self._db.execute(
                f"SELECT * FROM event_log{where}"
                " ORDER BY last_seen_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    def kursor_line(self, line_code: str) -> KursorLine:
        """Sampai mana log satu line sudah ditarik (batch 3.2)."""
        with self._lock:
            return log_serap_line.kursor_line(self._db, line_code)

    def galat_baru_line(self, line_code: str, jawaban: JawabanLog) -> tuple[TambahGalat, ...]:
        """ERROR halaman ini yang belum terlihat, TANPA menulis: diteruskan ke digest
        Discord SEBELUM `serap_line` (lihat log_serap_line)."""
        with self._lock:
            return log_serap_line.galat_baru(self._db, line_code, jawaban)

    def serap_line(self, line_code: str, jawaban: JawabanLog, *, now: float) -> HasilSerap:
        """Satu halaman log line + kursornya dalam SATU transaksi (lihat log_serap_line)."""
        with self._lock, self._db:
            return log_serap_line.serap_line(self._db, line_code, jawaban, now=now)

    def hapus_semua(self) -> int:
        """Danger Zone: kosongkan log. Jejak siapa yang menghapus ditulis SESUDAH
        ini oleh pemanggil, jadi ia jadi baris pertama di log yang baru."""
        with self._lock, self._db:
            return self._db.execute("DELETE FROM event_log").rowcount

    def purge_expired(self, *, now: float) -> int:
        """Delete rows past the retention window. Return how many were removed.

        Time-based only, never row-count-based: a count cap would discard the
        old rows that matter precisely while errors are flooding.
        """
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM event_log WHERE last_seen_at < ?", (now - self._retention_s,)
            )
            return cur.rowcount


def _fingerprint(level: str, source: str, message: str) -> str:
    return hashlib.sha256(f"{level}|{source}|{message}".encode()).hexdigest()[:32]
