"""`console.db` membawa nomor skema (`PRAGMA user_version`), batch 4.5.

Aturan B5/C3: migrasi aditif dan idempoten, image lama tetap bisa membuka berkas.
Nomor ini cuma penanda untuk launcher dan teknisi; migrasi tetap berbasis
`PRAGMA table_info`, jadi angka ini tidak pernah diturunkan.
"""
from __future__ import annotations

import sqlite3

from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.console_skema import _CREATE_SQL, VERSI_SKEMA, siapkan_skema


def _db(path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    return db


def _versi(path) -> int:
    db = sqlite3.connect(str(path))
    try:
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def test_versi_skema_dimulai_dari_satu():
    assert VERSI_SKEMA == 1


def test_db_baru_diberi_nomor_versi_skema(tmp_path):
    ConsoleStore(tmp_path / "console.db")
    assert _versi(tmp_path / "console.db") == VERSI_SKEMA


def test_aman_diulang(tmp_path):
    db = _db(tmp_path / "console.db")
    siapkan_skema(db)
    siapkan_skema(db)
    db.close()
    assert _versi(tmp_path / "console.db") == VERSI_SKEMA


def test_db_skema_lama_naik_dan_datanya_utuh(tmp_path):
    """Berkas dari build sebelum user_version (nilai 0, nama kolom lama)."""
    path = tmp_path / "lama.db"
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE weighings (id TEXT PRIMARY KEY, ref TEXT, plate_number TEXT,
            plate_norm TEXT, truck_id TEXT, tanggal_kerja TEXT, bruto_kg REAL,
            tara_kg REAL, neto_kg REAL, waktu_masuk TEXT, waktu_keluar TEXT,
            received_at REAL);
        CREATE TABLE inspections (event_id TEXT PRIMARY KEY, tanggal_kerja TEXT,
            line_code TEXT, timestamp TEXT);
        INSERT INTO weighings (id, plate_number, plate_norm, tanggal_kerja, bruto_kg,
            tara_kg, neto_kg, waktu_masuk, received_at)
        VALUES ('w1', 'BE 1 A', 'BE1A', '2026-09-15', 12480.0, 5120.0, 7360.0,
                '2026-09-15T08:00:00+07:00', 1.0);
        """
    )
    db.commit()
    db.close()
    assert _versi(path) == 0

    store = ConsoleStore(path)
    with store._lock:
        neto = store._db.execute("SELECT net_kg FROM weighings WHERE id = 'w1'").fetchone()[0]

    assert neto == 7360.0
    assert _versi(path) == VERSI_SKEMA


def test_nomor_dari_image_lebih_baru_tidak_diturunkan(tmp_path):
    """Rollback: image ini membuka berkas yang sudah dinaikkan image lebih baru."""
    path = tmp_path / "console.db"
    ConsoleStore(path)
    db = sqlite3.connect(str(path))
    db.execute(f"PRAGMA user_version = {VERSI_SKEMA + 5}")
    db.commit()
    db.close()

    store = ConsoleStore(path)
    with store._lock:
        tabel = {r["name"] for r in store._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "weighings" in tabel
    assert _versi(path) == VERSI_SKEMA + 5


def test_image_lama_tetap_membuka_berkas_bernomor(tmp_path):
    """Image sebelum PR ini cuma menjalankan `_CREATE_SQL` + migrasi berbasis kolom
    dan tidak pernah membaca user_version: berkas bernomor harus tetap terbuka utuh."""
    path = tmp_path / "console.db"
    ConsoleStore(path)

    db = sqlite3.connect(str(path))
    db.executescript(_CREATE_SQL)            # yang dijalankan image lama saat start
    cek = db.execute("PRAGMA quick_check").fetchone()[0]
    db.close()

    assert cek == "ok"
    assert _versi(path) == VERSI_SKEMA
