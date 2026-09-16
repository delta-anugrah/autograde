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

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS log_kejadian (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    waktu       REAL NOT NULL,
    level       TEXT NOT NULL,
    sumber      TEXT NOT NULL,
    pesan       TEXT NOT NULL,
    detail      TEXT,
    sidik       TEXT NOT NULL,
    jumlah      INTEGER NOT NULL DEFAULT 1,
    terakhir_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_waktu ON log_kejadian (waktu DESC);
CREATE INDEX IF NOT EXISTS idx_log_sidik ON log_kejadian (sidik, terakhir_at DESC);
"""

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
            self._db.executescript(_CREATE_SQL)

    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None:
        """Record one event, or bump the counter if it is a duplicate within the merge window."""
        fingerprint = _fingerprint(level, source, message)
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT id FROM log_kejadian"
                " WHERE sidik = ? AND terakhir_at >= ?"
                " ORDER BY terakhir_at DESC LIMIT 1",
                (fingerprint, now - MERGE_WINDOW_S),
            ).fetchone()
            if row is not None:
                self._db.execute(
                    "UPDATE log_kejadian SET jumlah = jumlah + 1, terakhir_at = ?"
                    " WHERE id = ?",
                    (now, row["id"]),
                )
                return
            self._db.execute(
                "INSERT INTO log_kejadian"
                " (waktu, level, sumber, pesan, detail, sidik, jumlah, terakhir_at)"
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
            conditions.append("(pesan LIKE ? OR sumber LIKE ?)")
            args.extend([f"%{search}%", f"%{search}%"])
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._lock:
            total = self._db.execute(
                f"SELECT COUNT(*) AS n FROM log_kejadian{where}", args
            ).fetchone()["n"]
            rows = self._db.execute(
                f"SELECT * FROM log_kejadian{where}"
                " ORDER BY terakhir_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    def purge_expired(self, *, now: float) -> int:
        """Delete rows past the retention window. Return how many were removed.

        Time-based only, never row-count-based: a count cap would discard the
        old rows that matter precisely while errors are flooding.
        """
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM log_kejadian WHERE terakhir_at < ?", (now - self._retention_s,)
            )
            return cur.rowcount


def _fingerprint(level: str, source: str, message: str) -> str:
    return hashlib.sha256(f"{level}|{source}|{message}".encode()).hexdigest()[:32]
