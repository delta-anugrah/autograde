"""End to end (batch 5.11): a night shift across midnight lands on one working day, and a
cutoff changed mid-unload leaves the bunches already stored where they were."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-e2e-cutoff"


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual({"email": "support@pks.test", "full_name": "Support",
                                  "password_hash": hash_password(SANDI), "role": ROLE_SUPPORT})
    service = ConsoleService(settings, store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return app, service


def _janjang(service, nomor, ts, truk):
    return service.ingest({
        "event_id": f"ev-{nomor}", "machine_id": service.lines[0].machine_id, "timestamp": ts,
        "ripeness_status": "ACC", "ripeness_confidence": 0.9, "capture_type": "auto",
        "image_path": f"captures/results/x/{nomor}.webp", "truck_id": truk, "assignment_id": "as-1",
    })


def test_a_truck_unloaded_across_midnight_is_one_row_in_the_recap(rakitan):
    app, service = rakitan

    async def alur():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as k:
            assert (await k.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI})).status_code == 200
            assert (await k.post("/api/console/dev/shift", json={"cutoff": "05:00"})).status_code == 200
            truk = (await k.post("/api/console/trucks", json={"plate_number": "BE 1 AA"})).json()["id"]
            service.store.set_assignment("line-1", "as-1", truk)
            for nomor, ts in enumerate(("2026-10-05T23:30:00+07:00", "2026-10-05T23:59:00+07:00",
                                        "2026-10-06T00:10:00+07:00", "2026-10-06T00:30:00+07:00")):
                _janjang(service, nomor, ts, truk)
            rekap = (await k.get("/api/console/recap?work_date=2026-10-05")).json()["items"]
            esok = (await k.get("/api/console/recap?work_date=2026-10-06")).json()["items"]
            return rekap, esok

    rekap, esok = asyncio.run(alur())

    assert [(r["plate_number"], r["total"]) for r in rekap] == [("BE 1 AA", 4)]
    assert esok == []


def test_a_cutoff_changed_mid_unload_moves_nothing_already_stored(rakitan):
    _, service = rakitan
    truk = service.register_manual_truck("BE 2 BB")["id"]
    service.store.set_assignment("line-1", "as-1", truk)
    assert _janjang(service, 1, "2026-10-06T02:00:00+07:00", truk) == "2026-10-06"

    service.hari_kerja.atur("05:00")

    assert _janjang(service, 2, "2026-10-06T02:10:00+07:00", truk) == "2026-10-05"
    assert {r["event_id"] for r in service.store.inspections("2026-10-06", limit=10)} == {"ev-1"}


def test_a_truck_weighed_in_before_midnight_is_still_today_after_it(rakitan):
    """Weighed in at 23:50, still on the scale at 00:20, cutoff 05:00: the Timbangan table of
    "today" is the working day of the weigh-in, so the ticket is a row of today, not carried."""
    app, service = rakitan
    service.hari_kerja.atur("05:00")
    service.register_manual_truck("BE 3 CC")
    asyncio.run(service.record_weighing({
        "plate_number": "BE 3 CC", "gross_kg": 12000, "entered_at": "2026-10-05T23:50:00+07:00"}))
    service.sekarang = lambda: datetime(2026, 10, 6, 0, 20, tzinfo=ZoneInfo("Asia/Jakarta"))

    async def tabel():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as k:
            assert (await k.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI})).status_code == 200
            return (await k.get("/api/console/weighings")).json()

    hari_ini = asyncio.run(tabel())

    assert hari_ini["work_date"] == "2026-10-05"
    assert [r["plate_number"] for r in hari_ini["items"]] == ["BE 3 CC"]
