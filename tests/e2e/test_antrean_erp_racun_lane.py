"""End-to-end (batch 2.7): kunjungan yang membuat AutoERP crash tidak menahan antrean.

Operator menimbang tiga truk dari lane operator; salah satunya membuat handler
`upsert_visit` crash (500 dengan amplop galat Frappe). Support melihat di Antrean ERP
(tab Status): satu baris gagal dengan alasan dari Frappe, dua lainnya terkirim.
Operator melihat di Last Sync: AutoERP tersambung, satu menunggu. Lalu portal login
hotspot: Last Sync terputus, antrean tetap tercatat, dan Kirim Ulang mengirim
semuanya begitu portalnya hilang.

App dirakit sendiri dengan dependensi di-override, bukan `create_console_app()`.
Stream C (batch 2.4) menambah `/api/console/dev/antrean/line` di modul rute sendiri;
`/api/console/dev/antrean` yang dibaca di sini tidak diubah siapa pun (dicek preflight).
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from autoerp_palsu import AutoErpPalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.dev_service import DevService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.services.status_sinkron import StatusSinkron
from palmgrade.workers.erp_link import outbox_handlers
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker

SANDI = "sandi-e2e-antrean"
WIB = ZoneInfo("Asia/Jakarta")
PLAT = ("BE 1 AA", "BE 2 BB", "BE 3 CC")


class _Line:
    async def assign_truck(self, line, **_kw) -> None: ...


class Pabrik:
    def __init__(self, root) -> None:
        settings = replace(Settings(), repo_root=root, factory_tz="Asia/Jakarta", erp_url="http://erp.local")
        store = ConsoleStore(root / "console.db")
        store.upsert_operator_manual({
            "email": "support@pks.test", "full_name": "Support",
            "password_hash": hash_password(SANDI), "role": "support",
        })
        outbox = ErpOutboxStore(root / "erp_outbox.db")
        status = StatusSinkron(store, erp_aktif=True, r2_aktif=False)
        service = ConsoleService(
            settings, store, _Line(), erp_queue=ErpQueue(store, outbox), status_sinkron=status
        )
        dev = DevService(LogStore(root / "log.db"), erp_outbox=outbox, settings=settings, console_store=store)
        self.erp = AutoErpPalsu()
        klien = ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(self.erp))
        self.worker = ErpOutboxWorker(outbox, klien, outbox_handlers(store), status=status)
        app = FastAPI()
        app.include_router(console_router)
        app.dependency_overrides[get_console_service] = lambda: service
        app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
        app.dependency_overrides[get_dev_service] = lambda: dev
        self.client = TestClient(app)
        res = self.client.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI})
        assert res.status_code == 200, res.text

    def timbang_masuk(self, plat: str) -> str:
        res = self.client.post("/api/console/weighings", json={
            "ref": f"SCL-{plat}", "plate_number": plat,
            "entered_at": datetime.now(WIB).isoformat(), "gross_kg": 14560,
        })
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def kirim(self) -> int:
        return asyncio.run(self.worker.drain_once())

    def autoerp(self) -> dict:
        return self.client.get("/api/console/state").json()["sinkron"]["autoerp"]


@pytest.fixture
def pabrik(tmp_path) -> Pabrik:
    return Pabrik(tmp_path)


def test_kunjungan_beracun_terlihat_di_antrean_dan_sisanya_terkirim(pabrik):
    pabrik.erp.racun.add("BE 1 AA")
    tiket = {plat: pabrik.timbang_masuk(plat) for plat in PLAT}

    assert pabrik.kirim() == 2

    antrean = pabrik.client.get("/api/console/dev/antrean").json()
    assert (antrean["pending"], antrean["gagal"]) == (0, 1)
    [racun] = antrean["items"]
    assert racun["key"] == tiket["BE 1 AA"]
    assert "HTTP 500" in racun["last_error"] and "KeyError" in racun["last_error"]
    assert (pabrik.autoerp()["keadaan"], pabrik.autoerp()["antre"]) == ("tersambung", 1)


def test_portal_login_terbaca_terputus_lalu_kirim_ulang_mengosongkan_antrean(pabrik):
    pabrik.erp.portal = True
    for plat in PLAT[:2]:
        pabrik.timbang_masuk(plat)

    assert pabrik.kirim() == 0

    assert (pabrik.autoerp()["keadaan"], pabrik.autoerp()["antre"]) == ("terputus", 2)
    [baris] = pabrik.client.get("/api/console/dev/antrean").json()["items"]
    assert "HTTP 200" in baris["last_error"] and "Login hotspot" in baris["last_error"]

    pabrik.erp.portal = False
    assert pabrik.client.post("/api/console/dev/antrean/kirim-ulang").json() == {"dikirim_ulang": 1}
    assert pabrik.kirim() == 2
    assert pabrik.autoerp()["antre"] == 0
