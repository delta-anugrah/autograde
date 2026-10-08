"""End to end (batch 5.9): support switches the slip on, an operator's Rekap row offers Print,
and the slip the server builds is laid out by the screen.

A real sign-in for both accounts over ASGI, a real store with real bunches and a real
weighing; `barisRiwayatTruk` and `htmlSlip` run in node on the real answers.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from konsol_js import NODE, jalankan

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_riwayat_service, get_slip_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.riwayat_service import RiwayatService
from palmgrade.services.slip_grading import SlipGrading

pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SANDI = "sandi-e2e-slip"
WIB = ZoneInfo("Asia/Jakarta")
_STUB = """
const kg = (v) => (v === null || v === undefined ? KOSONG : Number(v).toLocaleString(lokal()));
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const tanggalRiwayat = (d) => d; const rasioRiwayat = () => "";
"""


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", erp_company="PT Sawit Uji")
    db = tmp_path / "console.db"
    store = ConsoleStore(db)
    for email, peran in (("operator@pks.test", None), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual({"email": email, "full_name": email, "password_hash": hash_password(SANDI),
                                      **({"role": peran} if peran else {})})
    service = ConsoleService(settings, store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_slip_service] = lambda: SlipGrading(store, perusahaan=settings.erp_company)
    app.dependency_overrides[get_riwayat_service] = lambda: RiwayatService(
        RiwayatStore(db), hari_ini=service.today, zona="Asia/Jakarta")
    return app, service


async def _alur(app, service) -> tuple[list[dict], dict]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://konsol") as op, \
            httpx.AsyncClient(transport=transport, base_url="http://konsol") as sup:
        for klien, email in ((op, "operator@pks.test"), (sup, "support@pks.test")):
            assert (await klien.post("/api/console/login", json={"email": email, "sandi": SANDI})).status_code == 200
        truk = (await op.post("/api/console/trucks", json={"plate_number": "BE 1 AA"})).json()["id"]
        service.store.set_assignment("line-1", "as-1", truk)
        sekarang = datetime.now(WIB).isoformat()
        for nomor, (status, kelas) in enumerate((("ACC", "Ripe"), ("ACC", "Ripe"), ("REJ", "Unripe"))):
            service.ingest({"event_id": f"ev-{nomor}", "machine_id": service.lines[0].machine_id, "timestamp": sekarang,
                            "ripeness_status": status, "ripeness_confidence": 0.9, "capture_type": "auto",
                            "grade_class": kelas, "image_path": f"captures/results/x/{nomor}.webp",
                            "truck_id": truk, "assignment_id": "as-1"})
        await op.post("/api/console/weighings", json={"plate_number": "BE 1 AA", "gross_kg": "12000",
                                                       "tare_kg": "4000", "entered_at": sekarang})
        assert (await sup.post("/api/console/dev/slip", json={"aktif": True})).status_code == 200
        hari = service.today()
        rekap = (await op.get(f"/api/console/riwayat?dari={hari}&sampai={hari}&tampilan=truk")).json()["items"]
        slip = (await op.get(f"/api/console/slip?work_date={hari}&truck_id={truk}")).json()
        return rekap, slip


def test_support_switches_it_on_and_the_operator_gets_a_printable_slip(rakitan):
    app, service = rakitan

    rekap, slip = asyncio.run(_alur(app, service))
    baris = jalankan(["chipPlat", "barisRiwayatTruk"], f"{json.dumps(rekap)}.map(barisRiwayatTruk).join('')",
                     tambahan=_STUB + "let slipCetak = true;")
    html = jalankan(["waktu", "angkaSlip", "htmlSlip"], f"htmlSlip({json.dumps(slip)}, 0)",
                    tambahan='const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));')

    assert f'data-truk="{slip["truck_id"]}"' in baris and 'data-cetak="1"' in baris
    assert slip["rasio_ripe"] == 66.7 and slip["neto_kg"] == 8000.0
    for isi in ("BE 1 AA", "PT Sawit Uji", "66,7%", "8.000 kg"):
        assert isi in html, isi
