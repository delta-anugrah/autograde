"""`waiting_arrivals`: menit tunggu dari jam server; jam rusak atau mundur = None, bukan 0.

Yang menunggu dipilih dengan jendela klaim (12 jam ke belakang dari sekarang), bukan hari
kerja: truk yang datang 23:50 masih menunggu pukul 00:10, sama seperti timbang isi 00:10
masih mengklaimnya (temuan Q3, review akhir Part 3).
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from palmgrade.core.config import Settings
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.working_day import work_date_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService

PLAT = "BE 4412 OFL"
WIB = ZoneInfo("Asia/Jakarta")


def _konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    return ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None), store


def _datang(store, id_, jam, hari=None, plat=PLAT):
    store.record_arrival({
        "id": id_, "plate_number": plat, "plate_norm": plat.replace(" ", ""), "truck_id": truck_id_for(plat),
        "work_date": hari or work_date_for(jam, WIB), "arrived_at": jam,
    })


def _lewat_tengah_malam() -> datetime:
    """00:10 WIB hari ini (tanggal sungguhan, bukan 2026-10-01 yang ditulis mati)."""
    return datetime.now(WIB).replace(hour=0, minute=10, second=0, microsecond=0)


def test_menit_tunggu_dari_jam_server(tmp_path):
    service, store = _konsol(tmp_path)
    _datang(store, "a1", (datetime.now(UTC) - timedelta(minutes=12)).isoformat())
    [baris] = service.waiting_arrivals()
    assert baris["menit"] in (12, 13)


def test_jam_mundur_atau_rusak_bukan_nol_menit(tmp_path):
    service, store = _konsol(tmp_path)
    hari_ini = datetime.now(WIB).strftime("%Y-%m-%d")
    _datang(store, "a1", (datetime.now(UTC) + timedelta(hours=2)).isoformat())
    _datang(store, "a2", "bukan-jam", hari_ini)
    menit = {b["arrived_at"][:5]: b["menit"] for b in service.waiting_arrivals()}
    assert list(menit.values()) == [None, None]
    assert store.claim_arrival("a2", "w1") is False


def test_truk_datang_2350_masih_menunggu_sesudah_tengah_malam(tmp_path):
    service, store = _konsol(tmp_path)
    sekarang = _lewat_tengah_malam()
    datang = (sekarang - timedelta(minutes=20)).isoformat()  # 23:50 WIB kemarin
    assert GateService(store, service.tz).arrive(PLAT, datang)["hasil"] == "tercatat"
    assert work_date_for(datang, WIB) != work_date_for(sekarang.isoformat(), WIB)

    [baris] = service.waiting_arrivals(sekarang)
    assert (baris["arrived_at"], baris["menit"]) == (datang, 20)

    # Timbang isi 00:10 mengklaim kedatangan yang sama, lalu dia tidak menunggu lagi.
    asyncio.run(service.record_weighing({"plate_number": PLAT, "gross_kg": 14000, "entered_at": sekarang.isoformat()}))
    assert service.waiting_arrivals(sekarang) == []


def test_yang_lebih_tua_dari_jendela_klaim_tidak_menunggu_lagi(tmp_path):
    """Satu hari kerja, dua kedatangan: 11 jam lalu masih bisa diklaim, 13 jam lalu tidak."""
    service, store = _konsol(tmp_path)
    sekarang = datetime.now(WIB).replace(hour=23, minute=30, second=0, microsecond=0)
    _datang(store, "masih", (sekarang - timedelta(hours=11)).isoformat(), plat="BE 1 AA")
    _datang(store, "basi", (sekarang - timedelta(hours=13)).isoformat(), plat="BE 2 BB")
    assert [b["plate_number"] for b in service.waiting_arrivals(sekarang)] == ["BE 1 AA"]
