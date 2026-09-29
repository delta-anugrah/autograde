"""End-to-end (batch 2.5): layar operator tetap menjawab saat query berat berjalan.

Store di sini sungguhan tapi sengaja diperlambat (`jeda`). Lewat transport ASGI dengan
login sungguhan, permintaan berat (polling `/state`, atau janjang dari line) dikirim
dulu; begitu query lambatnya MULAI (`mulai`, dari thread mana pun ia jalan), permintaan
ringan (`/api/console/me`) dikirim. Kalau yang berat jalan di event loop, loop membeku
dan yang ringan baru jalan sesudah yang berat selesai; di thread pool, yang ringan
selesai lebih dulu.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.vision_event import build_event_payload
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-e2e-responsif"
SECRET = "kunci-e2e-palsu"
JEDA_S = 0.5


class _StoreLambat(ConsoleStore):
    jeda = 0.0

    def __init__(self, db_path) -> None:
        super().__init__(db_path)
        self.mulai = threading.Event()

    def _lambat(self) -> None:
        if self.jeda:
            self.mulai.set()
            time.sleep(self.jeda)

    def summary(self, work_date):
        self._lambat()
        return super().summary(work_date)

    def add_inspection(self, row):
        self._lambat()
        return super().add_inspection(row)


class _Dev:
    async def license_state(self) -> dict:
        return {}

    def app_version(self) -> str:
        return "v-e2e"


@pytest.fixture
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", webhook_secret=SECRET)
    store = _StoreLambat(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    app.include_router(ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: _Dev()
    return app, store, service


def _janjang(service: ConsoleService) -> dict:
    return build_event_payload(
        machine_id=service.lines[0].machine_id, file_ts="2026-09-28_07-41-00_000000",
        timestamp=datetime.now(UTC).isoformat(), ripeness_status="ACC", ripeness_confidence=0.9,
        capture_type="auto", image_path="captures/results/2026-09-28/x.webp",
        truck_id=None, assignment_id=None,
    )


BERAT = {
    "state": lambda klien, service: klien.get("/api/console/state"),
    "ingest": lambda klien, service: klien.post(
        f"{service.settings.backend_api_ver}/internal/vision/events",
        json=_janjang(service), headers={"x-webhook-secret": SECRET},
    ),
}


async def _urutan_selesai(app, store, service, berat) -> list[str]:
    selesai: list[str] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://konsol") as klien:
        res = await klien.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
        assert res.status_code == 200, res.text
        store.jeda = JEDA_S

        async def jalan(nama, permintaan):
            res = await permintaan
            assert res.status_code < 300, res.text
            selesai.append(nama)

        tugas_berat = asyncio.create_task(jalan("berat", berat(klien, service)))
        while not store.mulai.is_set():          # tunggu sampai query lambatnya mulai
            await asyncio.sleep(0.005)
        await jalan("ringan", klien.get("/api/console/me"))
        await tugas_berat
    return selesai


@pytest.mark.parametrize("nama", sorted(BERAT))
def test_layar_tetap_menjawab_saat_query_berat_berjalan(rakitan, nama):
    app, store, service = rakitan

    assert asyncio.run(_urutan_selesai(app, store, service, BERAT[nama])) == ["ringan", "berat"]
