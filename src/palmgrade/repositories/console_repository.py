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

from ..domain.operator_auth import normalise_email, normalise_nama, operator_id_for
from ..domain.role import ROLE_SUPPORT, filter_erp_role, sanitize_role

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS inspections (
    event_id            TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    line_code           TEXT NOT NULL,
    work_date           TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    ripeness_status     TEXT NOT NULL,
    ripeness_confidence REAL,
    capture_type        TEXT NOT NULL,
    image_path          TEXT,
    truck_id            TEXT,
    assignment_id       TEXT,
    received_at         REAL NOT NULL,
    -- Stored as sent by the line, NOT re-derived from `ripeness_status`: ERP
    -- requires `prediction`, and deriving it in two repos means two rules that
    -- can drift apart with nobody noticing.
    prediction          TEXT,
    -- Kelas model yang sebenarnya (Ripe/Unripe/JK/TP), di samping verdict biner
    -- di `ripeness_status`. Dua kolom, bukan satu, karena piston dan buku besar
    -- AutoERP cuma mengenal ACC/REJ (`domain/grade_class.py`). NULL untuk baris
    -- yang ditulis sebelum kolom ini ada, dan untuk capture manual — yang itu
    -- tidak pernah lewat model, jadi kelasnya memang tidak diketahui.
    grade_class         TEXT,
    tp_status           TEXT,
    tp_confidence       REAL,
    -- Unused since the per-bunch push was dropped: AutoERP takes one message
    -- per truck visit. Kept so factory databases need no table rebuild.
    erp_state           TEXT
);
CREATE INDEX IF NOT EXISTS idx_inspections_hari ON inspections (work_date, line_code);
CREATE INDEX IF NOT EXISTS idx_inspections_urut ON inspections (work_date, timestamp DESC);

CREATE TABLE IF NOT EXISTS suppliers (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    source_group TEXT,
    status       TEXT,
    -- The AutoERP document name, this row's id on the other side. NULL until a
    -- pull matches it; unique, so two local rows can never claim one supplier.
    erp_name TEXT
);

CREATE TABLE IF NOT EXISTS trucks (
    id           TEXT PRIMARY KEY,
    plate_number TEXT,
    supplier_id  TEXT,
    capacity     REAL,
    status       TEXT,
    erp_name     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trucks_plat ON trucks (plate_number);

CREATE TABLE IF NOT EXISTS assignments (
    line_code     TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    truck_id      TEXT,
    started_at    REAL NOT NULL
);

-- Line yang dilepas OLEH TIMBANG KELUAR, bukan oleh operator (G5). Dicatat
-- supaya pelepasannya terlihat: operator yang menimbang keluar terlalu cepat
-- (antrean jembatan timbang, bongkar belum habis) harus tahu line-nya baru saja
-- lepas, supaya bisa meng-assign ulang. Pelepasan senyap hanya menukar satu
-- kegagalan diam dengan kegagalan diam yang lain.
CREATE TABLE IF NOT EXISTS auto_releases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    line_code     TEXT NOT NULL,
    truck_id      TEXT NOT NULL,
    plate_number  TEXT,
    assignment_id TEXT,
    released_at   REAL NOT NULL
);

