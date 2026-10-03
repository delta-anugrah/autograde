"""The Timbangan table and the gate with a visit that never got its Keluar (user 2026-10-03).

Store + service + gate on one real `console.db`. A tared ticket without a leave time is
carried up to 24 h from its weigh-out, then shows SELESAI "tanpa scan 4"; it is finished at
once when the same truck arrives again or weighs in again. A ticket without a tare keeps the
12 h window. Nothing is written for it: `left_at` stays empty.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.gerbang import (
    TAHAP_BONGKAR,
    TAHAP_SELESAI,
    TAHAP_TIMBANG_KOSONG,
    baca_waktu,
)
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService

PLAT = "BE 4412 OFL"
HARI_1, HARI_2 = "2026-10-01", "2026-10-02"
DATANG = f"{HARI_1}T08:30:00+07:00"
MASUK = f"{HARI_1}T09:00:00+07:00"
KOSONG = f"{HARI_1}T10:00:00+07:00"


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


@pytest.fixture
def konsol(store):
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    return service, GateService(store, service.tz)


def _pada(service, teks: str, **selisih) -> None:
    jam = baca_waktu(teks) + timedelta(**selisih)
    service.sekarang = lambda: jam


def _isi(service, jam, plat=PLAT):
    return asyncio.run(service.record_weighing({"plate_number": plat, "gross_kg": 14000, "entered_at": jam}))


def _kosong(service, masuk, keluar, plat=PLAT):
    return asyncio.run(service.record_weighing(
        {"plate_number": plat, "entered_at": masuk, "tare_kg": 6000, "exited_at": keluar}))


def _kunjungan_tanpa_keluar(konsol):
    service, gate = konsol
    _pada(service, DATANG)
    gate.arrive(PLAT, DATANG)
    _isi(service, MASUK)
    return _kosong(service, MASUK, KOSONG)


def _baris(service, hari, plat=PLAT):
    return [w for w in service.weighings(hari) if w["plate_number"] == plat]


# ── 24 h after the weigh-out ─────────────────────────────────────────────────


def test_23_jam_59_masih_timbang_kosong_dengan_tombol_keluar(konsol):
    service, _ = konsol
    _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=23, minutes=59)
    [w] = _baris(service, HARI_1)
    assert (w["tahap"], w["tanpa_scan_4"], w["total_menit"]) == (TAHAP_TIMBANG_KOSONG, False, None)


def test_24_jam_01_selesai_tanpa_scan_4_total_sampai_timbang_kosong(konsol, store):
    service, _ = konsol
    row = _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=24, minutes=1)
    [w] = _baris(service, HARI_1)
    assert (w["tahap"], w["tanpa_scan_4"], w["antre_menit"], w["total_menit"]) == (TAHAP_SELESAI, True, 30, 90)
    assert store.weighing(row["id"])["left_at"] is None  # computed, never written


def test_kunjungan_bertara_dibawa_ke_hari_ini_sampai_24_jam(konsol):
    """Weighed in 16 h ago (outside the 12 h visit window) and weighed out 15 h ago:
    still waiting for its Keluar, so today's table carries it."""
    service, _ = konsol
    _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=15)
    assert service.today() == HARI_2
    [w] = _baris(service, HARI_2)
    assert (w["work_date"], w["tahap"]) == (HARI_1, TAHAP_TIMBANG_KOSONG)

    _pada(service, KOSONG, hours=24, minutes=1)
    assert _baris(service, HARI_2) == []


def test_tiket_tanpa_tara_tetap_jendela_12_jam(konsol):
    service, _ = konsol
    malam = f"{HARI_1}T20:00:00+07:00"
    _pada(service, malam)
    _isi(service, malam)
    _pada(service, malam, hours=11, minutes=59)
    assert [w["tahap"] for w in _baris(service, HARI_2)] == [TAHAP_BONGKAR]
    _pada(service, malam, hours=12, minutes=1)
    assert _baris(service, HARI_2) == []
    # On its own day it is still unloading: no tare, so never "tanpa scan 4".
    [w] = _baris(service, HARI_1)
    assert (w["tahap"], w["tanpa_scan_4"]) == (TAHAP_BONGKAR, False)


# ── the truck comes back before 24 h ─────────────────────────────────────────


def test_datang_lagi_menutup_kunjungan_lama(konsol, store):
    service, gate = konsol
    row = _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=3)
    assert gate.arrive(PLAT, f"{HARI_1}T13:00:00+07:00")["hasil"] == "tercatat"

    [w] = _baris(service, HARI_1)
    assert (w["tahap"], w["tanpa_scan_4"], w["total_menit"]) == (TAHAP_SELESAI, True, 90)
    [a] = service.waiting_arrivals(baca_waktu(f"{HARI_1}T13:05:00+07:00"))
    assert (a["tahap"], a["menit"], bool(a["id"])) == ("datang", 5, True)
    assert store.weighing(row["id"])["left_at"] is None


