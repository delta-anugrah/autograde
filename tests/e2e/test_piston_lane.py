"""End-to-end: the piston lane on a real console app.

Same shape as `test_dev_plc_lane.py`: a real session cookie from a real login
and `get_console_service` resolving to a real `ConsoleService`, not
`create_console_app()`, which would reach for a developer's own `state/*.db`.

Batch 1.1: `/piston` was the only operator lane that forgot the session
dependency. Every scenario here proves the fix end to end: an operator can
press it under their own name, a session that ends locks it out again, and a
line that does not answer still leaves a trail.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.domain.role import ROLE_OPERATOR
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sokongan2026"


class _LinePiston:
    def __init__(self, *, mati: bool = False) -> None:
        self.mati = mati
        self.perintah: list[tuple[str, bool, str]] = []

    async def set_piston(self, line, *, open, requested_by, requested_at):
        if self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab", line=line.name)
        self.perintah.append((line.line_code, open, requested_by))


@pytest.fixture
def gerbang(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log_store = LogStore(tmp_path / "log.db")
    store.upsert_operator_manual(
        {
            "email": "operator@pks.test",
            "full_name": "Operator Biasa",
            "password_hash": hash_password(SANDI),
            "role": ROLE_OPERATOR,
        }
    )
    line_client = _LinePiston()
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, store, line_client)

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return TestClient(app), store, log_store, line_client


def _masuk(client: TestClient, email: str = "operator@pks.test") -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_operator_biasa_bisa_membuka_piston_atas_namanya(gerbang):
    client, _, log_store, line_client = gerbang
    svc_logger = logging.getLogger("palmgrade.services.console_service")
    svc_logger.handlers.clear()
    svc_logger.setLevel(logging.DEBUG)
    svc_logger.addHandler(SqliteLogHandler(log_store))
    svc_logger.propagate = False
    try:
        _masuk(client)

        jawab = client.post("/api/console/lines/line-1/piston", json={"open": True})

        assert jawab.status_code == 200
        assert line_client.perintah == [("line-1", True, "Operator Biasa")]

        baris = log_store.read(level="WARNING", search="Piston", limit=10, offset=0)["items"]
        assert len(baris) == 1
        assert "Operator Biasa" in baris[0]["message"]
    finally:
        svc_logger.handlers.clear()


def test_sesudah_logout_piston_ditolak(gerbang):
    client, _, _, line_client = gerbang
    _masuk(client)
    assert client.post("/api/console/logout").status_code == 200

    jawab = client.post("/api/console/lines/line-1/piston", json={"open": True})

    assert jawab.status_code == 401
    assert line_client.perintah == []


def test_line_mati_502_tetap_tercatat(gerbang):
    client, _, log_store, line_client = gerbang
    line_client.mati = True
    svc_logger = logging.getLogger("palmgrade.services.console_service")
    svc_logger.handlers.clear()
    svc_logger.setLevel(logging.DEBUG)
    svc_logger.addHandler(SqliteLogHandler(log_store))
    svc_logger.propagate = False
    try:
        _masuk(client)

        jawab = client.post("/api/console/lines/line-1/piston", json={"open": True})

        assert jawab.status_code == 502

        baris = log_store.read(level="WARNING", search="Piston", limit=10, offset=0)["items"]
        assert len(baris) == 1
    finally:
        svc_logger.handlers.clear()
