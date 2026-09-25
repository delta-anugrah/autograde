"""End-to-end: layar Rekam Video → konsol → line.

Tiga sambungan yang masing-masing pernah jadi sumber bug di repo ini:

1. **Penjaga**: lane developer harus menolak operator biasa di backend, bukan
   cuma menyembunyikan tabnya di layar.
2. **Konsol → line**: setelan yang tersimpan harus benar-benar ikut saat
   menekan Rekam, bukan bawaan yang dikirim diam-diam.
3. **Line mati**: satu line yang tidak menjawab tidak boleh mengosongkan
   seluruh layar.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console as console_routes
from palmgrade.services.console_service import ConsoleService

SECRET = "e2e-secret"


class _LineMerekam:
    """Berdiri sebagai tiga line: mencatat apa yang benar-benar dikirim konsol."""

    def __init__(self) -> None:
        self.mulai: list[dict] = []
        self.stop: list[str] = []
        self.meledak_untuk: str | None = None
        self._merekam: set[str] = set()

    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...

    async def rekam_mulai(self, line, setelan: dict) -> dict:
        self.mulai.append({"line_code": line.line_code, "setelan": setelan})
        self._merekam.add(line.line_code)
        return {"line_code": line.line_code, "merekam": True, "berkas": "x.mp4"}

    async def rekam_stop(self, line) -> dict:
        self.stop.append(line.line_code)
        self._merekam.discard(line.line_code)
        return {"line_code": line.line_code, "merekam": False, "berkas": "x.mp4"}

    async def rekam_status(self, line) -> dict:
        if self.meledak_untuk == line.line_code:
            raise RuntimeError("line tidak menjawab")
        return {"merekam": line.line_code in self._merekam, "berkas": None}


@pytest.fixture()
def konsol(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    settings = Settings()
    store = ConsoleStore(tmp_path / "console.db")
    line = _LineMerekam()
    service = ConsoleService(settings, store, line)

    app = FastAPI()
    app.include_router(console_routes.router)
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    app.dependency_overrides[console_routes.require_support] = lambda: {
        "email": "support@test", "role": "support"
    }
    with TestClient(app) as c:
        yield c, service, line


# ── setelan ─────────────────────────────────────────────────────────────────


def test_setelan_awal_memakai_bawaan(konsol):
    c, _service, _line = konsol
    res = c.get("/api/console/dev/rekam")
    assert res.status_code == 200, res.text
    assert res.json()["setelan"]["width"] == 1280


def test_simpan_setelan_lalu_terbaca(konsol):
    c, _service, _line = konsol
    c.post(
        "/api/console/dev/rekam/setelan",
        json={"width": 640, "height": 480},
    )
    assert c.get("/api/console/dev/rekam").json()["setelan"]["width"] == 640


def test_setelan_ngawur_jawab_400_dan_tidak_menimpa(konsol):
    c, _service, _line = konsol
    c.post("/api/console/dev/rekam/setelan", json={"fps": 10})
    res = c.post("/api/console/dev/rekam/setelan", json={"fps": 999})

    assert res.status_code == 400
    assert c.get("/api/console/dev/rekam").json()["setelan"]["fps"] == 10


def test_setelan_tersimpan_ikut_saat_mulai(konsol):
    """Sambungan yang paling mudah putus tanpa terlihat: layar menyimpan 7 fps,
    line merekam pada bawaan karena setelannya tidak pernah ikut dikirim."""
    c, _service, line = konsol
    c.post("/api/console/dev/rekam/setelan", json={"fps": 7})

    c.post("/api/console/dev/rekam/line-1/mulai")

    assert line.mulai, "line tidak pernah disuruh mulai"
    assert line.mulai[-1]["setelan"]["fps"] == 7


# ── tombol per line ─────────────────────────────────────────────────────────


def test_mulai_hanya_mengenai_line_yang_ditekan(konsol):
    c, _service, line = konsol
    c.post("/api/console/dev/rekam/line-2/mulai")

    assert [m["line_code"] for m in line.mulai] == ["line-2"]


def test_stop_hanya_mengenai_line_yang_ditekan(konsol):
    c, _service, line = konsol
    c.post("/api/console/dev/rekam/line-2/mulai")
    c.post("/api/console/dev/rekam/line-2/stop")

    assert line.stop == ["line-2"]


def test_line_tak_dikenal_jawab_404(konsol):
    c, _service, _line = konsol
    assert c.post("/api/console/dev/rekam/line-99/mulai").status_code == 404
    assert c.post("/api/console/dev/rekam/line-99/stop").status_code == 404


# ── status ──────────────────────────────────────────────────────────────────


def test_status_menyebut_tiap_line(konsol):
    c, service, _line = konsol
    hasil = c.get("/api/console/dev/rekam").json()
    assert len(hasil["lines"]) == len(service.lines)


def test_status_membawa_sisa_disk(konsol):
    c, _service, _line = konsol
    assert "disk_bebas_gb" in c.get("/api/console/dev/rekam").json()


def test_line_mati_tidak_mengosongkan_layar(konsol):
    """Satu line yang sedang restart adalah kejadian normal, bukan alasan
    layar berhenti menampilkan dua line lainnya."""
    c, _service, line = konsol
    line.meledak_untuk = "line-2"

    hasil = c.get("/api/console/dev/rekam").json()

    baris = {b["line_code"]: b for b in hasil["lines"]}
    assert baris["line-2"]["terbaca"] is False
    assert baris["line-1"]["terbaca"] is True
    assert baris["line-3"]["terbaca"] is True


def test_status_mencerminkan_line_yang_sedang_merekam(konsol):
    c, _service, _line = konsol
    c.post("/api/console/dev/rekam/line-1/mulai")

    baris = {b["line_code"]: b for b in c.get("/api/console/dev/rekam").json()["lines"]}
    assert baris["line-1"]["merekam"] is True
    assert baris["line-2"]["merekam"] is False


# ── penjaga ─────────────────────────────────────────────────────────────────


def test_operator_biasa_ditolak_backend(tmp_path, monkeypatch):
    """Tab yang disembunyikan di layar itu kerapian, bukan pengaman: siapa pun
    yang tahu URL-nya harus tetap ditolak di backend."""
    from palmgrade.domain.operator_error import OperatorError
    from palmgrade.routes.console import _operator_error

    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    service = ConsoleService(Settings(), ConsoleStore(tmp_path / "c.db"), _LineMerekam())

    def _tolak():
        # Persis yang dilakukan `require_support` untuk akun non-support.
        raise _operator_error(
            403, OperatorError("bukan_support", "menu ini untuk akun support")
        )

    app = FastAPI()
    app.include_router(console_routes.router)
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    app.dependency_overrides[console_routes.require_support] = _tolak

    with TestClient(app) as c:
        assert c.get("/api/console/dev/rekam").status_code == 403
        assert c.post("/api/console/dev/rekam/line-1/mulai").status_code == 403
        assert c.post("/api/console/dev/rekam/line-1/stop").status_code == 403
        assert c.post(
            "/api/console/dev/rekam/setelan", json={"fps": 5}
        ).status_code == 403


# ── penolakan dari line diteruskan apa adanya ───────────────────────────────


class _LineMenolak(_LineMerekam):
    """Line yang menjawab tapi menolak — 409 sudah merekam, 507 disk penuh."""

    def __init__(self, status: int, pesan: str) -> None:
        super().__init__()
        self._status = status
        self._pesan = pesan

    async def rekam_mulai(self, line, setelan: dict) -> dict:
        from palmgrade.integrations.notifications.line_client import LinePlcTolak

        raise LinePlcTolak(self._status, self._pesan)

    async def rekam_stop(self, line) -> dict:
        from palmgrade.integrations.notifications.line_client import LinePlcTolak

        raise LinePlcTolak(self._status, self._pesan)


def _konsol_dengan(line, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    service = ConsoleService(Settings(), ConsoleStore(tmp_path / "c.db"), line)
    app = FastAPI()
    app.include_router(console_routes.router)
    app.dependency_overrides[console_routes.get_console_service] = lambda: service
    app.dependency_overrides[console_routes.require_support] = lambda: {
        "email": "support@test", "role": "support"
    }
    return TestClient(app)


def test_stop_line_yang_tidak_merekam_jawab_409_bukan_500(tmp_path, monkeypatch):
    """Ditemukan di browser: penolakan line bocor sebagai 500.

    500 terbaca seperti konsol rusak dan memancing penelusuran yang salah,
    padahal yang terjadi cuma "line itu memang tidak sedang merekam" — sesuatu
    yang terjadi tiap kali dua tab terbuka bersamaan.
    """
    with _konsol_dengan(_LineMenolak(409, "tidak sedang merekam"), tmp_path, monkeypatch) as c:
        res = c.post("/api/console/dev/rekam/line-1/stop")
        assert res.status_code == 409, res.text


def test_mulai_saat_sudah_merekam_jawab_409(tmp_path, monkeypatch):
    with _konsol_dengan(_LineMenolak(409, "sudah merekam"), tmp_path, monkeypatch) as c:
        assert c.post("/api/console/dev/rekam/line-1/mulai").status_code == 409


def test_disk_penuh_diteruskan_sebagai_507(tmp_path, monkeypatch):
    """507 dan 409 butuh tindakan yang berbeda; meratakannya jadi satu kode
    membuat support menebak mana yang sedang terjadi."""
    with _konsol_dengan(_LineMenolak(507, "disk mepet"), tmp_path, monkeypatch) as c:
        assert c.post("/api/console/dev/rekam/line-1/mulai").status_code == 507


# ── field yang dicabut 2026-09-25 (FPS & Bitrate dari layar) ────────────────


def test_setelan_lama_berbitrate_tidak_ikut_keluar(konsol):
    """PC pabrik yang pernah menyimpan setelan dari layar lama masih punya
    `bitrate_kbps` di `sync_state`. Angka itu tidak boleh muncul lagi di layar
    maupun terkirim ke line — dua-duanya sudah tidak punya tempat untuknya."""
    import json as _json

    c, service, line = konsol
    service.store.set_state(
        "setelan_rekam",
        _json.dumps({"width": 800, "height": 600, "fps": 7, "bitrate_kbps": 2000}),
    )

    setelan = c.get("/api/console/dev/rekam").json()["setelan"]
    assert setelan == {"width": 800, "height": 600, "fps": 7}

    assert c.post("/api/console/dev/rekam/line-1/mulai").status_code == 200
    assert line.mulai[-1]["setelan"] == {"width": 800, "height": 600, "fps": 7}


def test_layar_baru_cuma_mengirim_lebar_dan_tinggi(konsol):
    """Layar sesudah 2026-09-25 mengirim dua field; fps kembali ke cadangan
    bawaan (5), yang cuma dipakai kalau kamera tidak melapor dan CAMERA_FPS=0."""
    c, _service, _line = konsol
    res = c.post("/api/console/dev/rekam/setelan", json={"width": 640, "height": 480})
    assert res.status_code == 200, res.text
    assert c.get("/api/console/dev/rekam").json()["setelan"] == {
        "width": 640, "height": 480, "fps": 5,
    }
