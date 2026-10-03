"""Batch 4.6 routes: operator AND support may install; never with a truck on a line.

App assembled here with overrides (pattern `test_bahaya_routes.py`), never
`create_console_app()`, which touches the developer's `state/*.db`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_dev_service,
    get_pembaruan_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.pembaruan_service import HASIL, PERMINTAAN, STATUS, PembaruanService

SANDI = "sandi-rute-2026"
JAM = datetime(2026, 10, 20, 8, 0, tzinfo=timezone(timedelta(hours=7)))


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store
        self.ditugaskan: list[tuple[str, str]] = []

    def state(self) -> dict:
        return {"lines": [], "timezone": "Asia/Jakarta"}

    async def assign_truck(self, line_code: str, truck_id: str) -> dict:
        self.ditugaskan.append((line_code, truck_id))
        self.store.set_assignment(line_code, "a-1", truck_id)
        return {"assignment_id": "a-1", "truck_id": truck_id, "line_code": line_code}


class _StubDev:
    async def license_state(self) -> dict:
        return {"aktif": False}

    def app_version(self) -> str:
        return "v1.22.0"


@pytest.fixture
def rakit(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    folder = tmp_path / "update"
    folder.mkdir()
    (folder / STATUS).write_text(
        json.dumps(
            {
                "schema": 1,
                "installed": "v1.22.0",
                "staged": "v1.22.1",
                "checked_at": "2026-10-20T07:00:00+07:00",
                "watcher": True,
            }
        )
    )
    konsol = _StubConsole(store)
    svc = PembaruanService(folder, lambda: "v1.22.0", lambda: JAM, buat_id=lambda: "r-1")
    aplikasi = FastAPI()
    aplikasi.include_router(console_router)
    pasang_penangan_validasi(aplikasi)
    aplikasi.dependency_overrides[get_console_service] = lambda: konsol
    aplikasi.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    aplikasi.dependency_overrides[get_dev_service] = lambda: _StubDev()
    aplikasi.dependency_overrides[get_pembaruan_service] = lambda: svc
    return aplikasi, store, folder, konsol


def _masuk(aplikasi, store, email: str, role: str) -> TestClient:
    store.upsert_operator_manual({"email": email, "full_name": email, "password_hash": hash_password(SANDI)})
    store.set_role(store.operator_by_email(email)["id"], role)
    client = TestClient(aplikasi)
    assert client.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200
    return client


@pytest.mark.parametrize(
    ("metode", "jalur"),
    [
        ("get", "/api/console/update"),
        ("post", "/api/console/update/install"),
    ],
)
def test_tanpa_sesi_401(rakit, metode, jalur):
    aplikasi, _store, folder, _konsol = rakit
    assert getattr(TestClient(aplikasi), metode)(jalur).status_code == 401
    assert not (folder / PERMINTAAN).exists()


def test_operator_melihat_versi_siap(rakit):
    aplikasi, store, _folder, _konsol = rakit
    res = _masuk(aplikasi, store, "op@pks.test", "operator").get("/api/console/update")
    assert res.status_code == 200
    assert res.json() == {
        "terpasang": True,
        "versi_jalan": "v1.22.0",
        "siap": "v1.22.1",
        "berjalan": False,
        "hasil": None,
    }


def test_ditolak_kalau_ada_truk(rakit):
    aplikasi, store, folder, _konsol = rakit
    store.set_assignment("L2", "a-2", "T-2")
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_ada_truk"
    assert res.json()["detail"]["params"] == {"line": "L2"}
    assert not (folder / PERMINTAAN).exists()


@pytest.mark.parametrize("role", ["operator", "support"])
def test_diterima_tanpa_truk(rakit, role):
    aplikasi, store, folder, _konsol = rakit
    store.set_assignment("L1", "", None)  # truk sudah dilepas: baris tetap ada, truck_id kosong
    res = _masuk(aplikasi, store, f"{role}@pks.test", role).post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 202
    assert res.json() == {"id": "r-1", "target": "v1.22.1"}
    assert json.loads((folder / PERMINTAAN).read_text())["by"] == f"{role}@pks.test"


def test_assign_ditolak_selama_pembaruan_menunggu(rakit):
    aplikasi, store, folder, konsol = rakit
    op = _masuk(aplikasi, store, "op@pks.test", "operator")
    assert op.post("/api/console/update/install", json={"target": "v1.22.1"}).status_code == 202
    res = op.post("/api/console/lines/L1/assign-truck", json={"truck_id": "T-1"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_berjalan"
    assert konsol.ditugaskan == []

    (folder / HASIL).write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "r-1",
                "state": "ok",
                "target": "v1.22.1",
                "installed": "v1.22.1",
                "at": "2026-10-20T08:03:00+07:00",
            }
        )
    )
    assert op.post("/api/console/lines/L1/assign-truck", json={"truck_id": "T-1"}).status_code == 200
    assert konsol.ditugaskan == [("L1", "T-1")]


def test_tekan_kedua_409_berjalan(rakit):
    aplikasi, store, _folder, _konsol = rakit
    op = _masuk(aplikasi, store, "op@pks.test", "operator")
    op.post("/api/console/update/install", json={"target": "v1.22.1"})
    res = op.post("/api/console/update/install", json={"target": "v1.22.1"})
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "pembaruan_berjalan")


def test_tanpa_penunggu_503(rakit):
    aplikasi, store, folder, _konsol = rakit
    (folder / STATUS).unlink()
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert (res.status_code, res.json()["detail"]["code"]) == (503, "pembaruan_belum_terpasang")


def test_body_salah_bentuk_400(rakit):
    aplikasi, store, _folder, _konsol = rakit
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post("/api/console/update/install", json={"target": 5})
    assert (res.status_code, res.json()["detail"]["code"]) == (400, "input_tidak_sah")


def test_state_membawa_pembaruan(rakit):
    aplikasi, store, _folder, _konsol = rakit
    res = _masuk(aplikasi, store, "op@pks.test", "operator").get("/api/console/state")
    assert res.status_code == 200
    assert res.json()["pembaruan"]["siap"] == "v1.22.1"


def test_truk_dari_hari_kerja_lalu_ikut_menolak(rakit):
    # Keputusan user 2026-10-02: truk yang lupa dilepas sejak kemarin juga menolak tombol.
    aplikasi, store, folder, _konsol = rakit
    store.set_assignment("L3", "a-kemarin", "T-9")
    store.set_assignment("L1", "a-1", "T-1")
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["params"] == {"line": "L1, L3"}
    assert not (folder / PERMINTAAN).exists()


def test_target_yang_tidak_dilihat_operator_ditolak(rakit):
    aplikasi, store, folder, _konsol = rakit
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.23.0"}
    )
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "pembaruan_tidak_ada")
    assert not (folder / PERMINTAAN).exists()
