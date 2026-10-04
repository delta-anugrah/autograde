"""Integration: Lepas paksa over real HTTP, from the signed-in route to a line that holds
its truck in memory (2026-10-04).

Signed-in console route, real `LineClient`, real `ConsoleService` and `LineStatusWorker`.
The line is a stand-in app with the real `AssignmentSyncRequest` (it turns the empty
release into None, as the line does) behind a transport that can drop every request, the
way a stopped container or a cut cable looks to httpx. The line router itself pulls torch.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.schemas.internal_schema import AssignmentSyncRequest
from palmgrade.services import lepas_paksa as layanan
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers.line_status_worker import LineStatusWorker

SANDI = "sawit2026"
PLAT = "BE 7 PKS"


class LineDiMemori:
    """What one line remembers: the truck it stamps on the next bunches."""

    def __init__(self) -> None:
        self.truck_id: str | None = None
        self.menolak = False
        self.app = FastAPI()

        @self.app.post("/internal/assignment")
        def assignment(body: AssignmentSyncRequest) -> dict:
            if self.menolak:
                raise HTTPException(status_code=409, detail="sibuk")
            self.truck_id = body.truck_id
            return {"accepted": True}

        @self.app.get("/internal/status")
        def status() -> dict:
            return {"truck_id": self.truck_id, "piston": {}, "alarms": []}


class Kabel(httpx.AsyncBaseTransport):
    """The network between the console and the line: `putus` drops every request."""

    def __init__(self, line: LineDiMemori) -> None:
        self.putus = False
        self._asgi = httpx.ASGITransport(app=line.app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.putus:
            raise httpx.ConnectError("connection refused", request=request)
        return await self._asgi.handle_async_request(request)


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(Settings(), console_line_host="http://line", factory_tz="Asia/Jakarta")
    line = LineDiMemori()
    kabel = Kabel(line)
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "budi@pks.test", "full_name": "Pak Budi", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, LineClient(settings, transport=kabel))
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": "budi@pks.test", "sandi": SANDI}).status_code == 200
    truk = service.register_manual_truck(PLAT)
    assert client.post("/api/console/lines/line-1/assign-truck", json={"truck_id": truk["id"]}).status_code == 200
    assert line.truck_id == truk["id"]
    # Only line-1 is reachable through this cable; the worker polls just that one.
    worker = LineStatusWorker(service.lines[:1], service.line_client, sesudah_terbaca=service.cocokkan_lepas_paksa)
    return client, service, line, kabel, worker, truk["id"]


def _kartu(client) -> dict:
    return next(k for k in client.get("/api/console/state").json()["lines"] if k["line_code"] == "line-1")


def test_a_dead_line_refuses_lepas_but_lepas_paksa_frees_it(pabrik):
    client, service, _line, kabel, _worker, _truk = pabrik
    kabel.putus = True

    assert client.post("/api/console/lines/line-1/release-truck").status_code == 502
    jawab = client.post("/api/console/lines/line-1/force-release")

    assert jawab.status_code == 200, jawab.text
    assert jawab.json()["paksa"] is True
    assert _kartu(client)["assignment"] is None
    # A line that starts again pulls this, and it is empty now.
    assert service.penugasan_untuk_mesin(service.lines[0].machine_id)["truck_id"] == ""


def test_a_line_cut_off_but_alive_is_released_again_once_it_answers(pabrik, caplog):
    client, _service, line, kabel, worker, truck_id = pabrik
    kabel.putus = True
    client.post("/api/console/lines/line-1/force-release")
    assert line.truck_id == truck_id, "cut off, the line still stamps the departed truck"

    kabel.putus = False
    with caplog.at_level(logging.WARNING, logger=layanan.__name__):
        asyncio.run(worker.run_once())

    assert line.truck_id is None
    assert any(PLAT in r.getMessage() for r in caplog.records)
    assert worker.snapshot()["line-1"]["reachable"] is True


def test_a_line_that_refuses_is_not_forced(pabrik):
    client, _service, line, _kabel, _worker, truck_id = pabrik
    line.menolak = True

    jawab = client.post("/api/console/lines/line-1/force-release")

    assert jawab.status_code == 502
    assert jawab.json()["detail"]["code"] == "line_menolak"
    assert _kartu(client)["assignment"]["truck_id"] == truck_id


def test_a_line_that_answers_is_released_normally(pabrik):
    client, _service, line, _kabel, _worker, _truk = pabrik

    jawab = client.post("/api/console/lines/line-1/force-release")

    assert jawab.status_code == 200 and jawab.json()["paksa"] is False
    assert line.truck_id is None
    assert _kartu(client)["assignment"] is None
