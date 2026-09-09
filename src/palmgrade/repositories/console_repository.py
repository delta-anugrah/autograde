"""Index SQLite konsol operator (§6.2 rencana PalmOS).

Konsol TIDAK BOLEH memindai direktori: tiga line menulis ribuan file per hari,
dan polling yang `listdir` tiap 2 detik akan menghabiskan disk I/O yang dipakai
grading. Semua yang dibaca layar operator datang dari index ini, yang ditulis
sekali saat event masuk.

Konvensi durability & locking mengikuti `integrations/outbox/outbox_store.py`
(WAL + synchronous=FULL + satu threading.Lock + INSERT OR IGNORE). Bebas
torch/cv2 supaya proses konsol tetap ringan dan bisa dites di CI.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

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
    received_at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspections_hari ON inspections (tanggal_kerja, line_code);
CREATE INDEX IF NOT EXISTS idx_inspections_urut ON inspections (tanggal_kerja, timestamp DESC);

CREATE TABLE IF NOT EXISTS suppliers (
    id     TEXT PRIMARY KEY,
    name   TEXT,
    sumber TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS trucks (
    id           TEXT PRIMARY KEY,
    plate_number TEXT,
    supplier_id  TEXT,
    capacity     REAL,
    status       TEXT
);
CREATE INDEX IF NOT EXISTS idx_trucks_plat ON trucks (plate_number);

CREATE TABLE IF NOT EXISTS assignments (
    line_code     TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    truck_id      TEXT,
    started_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


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

    # ---------------------------------------------------------- inspeksi

    def add_inspection(self, row: dict[str, Any]) -> None:
        """Idempoten: line mengirim ulang event yang sama setelah retry outbox.

        Kunci dedupe `event_id` = uuid5(machine_id, file_ts) — rumus beku yang
        sama dipakai palmgrade-api, jadi satu tandan tidak pernah dihitung dua kali.
        """
        with self._lock, self._db:
            self._db.execute(
                """INSERT OR IGNORE INTO inspections (
                       event_id, machine_id, line_code, tanggal_kerja, timestamp,
                       ripeness_status, ripeness_confidence, capture_type,
                       image_path, truck_id, assignment_id, received_at)
                   VALUES (:event_id, :machine_id, :line_code, :tanggal_kerja, :timestamp,
                           :ripeness_status, :ripeness_confidence, :capture_type,
                           :image_path, :truck_id, :assignment_id, :received_at)""",
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
                f"""SELECT i.*, t.plate_number, s.name AS supplier_name, s.sumber
                    FROM inspections i
                    LEFT JOIN trucks t ON t.id = i.truck_id
                    LEFT JOIN suppliers s ON s.id = t.supplier_id
                    WHERE {' AND '.join(where)}
                    ORDER BY i.timestamp DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- master data

    def upsert_supplier(self, row: dict[str, Any]) -> None:
        # Cloud selalu menang (§3.4): tanpa syarat `updated_at`, karena trigger
        # set_updated_at di cloud pernah mengunci baris permanen di edge sync.
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO suppliers (id, name, sumber, status) VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                       sumber=excluded.sumber, status=excluded.status""",
                (str(row["id"]), row.get("name"), row.get("sumber"), row.get("status")),
            )

    def upsert_truck(self, row: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO trucks (id, plate_number, supplier_id, capacity, status)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET plate_number=excluded.plate_number,
                       supplier_id=excluded.supplier_id, capacity=excluded.capacity,
                       status=excluded.status""",
                (
                    str(row["id"]),
                    row.get("plate_number"),
                    str(row["supplier_id"]) if row.get("supplier_id") else None,
                    row.get("capacity"),
                    row.get("status"),
                ),
            )

    def trucks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT t.id, t.plate_number, t.capacity, t.status,
                          s.name AS supplier_name, s.sumber
                   FROM trucks t LEFT JOIN suppliers s ON s.id = t.supplier_id
                   WHERE t.status IS NULL OR t.status != 'inactive'
                   ORDER BY t.plate_number"""
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
                """SELECT a.*, t.plate_number, s.name AS supplier_name, s.sumber
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
