"""Settings asks the lines for the PC's own detection box (2026-10-05), through the real parts:
the console route, `roi_bawaan`, `LineClient` and three line apps behind `LinePerPort`."""
from __future__ import annotations

from dataclasses import replace

import pytest
from antrean_line_rakit import LinePerPort
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.routes import console_roi_bawaan
from palmgrade.routes.console_deps import get_console_service, require_support

LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
    LineEndpoint("line-3", "Line 3", 8003, "m-3"),
)


def _line(roi_env: list[int] | None) -> FastAPI:
    app = FastAPI()

    @app.get("/internal/setelan")
    async def setelan() -> dict:
        jawab = {"conf_threshold": 0.75, "minimum_size": 460000, "sumber": "env"}
        return jawab if roi_env is None else {**jawab, "roi_env": roi_env}

    return app


def _menolak() -> FastAPI:
    app = FastAPI()

    @app.get("/internal/setelan")
    async def setelan() -> dict:
        raise HTTPException(status_code=401, detail="kunci")

    return app


class _Layanan:
    def __init__(self, apps: dict[int, FastAPI]) -> None:
        self.lines = LINES
        self.line_client = LineClient(
            replace(Settings(), console_line_host="http://line", internal_secret="rahasia"),
            transport=LinePerPort(apps),
        )


def _konsol(apps: dict[int, FastAPI], *, support: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(console_roi_bawaan.router)
    app.dependency_overrides[get_console_service] = lambda: _Layanan(apps)
    if support:
        app.dependency_overrides[require_support] = lambda: {"email": "support@test", "role": "support"}
    return TestClient(app)


def test_kotak_bawaan_dari_line_pertama_yang_menjawab():
    """Line 1 is down, line 2 refuses the key, line 3 answers."""
    konsol = _konsol({8002: _menolak(), 8003: _line([100, 100, 1180, 620])})

    res = konsol.get("/api/console/dev/roi-bawaan")

    assert res.status_code == 200, res.text
    assert res.json() == {"roi_x1": 100, "roi_y1": 100, "roi_x2": 1180, "roi_y2": 620, "line_code": "line-3"}


def test_line_versi_lama_menjawab_tanpa_kotak_berarti_belum_diketahui():
    konsol = _konsol({8001: _line(None), 8002: _line(None), 8003: _line(None)})

    assert konsol.get("/api/console/dev/roi-bawaan").json()["roi_x1"] is None


@pytest.mark.parametrize("support", [False])
def test_tanpa_akun_support_ditolak(support):
    konsol = _konsol({8001: _line([0, 0, 0, 0])}, support=support)

    assert konsol.get("/api/console/dev/roi-bawaan").status_code in (401, 403)
