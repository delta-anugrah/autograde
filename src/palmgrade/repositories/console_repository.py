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
    received_at         REAL NOT NULL,
    -- Disimpan apa adanya dari line, TIDAK diturunkan ulang dari
    -- `ripeness_status`: ERP mewajibkan `prediction` dan menurunkannya di dua
    -- repo berarti dua aturan yang bisa berbeda tanpa ada yang tahu.
    prediction          TEXT,
    tp_status           TEXT,
    tp_confidence       REAL,
    -- NULL = belum didorong ke ERP · 'ok' = mendarat · 'tolak' = ditolak
    -- permanen (417). Tidak ada 'gagal': kegagalan sementara ditandai dengan
    -- TIDAK mengubah kolom ini, jadi tick berikutnya mengambilnya lagi.
    erp_state           TEXT
);
CREATE INDEX IF NOT EXISTS idx_inspections_hari ON inspections (tanggal_kerja, line_code);
CREATE INDEX IF NOT EXISTS idx_inspections_urut ON inspections (tanggal_kerja, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_inspections_erp ON inspections (erp_state, received_at);

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

-- Timbangan jembatan (§3.5c). Diisi oleh program timbangan lewat
-- POST /internal/scale/weighing; formatnya belum diketahui (X1), jadi jalurnya
-- disiapkan dalam bentuk KITA dan yang perlu ditambah nanti cuma adapter.
-- `neto_kg` tidak pernah datang dari luar begitu saja — dihitung di service.
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
    received_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weighings_hari ON weighings (tanggal_kerja, waktu_masuk DESC);
CREATE INDEX IF NOT EXISTS idx_weighings_plat ON weighings (plate_norm);

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

    # --------------------------------------------------------- timbangan

    def upsert_weighing(self, row: dict[str, Any]) -> None:
        """Idempoten per `id`, dan HANYA kolom terisi yang menimpa.

        Timbang-masuk mengirim bruto, timbang-keluar mengirim tara — dua POST
        untuk baris yang sama. Tanpa `COALESCE` kiriman kedua akan menimpa
        bruto dengan NULL dan neto ikut hilang. Ini jalur uang; jangan sampai.
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

    def weighing(self, weighing_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM weighings WHERE id = ?", (weighing_id,)).fetchone()
        return dict(row) if row else None

    def weighings(self, tanggal_kerja: str, *, limit: int = 100) -> list[dict[str, Any]]:
        # ponytail: join lewat `truck_id` saja, jadi truk hasil sinkron cloud
        # (id-nya dari cloud, bukan uuid5 plat) belum ikut ternama. Cukup sampai
        # jalur ERP hidup — lihat docs/PERTANYAAN-TERBUKA.md S1-S3.
        with self._lock:
            rows = self._db.execute(
                """SELECT w.*, s.name AS supplier_name, s.sumber
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
                """SELECT a.*, t.plate_number, s.name AS supplier_name, s.sumber
                   FROM assignments a
                   LEFT JOIN trucks t ON t.id = a.truck_id
                   LEFT JOIN suppliers s ON s.id = t.supplier_id"""
            ).fetchall()
        return {r["line_code"]: dict(r) for r in rows}

    # ------------------------------------------------------- sync cursor

    # ------------------------------------------------------- dorong ke ERP

    def belum_didorong(self, limit: int) -> list[dict[str, Any]]:
        """Event yang belum mendarat di ERP, tertua dulu.

        `ORDER BY received_at` bukan `timestamp`: yang dikejar urutan kedatangan,
        dan event yang nyusul berjam-jam setelah listrik balik tidak boleh
        menyelinap ke depan antrean.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM inspections WHERE erp_state IS NULL
                   ORDER BY received_at LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def tandai_erp(self, event_id: str, state: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE inspections SET erp_state = ? WHERE event_id = ?", (state, event_id)
            )

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
