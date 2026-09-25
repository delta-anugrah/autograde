"""Rute `/api/console/dev/bahaya*` — penjaga sesi, peran, dan kode status.

App dirakit sendiri dengan dependensi di-override (pola `test_dev_routes.py`),
bukan `create_console_app()` yang menyentuh `state/*.db` milik developer.
"""
from __future__ import annotations

import pytest
from bahaya_palsu import HASH, LINES, LinePalsu, hitung, isi_data
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_bahaya_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.bahaya_service import BahayaService

SANDI = "sandi-rute-2026"


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def app(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    line = LinePalsu()
    svc = BahayaService(
        store, LogStore(tmp_path / "log.db"), line, LINES,
        ErpOutboxStore(tmp_path / "erp_outbox.db"), None,
        erp_aktif=True, hash_bawaan=HASH, hash_support=HASH,
        tunggu_mati_s=1.0, jeda_cek_s=0.0,
    )
    aplikasi = FastAPI()
    aplikasi.include_router(console_router)
    aplikasi.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    aplikasi.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    aplikasi.dependency_overrides[get_bahaya_service] = lambda: svc
    return aplikasi, store, line


def _masuk(app, store, email: str, role: str) -> TestClient:
    store.upsert_operator_manual(
        {"email": email, "full_name": email, "password_hash": hash_password(SANDI)}
    )
    store.set_role(store.operator_by_email(email)["id"], role)
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": email, "sandi": SANDI}).status_code == 200
    return client


@pytest.mark.parametrize(
    ("metode", "jalur"),
    [
        ("get", "/api/console/dev/bahaya"),
        ("post", "/api/console/dev/bahaya/restart-line"),
        ("post", "/api/console/dev/bahaya/logout-semua"),
        ("post", "/api/console/dev/bahaya/hapus-rekaman"),
        ("post", "/api/console/dev/bahaya/hapus-data"),
    ],
)
def test_tanpa_sesi_401_dan_operator_403(app, metode, jalur):
    aplikasi, store, line = app
    assert getattr(TestClient(aplikasi), metode)(jalur).status_code == 401
    operator = _masuk(aplikasi, store, "op@pks.test", "operator")
    assert getattr(operator, metode)(jalur).status_code == 403
    assert line.perintah == []


def test_ringkasan_untuk_support(app):
    aplikasi, store, _line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")

    res = support.get("/api/console/dev/bahaya")

    assert res.status_code == 200
    assert set(res.json()["aksi"]) == {"restart", "logout", "rekaman", "transaksi", "semua"}


def test_hapus_data_konfirmasi_salah_400(app):
    aplikasi, store, line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")

    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "hapus"}
    )

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "konfirmasi_salah"
    assert line.perintah == []


def test_hapus_data_mode_asing_400(app):
    aplikasi, store, _line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")
    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "x", "konfirmasi": "HAPUS"}
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "mode_asing"


def test_hapus_data_ditolak_409_membawa_kode_hambatan(app):
    aplikasi, store, line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")
    line.detail["line-1"]["current_assignment_id"] = "assign-1"

    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "bahaya_ditolak"
    assert detail["params"]["hambatan"] == "truk_terpasang"
    assert line.perintah == []


def test_hapus_data_transaksi_200(app):
    aplikasi, store, line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")
    isi_data(store)

    res = support.post(
        "/api/console/dev/bahaya/hapus-data", json={"mode": "transaksi", "konfirmasi": "HAPUS"}
    )

    assert res.status_code == 200, res.text
    assert res.json()["mode"] == "transaksi"
    assert len(line.perintah) == 3
    assert hitung(store, "inspections") == 0
    # Sesi yang menekan tetap hidup di mode transaksi.
    assert support.get("/api/console/dev/bahaya").status_code == 200


def test_hapus_rekaman_perlu_konfirmasi(app):
    aplikasi, store, line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")

    assert support.post("/api/console/dev/bahaya/hapus-rekaman", json={}).status_code == 400
    res = support.post("/api/console/dev/bahaya/hapus-rekaman", json={"konfirmasi": "HAPUS"})

    assert res.status_code == 200
    assert res.json()["berkas"] == 6
    assert ("rekam_hapus", "line-1") in line.perintah


def test_logout_semua_mengakhiri_sesi_yang_menekan(app):
    aplikasi, store, _line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")

    res = support.post("/api/console/dev/bahaya/logout-semua")

    assert res.status_code == 200
    assert res.json()["sesi_dihapus"] == 1
    assert support.get("/api/console/dev/bahaya").status_code == 401


def test_restart_line(app):
    aplikasi, store, line = app
    support = _masuk(aplikasi, store, "sp@pks.test", "support")

    res = support.post("/api/console/dev/bahaya/restart-line")

    assert res.status_code == 200
    assert [r["ok"] for r in res.json()["lines"]] == [True, True, True]
    assert [p for p in line.perintah if p[0] == "restart"] == [
        ("restart", "line-1"), ("restart", "line-2"), ("restart", "line-3"),
    ]
