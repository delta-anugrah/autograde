"""Batch 4.6 routes: operator AND support may install; Update now releases the trucks itself.

App assembled here with overrides (pattern `test_bahaya_routes.py`), never
`create_console_app()`, which touches the developer's `state/*.db`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
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
        self.pembaruan = None
        self.selama_panggilan: list = []
        self.dilepas: list[str] = []
        self.gagal_di: str | None = None
        self.aneh_di: str | None = None
        self.plat: dict[str, str] = {}
        self.status: dict[str, dict] = {}

    def line_status(self) -> dict:
        return self.status

    def state(self) -> dict:
        return {"lines": [], "timezone": "Asia/Jakarta"}

    def assignments(self) -> dict:
        return {k: {**v, "plate_number": self.plat.get(k)} for k, v in self.store.assignments().items()}

    async def release_truck(self, line_code: str, *, kirim: bool = True) -> dict:
        if line_code == self.gagal_di:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, f"{line_code} tidak menjawab")
        if line_code == self.aneh_di:
            raise RuntimeError("bug yang tidak diduga")
        self.dilepas.append(line_code)
        self.store.set_assignment(line_code, "a-1", "")
        return {"line_code": line_code}

    async def assign_truck(self, line_code: str, truck_id: str) -> dict:
        self.ditugaskan.append((line_code, truck_id))
        if self.pembaruan is not None:
            # What the install route would see while this line has not answered yet.
            self.selama_panggilan.append((self.pembaruan.kunci.locked(), self.pembaruan.line_sedang_ditugaskan()))
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
    konsol.pembaruan = svc
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


def test_truk_dilepas_dulu_lalu_dipasang(rakit):
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L2", "a-2", "T-2")
    konsol.plat["L2"] = "B 1995 SME"
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 202
    assert res.json() == {
        "id": "r-1",
        "target": "v1.22.1",
        "dilepas": [{"line_code": "L2", "plate_number": "B 1995 SME"}],
    }
    assert konsol.dilepas == ["L2"]
    assert (folder / PERMINTAAN).exists()


def test_line_tak_menjawab_menghentikan_pemasangan(rakit):
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L1", "a-1", "T-1")
    store.set_assignment("L2", "a-2", "T-2")
    konsol.gagal_di = "L2"
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_lepas_gagal"
    # L1 was released before L2 failed and stays released: the sentence names it.
    assert res.json()["detail"]["params"] == {"line": "L2", "dilepas": "L1"}
    assert konsol.dilepas == ["L1"]
    assert not (folder / PERMINTAAN).exists()


def test_line_pertama_gagal_tanpa_daftar_dilepas(rakit):
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L2", "a-2", "T-2")
    konsol.gagal_di = "L2"
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["params"] == {"line": "L2"}


def test_line_yang_sudah_tak_terbaca_tidak_melepas_apa_pun(rakit):
    """A line the status poll already cannot read: refused before any truck is released."""
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L1", "a-1", "T-1")
    store.set_assignment("L2", "a-2", "T-2")
    store.set_assignment("L3", "a-3", "T-3")
    konsol.status = {
        "L1": {"reachable": True},
        "L2": {"reachable": False, "sebab_kode": "tak_terjangkau"},
        "L3": {"reachable": False, "sebab_kode": "kunci_ditolak"},
    }
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_lepas_gagal"
    assert res.json()["detail"]["params"] == {"line": "L2, L3"}
    assert konsol.dilepas == []
    assert not (folder / PERMINTAAN).exists()


def test_line_tanpa_truk_yang_tak_terbaca_tidak_menghalangi(rakit):
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L1", "a-1", "T-1")
    konsol.status = {"L3": {"reachable": False, "sebab_kode": "tak_terjangkau"}}
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 202
    assert konsol.dilepas == ["L1"]


def test_galat_tak_terduga_sesudah_sebagian_dilepas_tetap_409(rakit):
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L1", "a-1", "T-1")
    store.set_assignment("L2", "a-2", "T-2")
    konsol.aneh_di = "L2"
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_lepas_gagal"
    assert res.json()["detail"]["params"] == {"line": "L2", "dilepas": "L1"}
    assert not (folder / PERMINTAAN).exists()


def test_ditolak_karena_alasan_lain_tidak_melepas_truk(rakit):
    aplikasi, store, folder, konsol = rakit
    store.set_assignment("L2", "a-2", "T-2")
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.99.0"}
    )
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "pembaruan_tidak_ada")
    assert konsol.dilepas == []
    assert not (folder / PERMINTAAN).exists()


def test_pemasangan_berjalan_tidak_melepas_truk(rakit):
    aplikasi, store, folder, konsol = rakit
    op = _masuk(aplikasi, store, "op@pks.test", "operator")
    assert op.post("/api/console/update/install", json={"target": "v1.22.1"}).status_code == 202
    store.set_assignment("L2", "a-2", "T-2")
    res = op.post("/api/console/update/install", json={"target": "v1.22.1"})
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "pembaruan_berjalan")
    assert konsol.dilepas == []


def test_assign_yang_masih_berjalan_tetap_menolak(rakit):
    aplikasi, store, folder, konsol = rakit
    op = _masuk(aplikasi, store, "op@pks.test", "operator")
    penjaga = aplikasi.dependency_overrides[get_pembaruan_service]()
    # The real context manager, entered on a loop of its own: inside it the line has not answered.
    # Safe because the lock is uncontended here, so it never binds to this loop.
    loop = asyncio.new_event_loop()
    masuk = penjaga.menugaskan("L3")
    loop.run_until_complete(masuk.__aenter__())
    try:
        res = op.post("/api/console/update/install", json={"target": "v1.22.1"})
    finally:
        loop.run_until_complete(masuk.__aexit__(None, None, None))
        loop.close()
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "pembaruan_ada_truk"
    assert res.json()["detail"]["params"] == {"line": "L3"}
    assert konsol.dilepas == []
    assert not (folder / PERMINTAAN).exists()


@pytest.mark.parametrize("role", ["operator", "support"])
def test_diterima_tanpa_truk(rakit, role):
    aplikasi, store, folder, _konsol = rakit
    store.set_assignment("L1", "", None)  # truk sudah dilepas: baris tetap ada, truck_id kosong
    res = _masuk(aplikasi, store, f"{role}@pks.test", role).post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 202
    assert res.json() == {"id": "r-1", "target": "v1.22.1", "dilepas": []}
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


def test_truk_dari_hari_kerja_lalu_ikut_dilepas(rakit):
    # Keputusan user 2026-10-02: a truck forgotten since yesterday counts too. Since 2026-10-07
    # Update now releases it instead of refusing, lines in order.
    aplikasi, store, _folder, konsol = rakit
    store.set_assignment("L3", "a-kemarin", "T-9")
    store.set_assignment("L1", "a-1", "T-1")
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.22.1"}
    )
    assert res.status_code == 202
    assert [d["line_code"] for d in res.json()["dilepas"]] == ["L1", "L3"]
    assert konsol.dilepas == ["L1", "L3"]


def test_target_yang_tidak_dilihat_operator_ditolak(rakit):
    aplikasi, store, folder, _konsol = rakit
    res = _masuk(aplikasi, store, "op@pks.test", "operator").post(
        "/api/console/update/install", json={"target": "v1.23.0"}
    )
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "pembaruan_tidak_ada")
    assert not (folder / PERMINTAAN).exists()


def test_assign_tidak_memegang_kunci_saat_menunggu_line_tapi_terlihat_install(rakit):
    """Review 2026-10-03: a dead line (10 s timeout) must not queue the other lines' assigns."""
    aplikasi, store, _folder, konsol = rakit
    op = _masuk(aplikasi, store, "op@pks.test", "operator")
    assert op.post("/api/console/lines/line-2/assign-truck", json={"truck_id": "t-1"}).status_code == 200
    assert konsol.selama_panggilan == [(False, ["line-2"])]


def test_route_tidak_membaca_store_langsung():
    """L1: route → service → repository."""
    from pathlib import Path

    import palmgrade.routes.console as rute

    assert "service.store." not in Path(rute.__file__).read_text(encoding="utf-8")
