"""Integration (batch 5.11): support saves the cutoff, every account sees it in the poll,
the next bunch follows it. Real routes, real SQLite."""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import (
    get_auth_service,
    get_console_service,
    get_dev_service,
    get_pembaruan_service,
    get_slip_service,
)
from palmgrade.routes.console import router as console_router
from palmgrade.routes.console_deps import pasang_penangan_validasi
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.slip_grading import SlipGrading

SANDI = "sandi-integrasi-cutoff"


class _Dev:
    async def license_state(self) -> dict:
        return {}

    def app_version(self) -> str:
        return "v-integrasi"


class _Keadaan:
    def as_dict(self) -> dict:
        return {}


class _Pembaruan:
    def keadaan(self) -> _Keadaan:
        return _Keadaan()


@pytest.fixture
def klien(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    for email, peran in (("operator@pks.test", None), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual({"email": email, "full_name": email, "password_hash": hash_password(SANDI),
                                      **({"role": peran} if peran else {})})
    service = ConsoleService(settings, store, line_client=None)
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: _Dev()
    app.dependency_overrides[get_pembaruan_service] = lambda: _Pembaruan()
    app.dependency_overrides[get_slip_service] = lambda: SlipGrading(store, perusahaan="")

    def masuk(email):
        k = TestClient(app)
        assert k.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200
        return k

    return masuk("operator@pks.test"), masuk("support@pks.test"), service


def test_support_saves_the_cutoff_and_every_account_sees_it(klien):
    operator, support, service = klien
    assert operator.get("/api/console/state").json()["cutoff_shift"] == "00:00"

    simpan = support.post("/api/console/dev/shift", json={"cutoff": "5:00"})

    assert simpan.status_code == 200 and simpan.json() == {"cutoff": "05:00"}
    assert support.get("/api/console/dev/shift").json() == {"cutoff": "05:00"}
    assert operator.get("/api/console/state").json()["cutoff_shift"] == "05:00"
    assert service.hari_kerja.untuk("2026-10-06T02:30:00+07:00") == "2026-10-05"


def test_an_operator_cannot_change_it_and_a_bad_value_is_refused(klien):
    operator, support, _ = klien
    assert operator.post("/api/console/dev/shift", json={"cutoff": "05:00"}).status_code == 403
    salah = support.post("/api/console/dev/shift", json={"cutoff": "13:00"})
    assert (salah.status_code, salah.json()["detail"]["code"]) == (400, "cutoff_tidak_sah")
    assert support.post("/api/console/dev/shift", json={"cutoff": 5}).status_code == 400
