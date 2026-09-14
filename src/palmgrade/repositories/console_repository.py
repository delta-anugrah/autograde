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

from ..domain.operator_auth import operator_id_for

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS inspections (
    event_id            TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    line_code           TEXT NOT NULL,
    tanggal_kerja       TEXT NOT NULL,
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
    tp_status           TEXT,
    tp_confidence       REAL,
    -- Unused since the per-bunch push was dropped: AutoERP takes one message
    -- per truck visit. Kept so factory databases need no table rebuild.
    erp_state           TEXT
);
CREATE INDEX IF NOT EXISTS idx_inspections_hari ON inspections (tanggal_kerja, line_code);
CREATE INDEX IF NOT EXISTS idx_inspections_urut ON inspections (tanggal_kerja, timestamp DESC);

CREATE TABLE IF NOT EXISTS suppliers (
    id     TEXT PRIMARY KEY,
    name   TEXT,
    sumber TEXT,
    status TEXT,
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

-- Weighbridge (§3.5c). Filled by the scale program via
-- POST /internal/scale/weighing; its format is unknown (X1), so the lane is
-- built in OUR shape and only an adapter is added later.
-- `neto_kg` never arrives from outside as-is — it is computed in the service.
CREATE TABLE IF NOT EXISTS weighings (
    id            TEXT PRIMARY KEY,
    ref           TEXT,
    plate_number  TEXT,
    plate_norm    TEXT,
    truck_id      TEXT,
    tanggal_kerja TEXT NOT NULL,
    bruto_kg      REAL,
    tara_kg       REAL,
    neto_kg       REAL,
    waktu_masuk   TEXT,
    waktu_keluar  TEXT,
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
CREATE INDEX IF NOT EXISTS idx_weighings_hari ON weighings (tanggal_kerja, waktu_masuk DESC);
CREATE INDEX IF NOT EXISTS idx_weighings_plat ON weighings (plate_norm);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Operator accounts for the console login (Fase 4). Local on purpose: AutoERP has no
-- operator DocType, and an operator must get in while the internet is down.
CREATE TABLE IF NOT EXISTS operators (
    id             TEXT PRIMARY KEY,
    nama           TEXT NOT NULL UNIQUE,
    pin_hash       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    -- Reserved for the day AutoERP grows that DocType: these rows then have
    -- somewhere to point and the pull needs no table rebuild.
    erp_name       TEXT,
    dibuat_at      REAL NOT NULL,
    -- Wrong-PIN counter, on disk so reloading the page cannot reset the lockout.
    gagal_count    INTEGER NOT NULL DEFAULT 0,
    gagal_terakhir REAL
);

CREATE TABLE IF NOT EXISTS sesi (
    token          TEXT PRIMARY KEY,
    operator_id    TEXT NOT NULL,
    dibuat_at      REAL NOT NULL,
    kedaluwarsa_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sesi_kedaluwarsa ON sesi (kedaluwarsa_at);
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
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)
            self._migrate()

    def _migrate(self) -> None:
        """Add what a console older than this build has not got.

        `CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it is,
        so a new column never reaches a factory database through the schema
        above — it needs its own pass, and the index that depends on it has to
        wait until the column exists.
        """
        for table, column in (
            ("suppliers", "erp_name"),
            ("trucks", "erp_name"),
            ("weighings", "assignment_id"),
            ("weighings", "erp_ticket"),
            ("weighings", "erp_status"),
            ("weighings", "erp_note"),
        ):
            kolom = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in kolom:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        self._db.executescript(_MIGRATE_SQL)

    # -------------------------------------------------------- inspections

    def add_inspection(self, row: dict[str, Any]) -> None:
        """Idempotent: a line resends the same event after an outbox retry.

        The dedupe key `event_id` = uuid5(machine_id, file_ts) — the same frozen
        formula palmgrade-api uses, so one bunch is never counted twice.
        """
        with self._lock, self._db:
            self._db.execute(
                """INSERT OR IGNORE INTO inspections (
                       event_id, machine_id, line_code, tanggal_kerja, timestamp,
                       ripeness_status, ripeness_confidence, capture_type,
                       image_path, truck_id, assignment_id, received_at, prediction,
                       tp_status, tp_confidence)
                   VALUES (:event_id, :machine_id, :line_code, :tanggal_kerja, :timestamp,
                           :ripeness_status, :ripeness_confidence, :capture_type,
                           :image_path, :truck_id, :assignment_id, :received_at, :prediction,
                           :tp_status, :tp_confidence)""",
                {**row, "received_at": time.time()},
            )

    def summary(self, tanggal_kerja: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT line_code,
                          COUNT(*) AS total,
                          SUM(CASE WHEN ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
                          SUM(CASE WHEN ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej
                   FROM inspections WHERE tanggal_kerja = ? GROUP BY line_code""",
                (tanggal_kerja,),
            ).fetchall()
        return [dict(r) for r in rows]

    def inspections(
        self,
        tanggal_kerja: str,
        *,
        line_code: str | None = None,
        truck_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["i.tanggal_kerja = ?"]
        params: list[Any] = [tanggal_kerja]
        if line_code:
            where.append("i.line_code = ?")
            params.append(line_code)
        if truck_id:
            where.append("i.truck_id = ?")
            params.append(truck_id)
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

    def rekap_truk(self, tanggal_kerja: str) -> list[dict[str, Any]]:
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
                          MIN(i.timestamp) AS mulai,
                          MAX(i.timestamp) AS selesai
                   FROM inspections i
                   LEFT JOIN trucks t ON t.id = i.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE i.tanggal_kerja = ?
                   GROUP BY i.truck_id
                   ORDER BY MAX(i.timestamp) DESC""",
                (tanggal_kerja,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- master data

    def upsert_supplier(self, row: dict[str, Any]) -> None:
        # Cloud always wins (§3.4): no `updated_at` condition, because the
        # cloud's set_updated_at trigger once froze rows forever in edge sync.
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO suppliers (id, name, sumber, status, erp_name)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                       sumber=excluded.sumber, status=excluded.status,
                       erp_name=excluded.erp_name""",
                (
                    str(row["id"]),
                    row.get("name"),
                    row.get("sumber"),
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
                       id, ref, plate_number, plate_norm, truck_id, tanggal_kerja,
                       bruto_kg, tara_kg, neto_kg, waktu_masuk, waktu_keluar, received_at)
                   VALUES (:id, :ref, :plate_number, :plate_norm, :truck_id, :tanggal_kerja,
                           :bruto_kg, :tara_kg, :neto_kg, :waktu_masuk, :waktu_keluar, :received_at)
                   ON CONFLICT(id) DO UPDATE SET
                       ref           = COALESCE(excluded.ref, weighings.ref),
                       plate_number  = COALESCE(excluded.plate_number, weighings.plate_number),
                       plate_norm    = COALESCE(excluded.plate_norm, weighings.plate_norm),
                       truck_id      = COALESCE(excluded.truck_id, weighings.truck_id),
                       bruto_kg      = COALESCE(excluded.bruto_kg, weighings.bruto_kg),
                       tara_kg       = COALESCE(excluded.tara_kg, weighings.tara_kg),
                       neto_kg       = COALESCE(excluded.neto_kg, weighings.neto_kg),
                       waktu_masuk   = COALESCE(excluded.waktu_masuk, weighings.waktu_masuk),
                       waktu_keluar  = COALESCE(excluded.waktu_keluar, weighings.waktu_keluar)""",
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

        Criteria mapping: mentah is REJ, tangkai panjang an ACC the line marked
        with `tp_confidence > 0.8`, matang the rest — AutoERP derives that one.
        None when the assignment graded nothing: there is no summary to send.
        """
        with self._lock:
            row = self._db.execute(
                """SELECT COUNT(*) AS total,
                          MIN(line_code) AS line_code,
                          SUM(CASE WHEN ripeness_status = 'ACC' THEN 1 ELSE 0 END) AS acc,
                          SUM(CASE WHEN ripeness_status = 'REJ' THEN 1 ELSE 0 END) AS rej,
                          SUM(CASE WHEN ripeness_status = 'ACC' AND tp_confidence > 0.8
                                   THEN 1 ELSE 0 END) AS tangkai_panjang,
                          SUM(CASE WHEN capture_type = 'manual' THEN 1 ELSE 0 END) AS manual_reject,
                          MIN(timestamp) AS mulai,
                          MAX(timestamp) AS selesai
                   FROM inspections WHERE assignment_id = ?""",
                (assignment_id,),
            ).fetchone()
        if not row or not row["total"]:
            return None
        return {"assignment_id": assignment_id, **dict(row)}

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

    def latest_weighing_for_truck(self, truck_id: str, tanggal_kerja: str) -> str | None:
        """The visit a truck's grading belongs to: its newest ticket that day."""
        with self._lock:
            row = self._db.execute(
                """SELECT id FROM weighings
                   WHERE truck_id = ? AND tanggal_kerja = ?
                   ORDER BY COALESCE(waktu_masuk, '') DESC, received_at DESC LIMIT 1""",
                (truck_id, tanggal_kerja),
            ).fetchone()
        return row["id"] if row else None

    def weighing_ids_on(self, tanggal_kerja: str) -> list[str]:
        """Every visit of one working day, oldest first (the daily resend)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id FROM weighings WHERE tanggal_kerja = ? ORDER BY received_at",
                (tanggal_kerja,),
            ).fetchall()
        return [row["id"] for row in rows]

    def weighing(self, weighing_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM weighings WHERE id = ?", (weighing_id,)).fetchone()
        return dict(row) if row else None

    def weighings(self, tanggal_kerja: str, *, limit: int = 100) -> list[dict[str, Any]]:
        # ponytail: joins on `truck_id` only, so a cloud-synced truck (id from
        # the cloud, not uuid5 of the plate) shows no name yet. Good enough
        # until the ERP lane is live — see docs/PERTANYAAN-TERBUKA.md S1-S3.
        with self._lock:
            rows = self._db.execute(
                f"""SELECT w.*, s.name AS supplier_name, {_SOURCE_FACTS}
                   FROM weighings w
                   LEFT JOIN trucks t ON t.id = w.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE w.tanggal_kerja = ?
                   ORDER BY w.waktu_masuk DESC, w.received_at DESC LIMIT ?""",
                (tanggal_kerja, limit),
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

    def upsert_operator(self, row: dict[str, Any]) -> str:
        """Add an operator, or reset the PIN of the one already holding that name.

        Idempotent by name, because the id is derived from it: running the operator
        command twice cannot leave two people sharing one face on the keypad. A reset
        also clears the lockout — that is what makes it a way back in.
        """
        operator_id = operator_id_for(row["nama"])
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO operators (id, nama, pin_hash, status, erp_name, dibuat_at)
                   VALUES (:id, :nama, :pin_hash, :status, :erp_name, :dibuat_at)
                   ON CONFLICT(id) DO UPDATE SET
                       nama           = excluded.nama,
                       pin_hash       = excluded.pin_hash,
                       status         = excluded.status,
                       gagal_count    = 0,
                       gagal_terakhir = NULL""",
                {
                    "id": operator_id,
                    "nama": " ".join(str(row["nama"]).split()),
                    "pin_hash": row["pin_hash"],
                    "status": row.get("status") or "active",
                    "erp_name": row.get("erp_name"),
                    "dibuat_at": time.time(),
                },
            )
        return operator_id

    def operator(self, operator_id: str) -> dict[str, Any] | None:
        """The whole row, hash included — for checking a PIN, and nothing else."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        return dict(row) if row else None

    def operators(self) -> list[dict[str, Any]]:
        """What the keypad may show before anyone is signed in: active names, no hashes."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, nama, status FROM operators WHERE status = 'active' ORDER BY nama"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_operator_status(self, operator_id: str, status: str) -> None:
        """`off` takes the name off the keypad, and `session()` drops the sessions it
        still holds — that is how a leaver or a shared PIN is handled."""
        with self._lock, self._db:
            self._db.execute("UPDATE operators SET status = ? WHERE id = ?", (status, operator_id))

    def record_login_failure(self, operator_id: str, *, now: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET gagal_count = gagal_count + 1, gagal_terakhir = ? "
                "WHERE id = ?",
                (now, operator_id),
            )

    def clear_login_failures(self, operator_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET gagal_count = 0, gagal_terakhir = NULL WHERE id = ?",
                (operator_id,),
            )

    def create_session(self, token: str, operator_id: str, *, now: float, ttl_s: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO sesi (token, operator_id, dibuat_at, kedaluwarsa_at) "
                "VALUES (?, ?, ?, ?)",
                (token, operator_id, now, now + ttl_s),
            )

    def session(self, token: str, *, now: float) -> dict[str, Any] | None:
        """Who is behind a token — None when it is unknown, expired, or the operator
        has been switched off since."""
        with self._lock:
            row = self._db.execute(
                """SELECT s.operator_id, s.kedaluwarsa_at, o.nama
                     FROM sesi s JOIN operators o ON o.id = s.operator_id
                    WHERE s.token = ? AND s.kedaluwarsa_at > ? AND o.status = 'active'""",
                (token, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sesi WHERE token = ?", (token,))

    def purge_sessions(self, *, now: float) -> int:
        """Sweep what has expired; returns how many rows went."""
        with self._lock, self._db:
            cursor = self._db.execute("DELETE FROM sesi WHERE kedaluwarsa_at <= ?", (now,))
        return cursor.rowcount