-- Weighbridge (§3.5c). Filled by the scale program via
-- POST /internal/scale/weighing; its format is unknown (X1), so the lane is
-- built in OUR shape and only an adapter is added later.
-- `net_kg` never arrives from outside as-is — it is computed in the service.
CREATE TABLE IF NOT EXISTS weighings (
    id            TEXT PRIMARY KEY,
    ref           TEXT,
    plate_number  TEXT,
    plate_norm    TEXT,
    truck_id      TEXT,
    work_date     TEXT NOT NULL,
    gross_kg      REAL,
    tare_kg       REAL,
    net_kg        REAL,
    entered_at    TEXT,
    exited_at     TEXT,
    received_at   REAL NOT NULL,
    -- The line assignment this visit's bunches belong to, written when the truck
    -- leaves the line. Without it a second ticket the same day would inherit the
    -- first one's grading.
    assignment_id TEXT,
    -- What AutoERP answered for this visit: the Weighbridge Ticket it made, that
    -- ticket's status, and the note it sends only when a human is needed — a
    -- finalised ticket whose grading changed, or a cancelled one it ignored.
    erp_ticket    TEXT,
    erp_status    TEXT,
    erp_note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_weighings_hari ON weighings (work_date, entered_at DESC);
CREATE INDEX IF NOT EXISTS idx_weighings_plat ON weighings (plate_norm);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Operator accounts for the console login (Fase 4). Two sources, and the row says
-- which: `erp` is pulled from AutoERP's `AutoGrade Operator` (§4.A), `lokal` is written
-- on this PC by `make operator` — the built-in and support accounts, which are how a
-- mill that has never reached the internet gets opened. Neither may overwrite the
-- other. The hash is verified here, offline; nothing is asked of AutoERP at sign-in.
CREATE TABLE IF NOT EXISTS operators (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    origin         TEXT NOT NULL DEFAULT 'lokal',
    erp_name       TEXT,
    -- `operator` or `support`. No CHECK on purpose: a third role later should
    -- not need a table migration; the route is what enforces this column.
    role           TEXT NOT NULL DEFAULT 'operator',
    created_at     REAL NOT NULL,
    -- Wrong-password counter, on disk so reloading the page cannot reset the lockout.
    fail_count     INTEGER NOT NULL DEFAULT 0,
    last_failed_at REAL
);

CREATE TABLE IF NOT EXISTS sesi (
    token          TEXT PRIMARY KEY,
    operator_id    TEXT NOT NULL,
    created_at     REAL NOT NULL,
    expires_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sesi_kedaluwarsa ON sesi (expires_at);
"""


# Runs after the ALTERs above, never inside `_CREATE_SQL`: on a database that
# predates the column, an index over it cannot be created yet. NULLs are exempt
# from a SQLite unique index, so unmatched rows stay allowed.
_MIGRATE_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_erp ON suppliers (erp_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trucks_erp ON trucks (erp_name);
-- Served only the dropped per-bunch push; it cost a write on every event.
DROP INDEX IF EXISTS idx_inspections_erp;
"""

# What the FFB source label needs from a truck (`domain/ffb_source.py`). One
# definition, so every screen labels the same truck the same way.
_SOURCE_FACTS = "t.supplier_id IS NOT NULL AS has_supplier, t.erp_name IS NOT NULL AS in_erp"


class ConsoleStore:
    def __init__(self, db_path: Path, *, erp_allowed_roles: frozenset[str] | None = None) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # ERP-pull role allow-list, read by `_upsert_operator`.
        self._erp_allowed_roles = erp_allowed_roles or frozenset()
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            # Before `_CREATE_SQL`: its indexes name the English columns, so on a
            # database written before the rename they would be created against
            # columns that do not exist yet.
            self._rename_indonesian_columns()
            self._db.executescript(_CREATE_SQL)
            self._migrate()

    def _migrate(self) -> None:
        """Add what a console older than this build has not got.

        `CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it is,
        so a new column never reaches a factory database through the schema
        above — it needs its own pass, and the index that depends on it has to
        wait until the column exists.
        """
        self._drop_pin_era_operators()
        for table, column in (
            ("suppliers", "erp_name"),
            ("trucks", "erp_name"),
            ("weighings", "assignment_id"),
            ("weighings", "erp_ticket"),
            ("weighings", "erp_status"),
            ("weighings", "erp_note"),
            # Konsol pabrik yang sudah jalan punya tabel `inspections` tanpa
            # kolom ini; `CREATE TABLE IF NOT EXISTS` di atas tidak akan
            # menambahkannya. Baris lama tetap NULL — sengaja, karena kelas
            # aslinya memang tidak pernah direkam dan menebaknya dari
            # `ripeness_status` akan mengarang: REJ bisa Unripe atau JK.
            ("inspections", "grade_class"),
        ):
            columns = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        # Separate from the loop above: that loop can only do a plain `ADD COLUMN
        # ... TEXT`, but this column needs NOT NULL + DEFAULT so old rows land on
        # `operator` instead of a NULL readers have to guess at.
        operator_columns = {r["name"] for r in self._db.execute("PRAGMA table_info(operators)")}
        if "role" not in operator_columns:
            self._db.execute(
                "ALTER TABLE operators ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'"
            )
        self._db.executescript(_MIGRATE_SQL)

    # Columns renamed to English after the schema had already been created on
    # developer machines. `CREATE TABLE IF NOT EXISTS` leaves an existing table
    # alone, so without this pass every read hits a column that is not there.
    _RENAMED_COLUMNS = (
        ("inspections", (("tanggal_kerja", "work_date"),)),
        ("suppliers", (("sumber", "source_group"),)),
        (
            "weighings",
            (
                ("tanggal_kerja", "work_date"),
                ("bruto_kg", "gross_kg"),
                ("tara_kg", "tare_kg"),
                ("neto_kg", "net_kg"),
                ("waktu_masuk", "entered_at"),
                ("waktu_keluar", "exited_at"),
            ),
        ),
        ("sesi", (("dibuat_at", "created_at"), ("kedaluwarsa_at", "expires_at"))),
        (
            "operators",
            (
                ("nama", "full_name"),
                ("asal", "origin"),
                ("dibuat_at", "created_at"),
                ("gagal_count", "fail_count"),
                ("gagal_terakhir", "last_failed_at"),
            ),
        ),
    )

    def _rename_indonesian_columns(self) -> None:
        """Carry a database written before the columns were renamed to English.

        The rename shipped without this pass, on the reasoning that no factory PC had
        ever run that schema. True for factory PCs, false for every machine that already
        had a console database — there the old names stayed and every read missed.

        `peran` is the sharp one: the pass in `_migrate` adds `role` as a *new* column
        defaulting to `operator`, so a database that still had `peran` came out with
        both — every support account silently demoted while keeping its name. The value
        is carried over before that runs, and `peran` dropped only once `role` holds it.
        """
        for table, pairs in self._RENAMED_COLUMNS:
            columns = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            if not columns:
                continue
            for old, new in pairs:
                if old in columns and new not in columns:
                    self._db.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
        self._rename_operator_role()

    def _rename_operator_role(self) -> None:
        """`peran` → `role`, keeping the value even when both columns exist."""
        columns = {r["name"] for r in self._db.execute("PRAGMA table_info(operators)")}
        if "peran" not in columns:
            return
        if "role" in columns:
            self._db.execute("UPDATE operators SET role = peran")
            self._db.execute("ALTER TABLE operators DROP COLUMN peran")
        else:
            self._db.execute("ALTER TABLE operators RENAME COLUMN peran TO role")

    def _drop_pin_era_operators(self) -> None:
        """Rebuild `operators` if it still carries the six-digit-PIN shape.

        Dropped rather than migrated, deliberately. The PIN table keyed accounts by
        `full_name` with no email anywhere, and an email cannot be invented for a row — a
        guessed one would be a sign-in that silently belongs to nobody. The accounts are
        re-made by `make operator` or arrive with the next AutoERP pull, so the cost is
        one command on a dev database. No factory PC ran the PIN build: it never left
        this branch, and the sessions go with the table so nobody stays signed in
        against an account that no longer exists.
        """
        columns = {r["name"] for r in self._db.execute("PRAGMA table_info(operators)")}
        if columns and "pin_hash" in columns:
            self._db.execute("DROP TABLE IF EXISTS sesi")
            self._db.execute("DROP TABLE operators")
            self._db.executescript(_CREATE_SQL)

    # -------------------------------------------------------- inspections

    def add_inspection(self, row: dict[str, Any]) -> None:
        """Idempotent: a line resends the same event after an outbox retry.

        The dedupe key `event_id` = uuid5(machine_id, file_ts) — the same frozen
        formula palmgrade-api uses, so one bunch is never counted twice.
        """
        with self._lock, self._db:
            self._db.execute(
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
                f"""SELECT i.*, t.plate_number, s.name AS supplier_name, {_SOURCE_FACTS}
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
                          {_SOURCE_FACTS},
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

        `truck_id` lives in three tables, and a half-done move is worse than none:
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
            for tabel in ("inspections", "assignments", "weighings"):
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
                          s.name AS supplier_name, {_SOURCE_FACTS}
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

        Criteria mapping (AutoERP contract field names, do not rename): `mentah` is
        REJ, `tangkai_panjang` an ACC the line marked with `tp_confidence > 0.8`,
        `matang` the rest — AutoERP derives that one. None when the assignment
        graded nothing: there is no summary to send.
        """
        with self._lock:
            row = self._db.execute(
                """SELECT COUNT(*) AS total,
                          MIN(line_code) AS line_code,
                          SUM(CASE WHEN ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
                          SUM(CASE WHEN ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej,
                          SUM(CASE WHEN ripeness_status = 'ACC' AND tp_confidence > 0.8
                                   THEN 1 ELSE 0 END) AS tangkai_panjang,
                          -- Rincian 4 kelas, buat layar konsol. Sengaja TIDAK
                          -- ikut ke AutoERP: `erp_messages._grading` memilih
                          -- field satu per satu, dan `jk` tidak punya kriteria
                          -- di sana (lihat `domain/grade_class.py`).
                          SUM(CASE WHEN grade_class = 'Ripe'   THEN 1 ELSE 0 END) AS ripe,
                          SUM(CASE WHEN grade_class = 'Unripe' THEN 1 ELSE 0 END) AS unripe,
                          SUM(CASE WHEN grade_class = 'JK'     THEN 1 ELSE 0 END) AS jk,
                          SUM(CASE WHEN capture_type = 'manual' THEN 1 ELSE 0 END) AS manual_reject,
                          MIN(timestamp) AS started_at,
                          MAX(timestamp) AS ended_at
                   FROM inspections WHERE assignment_id = ?""",
                (assignment_id,),
            ).fetchone()
        if not row or not row["total"]:
            return None
        return {"assignment_id": assignment_id, **dict(row)}

    def bunches_for_assignment(self, assignment_id: str) -> list[dict[str, Any]]:
        """Every bunch of one line assignment, oldest first — the visit manifest."""
        with self._lock:
            rows = self._db.execute(
                """SELECT event_id, machine_id, line_code, timestamp, ripeness_status,
                          ripeness_confidence, capture_type, image_path, grade_class,
                          tp_status, tp_confidence
                   FROM inspections WHERE assignment_id = ? ORDER BY timestamp""",
                (assignment_id,),
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

    def link_weighing_to_assignment(self, weighing_id: str, assignment_id: str) -> None:
        """Written when the truck leaves the line: these bunches are that visit's."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE weighings SET assignment_id = ? WHERE id = ?", (assignment_id, weighing_id)
            )

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

    def latest_weighing_for_truck(self, truck_id: str, work_date: str) -> str | None:
        """The visit a truck's grading belongs to: its newest ticket that day."""
        with self._lock:
            row = self._db.execute(
                """SELECT id FROM weighings
                   WHERE truck_id = ? AND work_date = ?
                   ORDER BY COALESCE(entered_at, '') DESC, received_at DESC LIMIT 1""",
                (truck_id, work_date),
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
                f"""SELECT w.*, s.name AS supplier_name, {_SOURCE_FACTS}
                   FROM weighings w
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
                f"""SELECT a.*, t.plate_number, s.name AS supplier_name, {_SOURCE_FACTS}
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

    # ------------------------------------------------- operators & sessions

    def upsert_operator_manual(self, row: dict[str, Any]) -> str:
        """Write an account that lives only on this PC (`make operator`).

        Refuses to touch a row AutoERP owns: backoffice owns those passwords, and a
        change made here would be silently undone by the next pull — worse than being
        told no, because the operator would believe the new password works.
        """
        return self._upsert_operator(
            row, origin="lokal", overwrite_origin=("lokal",), always_end_session=True
        )

    def upsert_operator_erp(self, row: dict[str, Any]) -> str:
        """Apply one `AutoGrade Operator` document from the §4.A pull.

        Refuses to touch a local row. The support and built-in accounts exist so a mill
        with no internet can be opened at all; a pull that flattened them would take
        that away at exactly the moment it is needed.
        """
        return self._upsert_operator(row, origin="erp", overwrite_origin=("erp",))

    def _upsert_operator(
        self,
        row: dict[str, Any],
        *,
        origin: str,
        overwrite_origin: tuple[str, ...],
        always_end_session: bool = False,
    ) -> str:
        """Add or update one account, id derived from the email.

        Deriving the id means both sources land on the same row for one person instead
        of beside each other — the same adoption trick as trucks (§4.B). `active` is
        AutoERP's word for it and `status` is ours; the pull passes the former.
        """
        email = normalise_email(row["email"])
        operator_id = operator_id_for(email)
        status = row.get("status") or ("active" if row.get("active", 1) else "off")
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT origin, password_hash, status, role FROM operators WHERE id = ?",
                (operator_id,),
            ).fetchone()
            if existing and existing["origin"] not in overwrite_origin:
                return operator_id
            # Only an ERP row sets `role` here, via the allow-list. Otherwise keep
            # the existing role — overwriting it would erase a local account's role
            # every time `make operator` resets its password.
            if origin == "erp":
                role = filter_erp_role(row.get("role"), self._erp_allowed_roles)
            elif existing is not None:
                role = existing["role"]
            else:
                role = sanitize_role(row.get("role"))
            # Worked out before the write, while the old row is still readable.
            end_session = always_end_session or existing is None or any(
                existing[column] != new_value
                for column, new_value in (
                    ("password_hash", row["password_hash"]),
                    ("status", status),
                )
            )
            self._db.execute(
                """INSERT INTO operators
                       (id, email, full_name, password_hash, status, origin, erp_name, role, created_at)
                   VALUES (:id, :email, :full_name, :password_hash, :status, :origin, :erp_name, :role, :created_at)
                   ON CONFLICT(id) DO UPDATE SET
                       email          = excluded.email,
                       full_name      = excluded.full_name,
                       password_hash  = excluded.password_hash,
                       status         = excluded.status,
                       origin         = excluded.origin,
                       erp_name       = excluded.erp_name,
                       role           = excluded.role,
                       fail_count     = 0,
                       last_failed_at = NULL""",
                {
                    "id": operator_id,
                    "email": email,
                    "full_name": normalise_nama(row.get("full_name") or email),
                    "password_hash": row["password_hash"],
                    "status": status,
                    "origin": origin,
                    "role": role,
                    "erp_name": row.get("erp_name"),
                    "created_at": time.time(),
                },
            )
            # A new password, or an account switched off by a pull: every session opened
            # before it ends. A password is reset because someone saw it, and a session
            # that outlives the reset would make it a formality.
            #
            # But ONLY then. A pull re-reads unchanged rows by design (`_rewind` steps
            # back a few seconds because two clocks never agree), so deleting here
            # unconditionally signed the operator out on every sync — every 5 minutes at
            # the mill, with the screen blaming an expired session. Seen in a browser
            # 2026-09-15.
            if end_session:
                self._db.execute("DELETE FROM sesi WHERE operator_id = ?", (operator_id,))
        return operator_id

    def operator(self, operator_id: str) -> dict[str, Any] | None:
        """The whole row, hash included — for checking a password, and nothing else."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        return dict(row) if row else None

    def operator_by_email(self, email: str) -> dict[str, Any] | None:
        """Sign-in has an email, not an id. Kept here rather than derived by the caller
        so the normalisation rule stays in one place."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM operators WHERE email = ?", (normalise_email(email),)
            ).fetchone()
        return dict(row) if row else None

    def operators(self) -> list[dict[str, Any]]:
        """What the sign-in screen may show before anyone is in: active accounts, no
        hashes. Whatever this returns is readable by any unauthenticated page."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, email, full_name, status, origin FROM operators "
                "WHERE status = 'active' ORDER BY full_name"
            ).fetchall()
        return [dict(row) for row in rows]

    def has_support_account(self) -> bool:
        """Whether any active account can reach the developer screens.

        Existence check in SQL, not a Python loop over `operators()`: the
        lifespan asks this once at every startup, and a mill can carry years
        of accounts by then.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM operators WHERE role = ? AND status = 'active' LIMIT 1",
                (ROLE_SUPPORT,),
            ).fetchone()
        return row is not None

    def set_operator_status(self, operator_id: str, status: str) -> None:
        """`off` takes the account off the sign-in screen and ends the sessions it still
        holds — that is how a leaver or a shared password is handled.

        The sessions are deleted, not just filtered out by `session()`: filtering alone
        would hand an old, unexpired token its power back the moment the account is
        switched on again.
        """
        with self._lock, self._db:
            self._db.execute("UPDATE operators SET status = ? WHERE id = ?", (status, operator_id))
            if status != "active":
                self._db.execute("DELETE FROM sesi WHERE operator_id = ?", (operator_id,))

    def set_role(self, operator_id: str, role: str) -> None:
        """Set one account's role. An unknown value is stored as `operator`,
        not trusted from the caller — this column gates the piston screen."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET role = ? WHERE id = ?",
                (sanitize_role(role), operator_id),
            )

    def record_login_failure(self, operator_id: str, *, now: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET fail_count = fail_count + 1, last_failed_at = ? "
                "WHERE id = ?",
                (now, operator_id),
            )

    def clear_login_failures(self, operator_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET fail_count = 0, last_failed_at = NULL WHERE id = ?",
                (operator_id,),
            )

    def create_session(self, token: str, operator_id: str, *, now: float, ttl_s: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO sesi (token, operator_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token, operator_id, now, now + ttl_s),
            )

    def session(self, token: str, *, now: float) -> dict[str, Any] | None:
        """Who is behind a token — None when it is unknown, expired, or the operator
        has been switched off since."""
        with self._lock:
            row = self._db.execute(
                """SELECT s.operator_id, s.expires_at, o.full_name, o.email, o.origin, o.role
                     FROM sesi s JOIN operators o ON o.id = s.operator_id
                    WHERE s.token = ? AND s.expires_at > ? AND o.status = 'active'""",
                (token, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sesi WHERE token = ?", (token,))

    def purge_sessions(self, *, now: float) -> int:
        """Sweep what has expired; returns how many rows went."""
        with self._lock, self._db:
            cursor = self._db.execute("DELETE FROM sesi WHERE expires_at <= ?", (now,))
        return cursor.rowcount
