"""End-to-end Update now (batch 4.6): what an operator and support go through, from login.

Real login, real `PembaruanService` on a real folder, the log sink installed as the console
lifespan does, and the Log tab read through its own route. The host watcher is faked by
writing `result.json` and `status.json` exactly as sawit `autograde.sh _update-now` does
(`tulis_hasil`, then `tulis_status`). The screen half is `tests/browser/test_browser_pembaruan.py`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.log_sink import install_log_sink
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_dev_service,
    get_pembaruan_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService
from palmgrade.services.pembaruan_service import PERMINTAAN, STATUS, PembaruanService

SANDI = "sandi-e2e-pembaruan"
JAM = datetime(2026, 10, 20, 8, 0, tzinfo=timezone(timedelta(hours=7)))
STATUS_SIAP = {
    "schema": 1,
    "installed": "v1.22.0",
    "staged": "v1.22.1",
    "checked_at": "2026-10-20T07:00:00+07:00",
    "watcher": True,
}


class _StubConsole:
    """Assign without a line: the line half of assign-truck has its own lanes."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store

    def assignments(self) -> dict:
        return self.store.assignments()

    async def assign_truck(self, line_code: str, truck_id: str) -> dict:
        self.store.set_assignment(line_code, "a-1", truck_id)
        return {"assignment_id": "a-1", "truck_id": truck_id, "line_code": line_code}

    async def release_truck(self, line_code: str) -> dict:
        self.store.set_assignment(line_code, "a-1", "")
        return {"line_code": line_code}

    async def release_truck_by_operator(self, line_code: str) -> dict:
        """The Lepas route's entry since automatic assignment (rule 36): nothing queued here."""
        return {**await self.release_truck(line_code), "dipasang": []}


@pytest.fixture
def konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    log = LogStore(tmp_path / "log.db")
    sink = install_log_sink(log)
    folder = tmp_path / "update"
    folder.mkdir()
    (folder / STATUS).write_text(json.dumps(STATUS_SIAP))
    pembaruan = PembaruanService(folder, lambda: "v1.22.0", lambda: JAM)
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(log)
    app.dependency_overrides[get_pembaruan_service] = lambda: pembaruan
    for email, peran in (("op@pks.test", "operator"), ("support@pks.test", "support")):
        store.upsert_operator_manual({"email": email, "full_name": email, "password_hash": hash_password(SANDI)})
        store.set_role(store.operator_by_email(email)["id"], peran)
    yield app, folder
    logging.getLogger().removeHandler(sink)


def _masuk(app, email: str) -> TestClient:
    client = TestClient(app)
    res = client.post("/api/console/login", json={"email": email, "sandi": SANDI})
    assert res.status_code == 200, res.text
    return client


def _pesan_log(support: TestClient) -> list[str]:
    return [baris["message"] for baris in support.get("/api/console/dev/log").json()["items"]]


def test_alur_ditolak_dengan_truk_lalu_terpasang_dan_tercatat_sekali(konsol):
    app, folder = konsol
    op = _masuk(app, "op@pks.test")
    support = _masuk(app, "support@pks.test")

    # 1. A truck from the morning is still on line-2: refused, nothing for the watcher.
    assert op.post("/api/console/lines/line-2/assign-truck", json={"truck_id": "t-1"}).status_code == 200
    res = op.post("/api/console/update/install", json={"target": "v1.22.1"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_ada_truk"
    assert res.json()["detail"]["params"]["line"] == "line-2"
    assert not (folder / PERMINTAAN).exists()

    # 2. Released: the marker lands, the screen says "installing", assign is held off.
    assert op.post("/api/console/lines/line-2/release-truck").status_code == 200
    assert op.post("/api/console/update/install", json={"target": "v1.22.1"}).status_code == 202
    minta = json.loads((folder / PERMINTAAN).read_text())
    assert (minta["target"], minta["by"]) == ("v1.22.1", "op@pks.test")
    assert op.get("/api/console/update").json()["berjalan"] is True
    ditahan = op.post("/api/console/lines/line-1/assign-truck", json={"truck_id": "t-2"})
    assert (ditahan.status_code, ditahan.json()["detail"]["code"]) == (409, "pembaruan_berjalan")
    assert any("op@pks.test" in pesan and "v1.22.1" in pesan for pesan in _pesan_log(support))

    # 3. The watcher answers rolled_back: red sentence data, version hidden, one ERROR line.
    (folder / "result.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": minta["id"],
                "state": "rolled_back",
                "target": "v1.22.1",
                "installed": "v1.22.0",
                "at": "2026-10-20T08:04:00+07:00",
            }
        )
        + "\n"
    )
    for _ in range(3):  # three polls, as the screen does every 2 s
        keadaan = op.get("/api/console/update").json()
    assert (keadaan["berjalan"], keadaan["siap"], keadaan["hasil"]["state"]) == (False, None, "rolled_back")
    gagal = [pesan for pesan in _pesan_log(support) if "gagal dinyalakan" in pesan]
    assert len(gagal) == 1, gagal
    assert "v1.22.1" in gagal[0] and "v1.22.0" in gagal[0]

    # 4. Assigning is allowed again once the install is over.
    assert op.post("/api/console/lines/line-1/assign-truck", json={"truck_id": "t-2"}).status_code == 200
