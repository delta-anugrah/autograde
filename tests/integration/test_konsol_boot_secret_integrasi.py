"""Integrasi: Settings -> lifespan konsol sungguhan -> SqliteLogHandler -> tab Log.

Membuktikan bahwa peringatan INTERNAL_SECRET dari `validate_secrets()` benar-benar
mendarat di `event_log` (tab Log yang dibaca support), bukan cuma di stdout, karena
`validate_secrets()` dipanggil SESUDAH `install_log_sink`.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI

from palmgrade import console_main
from palmgrade.core.config import Settings
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.console_service import ConsoleService


def _run_lifespan(service: ConsoleService) -> None:
    original = console_main.get_console_service
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    console_main.get_console_service = lambda: service
    try:
        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                pass

        asyncio.run(_runner())
    finally:
        console_main.get_console_service = original
        root.handlers = original_handlers


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
    service = ConsoleService(settings, store, LineClient(settings))

    _run_lifespan(service)

    log_store = LogStore(settings.log_db_path)
    hasil = log_store.read(level="WARNING", search="INTERNAL_SECRET", limit=10, offset=0)
    assert len(hasil["items"]) == 1
