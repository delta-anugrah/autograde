"""End-to-end: app konsol yang sebenarnya menolak start dengan secret bawaan."""
from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from uvicorn.lifespan.on import LifespanOn
from uvicorn_tanpa_socket import konfigurasi

from palmgrade import console_main
from palmgrade.core.config import _DEFAULT_WEBHOOK_SECRET, Settings
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes import console_deps
from palmgrade.services.console_service import ConsoleService


def test_konsol_produksi_secret_bawaan_tidak_pernah_melayani(tmp_path, monkeypatch):
    settings = Settings(
        repo_root=tmp_path, environment="production", webhook_secret=_DEFAULT_WEBHOOK_SECRET,
        internal_secret=_DEFAULT_WEBHOOK_SECRET, console_default_hash="", console_support_hash="", erp_url="",
    )
    service = ConsoleService(settings, ConsoleStore(settings.console_db_path), LineClient(settings))
    monkeypatch.setattr(console_main, "get_console_service", lambda: service)
    akar = logging.getLogger()
    semula = list(akar.handlers)
    try:
        app = console_main.create_console_app()
        with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
            with TestClient(app):
                pass
    finally:
        akar.handlers = semula


def test_penolakan_start_sampai_tab_log_dengan_traceback(tmp_path, monkeypatch):
    """Start yang gagal sengaja TIDAK melepas logging konsol (batch 3.1).

    uvicorn menulis traceback penolakan SESUDAH lifespan melempar, lewat
    `uvicorn.error`. Karena pemasangan konsol masih terpasang, baris itu sampai tab
    Log, tempat support membacanya sesudah container menyerah. Boot dijalankan lewat
    `LifespanOn` uvicorn yang sungguhan, sama dengan `entrypoint.sh`. Pemasangan yang
    tertinggal dilepas `tests/conftest.py` sesudah test.
    """
    settings = Settings(
        repo_root=tmp_path, environment="production", webhook_secret=_DEFAULT_WEBHOOK_SECRET,
        internal_secret=_DEFAULT_WEBHOOK_SECRET, console_default_hash="", console_support_hash="", erp_url="",
    )
    service = ConsoleService(settings, ConsoleStore(settings.console_db_path), LineClient(settings))
    monkeypatch.setattr(console_main, "get_console_service", lambda: service)
    monkeypatch.setattr(console_deps, "get_console_service", lambda: service)
    lifespan = LifespanOn(konfigurasi(console_main.create_console_app(), lifespan="on"))

    asyncio.run(lifespan.startup())

    assert lifespan.should_exit
    rows = LogStore(settings.log_db_path).read(level="ERROR", search=None, limit=20, offset=0)["items"]
    dari_uvicorn = [r["message"] for r in rows if r["source"] == "uvicorn.error"]
    assert "Application startup failed. Exiting." in dari_uvicorn
    [traceback] = [m for m in dari_uvicorn if m.startswith("Traceback")]
    assert "RuntimeError" in traceback and "WEBHOOK_SECRET" in traceback
