"""Suhu kamera dari capture worker line sampai jawaban `/api/console/dev/diagnostik` konsol.

Line ASLI (`HealthService` + `FrameCaptureWorker` di `LinePalsu`, dijawab sebagai
`HealthDetailSchema` seperti `routes/health.py`), konsol ASLI (`LineClient` + `DevService`),
disambung `httpx.ASGITransport` tanpa jaringan. Rutenya dirakit di sini, bukan di-import:
`routes/health.py` menarik `core.dependencies`, yang meng-import torch (CI tidak punya).
"""
from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import replace

import httpx
import pytest
from ai_palsu import LinePalsu
from fastapi import FastAPI

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.log_repository import LogStore
from palmgrade.schemas.common_schema import HealthDetailSchema
from palmgrade.services.dev_service import DevService
from palmgrade.services.health_service import HealthService

LINE_1 = LineEndpoint("line-1", "Line 1", 8001, "m-1")


class _Outbox:
    def pending_count(self):
        return 0

    def failed_count(self):
        return 0


@pytest.fixture
def torch_palsu(monkeypatch):
    cuda = types.SimpleNamespace(is_available=lambda: False, get_device_name=lambda _i: "-")
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))


def _diagnostik(tmp_path, line: LinePalsu) -> dict:
    health = HealthService(settings=line.settings, state=line.state, camera=line.kamera, outbox=_Outbox())
    app = FastAPI()

    @app.get("/health/detail", response_model=HealthDetailSchema)
    async def detail() -> HealthDetailSchema:
        return health.get_health_detail()

    settings = replace(Settings(), repo_root=tmp_path)
    dev = DevService(
        LogStore(tmp_path / "log.db"),
        line_client=LineClient(settings, transport=httpx.ASGITransport(app=app)),
        lines=(LINE_1,),
        settings=settings,
    )
    return asyncio.run(dev.diagnostics())["lines"]["line-1"]


def test_suhu_sampai_ke_jawaban_diagnostik_konsol(tmp_path, torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.kamera.suhu = 47.3
    line.jalan(3)
    kartu = _diagnostik(tmp_path, line)
    assert kartu["terjangkau"] is True
    assert kartu["suhu_kamera_c"] == 47.3


def test_suhu_basi_sampai_konsol_sebagai_null(tmp_path, torch_palsu):
    line = LinePalsu()
    line.mulai()
    line.kamera.suhu = 47.3
    line.jalan(1)
    line.jam.sekarang += 120
    assert _diagnostik(tmp_path, line)["suhu_kamera_c"] is None
