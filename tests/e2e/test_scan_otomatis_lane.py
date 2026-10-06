"""End-to-end: the one scan field over real HTTP, behind a session (2026-10-06).

Assembled here, not through `create_console_app()` (that opens the developer's
`state/console.db`). The live scale is the route's own singleton, never connected in a
test, so every weight step answers `perlu_berat`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import get_scan_otomatis, pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService
from palmgrade.services.scan_otomatis import ScanOtomatis
from palmgrade.services.timbangan_live import TimbanganLive

SANDI = "sawit2026"
OPERATOR = "op@pks.test"
RUTE = "/api/console/scan/otomatis"
PLAT = "BE 4412 OFL"


@pytest.fixture
def client(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": OPERATOR, "full_name": OPERATOR, "password_hash": hash_password(SANDI), "role": "operator"}
    )
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    service.register_manual_truck(PLAT)
    scan = ScanOtomatis(service, GateService(store, service.tz), TimbanganLive(dipakai=False))
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_scan_otomatis] = lambda: scan
    return TestClient(app)


def _masuk(client) -> TestClient:
    r = client.post("/api/console/login", json={"email": OPERATOR, "sandi": SANDI})
    assert r.status_code == 200, r.text
    return client


def test_tanpa_sesi_ditolak(client):
    assert client.post(RUTE, json={"qr": PLAT}).status_code == 401


def test_datang_lalu_timbang_isi_minta_berat(client):
    c = _masuk(client)
    r = c.post(RUTE, json={"qr": "be4412ofl", "at": "2026-10-06T01:00:00+00:00"})
    assert r.status_code == 200, r.text
    assert (r.json()["langkah"], r.json()["hasil"], r.json()["plate_number"]) == ("datang", "tercatat", PLAT)
    r = c.post(RUTE, json={"qr": PLAT, "at": "2026-10-06T01:20:00+00:00"})
    assert (r.json()["langkah"], r.json()["hasil"]) == ("timbang_isi", "perlu_berat")


def test_baca_ganda_ditanya_lalu_konfirmasi(client):
    c = _masuk(client)
    c.post(RUTE, json={"qr": PLAT, "at": "2026-10-06T01:00:00+00:00"})
    r = c.post(RUTE, json={"qr": PLAT, "at": "2026-10-06T01:00:01+00:00"})
    assert r.json()["hasil"] == "perlu_konfirmasi"
    r = c.post(RUTE, json={"qr": PLAT, "at": "2026-10-06T01:00:02+00:00", "konfirmasi": True})
    assert r.json()["hasil"] == "perlu_berat"


def test_bukan_plat_400(client):
    r = _masuk(client).post(RUTE, json={"qr": "https://promo.example/qr"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "bukan_plat"


def test_bentuk_salah_400(client):
    r = _masuk(client).post(RUTE, json={"qr": PLAT, "konfirmasi": "mungkin"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "input_tidak_sah"
