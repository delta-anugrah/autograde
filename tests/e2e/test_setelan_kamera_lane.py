"""End-to-end: Setelan Kamera, console route to the real line routes. Line 1 is a Hikrobot camera, line 2 a
video source, line 3 is down."""
from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from ai_palsu import KameraPalsu
from antrean_line_rakit import LinePerPort, masuk
from fastapi import FastAPI

from palmgrade.core.config import Settings
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.domain.setelan_kamera import NilaiSetelan
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.internal_kamera import buat_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-setelan-e2e"
JALUR = "/api/console/dev/camera-settings"


def _line(settings: Settings, setelan: list | None) -> tuple[FastAPI, RuntimeState]:
    state, kamera = RuntimeState(), KameraPalsu()
    kamera.setelan = setelan
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))
    return app, state


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, console_line_host="http://line", internal_secret=SECRET)
    l1, l2, _l3 = settings.console_lines
    app_1, state_1 = _line(settings, [NilaiSetelan("exposure", 4000.0, 15.0, 9959540.0)])
    app_2, _ = _line(settings, None)
    henti = threading.Event()

    def _capture() -> None:
        while not henti.is_set():
            state_1.perintah_kamera.jalankan(state_1.lock)
            henti.wait(0.01)

    threading.Thread(target=_capture, daemon=True).start()
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(settings, store, LineClient(settings, transport=LinePerPort({l1.port: app_1, l2.port: app_2})))
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    yield app, store
    henti.set()


def test_support_melihat_setelan_tiap_line(pabrik):
    app, store = pabrik
    client = masuk(app, store, role=ROLE_SUPPORT)
    lines = client.get(JALUR).json()["lines"]
    assert lines["line-1"]["terjangkau"] is True
    assert lines["line-1"]["setelan"][0]["nilai"] == 4000.0
    assert lines["line-2"] == {"terjangkau": False, "sebab_kode": "bukan_kamera"}
    assert lines["line-3"]["terjangkau"] is False


def test_operator_ditolak(pabrik):
    app, store = pabrik
    assert masuk(app, store, role=ROLE_OPERATOR).get(JALUR).status_code == 403
