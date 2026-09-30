"""End-to-end batch 3A: yang dilihat support di `docker logs` dan di tab Log.

App konsol yang SUNGGUHAN (`create_console_app`, lifespan asli, SQLite di `tmp_path`)
dilayani lewat protokol HTTP uvicorn yang SUNGGUHAN tanpa socket
(`tests/uvicorn_tanpa_socket.py`), jadi baris access log dan "Exception in ASGI
application" ditulis uvicorn sendiri, bukan ditiru test:

1. Route yang meledak (500) sampai tab Log dengan traceback, dan terbaca support
   lewat `GET /api/console/dev/log` sesudah konsol restart.
2. Polling yang sukses tidak tertulis di access log; 401 dan 500 tertulis.
3. AutoERP tidak terjangkau seharian: tab Log berisi satu baris master data, bukan 288.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from uvicorn_tanpa_socket import konfigurasi, minta

from palmgrade import console_main
from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console_deps
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.master_data_worker import MasterDataWorker

SANDI = "sandi-e2e-log-3a"
_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture
def konsol(tmp_path, monkeypatch):
    settings = Settings(
        repo_root=tmp_path, console_default_hash="", console_support_hash="", erp_url="",
        factory_tz="Asia/Jakarta", log_level="INFO",
    )
    store = ConsoleStore(settings.console_db_path)
    store.upsert_operator_manual(
        {"email": "support@pks.test", "nama": "Support", "password_hash": hash_password(SANDI), "role": ROLE_SUPPORT}
    )
    service = ConsoleService(
        settings, store, LineClient(settings), erp_queue=ErpQueue(store, ErpOutboxStore(settings.erp_outbox_db_path))
    )
    monkeypatch.setattr(console_main, "get_console_service", lambda: service)
    monkeypatch.setattr(console_deps, "get_console_service", lambda: service)
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    semula = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate) for n in _UVICORN}
    root = logging.getLogger()
    handler_root, level_root = list(root.handlers), root.level
    app = console_main.create_console_app()

    @app.get("/api/uji/meledak")
    def meledak() -> None:
        raise RuntimeError("uji meledak di route konsol")

    yield app, service
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    root.handlers, root.level = handler_root, level_root
    for nama, (handlers, propagate) in semula.items():
        logging.getLogger(nama).handlers, logging.getLogger(nama).propagate = handlers, propagate


def _layani(app, permintaan: list[str]) -> list[int]:
    """Boot seperti produksi: uvicorn memasang log-nya, lalu lifespan app, lalu permintaan."""
    config = konfigurasi(app)

    async def _jalan() -> list[int]:
        async with console_main.lifespan(app):
            return [await minta(config, jalur) for jalur in permintaan]

    return asyncio.run(_jalan())


def _baca_tab_log(app, cari: str) -> list[dict]:
    with TestClient(app) as client:
        assert client.post("/api/console/login", json={"email": "support@pks.test", "sandi": SANDI}).status_code == 200
        jawab = client.get("/api/console/dev/log", params={"cari": cari})
        assert jawab.status_code == 200, jawab.text
        return jawab.json()["items"]


def test_galat_500_sampai_tab_log_dengan_traceback(konsol):
    app, _ = konsol
    assert _layani(app, ["/api/uji/meledak"]) == [500]

    [baris] = _baca_tab_log(app, "ASGI")

    assert baris["level"] == "ERROR" and baris["source"] == "uvicorn.error"
    assert "uji meledak di route konsol" in baris["detail"]


def test_polling_sukses_diam_galat_tertulis_di_docker_logs(konsol, capsys):
    app, _ = konsol
    kode = _layani(app, ["/health", "/health", "/api/console/state", "/api/uji/meledak"])
    keluaran = capsys.readouterr().err

    assert kode == [200, 200, 401, 500]
    akses = [b for b in keluaran.splitlines() if "| uvicorn.access |" in b]
    assert len(akses) == 2, akses
    assert '"GET /api/console/state HTTP/1.1" 401' in akses[0] and "| console |" in akses[0]
    assert '"GET /api/uji/meledak HTTP/1.1" 500' in akses[1] and "+07:00" in akses[1]


def test_autoerp_mati_seharian_satu_baris_master_data_di_tab_log(konsol):
    app, service = konsol

    def mati(_request):
        raise httpx.ConnectError("[Errno 113] No route to host")

    worker = MasterDataWorker(
        service.store, ErpClient("http://erp.local", "k", "s", transport=httpx.MockTransport(mati)),
        interval_s=300, status=service.status_sinkron,
    )

    async def _jalan() -> None:
        async with console_main.lifespan(app):
            for _ in range(288):
                await worker.run_once()

    asyncio.run(_jalan())

    baris = _baca_tab_log(app, "Master data")
    assert len(baris) == 1 and baris[0]["count"] == 1
    assert "jaringan" in baris[0]["message"]
