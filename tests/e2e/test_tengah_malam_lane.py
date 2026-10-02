"""End-to-end: one truck visit across midnight, over real HTTP behind an operator session.

Weigh-in 23:50 WIB, the exit scan and the tare at 00:10, the leave scan at 00:20 the next
calendar day. What the operator's screen asks for, route by route: the weighings list keeps
the visit with its stage until it leaves, the exit scan finds its ticket, and the day it
belongs to (Rekap, the day list) never moves. The console clock is pinned
(`ConsoleService.sekarang`), so this runs the same at noon and at midnight.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.gerbang import TAHAP_BONGKAR, TAHAP_SELESAI, TAHAP_TIMBANG_KOSONG
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_gate_service,
    get_scan_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService
from palmgrade.services.scan_service import ScanService

EMAIL = "gerbang@pks.test"
SANDI = "timbangan2026"
PLAT = "BE 4412 OFL"
WIB = ZoneInfo("Asia/Jakarta")
HARI_1 = "2026-09-20"
HARI_2 = "2026-09-21"


class _Jam:
    """The console's clock, moved by the test."""

    def __init__(self) -> None:
        self.saat = datetime(2026, 9, 20, 23, 50, tzinfo=WIB)

    def __call__(self) -> datetime:
        return self.saat


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual({"email": EMAIL, "full_name": "Operator Gerbang", "password_hash": hash_password(SANDI)})
    store.upsert_truck({"id": truck_id_for(PLAT), "plate_number": PLAT, "status": "active"})
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    jam = _Jam()
    service.sekarang = jam
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_service] = lambda: ScanService(store)
    app.dependency_overrides[get_gate_service] = lambda: GateService(store, service.tz)
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": EMAIL, "sandi": SANDI}).status_code == 200
    return client, jam


def _tabel(client, **params):
    return client.get("/api/console/weighings", params=params).json()


def _baris(isi):
    return [(w["plate_number"], w["work_date"], w["tahap"]) for w in isi["items"]]


def test_kunjungan_2350_sampai_0020_lewat_semua_jalur(konsol):
    client, jam = konsol
    r = client.post("/api/console/weighings", json={
        "plate_number": PLAT, "gross_kg": 14000, "entered_at": "2026-09-20T16:50:00.000Z",
    })
    assert r.status_code == 201, r.text

    # 00:10: a new calendar day. The table is today's, and still shows the truck.
    jam.saat = datetime(2026, 9, 21, 0, 10, tzinfo=WIB)
    isi = _tabel(client)
    assert isi["work_date"] == HARI_2
    assert _baris(isi) == [(PLAT, HARI_1, TAHAP_BONGKAR)]

    # Scan 3 finds the ticket (it used to answer "no open ticket today").
    scan = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"}).json()
    assert scan["ditemukan"] is True
    w = scan["weighing"]
    r = client.post("/api/console/weighings", json={
        "plate_number": PLAT, "ref": w["ref"], "entered_at": w["entered_at"],
        "tare_kg": 6000, "exited_at": "2026-09-20T17:10:00.000Z",
    })
    assert r.status_code == 201, r.text
    assert (r.json()["net_kg"], r.json()["work_date"]) == (8000.0, HARI_1)
    assert _baris(_tabel(client)) == [(PLAT, HARI_1, TAHAP_TIMBANG_KOSONG)]

    # Scan 4 at 00:20: the visit is finished and leaves today's table.
    jam.saat = datetime(2026, 9, 21, 0, 20, tzinfo=WIB)
    keluar = client.post("/api/console/departures", json={"qr": PLAT, "at": "2026-09-20T17:20:00Z"}).json()
    assert keluar["hasil"] == "tercatat"
    assert _tabel(client)["items"] == []

    # It stays on its own day: 2 October's list holds it once, finished.
    assert _baris(_tabel(client, work_date=HARI_1)) == [(PLAT, HARI_1, TAHAP_SELESAI)]


def test_scan_keluar_menolak_tiket_yang_lebih_tua_dari_jendela(konsol):
    """11:00 yesterday, never weighed out: at 00:10 it is out of the 12 h window, so
    tonight's tare cannot land on it, and it is no longer carried on today's table."""
    client, jam = konsol
    client.post("/api/console/weighings", json={
        "plate_number": PLAT, "gross_kg": 14000, "entered_at": "2026-09-20T11:00:00+07:00",
    })
    jam.saat = datetime(2026, 9, 21, 0, 10, tzinfo=WIB)
    scan = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"}).json()
    assert scan["ditemukan"] is False and scan.get("ganda") is not True
    assert _tabel(client)["items"] == []
    assert _baris(_tabel(client, work_date=HARI_1)) == [(PLAT, HARI_1, TAHAP_BONGKAR)]


def test_dua_tiket_terbuka_lewat_tengah_malam_minta_pilih(konsol):
    client, jam = konsol
    for masuk in ("2026-09-20T23:40:00+07:00", "2026-09-21T00:05:00+07:00"):
        client.post("/api/console/weighings", json={"plate_number": PLAT, "gross_kg": 14000, "entered_at": masuk})
    jam.saat = datetime(2026, 9, 21, 0, 10, tzinfo=WIB)
    scan = client.post("/api/console/scan/keluar", json={"qr": "BE4412OFL"}).json()
    assert (scan["ditemukan"], scan["ganda"], len(scan["choices"])) == (False, True, 2)
    # Both rows on today's table, each with its own work date.
    assert _baris(_tabel(client)) == [(PLAT, HARI_2, TAHAP_BONGKAR), (PLAT, HARI_1, TAHAP_BONGKAR)]
