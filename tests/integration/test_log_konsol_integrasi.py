"""Integrasi batch 3.1: lifespan konsol sungguhan -> configure_logging -> stderr + tab Log.

Settings asli, `ConsoleService` asli, `LogStore` SQLite di `tmp_path`, lifespan asli.
Membuktikan tiga hal yang dulu tidak terjadi: INFO konsol sampai keluaran proses,
WARNING konsol sampai keluaran proses DAN tab Log, dan galat uvicorn sampai tab Log
dengan tracebacknya. Plus: sesudah lifespan selesai semuanya dilepas lagi.
"""
from __future__ import annotations

import asyncio
import logging
import logging.config

import uvicorn.config
from fastapi import FastAPI

from palmgrade import console_main
from palmgrade.core.config import Settings
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes import console_deps
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue

_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _service(tmp_path) -> ConsoleService:
    settings = Settings(
        repo_root=tmp_path, console_default_hash="", console_support_hash="", erp_url="",
        factory_tz="Asia/Jakarta", log_level="INFO",
    )
    store = ConsoleStore(settings.console_db_path)
    erp_queue = ErpQueue(store, ErpOutboxStore(settings.erp_outbox_db_path))
    return ConsoleService(settings, store, LineClient(settings), erp_queue=erp_queue)


def _jalankan(service: ConsoleService, selama) -> None:
    asli, asli_deps = console_main.get_console_service, console_deps.get_console_service
    console_main.get_console_service = lambda: service
    console_deps.get_console_service = lambda: service
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    console_deps.get_lapor_discord.cache_clear()
    try:
        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                selama()

        asyncio.run(_runner())
    finally:
        console_main.get_console_service, console_deps.get_console_service = asli, asli_deps
        console_deps.get_auth_service.cache_clear()
        console_deps.get_dev_service.cache_clear()
        console_deps.get_lapor_discord.cache_clear()


def test_konsol_menulis_ke_keluaran_proses_dan_tab_log(tmp_path, capsys):
    semula = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate) for n in _UVICORN}
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)  # uvicorn memasang dulu, seperti saat boot
    root = logging.getLogger()
    handler_semula, level_semula = list(root.handlers), root.level
    service = _service(tmp_path)

    def selama() -> None:
        logging.getLogger("palmgrade.uji").info("info konsol")
        logging.getLogger("palmgrade.uji").warning("peringatan konsol")
        try:
            raise RuntimeError("route meledak")
        except RuntimeError as exc:
            logging.getLogger("uvicorn.error").error("Exception in ASGI application\n", exc_info=exc)

    try:
        _jalankan(service, selama)
        keluaran = capsys.readouterr().err
        rows = LogStore(service.settings.log_db_path).read(level=None, search=None, limit=20, offset=0)["items"]

        assert "+07:00 | INFO | console | palmgrade.uji | info konsol" in keluaran
        assert "| WARNING | console | palmgrade.uji | peringatan konsol" in keluaran
        pesan = {r["message"]: r for r in rows}
        assert "peringatan konsol" in pesan
        assert "info konsol" not in pesan
        galat = pesan["Exception in ASGI application\n"]
        assert galat["source"] == "uvicorn.error" and "route meledak" in galat["detail"]
        # Dilepas lagi: root dan uvicorn kembali seperti sebelum lifespan.
        assert root.handlers == handler_semula and root.level == level_semula
        assert logging.getLogger("uvicorn").propagate is False
    finally:
        for nama, (handlers, propagate) in semula.items():
            logging.getLogger(nama).handlers, logging.getLogger(nama).propagate = handlers, propagate
