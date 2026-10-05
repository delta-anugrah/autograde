"""Integration (batch 5.9): the slip switch and the slip lane, real routes on real SQLite.

Support switches the slip on; every operator sees `slip_cetak` in the 2 s poll and can ask for
one truck's slip. While it is off the lane answers 403 whatever the screen shows, and an
operator cannot switch it.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_SUPPORT
from palmgrade.domain.vision_event import build_event_payload
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

SANDI = "sandi-integrasi-slip"


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
def rakitan(tmp_path):
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", erp_company="PT Sawit Uji")
    store = ConsoleStore(tmp_path / "console.db")
    for email, peran in (("operator@pks.test", None), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual({"email": email, "full_name": email, "password_hash": hash_password(SANDI),
                                      **({"role": peran} if peran else {})})
    service = ConsoleService(settings, store, line_client=None)
    slip = SlipGrading(store, perusahaan=settings.erp_company)
    app = FastAPI()
    app.include_router(console_router)
    pasang_penangan_validasi(app)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: _Dev()
    app.dependency_overrides[get_pembaruan_service] = lambda: _Pembaruan()
    app.dependency_overrides[get_slip_service] = lambda: slip

    def masuk(email):
        klien = TestClient(app)
        assert klien.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200
        return klien

    return masuk("operator@pks.test"), masuk("support@pks.test"), service


def _truk_berjanjang(service) -> str:
    truk = service.register_manual_truck("BE 1 AA")["id"]
    service.store.set_assignment("line-1", "as-1", truk)
    service.ingest(build_event_payload(
        machine_id=service.lines[0].machine_id, file_ts="2026-10-05_07-41-01_000000",
        timestamp=datetime.now(UTC).isoformat(), ripeness_status="ACC", ripeness_confidence=0.9,
        capture_type="auto", image_path="captures/results/x/1.webp", truck_id=truk, assignment_id="as-1",
    ))
    return truk


def test_support_switches_it_on_and_an_operator_prints_a_slip(rakitan):
    operator, support, service = rakitan
    truk = _truk_berjanjang(service)
    hari = service.today()
    alamat = f"/api/console/slip?work_date={hari}&truck_id={truk}"
    assert operator.get("/api/console/state").json()["slip_cetak"] is False
    mati = operator.get(alamat)
    assert (mati.status_code, mati.json()["detail"]["code"]) == (403, "slip_mati")

    simpan = support.post("/api/console/dev/slip", json={"aktif": True})

    assert simpan.status_code == 200 and simpan.json() == {"aktif": True}
    assert support.get("/api/console/dev/slip").json() == {"aktif": True}
    assert operator.get("/api/console/state").json()["slip_cetak"] is True
    slip = operator.get(alamat)
    assert slip.status_code == 200, slip.text
    assert (slip.json()["plate_number"], slip.json()["kelas"]["total"]) == ("BE 1 AA", 1)
    assert slip.json()["perusahaan"] == "PT Sawit Uji"


def test_an_operator_cannot_switch_it_and_an_unknown_truck_has_no_slip(rakitan):
    operator, support, service = rakitan
    assert operator.post("/api/console/dev/slip", json={"aktif": True}).status_code == 403
    support.post("/api/console/dev/slip", json={"aktif": True})

    tidak_ada = operator.get(f"/api/console/slip?work_date={service.today()}&truck_id=tidak-ada")

    assert (tidak_ada.status_code, tidak_ada.json()["detail"]["code"]) == (404, "slip_tidak_ada")
    assert support.post("/api/console/dev/slip", json={"aktif": "ya"}).status_code == 400