def test_timbang_isi_lagi_menutup_kunjungan_lama(konsol):
    service, _ = konsol
    lama = _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=3)
    baru = _isi(service, f"{HARI_1}T13:00:00+07:00")
    tahap = {w["id"]: (w["tahap"], w["tanpa_scan_4"]) for w in service.weighings(HARI_1)}
    assert tahap == {lama["id"]: (TAHAP_SELESAI, True), baru["id"]: (TAHAP_BONGKAR, False)}


def test_kunjungan_terbawa_yang_digantikan_tidak_dibawa(konsol):
    """Yesterday's weighed-out visit is on today's table while it waits for Keluar; once the
    truck is back it is finished and stays on its own day only."""
    service, gate = konsol
    _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=15)
    assert [w["tahap"] for w in _baris(service, HARI_2)] == [TAHAP_TIMBANG_KOSONG]
    gate.arrive(PLAT, f"{HARI_2}T00:30:00+07:00")
    assert _baris(service, HARI_2) == []
    assert [w["tahap"] for w in _baris(service, HARI_1)] == [TAHAP_SELESAI]


def test_truk_lain_yang_datang_tidak_menutup(konsol):
    service, gate = konsol
    _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=3)
    gate.arrive("BE 7001 XY", f"{HARI_1}T13:00:00+07:00")
    assert [w["tahap"] for w in _baris(service, HARI_1)] == [TAHAP_TIMBANG_KOSONG]


def test_tiket_bertara_tidak_menahan_kedatangan_baru(konsol):
    service, gate = konsol
    _kunjungan_tanpa_keluar(konsol)
    assert gate.arrive(PLAT, f"{HARI_1}T10:30:00+07:00")["hasil"] == "tercatat"


def test_keluar_kunjungan_baru_tidak_pernah_menutup_tiket_lama(konsol, store):
    service, gate = konsol
    lama = _kunjungan_tanpa_keluar(konsol)
    _pada(service, KOSONG, hours=3)
    gate.arrive(PLAT, f"{HARI_1}T13:00:00+07:00")
    # Leaving before the new visit is weighed in: the old ticket is finished, not reopened.
    assert gate.leave(PLAT, f"{HARI_1}T13:10:00+07:00")["hasil"] == "sudah_keluar"
    baru = _isi(service, f"{HARI_1}T13:20:00+07:00")
    assert gate.leave(PLAT, f"{HARI_1}T13:30:00+07:00")["hasil"] == "belum_timbang_kosong"
    _kosong(service, f"{HARI_1}T13:20:00+07:00", f"{HARI_1}T14:00:00+07:00")

    jawab = gate.leave(PLAT, f"{HARI_1}T14:10:00+07:00")
    assert (jawab["hasil"], jawab["weighing_id"]) == ("tercatat", baru["id"])
    assert gate.leave(PLAT, f"{HARI_1}T14:20:00+07:00")["hasil"] == "sudah_keluar"
    # The old ticket's row button answers "already left" too, and nothing is written.
    assert gate.leave(None, f"{HARI_1}T14:30:00+07:00", weighing_id=lama["id"])["hasil"] == "sudah_keluar"
    assert store.weighing(lama["id"])["left_at"] is None
    assert store.weighing(baru["id"])["left_at"] == f"{HARI_1}T14:10:00+07:00"


def test_tombol_baris_sesudah_24_jam_tidak_menulis(konsol, store):
    service, gate = konsol
    row = _kunjungan_tanpa_keluar(konsol)
    at = (baca_waktu(KOSONG) + timedelta(hours=24, minutes=1)).isoformat()
    assert gate.leave(None, at, weighing_id=row["id"])["hasil"] == "sudah_keluar"
    assert store.weighing(row["id"])["left_at"] is None


def test_jejak_truk_cuma_kedatangan_menunggu_dan_timbang_isi(konsol, store):
    service, gate = konsol
    _kunjungan_tanpa_keluar(konsol)  # its arrival is claimed: not in the trail
    gate.arrive(PLAT, f"{HARI_1}T13:00:00+07:00")
    jejak = store.jejak_truk([truck_id_for(PLAT), "lain"], HARI_1)
    assert sorted(jejak[truck_id_for(PLAT)]) == sorted([MASUK, f"{HARI_1}T13:00:00+07:00"])
    assert store.jejak_truk([], HARI_1) == {}
