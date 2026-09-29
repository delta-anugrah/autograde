"""Route konsol yang membaca atau menulis SQLite berat tidak jalan di event loop (batch 2.5).

Satu event loop melayani layar semua operator DAN kiriman janjang tiga line. Pola yang
dipakai sama dengan tab Rekap (`console_riwayat`): route `def` (FastAPI menjalankannya
di thread pool), atau `run_in_threadpool` kalau route itu juga harus `await`.

Bukti: kolaborator palsu mencatat apakah ia dipanggil dari thread yang punya event loop
berjalan.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_dev_service,
    require_operator,
)
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_ingest import ingest_router

SECRET = "kunci-uji-palsu"


def _di_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _Catatan(dict):
    def tandai(self, nama: str) -> None:
        self[nama] = _di_event_loop()


class _Service:
    def __init__(self, catatan: _Catatan, settings: Settings) -> None:
        self.catatan, self.settings = catatan, settings

    def today(self) -> str:
        return "2026-09-28"

    def state(self) -> dict:
        self.catatan.tandai("state")
        return {"lines": []}

    def history_halaman(self, *_a, **_k) -> dict:
        self.catatan.tandai("history")
        return {"items": [], "total": 0}

    def trucks(self) -> list:
        self.catatan.tandai("trucks")
        return []

    def weighings(self, *_a, **_k) -> list:
        self.catatan.tandai("weighings")
        return []

    def recap(self, *_a, **_k) -> list:
        self.catatan.tandai("recap")
        return []

    def ingest(self, payload: dict) -> str:
        self.catatan.tandai("ingest")
        return "2026-09-28"


class _Dev:
    def __init__(self, catatan: _Catatan) -> None:
        self.catatan = catatan

    async def license_state(self) -> dict:
        return {}

    def app_version(self) -> str:
        return "v-uji"

    def log(self, **_k) -> dict:
        self.catatan.tandai("log")
        return {"items": [], "total": 0}


class _Auth:
    def __init__(self, catatan: _Catatan) -> None:
        self.catatan = catatan

    def login(self, email: str, sandi: str):
        self.catatan.tandai("login")
        return "token-uji", {"email": email}


@pytest.fixture
def uji():
    catatan = _Catatan()
    settings = replace(Settings(), webhook_secret=SECRET)
    app = FastAPI()
    app.include_router(console_router)
    app.include_router(ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[get_console_service] = lambda: _Service(catatan, settings)
    app.dependency_overrides[get_dev_service] = lambda: _Dev(catatan)
    app.dependency_overrides[get_auth_service] = lambda: _Auth(catatan)
    app.dependency_overrides[require_operator] = lambda: {
        "operator_id": "o", "email": "s@pks.test", "full_name": "S", "role": "support",
    }
    return TestClient(app), catatan, settings


PERMINTAAN = {
    "state": ("GET", "/api/console/state", None),
    "history": ("GET", "/api/console/history", None),
    "trucks": ("GET", "/api/console/trucks", None),
    "weighings": ("GET", "/api/console/weighings", None),
    "recap": ("GET", "/api/console/recap", None),
    "log": ("GET", "/api/console/dev/log", None),
    "login": ("POST", "/api/console/login", {"email": "s@pks.test", "sandi": "x"}),
    "ingest": ("POST", "{api}/internal/vision/events", {"event_id": "e"}),
}


@pytest.mark.parametrize("nama", sorted(PERMINTAAN))
def test_kerja_berat_route_konsol_jalan_di_thread_pool(uji, nama):
    client, catatan, settings = uji
    verb, path, body = PERMINTAAN[nama]

    res = client.request(verb, path.format(api=settings.backend_api_ver), json=body,
                         headers={"x-webhook-secret": SECRET})

    assert res.status_code < 300, res.text
    assert catatan[nama] is False, f"{nama} masih jalan di event loop"
