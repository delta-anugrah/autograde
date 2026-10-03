"""End-to-end: Sambung ulang on a line card, console route to the real line route.

The console app runs its real routes with a real login; `LineClient` reaches the real
line router (`routes/internal_kamera.py`) in-process over `httpx.ASGITransport`. Line 2
is a video source, line 3 is down.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from ai_palsu import KameraPalsu
from antrean_line_rakit import LinePerPort, masuk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import BELUM_MASUK
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.routes.internal_kamera import buat_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-sambung-ulang-e2e"


def _line(settings: Settings, *, kamera_asli: bool) -> tuple[FastAPI, RuntimeState]:
    state = RuntimeState()
    kamera = KameraPalsu()
    kamera.bisa_sambung_ulang = kamera_asli
    app = FastAPI()
    app.include_router(buat_router(settings=lambda: settings, state=lambda: state, kamera=lambda: kamera))
    return app, state


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(
        Settings(), repo_root=tmp_path, console_line_host="http://line", internal_secret=SECRET,
    )
    l1, l2, l3 = settings.console_lines
    app_1, state_1 = _line(settings, kamera_asli=True)
    app_2, state_2 = _line(settings, kamera_asli=False)
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(
        settings, store, LineClient(settings, transport=LinePerPort({l1.port: app_1, l2.port: app_2}))
    )
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return app, store, {l1.line_code: state_1, l2.line_code: state_2}


def _jalur(kode: str) -> str:
    return f"/api/console/lines/{kode}/reconnect-camera"


@pytest.mark.parametrize("role", [ROLE_OPERATOR, ROLE_SUPPORT])
def test_every_account_may_ask_and_the_line_gets_the_name(pabrik, role):
    app, store, states = pabrik
    jawab = masuk(app, store, role=role).post(_jalur("line-1"))
    assert jawab.status_code == 202, jawab.text
    assert jawab.json() == {"line_code": "line-1", "status": "requested"}
    assert states["line-1"].ambil_permintaan_sambung_ulang() == role.title()


def test_without_a_session_401_and_the_line_hears_nothing(pabrik):
    app, _, states = pabrik
    jawab = TestClient(app).post(_jalur("line-1"))
    assert (jawab.status_code, jawab.json()["detail"]["code"]) == (401, BELUM_MASUK)
    assert states["line-1"].ambil_permintaan_sambung_ulang() is None


def test_a_video_line_answers_409_with_the_code_and_line_name(pabrik):
    app, store, states = pabrik
    jawab = masuk(app, store, role=ROLE_OPERATOR).post(_jalur("line-2"))
    detail = jawab.json()["detail"]
    assert (jawab.status_code, detail["code"], detail["params"]["line"]) == (
        409, "kamera_tanpa_sambung_ulang", "Line 2",
    )
    assert states["line-2"].ambil_permintaan_sambung_ulang() is None


def test_a_line_that_is_down_answers_502_line_tidak_menjawab(pabrik):
    app, store, _ = pabrik
    jawab = masuk(app, store, role=ROLE_OPERATOR).post(_jalur("line-3"))
    detail = jawab.json()["detail"]
    assert (jawab.status_code, detail["code"], detail["params"]["line"]) == (502, "line_tidak_menjawab", "Line 3")


def test_an_unknown_line_answers_404(pabrik):
    app, store, _ = pabrik
    jawab = masuk(app, store, role=ROLE_OPERATOR).post(_jalur("line-9"))
    assert (jawab.status_code, jawab.json()["detail"]["code"]) == (404, "line_tidak_dikenal")


def test_a_different_key_answers_502_line_menolak(tmp_path):
    settings = replace(Settings(), console_line_host="http://line", internal_secret=SECRET)
    line_settings = replace(settings, internal_secret="kunci-lain")
    app_1, _ = _line(line_settings, kamera_asli=True)
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(
        settings, store,
        LineClient(settings, transport=LinePerPort({settings.console_lines[0].port: app_1})),
    )
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    jawab = masuk(app, store, role=ROLE_OPERATOR).post(_jalur("line-1"))
    assert (jawab.status_code, jawab.json()["detail"]["code"]) == (502, "line_menolak")
