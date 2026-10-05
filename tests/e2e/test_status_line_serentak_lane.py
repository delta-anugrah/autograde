"""End-to-end, batch 6.5: one stuck line no longer freezes the other line cards.

What the operator sees is `/api/console/state`, which reads the last status
`LineStatusWorker` recorded for each line. Before 6.5 the lines were read in turn, so while
line 2 hung until its timeout the card of line 3 behind it showed nothing new, round after
round.

Console side assembled like `console_main` (never `create_console_app()`): the real
`ConsoleService`, console routes with an operator login, `LineClient` and `LineStatusWorker`.
Lines: three small apps behind the in-process transport `LinePerPort`. The worker round runs
in its own thread and event loop, as it does beside the request handlers in the console.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace

import pytest
from antrean_line_rakit import LinePerPort
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers.line_status_worker import LineStatusWorker

SANDI = "sandi-e2e-status-serentak"
BATAS_TUNGGU_S = 5.0


def _line(tahan: threading.Event | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/internal/status")
    async def status() -> dict:
        while tahan is not None and not tahan.is_set():
            await asyncio.sleep(0.005)
        return {"truck_id": None, "ffb_source": None, "piston": {"requested": False}, "alarms": []}

    return app


@pytest.fixture
def pabrik(tmp_path):
    tahan = threading.Event()
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta",
                       console_line_host="http://line")
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": "operator@pks.test", "full_name": "Operator", "password_hash": hash_password(SANDI)}
    )
    ports = {line.line_code: line.port for line in settings.console_lines}
    klien_line = LineClient(settings, transport=LinePerPort({
        ports["line-1"]: _line(), ports["line-2"]: _line(tahan), ports["line-3"]: _line(),
    }))
    service = ConsoleService(settings, store, klien_line)
    worker = LineStatusWorker(service.lines, klien_line)
    service.line_status = worker.snapshot

    konsol = FastAPI()
    konsol.include_router(console_router)
    konsol.dependency_overrides[get_console_service] = lambda: service
    konsol.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    operator = TestClient(konsol)
    masuk = operator.post("/api/console/login", json={"email": "operator@pks.test", "sandi": SANDI})
    assert masuk.status_code == 200, masuk.text

    def kartu() -> dict[str, dict]:
        res = operator.get("/api/console/state")
        assert res.status_code == 200, res.text
        return {x["line_code"]: x for x in res.json()["lines"]}

    putaran = threading.Thread(target=lambda: asyncio.run(worker.run_once()), daemon=True)
    try:
        yield kartu, putaran, tahan
    finally:
        tahan.set()
        if putaran.is_alive():
            putaran.join(timeout=BATAS_TUNGGU_S)


def _terbaca(kartu_line: dict) -> bool:
    return bool((kartu_line.get("plc") or {}).get("reachable"))


def test_dua_kartu_line_tetap_terisi_selama_line_kedua_tersangkut(pabrik):
    kartu, putaran, tahan = pabrik
    putaran.start()

    tenggat = time.monotonic() + BATAS_TUNGGU_S
    while time.monotonic() < tenggat:
        layar = kartu()
        if _terbaca(layar["line-1"]) and _terbaca(layar["line-3"]):
            break
        time.sleep(0.01)

    assert _terbaca(layar["line-1"]), "line 1 never showed a status"
    assert _terbaca(layar["line-3"]), "line 3 waited behind the stuck line 2"
    assert not _terbaca(layar["line-2"]), "line 2 had not answered yet"

    tahan.set()
    putaran.join(timeout=BATAS_TUNGGU_S)
    assert not putaran.is_alive()
    assert _terbaca(kartu()["line-2"]), "line 2 answered, its card must follow"
