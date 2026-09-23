"""Konsol memberi tahu layar DI MANA rekaman disimpan.

Layar tidak boleh mengarang jalurnya: di PC pabrik foldernya
`/opt/palmgrade/autograde/videos/`, di jalur native `<repo>/videos/`, dan di
dalam container `/app/videos`. Support yang membuka lewat AnyDesk perlu jalur
yang benar-benar ada di mesin itu, bukan tebakan.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console as console_routes
from palmgrade.services.console_service import ConsoleService


class _LineDiam:
    async def assign_truck(self, line, **_kw) -> None: ...
    async def manual_reject(self, line, **_kw) -> None: ...
    async def rekam_status(self, line) -> dict:
        return {"merekam": False, "berkas": None}


@pytest.fixture()
def konsol(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "uji")
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    service = ConsoleService(Settings(), ConsoleStore(tmp_path / "c.db"), _LineDiam())
    app = FastAPI()
    app.include_router(console_routes.router)
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    app.dependency_overrides[console_routes.require_support] = lambda: {
        "email": "support@test", "role": "support"
    }
    with TestClient(app) as c:
        yield c, tmp_path / "videos"


def test_status_membawa_folder_rekaman(konsol):
    c, videos = konsol
    hasil = c.get("/api/console/dev/rekam").json()
    assert hasil["folder"] == str(videos)


def test_folder_jalur_penuh_bukan_relatif(konsol):
    """`videos/` relatif tidak menolong siapa pun yang membukanya lewat
    AnyDesk — dia perlu tahu dari mana relatifnya."""
    c, _videos = konsol
    assert c.get("/api/console/dev/rekam").json()["folder"].startswith("/")


# ── jalur yang ditampilkan harus jalur HOST, bukan jalur container ───────────


def test_konsol_punya_jalur_rekaman_di_compose():
    """Layar menampilkan jalur ini ke teknisi yang membuka PC pabrik lewat
    AnyDesk, jadi yang berguna adalah jalur HOST (`/opt/palmgrade/autograde/
    videos`), bukan jalur di dalam container (`/app/videos`).

    Konsol sendiri tidak pernah menulis rekaman — ia cuma perlu tahu namanya
    untuk ditampilkan, jadi variabelnya disetel tanpa mount apa pun.
    """
    import re
    from pathlib import Path

    import yaml

    akar = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((akar / "docker-compose.yml").read_text(encoding="utf-8"))
    env = [str(e) for e in compose["services"]["console"].get("environment", [])]
    cocok = [e for e in env if e.startswith("REKAMAN_TAMPIL=")]
    assert cocok, "konsol tidak tahu jalur mana yang harus ditampilkan"
    # Bukan jalur container: itu tidak ada artinya di Finder/Explorer host.
    assert "/app/videos" not in cocok[0], cocok[0]
    assert re.search(r"REKAMAN_TAMPIL=\$\{REKAMAN_TAMPIL:-", cocok[0]), cocok[0]


def test_jalur_tampil_menang_atas_jalur_tulis(tmp_path, monkeypatch):
    """`REKAMAN_TAMPIL` cuma untuk dibaca manusia; yang menulis tetap
    `REKAMAN_DIR`. Di line keduanya sama, di konsol berbeda."""
    monkeypatch.setenv("REKAMAN_DIR", "/app/videos")
    monkeypatch.setenv("REKAMAN_TAMPIL", "/opt/palmgrade/autograde/videos")
    s = Settings()
    assert str(s.videos_dir) == "/app/videos"
    assert s.videos_dir_tampil == "/opt/palmgrade/autograde/videos"


def test_tanpa_jalur_tampil_jatuh_ke_jalur_tulis(tmp_path, monkeypatch):
    """Jalur native (`make console`) tidak punya container, jadi keduanya sama
    dan tidak ada yang perlu disetel."""
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    monkeypatch.delenv("REKAMAN_TAMPIL", raising=False)
    s = Settings()
    assert s.videos_dir_tampil == str(s.videos_dir)


def test_konsol_prod_juga_punya_jalur_tampil():
    """Override MENGGANTI seluruh blok `environment:`, bukan menambahinya.

    Tanpa baris ini di prod, variabelnya hilang persis di mesin yang paling
    membutuhkannya — PC pabrik — dan layar menyebut `/app/videos`, tempat yang
    tidak bisa dibuka siapa pun lewat AnyDesk.
    """
    from pathlib import Path

    teks = (Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text(
        encoding="utf-8"
    )
    assert "REKAMAN_TAMPIL=" in teks
