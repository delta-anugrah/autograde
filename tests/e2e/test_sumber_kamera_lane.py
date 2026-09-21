"""Alur simpan sumber kamera lewat HTTP, dari layar sampai berkas di disk.

Dirakit seperti `test_dev_lane_role.py` — router asli, sesi asli, store di
tmp_path — bukan lewat `create_console_app()`, yang akan menyentuh
`state/console.db` milik pengembang dan meninggalkan baris tes di sana.

Di sinilah `_buktikan_berkas` benar-benar dijalankan: unit suite melewatinya
karena berjalan tanpa cv2 dengan sengaja. Itu satu-satunya penjaga yang
membedakan berkas yang ADA dari berkas yang benar-benar bisa dibuka sebagai
gambar/video — tanpanya, berkas rusak lolos ke `media.env` dan line masuk
boot-fail-restart loop yang cuma bisa diputus lewat AnyDesk.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.domain.role import ROLE_OPERATOR, ROLE_SUPPORT
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console import get_auth_service, get_console_service
from palmgrade.routes.console import router as console_router
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
    """Konsol nyata dengan folder media dan media.env di tmp_path."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    media = tmp_path / "media"
    media.mkdir()
    # Gambar sungguhan, supaya pembuktian cv2 di service benar-benar jalan.
    cv2.imwrite(str(media / "sawit.jpg"), np.zeros((32, 32, 3), dtype=np.uint8))
    # Berkas yang ADA dan punya ekstensi gambar, tapi isinya bukan gambar.
    # `MediaLibrary.ada()` cuma mencocokkan nama+ekstensi terhadap daftar folder,
    # jadi berkas ini lolos lapis itu; hanya `_buktikan_berkas` (cv2.imread di
    # dalamnya) yang menangkapnya. Ini kasus yang paling berharga di berkas ini —
    # kasus "hantu.mp4" di bawah cuma menguji cek keberadaan.
    (media / "rusak.jpg").write_bytes(b"bukan gambar")

    monkeypatch.setenv("MEDIA_DIR", str(media))
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))

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

    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, store, FakeLine())

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    return TestClient(app), service, tmp_path


def _masuk(client: TestClient, email: str) -> None:
    assert client.post(
        "/api/console/login", json={"email": email, "sandi": SANDI}
    ).status_code == 200


def test_simpan_foto_menulis_berkas_dan_merestart(lane):
    client, service, tmp_path = lane
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/sumber-kamera",
        json={
            "line-1": {"sumber": "foto", "berkas": "sawit.jpg"},
            "line-2": {"sumber": "hikrobot"},
            "line-3": {"sumber": "hikrobot"},
        },
    )
    assert r.status_code == 200, r.text
    # POST membalas `lines` sebagai ARRAY hasil restart per line, bukan dict
    # setelan seperti GET — jangan tertukar dengan bentuk di test berikutnya.
    hasil = {baris["line_code"]: baris for baris in r.json()["lines"]}
    assert hasil["line-1"] == {"line_code": "line-1", "direstart": True, "berubah": True}

    isi = (tmp_path / "media.env").read_text(encoding="utf-8")
    assert "LINE_1_CAMERA_TYPE=photo" in isi
    assert "LINE_1_MEDIA_FILE=sawit.jpg" in isi
    assert service.line_client.restarted == ["line-1"]


def test_berkas_hantu_ditolak_400_tanpa_menulis(lane):
    client, service, tmp_path = lane

    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/sumber-kamera",
        json={
            "line-1": {"sumber": "video", "berkas": "hantu.mp4"},
            "line-2": {"sumber": "hikrobot"},
            "line-3": {"sumber": "hikrobot"},
        },
    )
    assert r.status_code == 400
    assert not (tmp_path / "media.env").exists()
    assert service.line_client.restarted == []


def test_berkas_rusak_ditolak_400_tanpa_menulis(lane):
    """Berkas ADA dan ekstensinya `.jpg`, tapi isinya bukan gambar.

    `MediaLibrary.ada()` menjawab True (nama + ekstensi cocok dengan daftar
    folder); cuma `_buktikan_berkas` (cv2.imread nyata) yang menangkapnya. Ini
    yang membuktikan penjaga boot-fail-restart-loop benar-benar berjalan di
    jalur HTTP, bukan cuma dijamin unit test yang men-stub cv2.
    """
    client, service, tmp_path = lane
    _masuk(client, "support@pks.test")

    r = client.post(
        "/api/console/dev/sumber-kamera",
        json={
            "line-1": {"sumber": "foto", "berkas": "rusak.jpg"},
            "line-2": {"sumber": "hikrobot"},
            "line-3": {"sumber": "hikrobot"},
        },
    )
    assert r.status_code == 400
    assert not (tmp_path / "media.env").exists()
    assert service.line_client.restarted == []


def test_operator_biasa_ditolak_403(lane):
    client, _, _ = lane
    _masuk(client, "operator@pks.test")
    assert client.get("/api/console/dev/sumber-kamera").status_code == 403
