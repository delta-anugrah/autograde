"""End-to-end: lane tab Status → Antrean line pada app konsol sungguhan dengan sesi login.

Sama bentuknya dengan `test_dev_diagnostik_lane.py`: login sungguhan, role dari store
yang sama, dan line di balik `LineClient` sungguhan (router line asli, transport ASGI).
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from antrean_line_rakit import LinePerPort, app_konsol, klien_konsol_mati, masuk, rakit_line
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.operator_error import BELUM_MASUK, BUKAN_SUPPORT
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.pantau_antrean_line import PantauAntreanLine

SECRET = "kunci-internal-e2e"
LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")
LINE_2 = LineEndpoint("line-2", "Line 2", 8002, "m-2")  # mati
JALUR = ("get", "/api/console/dev/antrean/line"), ("post", "/api/console/dev/antrean/line/line-1/kirim-ulang")


@pytest.fixture
def konsol(tmp_path):
    line_1 = rakit_line(tmp_path / "line-1", internal_secret=SECRET, klien_konsol=klien_konsol_mati())
    klien = LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret=SECRET),
        transport=LinePerPort({8001: line_1.app}),
    )
    store = ConsoleStore(tmp_path / "console.db")
    return app_konsol(store, PantauAntreanLine(klien, (LINE_1, LINE_2))), store


@pytest.mark.parametrize("metode,jalur", JALUR)
def test_support_boleh(konsol, metode, jalur):
    app, store = konsol
    assert getattr(masuk(app, store, role=ROLE_SUPPORT), metode)(jalur).status_code == 200


@pytest.mark.parametrize("metode,jalur", JALUR)
def test_operator_biasa_403(konsol, metode, jalur):
    app, store = konsol
    jawab = getattr(masuk(app, store, role=ROLE_OPERATOR), metode)(jalur)
    assert (jawab.status_code, jawab.json()["detail"]["code"]) == (403, BUKAN_SUPPORT)


@pytest.mark.parametrize("metode,jalur", JALUR)
def test_tanpa_sesi_401(konsol, metode, jalur):
    app, _ = konsol
    jawab = getattr(TestClient(app), metode)(jalur)
    assert (jawab.status_code, jawab.json()["detail"]["code"]) == (401, BELUM_MASUK)


def test_line_tak_dikenal_404(konsol):
    app, store = konsol
    jawab = masuk(app, store, role=ROLE_SUPPORT).post("/api/console/dev/antrean/line/line-9/kirim-ulang")
    assert (jawab.status_code, jawab.json()["detail"]["code"]) == (404, "line_tidak_dikenal")


def test_kirim_ulang_ke_line_mati_502_dengan_kodenya(konsol):
    app, store = konsol
    jawab = masuk(app, store, role=ROLE_SUPPORT).post("/api/console/dev/antrean/line/line-2/kirim-ulang")
    detail = jawab.json()["detail"]
    assert (jawab.status_code, detail["code"], detail["params"]["line"]) == (502, "line_tidak_menjawab", "Line 2")
