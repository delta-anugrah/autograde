"""Riwayat Batal datang (user 2026-10-03, round 4): a cancelled arrival is kept, not deleted.

The row stays in `arrivals` with `cancelled_at` and `cancelled_by`; every reader of a
WAITING arrival skips it (waiting list, the claim on weigh-in, the "truck came back" trail),
and the Timbangan tab reads it back as the day's history of cancellations.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.gerbang import DIBATALKAN, TERCATAT, TIDAK_ADA, baca_waktu
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService

HARI = "2026-09-30"
JAM_BATAL = f"{HARI}T00:40:00+00:00"
OLEH = "operator@pks.test"


def _kolom(db_path, tabel: str) -> set[str]:
    with sqlite3.connect(db_path) as db:
        return {r[1] for r in db.execute(f"PRAGMA table_info({tabel})")}


def _datang(store, id_, *, truck="t1", plat="BE 1 AA", jam=f"{HARI}T00:30:00+00:00", hari=HARI):
    store.record_arrival({"id": id_, "plate_number": plat, "plate_norm": plat.replace(" ", ""),
                          "truck_id": truck, "work_date": hari, "arrived_at": jam})


def _tiket(store, id_, *, truck="t1", tara=None, masuk=f"{HARI}T01:00:00+00:00"):
    store.upsert_weighing({
        "id": id_, "ref": None, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
        "truck_id": truck, "work_date": HARI, "gross_kg": 12000.0, "tare_kg": tara,
        "net_kg": None if tara is None else 12000.0 - tara, "entered_at": masuk, "exited_at": None,
    })


@pytest.fixture
def store(tmp_path):
    return ConsoleStore(tmp_path / "console.db")


# ── schema ───────────────────────────────────────────────────────────────────


def test_database_baru_punya_kolom_batal(tmp_path):
    ConsoleStore(tmp_path / "console.db")
    assert {"cancelled_at", "cancelled_by", "cancelled_by_name"} <= _kolom(tmp_path / "console.db", "arrivals")


def test_database_versi_4_mendapat_kolom_batal_tanpa_kehilangan_kedatangan(tmp_path):
    """A console.db written by the round 3 image: `arrivals` without the two columns."""
    db_path = tmp_path / "console.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """CREATE TABLE arrivals (id TEXT PRIMARY KEY, plate_number TEXT NOT NULL,
                   plate_norm TEXT NOT NULL, truck_id TEXT NOT NULL, work_date TEXT NOT NULL,
                   arrived_at TEXT NOT NULL, weighing_id TEXT);
               INSERT INTO arrivals VALUES ('lama', 'BE 1 AA', 'BE1AA', 't1', '2026-09-30',
                   '2026-09-30T00:30:00+00:00', NULL);
               PRAGMA user_version = 4;"""
        )
    store = ConsoleStore(db_path)
    assert {"cancelled_at", "cancelled_by", "cancelled_by_name"} <= _kolom(db_path, "arrivals")
    assert [a["id"] for a in store.waiting_arrivals_for_truck("t1")] == ["lama"]
    assert store.arrival("lama")["cancelled_at"] is None


def test_database_versi_5_tanpa_nama_mendapat_kolomnya_dan_riwayat_lama_tetap(tmp_path):
    """A console.db from this branch before the name column (a developer's, never a release):
    already `user_version` 5, cancelled rows with the email only. The migration reads
    `table_info`, not the number, so the column still arrives and the old row keeps its
    email with no name."""
    db_path = tmp_path / "console.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            f"""CREATE TABLE arrivals (id TEXT PRIMARY KEY, plate_number TEXT NOT NULL,
                   plate_norm TEXT NOT NULL, truck_id TEXT NOT NULL, work_date TEXT NOT NULL,
                   arrived_at TEXT NOT NULL, weighing_id TEXT, cancelled_at TEXT, cancelled_by TEXT);
               INSERT INTO arrivals VALUES ('lama', 'BE 1 AA', 'BE1AA', 't1', '{HARI}',
                   '{HARI}T00:30:00+00:00', NULL, '{JAM_BATAL}', '{OLEH}');
               PRAGMA user_version = 5;"""
        )
    store = ConsoleStore(db_path)
    assert "cancelled_by_name" in _kolom(db_path, "arrivals")
    [r] = store.cancelled_arrivals(HARI)
    assert (r["cancelled_by"], r["cancelled_by_name"]) == (OLEH, None)


# ── store: cancel keeps the row ──────────────────────────────────────────────


def test_batal_menyimpan_baris_dengan_jam_dan_operator(store):
    _datang(store, "a1")
    row = store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    assert row is not None and row["plate_number"] == "BE 1 AA"
    simpan = store.arrival("a1")
    assert (simpan["cancelled_at"], simpan["cancelled_by"], simpan["weighing_id"]) == (JAM_BATAL, OLEH, None)


def test_batal_dua_kali_yang_kedua_none_dan_jam_pertama_tetap(store):
    _datang(store, "a1")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    assert store.cancel_arrival("a1", cancelled_at=f"{HARI}T05:00:00+00:00", cancelled_by="lain@pks.test") is None
    assert (store.arrival("a1")["cancelled_at"], store.arrival("a1")["cancelled_by"]) == (JAM_BATAL, OLEH)


def test_kedatangan_yang_sudah_diklaim_tidak_bisa_dibatalkan(store):
    _tiket(store, "w1")
    _datang(store, "a1")
    assert store.claim_arrival("a1", "w1") is True
    assert store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH) is None
    assert store.arrival("a1")["cancelled_at"] is None


def test_id_tak_dikenal_none(store):
    assert store.cancel_arrival("hantu", cancelled_at=JAM_BATAL, cancelled_by=OLEH) is None


# ── store: every reader of a waiting arrival skips a cancelled one ────────────


def test_menunggu_per_truk_melewati_yang_dibatalkan(store):
    _datang(store, "a1")
    _datang(store, "a2", jam=f"{HARI}T00:50:00+00:00")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    assert [a["id"] for a in store.waiting_arrivals_for_truck("t1")] == ["a2"]


def test_daftar_menunggu_melewati_yang_dibatalkan(store):
    _datang(store, "a1")
    _datang(store, "a2", truck="t2", plat="BE 2 BB")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    assert [a["id"] for a in store.waiting_arrivals(HARI)] == ["a2"]


def test_yang_dibatalkan_tidak_bisa_diklaim(store):
    _tiket(store, "w1")
    _datang(store, "a1")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    assert store.claim_arrival("a1", "w1") is False
    assert store.arrival("a1")["weighing_id"] is None


def test_jejak_truk_melewati_yang_dibatalkan(store):
    _datang(store, "a1")
    _datang(store, "a2", truck="t2", plat="BE 2 BB")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    jejak = store.jejak_truk(["t1", "t2"], HARI)
    assert "t1" not in jejak
    assert jejak["t2"] == [f"{HARI}T00:30:00+00:00"]


def test_tabel_timbangan_tidak_menempelkan_jam_datang_yang_dibatalkan(store):
    _datang(store, "a1")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    _tiket(store, "w1")
    [tiket] = store.weighings(HARI)
    assert tiket["arrived_at"] is None


def test_hapus_transaksi_ikut_mengosongkan_yang_dibatalkan(store):
    _datang(store, "a1")
    store.cancel_arrival("a1", cancelled_at=JAM_BATAL, cancelled_by=OLEH)
    assert store.hapus_data("transaksi")["arrivals"] == 1
    assert store.cancelled_arrivals(HARI) == []


# ── store: the day's history ─────────────────────────────────────────────────


def test_riwayat_batal_satu_hari_terbaru_dulu(store):
    _datang(store, "a1", jam=f"{HARI}T00:10:00+00:00")
    _datang(store, "a2", truck="t2", plat="BE 2 BB", jam=f"{HARI}T00:20:00+00:00")
    _datang(store, "a3", truck="t3", plat="BE 3 CC")  # still waiting: not history
    _datang(store, "a4", truck="t4", plat="BE 4 DD", hari="2026-09-29", jam="2026-09-29T03:00:00+00:00")
    store.cancel_arrival("a1", cancelled_at=f"{HARI}T00:50:00+00:00", cancelled_by=OLEH,
                         cancelled_by_name="Operator Gerbang")
    # Written by the seeder's offset: the real instant decides the order, not the text.
    store.cancel_arrival("a2", cancelled_at=f"{HARI}T07:45:00+07:00", cancelled_by="b@pks.test")
    store.cancel_arrival("a4", cancelled_at="2026-09-29T03:10:00+00:00", cancelled_by=OLEH)

    riwayat = store.cancelled_arrivals(HARI)
    assert [r["plate_number"] for r in riwayat] == ["BE 1 AA", "BE 2 BB"]
    assert set(riwayat[0]) == {"plate_number", "arrived_at", "cancelled_at", "cancelled_by", "cancelled_by_name"}
    assert riwayat[0] == {"plate_number": "BE 1 AA", "arrived_at": f"{HARI}T00:10:00+00:00",
                          "cancelled_at": f"{HARI}T00:50:00+00:00", "cancelled_by": OLEH,
                          "cancelled_by_name": "Operator Gerbang"}
    # No name given: stored as NULL, the email stays the identity.
    assert (riwayat[1]["cancelled_by"], riwayat[1]["cancelled_by_name"]) == ("b@pks.test", None)
    assert [r["plate_number"] for r in store.cancelled_arrivals("2026-09-29")] == ["BE 4 DD"]


# ── services ─────────────────────────────────────────────────────────────────


@pytest.fixture
def konsol(store):
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    return service, GateService(store, service.tz)


def test_gate_menulis_operator_dan_jam_server(konsol, store):
    service, gate = konsol
    gate.arrive("BE 7742 ZB", "2026-10-01T01:00:00Z")
    [a] = service.waiting_arrivals(baca_waktu("2026-10-01T01:05:00Z"))
    assert gate.cancel_arrival(a["id"], oleh=OLEH) == {"hasil": DIBATALKAN, "plate_number": "BE7742ZB"}
    simpan = store.arrival(a["id"])
    assert simpan["cancelled_by"] == OLEH
    assert baca_waktu(simpan["cancelled_at"]).tzinfo is not None
    assert gate.cancel_arrival(a["id"], oleh=OLEH) == {"hasil": TIDAK_ADA}


def test_datang_lagi_sesudah_batal_tercatat_baru(konsol):
    service, gate = konsol
    gate.arrive("BE 7742 ZB", "2026-10-01T01:00:00Z")
    [a] = service.waiting_arrivals(baca_waktu("2026-10-01T01:05:00Z"))
    gate.cancel_arrival(a["id"], oleh=OLEH)
    assert gate.arrive("BE 7742 ZB", "2026-10-01T01:10:00Z")["hasil"] == TERCATAT
    [baru] = service.waiting_arrivals(baca_waktu("2026-10-01T01:15:00Z"))
    assert baru["id"] != a["id"] and baru["arrived_at"] == "2026-10-01T01:10:00Z"


def test_layanan_riwayat_batal_hari_kerja(konsol):
    service, gate = konsol
    gate.arrive("BE 7742 ZB", "2026-10-01T01:00:00Z")  # 08:00 WIB, work date 2026-10-01
    [a] = service.waiting_arrivals(baca_waktu("2026-10-01T01:05:00Z"))
    gate.cancel_arrival(a["id"], oleh=OLEH)
    [r] = service.kedatangan_dibatalkan("2026-10-01")
    assert (r["plate_number"], r["arrived_at"], r["cancelled_by"]) == ("BE7742ZB", "2026-10-01T01:00:00Z", OLEH)
    assert r["cancelled_by_name"] is None
    assert service.kedatangan_dibatalkan("2026-10-02") == []


def test_nama_operator_disimpan_saat_batal_dan_bertahan_sesudah_akun_dihapus(konsol, store):
    """The name is a snapshot (user 2026-10-03): renaming or deleting the account later does
    not change who the history says pressed the button. The email stays next to it."""
    service, gate = konsol
    store.upsert_operator_manual({"email": OLEH, "full_name": "Budi Santoso", "password_hash": "x"})
    gate.arrive("BE 7742 ZB", "2026-10-01T01:00:00Z")
    [a] = service.waiting_arrivals(baca_waktu("2026-10-01T01:05:00Z"))
    gate.cancel_arrival(a["id"], oleh=OLEH, nama="  Budi   Santoso ")

    store.upsert_operator_manual({"email": OLEH, "full_name": "Nama Baru", "password_hash": "x"})
    [r] = service.kedatangan_dibatalkan("2026-10-01")
    assert (r["cancelled_by"], r["cancelled_by_name"]) == (OLEH, "Budi Santoso")
    with store._lock, store._db:
        store._db.execute("DELETE FROM operators WHERE email = ?", (OLEH,))
    [r] = service.kedatangan_dibatalkan("2026-10-01")
    assert (r["cancelled_by"], r["cancelled_by_name"]) == (OLEH, "Budi Santoso")


@pytest.mark.parametrize("nama", [None, "", "   "])
def test_nama_kosong_disimpan_null(konsol, store, nama):
    service, gate = konsol
    gate.arrive("BE 7742 ZB", "2026-10-01T01:00:00Z")
    [a] = service.waiting_arrivals(baca_waktu("2026-10-01T01:05:00Z"))
    gate.cancel_arrival(a["id"], oleh=OLEH, nama=nama)
    assert store.arrival(a["id"])["cancelled_by_name"] is None
