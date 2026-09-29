"""Integrasi tombol piston: sesi konsol sungguhan sampai body HTTP yang diterima line."""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SECRET = "kunci-piston-palsu"
SANDI = "sawit2026"


class _Line:
    def __init__(self) -> None:
        self.diterima: list[tuple[dict, str | None]] = []
        self.app = FastAPI()

        @self.app.post("/internal/piston")
        async def piston(request: Request, x_internal_secret: str | None = Header(None)):
            self.diterima.append((await request.json(), x_internal_secret))
            return {"ok": True}


@pytest.fixture
def pabrik(tmp_path):
    line = _Line()
    settings = replace(
        Settings(), repo_root=tmp_path, console_line_host="http://line",
        internal_secret=SECRET, factory_tz="Asia/Jakarta",
    )
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "budi@pks.test", "full_name": "Pak Budi", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(
        settings, store, LineClient(settings, transport=httpx.ASGITransport(app=line.app))
    )
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return TestClient(app), line, service


def test_tanpa_sesi_perintah_tidak_pernah_sampai_ke_line(pabrik):
    client, line, _ = pabrik

    assert client.post("/api/console/lines/line-1/piston", json={"open": True}).status_code == 401
    assert line.diterima == []


def test_dengan_sesi_line_menerima_nama_operator(pabrik):
    client, line, service = pabrik
    client.post("/api/console/login", json={"email": "budi@pks.test", "sandi": SANDI})

    jawab = client.post("/api/console/lines/line-1/piston", json={"open": True})

    assert jawab.status_code == 200
    body, secret = line.diterima[0]
    assert body["requested_by"] == "Pak Budi"
    assert body["machine_id"] == service.lines[0].machine_id
    assert body["open"] is True
    assert secret == SECRET
