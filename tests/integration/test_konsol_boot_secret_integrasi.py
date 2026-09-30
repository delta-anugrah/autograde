"""Integrasi: Settings -> lifespan konsol sungguhan -> SqliteLogHandler -> tab Log.

Membuktikan bahwa peringatan INTERNAL_SECRET dari `validate_secrets()` benar-benar
mendarat di `event_log` (tab Log yang dibaca support), bukan cuma di stdout, karena
`validate_secrets()` dipanggil SESUDAH `configure_logging` memasang `SqliteLogHandler`.
"""
from __future__ import annotations

import asyncio
import logging

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


def _run_lifespan(service: ConsoleService) -> None:
    # Patched on both modules: the singletons the lifespan warms call it by
    # `console_deps`'s name, and the real one would open the developer's state/.
    original = console_main.get_console_service
    original_deps = console_deps.get_console_service
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    console_main.get_console_service = lambda: service
    console_deps.get_console_service = lambda: service
    _kosongkan_singleton()
    try:
        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                pass

        asyncio.run(_runner())
    finally:
        console_main.get_console_service = original
        console_deps.get_console_service = original_deps
        _kosongkan_singleton()
        root.handlers = original_handlers


def _kosongkan_singleton() -> None:
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()


def test_peringatan_internal_secret_mendarat_di_tab_log(tmp_path):
    settings = Settings(
        repo_root=tmp_path,
        environment="production",
        webhook_secret="kunci-palsu-w",
        internal_secret="kunci-palsu-w",
        console_default_hash="",
        console_support_hash="",
        erp_url="",
    )
    store = ConsoleStore(settings.console_db_path)
    erp_queue = ErpQueue(store, ErpOutboxStore(settings.erp_outbox_db_path))
    service = ConsoleService(settings, store, LineClient(settings), erp_queue=erp_queue)

    _run_lifespan(service)

    log_store = LogStore(settings.log_db_path)
    hasil = log_store.read(level="WARNING", search="INTERNAL_SECRET", limit=10, offset=0)
    assert len(hasil["items"]) == 1
