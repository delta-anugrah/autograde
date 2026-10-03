"""Penyimpanan jam gerbang: tabel `arrivals` dan kolom `weighings.left_at`."""
from __future__ import annotations

import sqlite3

from palmgrade.domain.bahaya import GOLONGAN_TABEL_KONSOL
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore

HARI = "2026-09-30"


def _kolom(db_path, tabel: str) -> set[str]:
    with sqlite3.connect(db_path) as db:
        return {r[1] for r in db.execute(f"PRAGMA table_info({tabel})")}


def _tiket(store, id_, *, truck="t1", tara=None, masuk=f"{HARI}T01:00:00+00:00", keluar=None):
    store.upsert_weighing({
        "id": id_, "ref": None, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
        "truck_id": truck, "work_date": HARI, "gross_kg": 12000.0, "tare_kg": tara,
        "net_kg": None if tara is None else 12000.0 - tara, "entered_at": masuk, "exited_at": keluar,
    })


def _datang(store, id_, *, truck="t1", jam=f"{HARI}T00:30:00+00:00", hari=HARI):
    store.record_arrival({"id": id_, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
                          "truck_id": truck, "work_date": hari, "arrived_at": jam})


def test_database_baru_punya_arrivals_dan_left_at(tmp_path):
    ConsoleStore(tmp_path / "console.db")
    assert {"id", "plate_number", "plate_norm", "truck_id", "work_date", "arrived_at",
            "weighing_id"} <= _kolom(tmp_path / "console.db", "arrivals")
    assert "left_at" in _kolom(tmp_path / "console.db", "weighings")


