"""End-to-end: app konsol yang sebenarnya menolak start dengan secret bawaan."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from palmgrade import console_main
from palmgrade.core.config import _DEFAULT_WEBHOOK_SECRET, Settings
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
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
