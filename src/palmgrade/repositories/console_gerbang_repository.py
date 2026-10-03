"""Gate times (scan 1 arrive, scan 4 leave), part of `ConsoleStore`.

Split out of `console_repository.py` (2026-09-30) because that file sits at the 1,000 line
cap (`tests/unit/test_ukuran_berkas.py`). A mixin, not a store of its own: one `console.db`,
one connection, one lock, same as `AkunStore`. The gate times stay on this PC: nothing here
is read by the AutoERP visit message.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Collection
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

    def cancel_arrival(
        self, arrival_id: str, *, cancelled_at: str, cancelled_by: str,
        cancelled_by_name: str | None = None,
    ) -> dict[str, Any] | None:
        """"Batal datang": mark one arrival that is still WAITING; the row, or None.

        Kept, not deleted (round 4, 2026-10-03): the operator asked to see who cancelled which
        truck and when. `cancelled_at` set = no longer waiting; every reader of a waiting
        arrival below says `cancelled_at IS NULL`. `weighing_id IS NULL` in the same
        statement: a weigh-in that claimed it a moment earlier keeps it, and a second cancel
        keeps the first one's time and operator.

        `cancelled_by` is the operator's email (identity); `cancelled_by_name` is the display
        name AT THAT MOMENT, a snapshot: an account renamed or deleted later (a local account
        is deleted for real, an AutoERP one disappears with the next sync) still reads as
        the person who pressed the button. NULL = no name known, the screen shows the email.
        """
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE arrivals SET cancelled_at = ?, cancelled_by = ?, cancelled_by_name = ?
                    WHERE id = ? AND weighing_id IS NULL AND cancelled_at IS NULL""",
                (cancelled_at, cancelled_by, cancelled_by_name, arrival_id),
            )
            if cur.rowcount != 1:
                return None
            row = self._db.execute("SELECT * FROM arrivals WHERE id = ?", (arrival_id,)).fetchone()
        return dict(row)

    def cancelled_arrivals(self, work_date: str) -> list[dict[str, Any]]:
        """One work day's cancelled arrivals, newest cancel first: the Timbangan history.

        By the arrival's work date (index `idx_arrivals_hari`), the day the table shows.
        Newest by the real instant (`julianday`), not the text, as `waiting_arrivals`.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT plate_number, arrived_at, cancelled_at, cancelled_by, cancelled_by_name
                     FROM arrivals
                   WHERE work_date = ? AND cancelled_at IS NOT NULL
                   ORDER BY julianday(cancelled_at) DESC, rowid DESC""",
                (work_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def arrival(self, arrival_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM arrivals WHERE id = ?", (arrival_id,)).fetchone()
        return dict(row) if row else None

    def waiting_arrivals_for_truck(self, truck_id: str) -> list[dict[str, Any]]:
        """This truck's unclaimed arrivals, every day: the caller's time window decides."""
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM arrivals
                   WHERE truck_id = ? AND weighing_id IS NULL AND cancelled_at IS NULL
                   ORDER BY arrived_at, rowid""",
                (truck_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def claim_arrival(self, arrival_id: str, weighing_id: str) -> bool:
        """Pair one waiting arrival with one ticket of the SAME truck. False when either
        side is taken, the ticket is unknown or belongs to another truck: a second claim is
        a normal race (double read at the gate), not an error."""
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE arrivals SET weighing_id = ?
                    WHERE id = ? AND weighing_id IS NULL AND cancelled_at IS NULL
                      AND truck_id = (SELECT truck_id FROM weighings WHERE id = ?)
                      AND NOT EXISTS (SELECT 1 FROM arrivals WHERE weighing_id = ?)""",
                (weighing_id, arrival_id, weighing_id, weighing_id),
            )
        return cur.rowcount == 1

    def waiting_arrivals(self, sejak_hari: str) -> list[dict[str, Any]]:
        """The queue at the scale: not weighed in yet, oldest first, from `sejak_hari` on.

        Oldest by the real instant (`julianday`), not the text: the browser writes `...Z`,
        the seeder `...+07:00`.

        The work date only narrows the read (index `idx_arrivals_hari`); the caller passes
        the work date of "now minus the claim window" and the domain applies the window
        itself (`masih_menunggu`), so a queue that crosses midnight stays one queue.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT id, plate_number, arrived_at FROM arrivals
                   WHERE work_date >= ? AND weighing_id IS NULL AND cancelled_at IS NULL
                   ORDER BY julianday(arrived_at), rowid""",
                (sejak_hari,),
            ).fetchall()
        return [dict(r) for r in rows]

    def jejak_truk(self, truck_ids: Collection[str], sejak_hari: str) -> dict[str, list[str]]:
        """When these trucks were seen again: waiting arrivals (scan 1) and weigh-ins, from work
        date `sejak_hari` on, per truck. What `selesai_tanpa_scan_4` compares a weighed-out
        ticket's weigh-out with; one read for the whole table (B6).

        A claimed arrival is left out on purpose: it belongs to a ticket whose weigh-in is
        already here, or to the ticket being judged, whose arrival came before its weigh-out.
        A cancelled one too: that truck never came back (round 3 test: cancelling gives the old
        visit its Keluar back).
        """
        if not truck_ids:
            return {}
        tanda = ", ".join("?" for _ in truck_ids)  # placeholders only, values stay bound (B5)
        with self._lock:
            rows = self._db.execute(
                f"""SELECT truck_id, arrived_at AS saat FROM arrivals
                     WHERE truck_id IN ({tanda}) AND weighing_id IS NULL AND cancelled_at IS NULL
                       AND work_date >= ?
                    UNION ALL
                    SELECT truck_id, entered_at FROM weighings
                     WHERE truck_id IN ({tanda}) AND work_date >= ? AND entered_at IS NOT NULL""",
                (*truck_ids, sejak_hari, *truck_ids, sejak_hari),
            ).fetchall()
        hasil: dict[str, list[str]] = {}
        for row in rows:
            hasil.setdefault(row["truck_id"], []).append(row["saat"])
        return hasil

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