def test_database_lama_mendapat_left_at_tanpa_kehilangan_tiket(tmp_path):
    db_path = tmp_path / "console.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            """CREATE TABLE weighings (id TEXT PRIMARY KEY, ref TEXT, plate_number TEXT,
               plate_norm TEXT, truck_id TEXT, work_date TEXT NOT NULL, gross_kg REAL,
               tare_kg REAL, net_kg REAL, entered_at TEXT, exited_at TEXT, received_at REAL NOT NULL)"""
        )
        db.execute("INSERT INTO weighings (id, work_date, gross_kg, received_at) VALUES ('lama', '2026-09-01', 14000, 0)")
    store = ConsoleStore(db_path)
    assert "left_at" in _kolom(db_path, "weighings")
    assert store.weighing("lama")["gross_kg"] == 14000


def test_arrivals_digolongkan_transaksi():
    assert GOLONGAN_TABEL_KONSOL["arrivals"] == "transaksi"


def test_kedatangan_sama_dua_kali_tetap_satu_baris(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _datang(store, "a1")
    _datang(store, "a1")
    assert [a["id"] for a in store.waiting_arrivals_for_truck("t1")] == ["a1"]


def test_klaim_memasangkan_kedatangan_ke_tiket(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1")
    _datang(store, "a1")
    assert store.claim_arrival("a1", "w1") is True
    assert store.waiting_arrivals_for_truck("t1") == []
    assert store.weighings(HARI)[0]["arrived_at"] == f"{HARI}T00:30:00+00:00"


def test_satu_kedatangan_satu_tiket_dua_arah(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1")
    _tiket(store, "w2", masuk=f"{HARI}T02:00:00+00:00")
    _datang(store, "a1")
    _datang(store, "a2", jam=f"{HARI}T00:40:00+00:00")
    assert store.claim_arrival("a1", "w1") is True
    assert store.claim_arrival("a1", "w2") is False
    assert store.claim_arrival("a2", "w1") is False


def test_tiket_tanpa_kedatangan_arrived_at_kosong(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1")
    row = store.weighings(HARI)[0]
    assert row["arrived_at"] is None and row["left_at"] is None


def test_antrean_timbang_hari_ini_urut_tertua(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1")
    _datang(store, "sudah", jam=f"{HARI}T00:10:00+00:00")
    store.claim_arrival("sudah", "w1")
    _datang(store, "b", truck="t2", jam=f"{HARI}T00:50:00+00:00")
    _datang(store, "a", truck="t3", jam=f"{HARI}T00:20:00+00:00")
    _datang(store, "kemarin", truck="t4", jam="2026-09-29T00:20:00+00:00", hari="2026-09-29")
    assert [r["arrived_at"] for r in store.waiting_arrivals(HARI)] == [
        f"{HARI}T00:20:00+00:00", f"{HARI}T00:50:00+00:00",
    ]


def test_left_at_cuma_untuk_tiket_yang_sudah_timbang_kosong(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "terbuka")
    _tiket(store, "selesai", tara=5000.0, keluar=f"{HARI}T02:00:00+00:00")
    assert store.set_left_at("terbuka", f"{HARI}T02:10:00+00:00") is False
    assert store.set_left_at("selesai", f"{HARI}T02:10:00+00:00") is True
    assert store.set_left_at("selesai", f"{HARI}T03:00:00+00:00") is False


def test_timbang_ulang_tidak_menghapus_left_at(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", tara=5000.0, keluar=f"{HARI}T02:00:00+00:00")
    store.set_left_at("w1", f"{HARI}T02:10:00+00:00")
    _tiket(store, "w1", tara=5000.0, keluar=f"{HARI}T02:00:00+00:00")
    assert store.weighing("w1")["left_at"] == f"{HARI}T02:10:00+00:00"


def test_tiket_per_truk_terbaru_dulu(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1")
    _tiket(store, "w2", masuk=f"{HARI}T02:00:00+00:00")
    _tiket(store, "lain", truck="t9")
    assert [r["id"] for r in store.weighings_for_truck("t1")] == ["w2", "w1"]


def test_rekonsiliasi_truk_ikut_memindahkan_kedatangan(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_truck({"id": "acak-lama", "plate_number": "BE 1 AA", "status": "active"})
    _datang(store, "a1", truck="acak-lama")
    store.pindahkan_truk("acak-lama", truck_id_for("BE 1 AA"))
    assert store.arrival("a1")["truck_id"] == truck_id_for("BE 1 AA")


def test_buka_dua_kali_tidak_mengubah_isi(tmp_path):
    """Migrasi saat boot aman diulang: kedatangan yang menunggu dan jam keluar tetap utuh."""
    db_path = tmp_path / "console.db"
    store = ConsoleStore(db_path)
    _tiket(store, "w1", tara=5000.0, keluar=f"{HARI}T02:00:00+00:00")
    store.set_left_at("w1", f"{HARI}T02:10:00+00:00")
    _datang(store, "a1", truck="t2")
    store._db.close()

    lagi = ConsoleStore(db_path)

    assert lagi.weighing("w1")["left_at"] == f"{HARI}T02:10:00+00:00"
    assert [a["id"] for a in lagi.waiting_arrivals_for_truck("t2")] == ["a1"]


# ── review fixes (Task 11) ───────────────────────────────────────────────────


def test_kedatangan_menunggu_diurut_tertua_dulu(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _datang(store, "c", jam=f"{HARI}T00:50:00+00:00")
    _datang(store, "a", jam=f"{HARI}T00:10:00+00:00")
    _datang(store, "b", jam=f"{HARI}T00:30:00+00:00")
    assert [a["id"] for a in store.waiting_arrivals_for_truck("t1")] == ["a", "b", "c"]


def test_kedatangan_tidak_boleh_dipasangkan_ke_tiket_truk_lain(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w-lain", truck="t2")
    _datang(store, "a1", truck="t1")
    assert store.claim_arrival("a1", "w-lain") is False
    assert [a["id"] for a in store.waiting_arrivals_for_truck("t1")] == ["a1"]
    _tiket(store, "w1", truck="t1")
    assert store.claim_arrival("a1", "w1") is True


def test_kedatangan_tidak_dipasangkan_ke_tiket_yang_tidak_ada(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _datang(store, "a1")
    assert store.claim_arrival("a1", "hantu") is False


def test_hapus_transaksi_ikut_mengosongkan_kedatangan(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1")
    _datang(store, "a1")
    hasil = store.hapus_data("transaksi")
    assert hasil["arrivals"] == 1
    assert store.arrival("a1") is None
    assert store.waiting_arrivals_for_truck("t1") == []
