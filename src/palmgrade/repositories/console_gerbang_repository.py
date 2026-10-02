"""Gate times (scan 1 arrive, scan 4 leave), part of `ConsoleStore`.

Split out of `console_repository.py` (2026-09-30) because that file sits at the 1,000 line
cap (`tests/unit/test_ukuran_berkas.py`). A mixin, not a store of its own: one `console.db`,
one connection, one lock, same as `AkunStore`. The gate times stay on this PC: nothing here
is read by the AutoERP visit message.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any


class GerbangStore:
    """Provided by `ConsoleStore`: the connection and the lock."""

    _db: sqlite3.Connection
    _lock: threading.Lock

    def record_arrival(self, row: dict[str, Any]) -> None:
        """Scan 1. The id is derived from plate + time, so a retried request is a no-op."""
        with self._lock, self._db:
            self._db.execute(
                """INSERT OR IGNORE INTO arrivals
                       (id, plate_number, plate_norm, truck_id, work_date, arrived_at)
                   VALUES (:id, :plate_number, :plate_norm, :truck_id, :work_date, :arrived_at)""",
                row,
            )

    def arrival(self, arrival_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM arrivals WHERE id = ?", (arrival_id,)).fetchone()
        return dict(row) if row else None

    def waiting_arrivals_for_truck(self, truck_id: str) -> list[dict[str, Any]]:
        """This truck's unclaimed arrivals, every day: the caller's time window decides."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM arrivals WHERE truck_id = ? AND weighing_id IS NULL", (truck_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def claim_arrival(self, arrival_id: str, weighing_id: str) -> bool:
        """Pair one waiting arrival with one ticket. False when either side is taken: a
        second claim is a normal race (double read at the gate), not an error."""
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE arrivals SET weighing_id = ?
                    WHERE id = ? AND weighing_id IS NULL
                      AND NOT EXISTS (SELECT 1 FROM arrivals WHERE weighing_id = ?)""",
                (weighing_id, arrival_id, weighing_id),
            )
        return cur.rowcount == 1

    def waiting_arrivals(self, work_date: str) -> list[dict[str, Any]]:
        """The queue at the scale: arrived that day, not weighed in yet, oldest first."""
        with self._lock:
            rows = self._db.execute(
                """SELECT plate_number, arrived_at FROM arrivals
                   WHERE work_date = ? AND weighing_id IS NULL ORDER BY arrived_at""",
                (work_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def weighings_for_truck(self, truck_id: str) -> list[dict[str, Any]]:
        """One truck's newest tickets, for scan 4 to choose from (window in the domain)."""
        with self._lock:
            rows = self._db.execute(
                """SELECT id, plate_number, entered_at, exited_at, tare_kg, left_at
                   FROM weighings WHERE truck_id = ?
                   ORDER BY received_at DESC, rowid DESC LIMIT 20""",
                (truck_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_left_at(self, weighing_id: str, left_at: str) -> bool:
        """Scan 4. Only a weighed-out ticket, and only once: the first read wins."""
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE weighings SET left_at = ?
                    WHERE id = ? AND left_at IS NULL AND tare_kg IS NOT NULL""",
                (left_at, weighing_id),
            )
        return cur.rowcount == 1
