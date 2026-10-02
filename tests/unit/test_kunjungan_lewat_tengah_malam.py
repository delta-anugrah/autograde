"""A truck visit that crosses midnight (user 2026-10-02: "benerin").

The mill runs about 20 h a day across midnight. A truck weighed in at 23:50 WIB and weighed
out at 00:10 WIB the next calendar day used to be lost three ways at 00:00: the exit scan
answered "no open ticket today", the Timbangan table dropped its row with the per-row
Timbang kosong and Keluar buttons, and the Danger Zone stopped counting it as a truck in the
yard. The rule now: one visit window (`JENDELA_KUNJUNGAN_DETIK`, 12 h) on the real weigh-in
instant, never the calendar date. The ticket keeps its own `work_date`: day totals do not move.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.gerbang import TAHAP_BONGKAR, TAHAP_TIMBANG_KOSONG
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.working_day import awal_kunjungan, work_date_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService
from palmgrade.services.scan_service import ScanService

WIB = ZoneInfo("Asia/Jakarta")
HARI_1 = "2026-09-20"
HARI_2 = "2026-09-21"
#: 00:10 WIB on the second calendar day: twenty minutes after the 23:50 weigh-in.
SEKARANG = datetime(2026, 9, 21, 0, 10, tzinfo=WIB)
PLAT = "BE 4412 OFL"


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _tiket(store, wid, entered_at, *, plat=PLAT, tare=None):
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": plat, "plate_norm": plat.replace(" ", ""),
        "truck_id": truck_id_for(plat), "work_date": work_date_for(entered_at, WIB),
        "gross_kg": 14000.0, "tare_kg": tare, "net_kg": None if tare is None else 14000.0 - tare,
        "entered_at": entered_at, "exited_at": None,
    })


def _terbuka(store, plat=PLAT):
    return [w["id"] for w in store.open_weighings_for_truck(truck_id_for(plat), awal_kunjungan(SEKARANG))]


# ── the open ticket of a truck: repository decision ─────────────────────────


def test_awal_kunjungan_dua_belas_jam_sebelum_sekarang():
    assert SEKARANG.timestamp() - awal_kunjungan(SEKARANG) == 12 * 3600


def test_tiket_2350_masih_terbuka_pukul_0010(store):
    _tiket(store, "w", f"{HARI_1}T23:50:00+07:00")
    assert _terbuka(store) == ["w"]


def test_tiket_dari_layar_berakhiran_z_juga_terbaca(store):
    _tiket(store, "w", f"{HARI_1}T16:50:00.000Z")  # 23:50 WIB as the browser writes it
    assert _terbuka(store) == ["w"]


def test_tiket_lebih_tua_dari_dua_belas_jam_tidak_terbuka_lagi(store):
    """The old reason for the work-date scope still holds: a ticket left open since 11:00
    yesterday must not take tonight's tare (net from yesterday's gross)."""
    _tiket(store, "lama", f"{HARI_1}T11:00:00+07:00")
    assert _terbuka(store) == []


def test_batas_jendela_dua_belas_jam(store):
    _tiket(store, "di-dalam", f"{HARI_1}T12:11:00+07:00", plat="BE 1001 AA")
    _tiket(store, "di-luar", f"{HARI_1}T12:09:00+07:00", plat="BE 1002 AB")
    assert _terbuka(store, "BE 1001 AA") == ["di-dalam"]
    assert _terbuka(store, "BE 1002 AB") == []


def test_tiket_yang_sudah_ada_taranya_tidak_terbuka(store):
    _tiket(store, "w", f"{HARI_1}T23:50:00+07:00", tare=6000.0)
    assert _terbuka(store) == []


def test_tiket_truk_lain_tidak_ikut(store):
    _tiket(store, "w", f"{HARI_1}T23:50:00+07:00", plat="BE 1001 AA")
    assert _terbuka(store) == []


# ── the exit scan (scan 3) across midnight ───────────────────────────────────


def test_scan_keluar_0010_menemukan_tiket_2350(store):
    _tiket(store, "w", f"{HARI_1}T23:50:00+07:00")
    hasil = ScanService(store).open_ticket("BE4412OFL", SEKARANG)
    assert hasil["ditemukan"] is True
    assert hasil["weighing"]["id"] == "w"
    assert hasil["weighing"]["work_date"] == HARI_1


def test_scan_keluar_tiket_kemarin_siang_tidak_ditemukan(store):
    _tiket(store, "lama", f"{HARI_1}T11:00:00+07:00")
    hasil = ScanService(store).open_ticket("BE4412OFL", SEKARANG)
    assert hasil["ditemukan"] is False
    assert hasil.get("ganda") is not True


def test_dua_tiket_terbuka_lewat_tengah_malam_ditolak_bukan_ditebak(store):
    """One before midnight, one after: still two open tickets of one truck, still refused."""
    _tiket(store, "sebelum", f"{HARI_1}T23:40:00+07:00")
    _tiket(store, "sesudah", f"{HARI_2}T00:05:00+07:00")
    hasil = ScanService(store).open_ticket("BE4412OFL", SEKARANG)
    assert hasil["ditemukan"] is False
    assert hasil["ganda"] is True
    assert [w["id"] for w in hasil["choices"]] == ["sesudah", "sebelum"]


# ── the Timbangan table: the operator's working view ─────────────────────────


@pytest.fixture
def konsol(store):
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    service.sekarang = lambda: SEKARANG
    return service, GateService(store, service.tz)


def _isi(service, plat, jam):
    asyncio.run(service.record_weighing({"plate_number": plat, "gross_kg": 14000, "entered_at": jam}))


def _kosong(service, plat, masuk, keluar):
    asyncio.run(service.record_weighing(
        {"plate_number": plat, "entered_at": masuk, "tare_kg": 6000, "exited_at": keluar}
    ))


def _malam_itu(konsol):
    """Five trucks around midnight; only the first two are still in the yard at 00:10."""
    service, gate = konsol
    _isi(service, "BE 1001 AA", f"{HARI_1}T23:50:00+07:00")  # unloading
    _isi(service, "BE 1002 AB", f"{HARI_1}T22:00:00+07:00")
    _kosong(service, "BE 1002 AB", f"{HARI_1}T22:00:00+07:00", f"{HARI_1}T23:30:00+07:00")  # no scan 4 yet
    _isi(service, "BE 1003 AC", f"{HARI_1}T21:00:00+07:00")
    _kosong(service, "BE 1003 AC", f"{HARI_1}T21:00:00+07:00", f"{HARI_1}T22:30:00+07:00")
    gate.leave("BE1003AC", f"{HARI_1}T22:40:00+07:00")  # left the yard: finished
    _isi(service, "BE 1004 AD", f"{HARI_1}T11:00:00+07:00")  # open, but 13 h old
    _isi(service, "BE 1005 AE", f"{HARI_2}T00:05:00+07:00")  # today's first truck


def test_tabel_hari_ini_membawa_kunjungan_kemarin_yang_belum_selesai(konsol):
    service, _ = konsol
    _malam_itu(konsol)

    baris = [(w["plate_number"], w["work_date"], w["tahap"]) for w in service.weighings(HARI_2)]

    # Today's rows first, then the carried ones, newest first by the real instant; each
    # keeps its own work date, and its stage decides its button (Timbang kosong / Keluar).
    assert baris == [
        ("BE 1005 AE", HARI_2, TAHAP_BONGKAR),
        ("BE 1001 AA", HARI_1, TAHAP_BONGKAR),
        ("BE 1002 AB", HARI_1, TAHAP_TIMBANG_KOSONG),
    ]


def test_hari_ini_dari_jam_yang_sama(konsol):
    service, _ = konsol
    assert service.today() == HARI_2


def test_hari_lampau_tidak_membawa_apa_pun_dan_tidak_ganda(konsol):
    """Yesterday's table is yesterday's tickets, each once: carrying is for today's view only."""
    service, _ = konsol
    _malam_itu(konsol)
    assert sorted(w["plate_number"] for w in service.weighings(HARI_1)) == [
        "BE 1001 AA", "BE 1002 AB", "BE 1003 AC", "BE 1004 AD",
    ]


