"""Hapus data di SQLite konsol — `ConsoleStore`, `ErpOutboxStore`, `LogStore`.

Yang paling penting di sini adalah yang TETAP: mode transaksi tidak boleh
menyentuh truk, akun, dan sesi; kedua mode tidak boleh menyentuh setelan
grading/rekam. Setelan yang diam-diam kembali ke `.env` mengubah angka yang
dibayar tanpa ada yang sadar.
"""
from __future__ import annotations

import time

import pytest

from palmgrade.domain.bahaya import MODE_SEMUA, MODE_TRANSAKSI
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore

SEKARANG = time.time()


def _isi(store: ConsoleStore) -> None:
    """Satu baris di tiap tabel, lewat SQL mentah: yang diuji penghapusnya,
    bukan jalur tulisnya — dan tabel baru yang dilupakan `_isi` akan ketahuan
    di `test_semua_tabel_konsol_digolongkan`."""
    db = store._db
    with store._lock, db:
        db.execute(
            "INSERT INTO inspections (event_id, machine_id, line_code, work_date, timestamp, "
            "ripeness_status, capture_type, received_at) VALUES ('e1', 'm', 'line-1', "
            "'2026-09-25', '2026-09-25T01:00:00Z', 'ACC', 'auto', ?)", (SEKARANG,),
        )
        db.execute("INSERT INTO suppliers (id, name) VALUES ('s1', 'Tani')")
        db.execute("INSERT INTO trucks (id, plate_number) VALUES ('t1', 'B1234XY')")
        db.execute(
            "INSERT INTO assignments (line_code, assignment_id, truck_id, started_at) "
            "VALUES ('line-1', 'a1', 't1', ?)", (SEKARANG,),
        )
        db.execute(
            "INSERT INTO auto_releases (line_code, truck_id, released_at) VALUES ('line-1', 't1', ?)",
            (SEKARANG,),
        )
        db.execute(
            "INSERT INTO weighings (id, plate_number, work_date, received_at) "
            "VALUES ('w1', 'B1234XY', '2026-09-25', ?)", (SEKARANG,),
        )
    store.set_state("setelan_grading", '{"conf_threshold": 0.6}')
    store.set_state("setelan_rekam", '{"width": 640}')
    store.set_state("erp_cursor_truck", "2026-09-25 01:00:00")
    store.set_state("erp_visit_resend_day", "2026-09-24")
    oid = store.upsert_operator_manual(
        {"email": "ani@pks.id", "full_name": "Ani", "password_hash": hash_password("sandi-uji-1")}
    )
    store.create_session("tok", oid, now=SEKARANG, ttl_s=3600)


def _hitung(store: ConsoleStore, tabel: str) -> int:
    with store._lock:
        return store._db.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]


@pytest.fixture
def store(tmp_path):
    s = ConsoleStore(tmp_path / "console.db")
    _isi(s)
    return s


def test_mode_transaksi(store):
    hasil = store.hapus_data(MODE_TRANSAKSI)

    for tabel in ("inspections", "assignments", "auto_releases", "weighings"):
        assert _hitung(store, tabel) == 0, tabel
    for tabel in ("trucks", "suppliers", "operators", "sesi"):
        assert _hitung(store, tabel) == 1, tabel
    assert store.get_state("setelan_grading") == '{"conf_threshold": 0.6}'
    assert store.get_state("setelan_rekam") == '{"width": 640}'
    assert store.get_state("erp_cursor_truck") == "2026-09-25 01:00:00"
    assert store.get_state("erp_visit_resend_day") is None
    assert hasil["inspections"] == 1
    assert hasil["weighings"] == 1
    assert hasil["sync_state"] == 1


def test_mode_semua(store):
    hasil = store.hapus_data(MODE_SEMUA)

    for tabel in ("inspections", "assignments", "auto_releases", "weighings", "trucks",
                  "suppliers", "operators", "sesi"):
        assert _hitung(store, tabel) == 0, tabel
    assert store.get_state("setelan_grading") == '{"conf_threshold": 0.6}'
    assert store.get_state("setelan_rekam") == '{"width": 640}'
    assert store.get_state("erp_cursor_truck") is None
    assert hasil["operators"] == 1
    assert hasil["sesi"] == 1
    assert hasil["sync_state"] == 2


def test_mode_asing_tidak_menghapus_apa_pun(store):
    with pytest.raises(ValueError):
        store.hapus_data("semuanya")
    assert _hitung(store, "inspections") == 1


def test_ringkas_data(store):
    ringkas = store.ringkas_data(now=SEKARANG)
    assert ringkas == {
        "janjang": 1, "tiket": 1, "truk": 1, "akun": 1, "akun_lokal": 1, "sesi_aktif": 1,
    }


def test_ringkas_tidak_menghitung_sesi_kedaluwarsa(store):
    assert store.ringkas_data(now=SEKARANG + 7200)["sesi_aktif"] == 0


def test_hapus_semua_sesi(store):
    assert store.hapus_semua_sesi() == 1
    assert _hitung(store, "sesi") == 0
    assert _hitung(store, "operators") == 1


def test_outbox_hapus_semua(tmp_path):
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    outbox.enqueue("visit", "k1", {"a": 1})
    outbox.enqueue("truck", "k2", {"b": 2})

    assert outbox.hapus_semua() == 2
    assert outbox.pending_count() == 0


def test_log_hapus_semua(tmp_path):
    log = LogStore(tmp_path / "log.db")
    log.write("ERROR", "uji", "pesan satu", None, now=SEKARANG)
    log.write("WARNING", "uji", "pesan dua", None, now=SEKARANG)

    assert log.hapus_semua() == 2
    assert log.read(level=None, search=None, limit=10, offset=0)["total"] == 0


def test_db_antrean_dan_log_konsol_cuma_berisi_tabel_yang_dikosongkan(tmp_path):
    """M-9: `hapus_semua()` mengosongkan SATU tabel per berkas. Tabel kedua di
    salah satu berkas ini akan selamat diam-diam dari "hapus semua data"."""
    import sqlite3

    def tabel(db) -> set[str]:
        con = sqlite3.connect(db)
        try:
            return {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
        finally:
            con.close()

    ErpOutboxStore(tmp_path / "erp_outbox.db")
    LogStore(tmp_path / "log.db")
    assert tabel(tmp_path / "erp_outbox.db") == {"erp_outbox"}
    assert tabel(tmp_path / "log.db") == {"event_log"}
