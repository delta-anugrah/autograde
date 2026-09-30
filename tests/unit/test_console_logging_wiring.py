"""Lifespan konsol memasang logging dengan konteks, zona, level, dan tab Log, lalu melepasnya.

`console_main` tidak menarik torch, jadi ini jalan di CI (beda dengan
`test_main_logging_wiring.py`). `configure_logging` diganti perekam supaya yang
diuji pemasangannya dari lifespan: argumen apa, sebelum `validate_secrets()`, dan
dilepas sekali di akhir. Perilaku logging sungguhannya diuji
`tests/integration/test_log_konsol_integrasi.py`.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI

from palmgrade import console_main
from palmgrade.core.config import _DEFAULT_WEBHOOK_SECRET, Settings
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.core.logging import KONTEKS_KONSOL
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes import console_deps
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue


class _Pemasangan:
    def __init__(self) -> None:
        self.dilepas = 0

    def lepas(self) -> None:
        self.dilepas += 1


class _Perekam:
    """Pengganti `configure_logging`: mencatat argumen, tidak memasang apa pun."""

    def __init__(self) -> None:
        self.panggilan: list[tuple[tuple, dict]] = []
        self.pemasangan = _Pemasangan()

    def __call__(self, *args, **kwargs) -> _Pemasangan:
        self.panggilan.append((args, kwargs))
        return self.pemasangan


def _service(tmp_path, **setelan) -> ConsoleService:
    settings = Settings(
        repo_root=tmp_path, console_default_hash="", console_support_hash="", erp_url="",
        factory_tz="Asia/Makassar", log_level="ERROR", **setelan,
    )
    store = ConsoleStore(settings.console_db_path)
    erp_queue = ErpQueue(store, ErpOutboxStore(settings.erp_outbox_db_path))
    return ConsoleService(settings, store, LineClient(settings), erp_queue=erp_queue)


@pytest.fixture
def jalankan(monkeypatch):
    perekam = _Perekam()
    monkeypatch.setattr(console_main, "configure_logging", perekam)
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    console_deps.get_lapor_discord.cache_clear()

    def _jalankan(service: ConsoleService, selama=lambda: None) -> None:
        monkeypatch.setattr(console_main, "get_console_service", lambda: service)
        monkeypatch.setattr(console_deps, "get_console_service", lambda: service)

        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                selama()

        asyncio.run(_runner())

    yield _jalankan, perekam
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    console_deps.get_lapor_discord.cache_clear()


def test_lifespan_memasang_logging_konsol_dengan_zona_level_dan_tab_log(tmp_path, jalankan):
    jalan, perekam = jalankan
    service = _service(tmp_path)
    selama_hidup = {}

    jalan(service, lambda: selama_hidup.setdefault("dilepas", perekam.pemasangan.dilepas))

    [(args, kwargs)] = perekam.panggilan
    assert args == ()
    handler = kwargs.pop("handler_tambahan")
    assert kwargs == {"konteks": KONTEKS_KONSOL, "zona": "Asia/Makassar", "level": "ERROR"}
    [sink] = handler
    assert isinstance(sink, SqliteLogHandler)
    # Handler tab Log menulis ke berkas log konsol itu sendiri, bukan ke tempat lain.
    sink.handle(logging.makeLogRecord({"name": "palmgrade.uji", "levelno": logging.WARNING,
                                       "levelname": "WARNING", "msg": "tanda uji wiring"}))
    [baris] = LogStore(service.settings.log_db_path).read(
        level=None, search="tanda uji wiring", limit=5, offset=0)["items"]
    assert baris["source"] == "palmgrade.uji"
    # Dilepas sekali, dan baru sesudah lifespan selesai, bukan selama konsol melayani.
    assert selama_hidup == {"dilepas": 0}
    assert perekam.pemasangan.dilepas == 1


def test_logging_sudah_terpasang_sebelum_secret_diperiksa(tmp_path, jalankan):
    """Secret bawaan di produksi menolak start; peringatannya harus sudah punya jalan ke tab Log."""
    jalan, perekam = jalankan
    service = _service(
        tmp_path, environment="production",
        webhook_secret=_DEFAULT_WEBHOOK_SECRET, internal_secret=_DEFAULT_WEBHOOK_SECRET,
    )

    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        jalan(service)

    assert len(perekam.panggilan) == 1
