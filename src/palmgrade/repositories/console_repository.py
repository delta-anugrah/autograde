"""SQLite index for the operator console (plan §6.2).

The console MUST NOT scan directories: three lines write thousands of files a
day, and a poll that runs `listdir` every 2 s would eat the disk I/O grading
needs. Everything the operator screen reads comes from this index, written once
when an event arrives.

Durability and locking follow `integrations/outbox/outbox_store.py` (WAL +
synchronous=FULL + one threading.Lock + INSERT OR IGNORE). Free of torch/cv2 so
the console process stays light and is testable in CI.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..domain.bahaya import kunci_state_dihapus, tabel_dihapus
from ..domain.plate import normalisasi_plat
from .console_akun_repository import AkunStore
from .console_gerbang_repository import GerbangStore
from .console_skema import siapkan_skema

# What the FFB source label needs from a truck (`domain/ffb_source.py`). One
# definition, so every screen labels the same truck the same way.
SOURCE_FACTS = "t.supplier_id IS NOT NULL AS has_supplier, t.erp_name IS NOT NULL AS in_erp"

#: One recap row, shared by the per-assignment and the per-visit recap so the two can
#: never count differently. Criteria mapping (AutoERP contract names, do not rename):
#: `mentah` is REJ, `tangkai_panjang` an ACC with `tp_confidence > 0.8`, `matang` the rest.
#: The 4-class breakdown (`ripe`, `unripe`, `jk`) is for the console screen only. It does
#: NOT go to AutoERP: `erp_messages._grading` picks fields one by one, and `jk` has no
#: criterion there (see `domain/grade_class.py`).
_KOLOM_REKAP = """COUNT(*) AS total,
       MIN(line_code) AS line_code,
       SUM(CASE WHEN ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
       SUM(CASE WHEN ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej,
       SUM(CASE WHEN ripeness_status = 'ACC' AND tp_confidence > 0.8
                THEN 1 ELSE 0 END) AS tangkai_panjang,
       SUM(CASE WHEN grade_class = 'Ripe'   THEN 1 ELSE 0 END) AS ripe,
       SUM(CASE WHEN grade_class = 'Unripe' THEN 1 ELSE 0 END) AS unripe,
       SUM(CASE WHEN grade_class = 'JK'     THEN 1 ELSE 0 END) AS jk,
       SUM(CASE WHEN capture_type = 'manual' THEN 1 ELSE 0 END) AS manual_reject,
       MIN(timestamp) AS started_at,
       MAX(timestamp) AS ended_at"""

#: The bunch columns of the detail page, for one assignment or one visit.
_KOLOM_JANJANG = """event_id, machine_id, line_code, timestamp, ripeness_status,
       ripeness_confidence, capture_type, image_path, grade_class,
       tp_status, tp_confidence"""

#: Every assignment linked to one visit; `?` is the weighing id.
_PENUGASAN_KUNJUNGAN = "SELECT assignment_id FROM visit_assignments WHERE weighing_id = ?"


class ConsoleStore(AkunStore, GerbangStore):
    def __init__(self, db_path: Path, *, erp_allowed_roles: frozenset[str] | None = None) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # ERP-pull role allow-list, read by `_upsert_operator`.
        self._erp_allowed_roles = erp_allowed_roles or frozenset()
        #: Danger Zone sedang menghapus data (`BahayaService.hapus_data`); selama
        #: benar, `ConsoleService.assign_truck` menolak truk baru. Di memori, bukan
        #: di disk: konsol yang restart di tengah jalan tidak sedang menghapus apa pun.
        self.hapus_berjalan = False
        #: Berapa kali `hapus_data` sudah jalan sejak konsol menyala. Impor CSV mencatatnya
        #: di awal: penghapusan yang mulai DAN selesai selama berkas diperiksa (bisa lebih dari
        #: 10 detik) tetap ketahuan, walau `hapus_berjalan` sudah kembali False.
        self.jumlah_hapus = 0
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            siapkan_skema(self._db)

    # -------------------------------------------------------- inspections

    def add_inspection(self, row: dict[str, Any]) -> bool:
        """Idempotent: a line resends the same event after an outbox retry.

        The dedupe key `event_id` = uuid5(machine_id, file_ts) — the same frozen
        formula palmgrade-api uses, so one bunch is never counted twice.
        True when the row is new; False when this event_id was already stored (a line
        resending after a retry).
        """
        with self._lock, self._db:
            cursor = self._db.execute(
                """INSERT OR IGNORE INTO inspections (
                       event_id, machine_id, line_code, work_date, timestamp,
                       ripeness_status, ripeness_confidence, capture_type,
                       image_path, truck_id, assignment_id, received_at, prediction,
                       grade_class, tp_status, tp_confidence)
                   VALUES (:event_id, :machine_id, :line_code, :work_date, :timestamp,
                           :ripeness_status, :ripeness_confidence, :capture_type,
                           :image_path, :truck_id, :assignment_id, :received_at, :prediction,
                           :grade_class, :tp_status, :tp_confidence)""",
                # `grade_class` diberi default di sini, bukan diwajibkan ke tiap
                # pemanggil: ini kolom rincian yang opsional, dan penulis yang
                # lebih tua darinya (atau capture manual, yang memang tidak lewat
                # model) tidak boleh gagal mencatat satu janjang cuma karena
                # labelnya tidak ada.
                {"grade_class": None, **row, "received_at": time.time()},
            )
        return cursor.rowcount == 1

    def summary(self, work_date: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT line_code,
                          COUNT(*) AS total,
                          SUM(CASE WHEN ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
                          SUM(CASE WHEN ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej,
                          SUM(CASE WHEN grade_class = 'Ripe'   THEN 1 ELSE 0 END) AS ripe,
                          SUM(CASE WHEN grade_class = 'Unripe' THEN 1 ELSE 0 END) AS unripe,
                          SUM(CASE WHEN grade_class = 'JK'     THEN 1 ELSE 0 END) AS jk,
                          SUM(CASE WHEN grade_class IS NULL THEN 1 ELSE 0 END) AS tanpa_kelas,
                          -- Ambang `> 0.8` SAMA PERSIS dengan `grading_counts`.
                          -- Kalau dibuat beda, angka TP di layar tidak akan
                          -- cocok dengan `tangkai_panjang` yang dibukukan
                          -- AutoERP, dan operator yang membandingkan keduanya
                          -- akan melapor "selisih" yang sebenarnya dua aturan.
                          SUM(CASE WHEN tp_confidence > 0.8 THEN 1 ELSE 0 END) AS tp
                   FROM inspections WHERE work_date = ? GROUP BY line_code""",
                (work_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _inspection_filter(
        work_date: str, line_code: str | None, truck_id: str | None
    ) -> tuple[list[str], list[Any]]:
        """One place both the page and its count are filtered.

        Built once and shared on purpose: a count that filters differently from the rows
        produces a page 4 of a list that only has one page - the Next button stays live
        and lands on an empty screen.
        """
        where = ["i.work_date = ?"]
        params: list[Any] = [work_date]
        if line_code:
            where.append("i.line_code = ?")
            params.append(line_code)
        if truck_id:
            where.append("i.truck_id = ?")
            params.append(truck_id)
        return where, params

    def inspection_count(
        self,
        work_date: str,
        *,
        line_code: str | None = None,
        truck_id: str | None = None,
    ) -> int:
        """How many rows the same filter matches across the whole day.

        Counted in SQL rather than measured with `len(items)`: that is only ever as long
        as one page, so the screen would claim 25 rows on a day that graded eight hundred.
        """
        where, params = self._inspection_filter(work_date, line_code, truck_id)
        with self._lock:
            row = self._db.execute(
                f"SELECT COUNT(*) AS n FROM inspections i WHERE {' AND '.join(where)}",
                params,
            ).fetchone()
        return int(row["n"])

    def inspections(
        self,
        work_date: str,
        *,
        line_code: str | None = None,
        truck_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, params = self._inspection_filter(work_date, line_code, truck_id)
        params += [limit, offset]
        with self._lock:
            rows = self._db.execute(
                f"""SELECT i.*, t.plate_number, s.name AS supplier_name, {SOURCE_FACTS}
                    FROM inspections i
                    LEFT JOIN trucks t ON t.id = i.truck_id
                    LEFT JOIN suppliers s ON s.id = t.supplier_id
                    WHERE {' AND '.join(where)}
                    ORDER BY i.timestamp DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def truck_recap(self, work_date: str) -> list[dict[str, Any]]:
        """Per-truck tally for one working day, newest truck first.

        Grouped on `truck_id`, so bunches graded before a truck was assigned
        land in one nameless row instead of being dropped - an unassigned line
        is exactly what the operator needs to see.
        """
        with self._lock:
            rows = self._db.execute(
                f"""SELECT i.truck_id,
                          t.plate_number,
                          s.name AS supplier_name,
                          {SOURCE_FACTS},
                          COUNT(*) AS total,
                          SUM(CASE WHEN i.ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
                          SUM(CASE WHEN i.ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej,
                          SUM(CASE WHEN i.grade_class = 'Ripe'   THEN 1 ELSE 0 END) AS ripe,
                          SUM(CASE WHEN i.grade_class = 'Unripe' THEN 1 ELSE 0 END) AS unripe,
                          SUM(CASE WHEN i.grade_class = 'JK'     THEN 1 ELSE 0 END) AS jk,
                          SUM(CASE WHEN i.grade_class IS NULL THEN 1 ELSE 0 END) AS tanpa_kelas,
                          SUM(CASE WHEN i.tp_confidence > 0.8 THEN 1 ELSE 0 END) AS tp,
                          MIN(i.timestamp) AS started_at,
                          MAX(i.timestamp) AS ended_at
                   FROM inspections i
                   LEFT JOIN trucks t ON t.id = i.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE i.work_date = ?
                   GROUP BY i.truck_id
                   ORDER BY MAX(i.timestamp) DESC""",
                (work_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- master data

    def upsert_supplier(self, row: dict[str, Any]) -> None:
        # Cloud always wins (§3.4): no `updated_at` condition, because the
        # cloud's set_updated_at trigger once froze rows forever in edge sync.
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO suppliers (id, name, source_group, status, erp_name)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                       source_group=excluded.source_group, status=excluded.status,
                       erp_name=excluded.erp_name""",
                (
                    str(row["id"]),
                    row.get("name"),
                    row.get("source_group"),
                    row.get("status"),
                    row.get("erp_name"),
                ),
            )

    def upsert_truck(self, row: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO trucks (id, plate_number, supplier_id, capacity, status, erp_name)
                   VALUES (?, ?, ?, ?, ?, ?)
                   -- Only the pull carries `erp_name`; an operator retyping the
                   -- same plate must not unlink the truck from AutoERP.
                   ON CONFLICT(id) DO UPDATE SET plate_number=excluded.plate_number,
                       supplier_id=excluded.supplier_id, capacity=excluded.capacity,
                       status=excluded.status,
                       erp_name=COALESCE(excluded.erp_name, trucks.erp_name)""",
                (
                    str(row["id"]),
                    row.get("plate_number"),
                    str(row["supplier_id"]) if row.get("supplier_id") else None,
                    row.get("capacity"),
                    row.get("status"),
                    row.get("erp_name"),
                ),
            )

    def truck(self, truck_id: str) -> dict[str, Any] | None:
        """One truck, including `erp_name` — who owns it decides what may edit it."""
        with self._lock:
            row = self._db.execute(
                """SELECT id, plate_number, supplier_id, capacity, status, erp_name
                   FROM trucks WHERE id = ?""",
                (truck_id,),
            ).fetchone()
        return dict(row) if row else None

    def link_truck(self, truck_id: str, erp_name: str, supplier_id: str | None = None) -> None:
        """Record what AutoERP answered for a truck sent up (contract §4.B).

        `supplier_id` only fills a gap: AutoERP owns the owner, so a value here
        is what it just told us, and the next pull carries any later change.
        """
        with self._lock, self._db:
            self._db.execute(
                """UPDATE trucks SET erp_name = ?, supplier_id = COALESCE(?, supplier_id)
                   WHERE id = ?""",
                (erp_name, supplier_id, truck_id),
            )

    def trucks_semua(self) -> list[dict[str, Any]]:
        """Every truck row, `inactive` included — for OPS-2 reconciliation only.

        `trucks()` hides `inactive` because the operator must not be offered a
        retired truck. Reconciliation needs the opposite: an inactive row still
        carrying an old random id will collide with the plate-derived id the next
        pull brings, and the twin appears months later when someone reactivates it.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT id, plate_number, supplier_id, capacity, status, erp_name
                   FROM trucks ORDER BY rowid"""
            ).fetchall()
        return [dict(r) for r in rows]

    def pindahkan_truk(self, dari: str, ke: str) -> None:
        """Move everything hanging off one truck id onto another, in ONE transaction
        (OPS-2, one-time reconciliation when a running mill PC gets AutoGrade).

        `truck_id` lives in four tables, and a half-done move is worse than none:
        rows left pointing at a deleted id vanish from the recap entirely, and that
        recap is what the supplier is paid on. So the whole move commits or nothing
        does.

        The surviving row keeps what either side knew: `erp_name` is the link to
        AutoERP (losing it sends the truck up again as a new owner-less truck), and
        `supplier_id` decides the FFB source label on every grading row of that truck,
        because the label is read from the truck and never copied onto the row.
        """
        if dari == ke:
            return
        with self._lock, self._db:
            lama = self._db.execute(
                "SELECT plate_number, supplier_id, capacity, status, erp_name"
                "  FROM trucks WHERE id = ?",
                (dari,),
            ).fetchone()
            if lama is None:
                return
            baru = self._db.execute("SELECT 1 FROM trucks WHERE id = ?", (ke,)).fetchone()
            if baru is None:
                # No row to merge into: the old row simply takes the right id, so a
                # later pull of that plate adopts it instead of adding a second row.
                self._db.execute("UPDATE trucks SET id = ? WHERE id = ?", (ke, dari))
            else:
                self._db.execute(
                    """UPDATE trucks SET
                           plate_number = COALESCE(plate_number, ?),
                           supplier_id  = COALESCE(supplier_id, ?),
                           capacity     = COALESCE(capacity, ?),
                           status       = COALESCE(status, ?),
                           erp_name     = COALESCE(erp_name, ?)
                       WHERE id = ?""",
                    (lama["plate_number"], lama["supplier_id"], lama["capacity"],
                     lama["status"], lama["erp_name"], ke),
                )
                self._db.execute("DELETE FROM trucks WHERE id = ?", (dari,))
            for tabel in ("inspections", "assignments", "weighings", "arrivals"):
                self._db.execute(
                    f"UPDATE {tabel} SET truck_id = ? WHERE truck_id = ?", (ke, dari)
                )

    def trucks(self) -> list[dict[str, Any]]:
        """Newest first.

        `rowid DESC`, not a timestamp column: the table has no insert time and
        an upsert from master data keeps its rowid, so a truck re-synced later
        does not jump the queue. What the operator wants is the truck they just
        registered, at the top.
        """
        with self._lock:
            rows = self._db.execute(
                f"""SELECT t.id, t.plate_number, t.capacity, t.status,
                          s.name AS supplier_name, {SOURCE_FACTS}
                   FROM trucks t LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE t.status IS NULL OR t.status != 'inactive'
                   ORDER BY t.rowid DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- weighings

    def upsert_weighing(self, row: dict[str, Any]) -> None:
        """Idempotent per `id`, and ONLY filled columns overwrite.

        Weigh-in sends bruto, weigh-out sends tara — two POSTs for one row.
        Without `COALESCE` the second payload would overwrite bruto with NULL
        and neto would go with it. This is the money lane; it must not happen.
        """
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO weighings (
                       id, ref, plate_number, plate_norm, truck_id, work_date,
                       gross_kg, tare_kg, net_kg, entered_at, exited_at, received_at)
                   VALUES (:id, :ref, :plate_number, :plate_norm, :truck_id, :work_date,
                           :gross_kg, :tare_kg, :net_kg, :entered_at, :exited_at, :received_at)
                   ON CONFLICT(id) DO UPDATE SET
                       ref           = COALESCE(excluded.ref, weighings.ref),
                       plate_number  = COALESCE(excluded.plate_number, weighings.plate_number),
                       plate_norm    = COALESCE(excluded.plate_norm, weighings.plate_norm),
                       truck_id      = COALESCE(excluded.truck_id, weighings.truck_id),
                       gross_kg      = COALESCE(excluded.gross_kg, weighings.gross_kg),
                       tare_kg       = COALESCE(excluded.tare_kg, weighings.tare_kg),
                       net_kg        = COALESCE(excluded.net_kg, weighings.net_kg),
                       entered_at    = COALESCE(excluded.entered_at, weighings.entered_at),
                       exited_at     = COALESCE(excluded.exited_at, weighings.exited_at)""",
                {**row, "received_at": time.time()},
            )

    def visit(self, weighing_id: str) -> dict[str, Any] | None:
        """One weighbridge row with what AutoERP needs around it (contract §4.C).

        `supplier_erp_name` comes from the pulled master data — AutoERP matches
        its supplier by its own name, never by anything the console invents.
        `truck_erp_name` is the same idea for the truck: AutoERP prefers it over
        the plate text, so a plate corrected upstream cannot become a twin truck.
        """
        with self._lock:
            row = self._db.execute(
                """SELECT w.*,
                          s.erp_name AS supplier_erp_name,
                          s.name AS supplier_name,
                          t.erp_name AS truck_erp_name
                   FROM weighings w
                   LEFT JOIN trucks t ON t.id = w.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE w.id = ?""",
                (weighing_id,),
            ).fetchone()
        return dict(row) if row else None

    def grading_counts(self, assignment_id: str) -> dict[str, Any] | None:
        """The AI result of one line assignment, counted in SQL (§4.C).

        None when the assignment graded nothing. Used to tell whether a release that found
        no ticket loses any bunches. A visit's recap, the one that is sent, is
        `grading_counts_for_visit`, which sums every line of the truck.
        """
        with self._lock:
            row = self._db.execute(
                f"SELECT {_KOLOM_REKAP} FROM inspections WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        if not row or not row["total"]:
            return None
        return {"assignment_id": assignment_id, **dict(row)}

    def grading_counts_for_visit(self, weighing_id: str) -> dict[str, Any] | None:
        """The AI result of one truck visit: every line assignment linked to it, summed.

        A truck unloaded on three lines has three assignments; counting only one sent
        AutoERP one line of three (fixed 2026-10-01). `assignment_id` is the first one
        linked, so the key AutoERP stores (`autograde_assignment_id`, unique) stays the
        same across resends. `line_code` names every line, for the detail page and the
        Log tab; AutoERP does not read it.
        """
        with self._lock:
            row = self._db.execute(
                f"""SELECT {_KOLOM_REKAP} FROM inspections
                    WHERE assignment_id IN ({_PENUGASAN_KUNJUNGAN})""",
                (weighing_id,),
            ).fetchone()
            if not row or not row["total"]:
                return None
            lines = [
                r["line_code"]
                for r in self._db.execute(
                    f"""SELECT DISTINCT line_code FROM inspections
                        WHERE assignment_id IN ({_PENUGASAN_KUNJUNGAN}) ORDER BY line_code""",
                    (weighing_id,),
                ).fetchall()
            ]
            pertama = self._db.execute(
                """SELECT assignment_id FROM visit_assignments WHERE weighing_id = ?
                   ORDER BY linked_at, rowid LIMIT 1""",
                (weighing_id,),
            ).fetchone()
        return {**dict(row), "assignment_id": pertama["assignment_id"], "line_code": ", ".join(lines)}

    def bunches_for_visit(self, weighing_id: str) -> list[dict[str, Any]]:
        """Every bunch of one truck visit across all its lines, oldest first (detail page)."""
        with self._lock:
            rows = self._db.execute(
                f"""SELECT {_KOLOM_JANJANG} FROM inspections
                    WHERE assignment_id IN ({_PENUGASAN_KUNJUNGAN}) ORDER BY timestamp""",
                (weighing_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def assignments_for_truck(self, truck_id: str) -> list[dict[str, Any]]:
        """Line mana saja yang sedang memegang truk ini.

        Bisa lebih dari satu: `assignments` berkunci `line_code`, karena satu truk
        memang boleh dibongkar paralel di beberapa line. Melepas hanya line pertama
        meninggalkan sisanya tetap menstempel truk yang sudah pulang.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT a.*, t.plate_number
                   FROM assignments a
                   LEFT JOIN trucks t ON t.id = a.truck_id
                   WHERE a.truck_id = ?""",
                (truck_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_auto_release(
        self, *, line_code: str, truck_id: str, plate_number: str | None, assignment_id: str | None
    ) -> None:
        """Jejak bahwa timbang keluar yang melepas line ini, bukan operator."""
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO auto_releases
                       (line_code, truck_id, plate_number, assignment_id, released_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (line_code, truck_id, plate_number, assignment_id, time.time()),
            )

    def auto_releases_terbaru(self, *, sejak_detik: float = 3600.0) -> list[dict[str, Any]]:
        """Pelepasan otomatis yang masih layak ditampilkan di layar operator.

        Dibatasi waktu, bukan jumlah: peringatan kemarin yang masih menempel hari
        ini mengajari operator mengabaikan kotak merah itu.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM auto_releases WHERE released_at >= ? ORDER BY released_at DESC",
                (time.time() - sejak_detik,),
            ).fetchall()
        return [dict(r) for r in rows]

    def link_weighing_to_assignment(
        self, weighing_id: str, assignment_id: str, line_code: str | None = None
    ) -> None:
        """Written when a line lets the truck go: that line's bunches are this visit's.

        Two writes, one transaction: the link row the recap sums, and the old single
        column, still read by an older image if the factory PC rolls back.
        """
        with self._lock, self._db:
            self._db.execute(
                "UPDATE weighings SET assignment_id = ? WHERE id = ?", (assignment_id, weighing_id)
            )
            self._db.execute(
                """INSERT OR IGNORE INTO visit_assignments
                       (assignment_id, weighing_id, line_code, linked_at)
                   VALUES (?, ?, ?, ?)""",
                (assignment_id, weighing_id, line_code, time.time()),
            )

    def weighing_for_assignment(self, assignment_id: str) -> str | None:
        """The ticket this assignment was linked to when its line let the truck go, or None.

        The link is written only at release, so a link means the assignment is closed and
        its visit was already queued without any bunch that arrives now. Every line of the
        visit finds it, not only the one released last.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT weighing_id FROM visit_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        return row["weighing_id"] if row else None

    def record_visit_answer(
        self, weighing_id: str, *, ticket: str | None, status: str | None, note: str | None
    ) -> None:
        """What AutoERP answered for this visit.

        The ticket is the trace back to the ledger. The status and the note are the two
        things only AutoERP knows: it never rewrites a finalised ticket, so a late
        grading change comes back as a note and a flag on its side — and used to leave
        no trace at all on ours.

        `ticket` and `status` are COALESCEd: a later answer that omits one must not erase
        it. `note` is replaced, because its absence is itself the news — whatever it
        described is no longer true of this visit.
        """
        with self._lock, self._db:
            self._db.execute(
                """UPDATE weighings
                      SET erp_ticket = COALESCE(?, erp_ticket),
                          erp_status = COALESCE(?, erp_status),
                          erp_note   = ?
                    WHERE id = ?""",
                (ticket, status, note, weighing_id),
            )

    def latest_weighing_for_truck_since(self, truck_id: str, sejak: float) -> str | None:
        """The visit a truck's grading belongs to: its newest ticket received since `sejak`.

        A time window on the console clock (epoch seconds), not a work date: the work
        date flips at midnight, and a truck weighed in at 23:30 and released at 00:30
        used to find no ticket at all, so its grading reached AutoERP linked to nothing.
        """
        with self._lock:
            row = self._db.execute(
                """SELECT id FROM weighings
                   WHERE truck_id = ? AND received_at >= ?
                   ORDER BY COALESCE(entered_at, '') DESC, received_at DESC LIMIT 1""",
                (truck_id, sejak),
            ).fetchone()
        return row["id"] if row else None

    def weighing_ids_on(self, work_date: str) -> list[str]:
        """Every visit of one working day, oldest first (the daily resend)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id FROM weighings WHERE work_date = ? ORDER BY received_at",
                (work_date,),
            ).fetchall()
        return [row["id"] for row in rows]

    def weighing(self, weighing_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM weighings WHERE id = ?", (weighing_id,)).fetchone()
        return dict(row) if row else None

    def weighings(self, work_date: str, *, limit: int = 100) -> list[dict[str, Any]]:
        # ponytail: joins on `truck_id` only, so a cloud-synced truck (id from
        # the cloud, not uuid5 of the plate) shows no name yet. Good enough
        # until the ERP lane is live — see docs/PERTANYAAN-TERBUKA.md S1-S3.
        with self._lock:
            rows = self._db.execute(
                f"""SELECT w.*, a.arrived_at AS arrived_at, s.name AS supplier_name, {SOURCE_FACTS}
                   FROM weighings w
                   LEFT JOIN arrivals a ON a.weighing_id = w.id
                   LEFT JOIN trucks t ON t.id = w.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE w.work_date = ?
                   ORDER BY w.entered_at DESC, w.received_at DESC LIMIT ?""",
                (work_date, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def ringkasan_timbangan(self, work_date: str) -> dict[str, Any]:
        """Tiket, yang menunggu tara, dan total neto satu hari kerja.

        Untuk strip "Hari ini" di layar operator, yang dipolling tiap 2 detik:
        satu query agregat, bukan menjumlah `weighings()` yang membawa join
        supplier dan batas 100 baris. Menunggu tara = sudah ada bruto, tara
        belum; neto cuma dijumlah dari tiket yang sudah lengkap.
        """
        with self._lock:
            row = self._db.execute(
                """SELECT COUNT(*) AS tiket,
                          COALESCE(SUM(CASE WHEN gross_kg IS NOT NULL AND tare_kg IS NULL
                                            THEN 1 ELSE 0 END), 0) AS menunggu_tara,
                          COALESCE(SUM(net_kg), 0) AS neto_kg
                   FROM weighings WHERE work_date = ?""",
                (work_date,),
            ).fetchone()
        return {
            "tiket": row["tiket"],
            "menunggu_tara": row["menunggu_tara"],
            "neto_kg": row["neto_kg"],
        }

    def open_weighings_for_truck(self, truck_id: str, work_date: str) -> list[dict[str, Any]]:
        """This truck's tickets not yet weighed out, for that working day only.

        `tare_kg IS NULL` is what makes a ticket open: one that already has a
        tare means its truck has left, and offering it again would overwrite
        the first tare — net silently changes, and net is what gets paid.

        Scoped to the working day: yesterday's ticket whose tare was never
        filled would otherwise produce a net from yesterday's gross and
        today's tare.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM weighings
                   WHERE truck_id = ? AND work_date = ? AND tare_kg IS NULL
                   ORDER BY COALESCE(entered_at, '') DESC, received_at DESC""",
                (truck_id, work_date),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------ unloading queue (2026-10-01)

    def unloading_queue(self, sejak: float) -> list[dict[str, Any]]:
        """Weighed in, not out, on no line, never on one, not skipped; oldest first.

        "Never on one" is the visit link (written when a line lets the truck go) plus the
        lines holding it right now: a truck being sorted, or already sorted, is never
        offered again. Only a truck's newest ticket is offered: an older one left open by
        a weigh-in typed twice would otherwise put the truck back on the lines after it
        left. "Newest" is ordered exactly as `latest_weighing_for_truck_since` orders it
        (weigh-in time, then arrival), so the ticket a release links is always the one
        this would offer. `sejak` is an epoch on `received_at`, the console's own clock.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT w.id AS weighing_id, w.truck_id, w.plate_number, w.entered_at,
                          w.received_at
                   FROM weighings w
                   WHERE w.tare_kg IS NULL AND w.gross_kg IS NOT NULL
                     AND w.truck_id IS NOT NULL
                     AND w.unloading_queue_skipped_at IS NULL
                     AND w.received_at >= ?
                     AND NOT EXISTS (SELECT 1 FROM visit_assignments va WHERE va.weighing_id = w.id)
                     AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.truck_id = w.truck_id)
                     AND NOT EXISTS (
                         SELECT 1 FROM weighings w2
                          WHERE w2.truck_id = w.truck_id AND w2.received_at >= ?
                            AND (COALESCE(w2.entered_at, ''), w2.received_at)
                                > (COALESCE(w.entered_at, ''), w.received_at))
                   ORDER BY w.received_at, w.rowid""",
                (sejak, sejak),
            ).fetchall()
        return [dict(r) for r in rows]

    def trucks_with_open_ticket(self, sejak: float) -> set[str]:
        """Trucks weighed in and not yet out: the ones still being sorted."""
        with self._lock:
            rows = self._db.execute(
                """SELECT DISTINCT truck_id FROM weighings
                   WHERE tare_kg IS NULL AND gross_kg IS NOT NULL
                     AND truck_id IS NOT NULL AND received_at >= ?""",
                (sejak,),
            ).fetchall()
        return {r["truck_id"] for r in rows}

    def skip_unloading_queue(self, weighing_id: str, at: str) -> bool:
        """"Lewati": out of the unloading queue, once, and only while the ticket is open."""
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE weighings SET unloading_queue_skipped_at = ?
                    WHERE id = ? AND unloading_queue_skipped_at IS NULL AND tare_kg IS NULL""",
                (at, weighing_id),
            )
        return cur.rowcount == 1

    # -------------------------------------------------------- assignment

    def set_assignment(self, line_code: str, assignment_id: str, truck_id: str | None) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO assignments (line_code, assignment_id, truck_id, started_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(line_code) DO UPDATE SET assignment_id=excluded.assignment_id,
                       truck_id=excluded.truck_id, started_at=excluded.started_at""",
                (line_code, assignment_id, truck_id, time.time()),
            )

    def assignments(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                f"""SELECT a.*, t.plate_number, s.name AS supplier_name, {SOURCE_FACTS}
                   FROM assignments a
                   LEFT JOIN trucks t ON t.id = a.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id"""
            ).fetchall()
        return {r["line_code"]: dict(r) for r in rows}

    # ------------------------------------------------------- sync cursor

    def get_state(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sync_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ── Danger Zone (layar Setelan, support) ────────────────────────────────

    # ------------------------------------------------------ impor grading

    def event_sudah_ada(self, event_ids: list[str]) -> set[str]:
        """Yang sudah tersimpan dari satu potongan id (pemanggil memotong per ratusan)."""
        if not event_ids:
            return set()
        tanda = ",".join("?" * len(event_ids))
        with self._lock:
            rows = self._db.execute(
                f"SELECT event_id FROM inspections WHERE event_id IN ({tanda})", event_ids
            ).fetchall()
        return {r["event_id"] for r in rows}

    def peta_truk_per_plat(self) -> dict[str, str]:
        """Plat ternormalisasi → id truk, untuk SEMUA baris truk.

        Termasuk truk warisan ber-id acak (sebelum OPS-2): impor memakai baris yang
        ada, bukan membuat kembaran ber-id plat yang membelah tonase satu truk.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT id, plate_number FROM trucks ORDER BY erp_name IS NULL, id"
            ).fetchall()
        peta: dict[str, str] = {}
        for r in rows:
            try:
                kunci = normalisasi_plat(r["plate_number"] or "")
            except ValueError:
                continue
            peta.setdefault(kunci, r["id"])
        return peta

    def supplier_per_nama(self) -> dict[str, str | None]:
        """Nama supplier (huruf kecil, tanpa spasi tepi) → id; None kalau namanya
        dipakai lebih dari satu supplier, karena menebak di situ memberi truk
        pemilik yang salah."""
        with self._lock:
            rows = self._db.execute("SELECT id, name FROM suppliers").fetchall()
        peta: dict[str, str | None] = {}
        for r in rows:
            nama = (r["name"] or "").strip().lower()
            if nama:
                peta[nama] = None if nama in peta else r["id"]
        return peta

    def mulai_impor(self, batch: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO grading_imports (id, file_name, fingerprint, imported_by,
                       started_at, rows_total, status)
                   VALUES (:id, :file_name, :fingerprint, :imported_by, :started_at,
                           :rows_total, 'running')""",
                batch,
            )

    def simpan_potongan_impor(
        self, batch_id: str, janjang: list[dict[str, Any]], truk: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Satu potongan dalam SATU transaksi: truk yang belum ada, lalu janjangnya.

        `INSERT OR IGNORE` di keduanya: janjang yang event_id-nya sudah ada tidak
        disentuh, dan truk yang sudah ada (milik AutoERP atau diketik operator) tidak
        diubah. Kembalikan (janjang ditambah, truk dibuat).
        """
        with self._lock, self._db:
            dibuat = 0
            for t in truk:
                dibuat += self._db.execute(
                    """INSERT OR IGNORE INTO trucks (id, plate_number, supplier_id, status)
                       VALUES (?, ?, ?, 'manual')""",
                    (t["id"], t["plate_number"], t.get("supplier_id")),
                ).rowcount
            ditambah = self._db.executemany(
                """INSERT OR IGNORE INTO inspections (
                       event_id, machine_id, line_code, work_date, timestamp,
                       ripeness_status, ripeness_confidence, capture_type, image_path,
                       truck_id, assignment_id, received_at, prediction, grade_class,
                       tp_status, tp_confidence, import_batch)
                   VALUES (:event_id, :machine_id, :line_code, :work_date, :timestamp,
                           :ripeness_status, :ripeness_confidence, :capture_type, :image_path,
                           :truck_id, :assignment_id, :received_at, :prediction, :grade_class,
                           :tp_status, :tp_confidence, :import_batch)""",
                [{**j, "import_batch": batch_id} for j in janjang],
            ).rowcount
        return max(ditambah, 0), dibuat

    def selesai_impor(self, batch_id: str, **hasil: Any) -> None:
        kolom = ("status", "finished_at", "added", "skipped_existing", "skipped_today",
                 "duplicates", "date_from", "date_to", "new_trucks")
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE grading_imports SET {', '.join(f'{k} = :{k}' for k in kolom)} WHERE id = :id",
                {**{k: hasil.get(k) for k in kolom}, "id": batch_id},
            )

    def impor_grading(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM grading_imports WHERE id = ?", (batch_id,)).fetchone()
        return dict(row) if row else None

    def daftar_impor(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM grading_imports ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def hapus_potongan_impor(self, batch_id: str, *, batas: int = 5000) -> int:
        """Hapus paling banyak `batas` janjang satu batch. Dipanggil berulang sampai 0:
        tiap potongan transaksi sendiri, jadi ingest dari line tidak menunggu satu
        penghapusan besar selesai."""
        with self._lock, self._db:
            return self._db.execute(
                """DELETE FROM inspections WHERE rowid IN (
                       SELECT rowid FROM inspections WHERE import_batch = ? LIMIT ?)""",
                (batch_id, batas),
            ).rowcount

    def tandai_impor_dibatalkan(self, batch_id: str, *, oleh: str, now: float, removed: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                """UPDATE grading_imports SET status = 'undone', undone_at = ?, undone_by = ?,
                       removed = removed + ? WHERE id = ?""",
                (now, oleh, removed, batch_id),
            )

    def tandai_impor_terputus(self) -> int:
        """Saat konsol menyala: impor yang masih `running` pasti terputus di tengah."""
        with self._lock, self._db:
            return self._db.execute(
                "UPDATE grading_imports SET status = 'interrupted' WHERE status = 'running'"
            ).rowcount

    def hapus_data(self, mode: str) -> dict[str, int]:
        """Kosongkan data konsol menurut mode, dalam SATU transaksi.

        Tabel dan kunci `sync_state` yang dihapus diputuskan `domain/bahaya.py`,
        bukan di sini: `setelan_*` tidak pernah dihapus, kursor tarik AutoERP
        cuma di mode semua. Mode asing ditolak SEBELUM apa pun tersentuh.
        Kembalikan jumlah baris yang hilang per tabel.
        """
        tabel = tabel_dihapus(mode)
        hasil: dict[str, int] = {}
        with self._lock, self._db:
            for nama in tabel:
                # Nama tabel datang dari daftar tetap di domain/bahaya.py, tidak
                # pernah dari luar — identifier SQL tidak bisa jadi parameter.
                hasil[nama] = self._db.execute(f"DELETE FROM {nama}").rowcount
            kunci = [row["key"] for row in self._db.execute("SELECT key FROM sync_state")]
            buang = [k for k in kunci if kunci_state_dihapus(k, mode)]
            for k in buang:
                self._db.execute("DELETE FROM sync_state WHERE key = ?", (k,))
            hasil["sync_state"] = len(buang)
        self.jumlah_hapus += 1
        return hasil

    def tiket_terbuka(self, hari_kerja: str) -> dict[str, int]:
        """Tiket yang sudah timbang masuk tapi belum keluar (bruto ada, tara belum):
        `hari_ini` = hari kerja berjalan — truk di tengah kunjungan; `lama` = hari
        lain, hampir pasti sisa uji coba yang taranya tidak pernah diisi."""
        with self._lock:
            row = self._db.execute(
                """SELECT COALESCE(SUM(work_date = ?), 0) AS hari_ini,
                          COALESCE(SUM(work_date <> ?), 0) AS lama
                   FROM weighings WHERE gross_kg IS NOT NULL AND tare_kg IS NULL""",
                (hari_kerja, hari_kerja),
            ).fetchone()
        return {"hari_ini": row["hari_ini"], "lama": row["lama"]}

    def hapus_semua_sesi(self) -> int:
        """Logout paksa: semua sesi, termasuk milik yang menekan tombolnya."""
        with self._lock, self._db:
            return self._db.execute("DELETE FROM sesi").rowcount

    def ringkas_data(self, *, now: float) -> dict[str, int]:
        """Angka untuk panel Danger Zone: apa yang akan hilang."""

        def hitung(sql: str, *args: Any) -> int:
            return self._db.execute(sql, args).fetchone()[0]

        with self._lock:
            return {
                "janjang": hitung("SELECT COUNT(*) FROM inspections"),
                "tiket": hitung("SELECT COUNT(*) FROM weighings"),
                "truk": hitung("SELECT COUNT(*) FROM trucks"),
                "akun": hitung("SELECT COUNT(*) FROM operators"),
                "akun_lokal": hitung("SELECT COUNT(*) FROM operators WHERE origin = 'lokal'"),
                "sesi_aktif": hitung("SELECT COUNT(*) FROM sesi WHERE expires_at > ?", now),
            }