def test_total_hari_rekap_dan_strip_tidak_berpindah_hari(konsol, store):
    service, _ = konsol
    _malam_itu(konsol)
    assert store.ringkasan_timbangan(HARI_2) == {"tiket": 1, "menunggu_tara": 1, "neto_kg": 0}
    assert store.ringkasan_timbangan(HARI_1)["tiket"] == 4
    assert service.state()["timbangan"]["tiket"] == 1
    assert [r for r in service.recap(HARI_2) if r.get("net_kg")] == []
    assert store.weighing_ids_on(HARI_2) == [w["id"] for w in store.weighings(HARI_2)]


def test_kunjungan_selesai_lewat_tengah_malam_lalu_hilang_dari_tabel_hari_ini(konsol, store):
    service, gate = konsol
    _isi(service, PLAT, f"{HARI_1}T23:50:00+07:00")

    tiket = ScanService(store).open_ticket("BE4412OFL", SEKARANG)["weighing"]
    _kosong(service, PLAT, tiket["entered_at"], f"{HARI_2}T00:10:00+07:00")
    [baris] = service.weighings(HARI_2)
    assert (baris["tahap"], baris["work_date"], baris["net_kg"]) == (TAHAP_TIMBANG_KOSONG, HARI_1, 8000.0)

    assert gate.leave("BE4412OFL", f"{HARI_2}T00:20:00+07:00")["hasil"] == "tercatat"
    assert service.weighings(HARI_2) == []
    assert store.weighing(tiket["id"])["work_date"] == HARI_1
