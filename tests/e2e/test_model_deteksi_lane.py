"""Alur simpan model deteksi lewat HTTP, dari layar sampai berkas di disk.

Dirakit seperti `test_sumber_kamera_lane.py`: router asli, sesi asli, store di
tmp_path. Folder model berisi checkpoint palsu (`model_palsu`) — tanpa torch.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from model_palsu import EMPAT, LAMA, buat_pt

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
from palmgrade.services import model_library
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SANDI = "sokongan2026"


class FakeLine:
    def __init__(self) -> None:
        self.restarted: list[str] = []

    async def restart(self, line):
        self.restarted.append(line.line_code)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    model_library._CACHE.clear()
    release = tmp_path / "models" / "release"
    release.mkdir(parents=True)
    (tmp_path / "engines").mkdir()
    buat_pt(release / "best.pt", EMPAT)
    buat_pt(release / "coba.pt", EMPAT)
    buat_pt(release / "lama.pt", LAMA)
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))

    store = ConsoleStore(tmp_path / "console.db")
    for email, role in (("operator@pks.test", ROLE_OPERATOR), ("support@pks.test", ROLE_SUPPORT)):
        store.upsert_operator_manual(
            {
                "email": email,
                "full_name": email,
                "password_hash": hash_password(SANDI),
                "role": role,
            }
        )

    settings = replace(Settings(), factory_tz="Asia/Jakarta", repo_root=tmp_path)
    service = ConsoleService(settings, store, FakeLine())

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    yield TestClient(app), service, tmp_path
    model_library._CACHE.clear()


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_baca_menampilkan_kelas_tiap_model(lane):
    client, _service, _tmp = lane
    _masuk(client, "support@pks.test")

    r = client.get("/api/console/dev/model-deteksi")

    assert r.status_code == 200, r.text
    daftar = {m["berkas"]: m for m in r.json()["model"]}
    assert daftar["best.pt"]["kelas"] == ["JK", "Ripe", "TP", "Unripe"]
    assert daftar["lama.pt"]["kelas"] == ["ACC", "Rej", "TP"]
    assert daftar["lama.pt"]["cocok"] is False


def test_simpan_menulis_berkas_dan_merestart(lane):
    client, service, tmp_path = lane
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/model-deteksi",
        json={"line-1": "", "line-2": "coba.pt", "line-3": ""},
    )

    assert r.status_code == 200, r.text
    hasil = {b["line_code"]: b for b in r.json()["lines"]}
    assert hasil["line-2"] == {"line_code": "line-2", "direstart": True, "berubah": True}
    assert "LINE_2_MODEL_FILE=coba.pt" in (tmp_path / "media.env").read_text(encoding="utf-8")
    assert service.line_client.restarted == ["line-2"]


def test_model_kelas_asing_400_tanpa_menulis(lane):
    client, service, tmp_path = lane
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/model-deteksi",
        json={"line-1": "lama.pt", "line-2": "", "line-3": ""},
    )

    assert r.status_code == 400
    assert "ACC" in r.json()["detail"]
    assert not (tmp_path / "media.env").exists()
    assert service.line_client.restarted == []


def test_operator_biasa_ditolak_403(lane):
    client, service, tmp_path = lane
    _masuk(client, "operator@pks.test")

    assert client.get("/api/console/dev/model-deteksi").status_code == 403
    r = client.post(
        "/api/console/dev/model-deteksi",
        json={"line-1": "coba.pt", "line-2": "", "line-3": ""},
    )
    assert r.status_code == 403
    assert not (tmp_path / "media.env").exists()
