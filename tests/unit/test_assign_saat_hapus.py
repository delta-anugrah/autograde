"""Memasang truk ditolak selama Danger Zone menghapus data (sisi konsol).

Truk yang dipasang di tengah penghapusan digrading ke penugasan yang barisnya
ikut terhapus: `lepas` sesudahnya tidak menemukan apa pun dan janjangnya tidak
pernah tertaut ke tiket. Line menjaga jendelanya sendiri (penanda hapus →
`/internal/assignment` 409); ini jendela konsol — sesudah line menerima perintah
dan sebelum konsol selesai mengosongkan datanya.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.bahaya import HapusBerjalan
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sandi-assign-2026"


class LineCatat:
    def __init__(self) -> None:
        self.kiriman: list[str] = []

    async def assign_truck(
        self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None
    ):
        self.kiriman.append(truck_id)


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), LineCatat())


def test_assign_ditolak_tanpa_menyentuh_line(service):
    truk = service.register_manual_truck("B 1234 XY")
    line_code = service.lines[0].line_code
    service.store.hapus_berjalan = True

    with pytest.raises(HapusBerjalan) as exc:
        asyncio.run(service.assign_truck(line_code, truk["id"]))

    assert exc.value.code == "hapus_berjalan"
    assert service.line_client.kiriman == []
    assert service.store.assignments().get(line_code, {}).get("truck_id") is None


def test_assign_jalan_lagi_sesudah_hapus_selesai(service):
    truk = service.register_manual_truck("B 1234 XY")
    line_code = service.lines[0].line_code
    service.store.hapus_berjalan = False

    asyncio.run(service.assign_truck(line_code, truk["id"]))

    assert service.line_client.kiriman == [truk["id"]]


def test_rute_menjawab_409_dengan_kode_yang_diterjemahkan_layar(service):
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(service.store)
    service.store.upsert_operator_manual(
        {"email": "op@pks.test", "full_name": "Op", "password_hash": hash_password(SANDI)}
    )
    client = TestClient(app)
    assert client.post(
        "/api/console/login", json={"email": "op@pks.test", "sandi": SANDI}
    ).status_code == 200
    truk = service.register_manual_truck("B 1234 XY")
    service.store.hapus_berjalan = True

    res = client.post(
        f"/api/console/lines/{service.lines[0].line_code}/assign-truck",
        json={"truck_id": truk["id"]},
    )

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "hapus_berjalan"
    assert service.line_client.kiriman == []
