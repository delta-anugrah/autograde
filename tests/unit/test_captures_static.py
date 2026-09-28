from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.domain.operator_error import BELUM_MASUK
from palmgrade.routes.captures import CapturesBersesi, StaticTanpaDb

FOTO = "results/2026-09-28/x.webp"
COOKIE = "konsol_sesi"


class _Sesi:
    def __init__(self, hidup: set[str]) -> None:
        self.hidup = hidup

    def current(self, token):
        return {"email": "budi@pks.test"} if token in self.hidup else None


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "results" / "2026-09-28").mkdir(parents=True)
    (tmp_path / FOTO).write_bytes(b"RIFFwebp")
    (tmp_path / "outbox.db").write_bytes(b"SQLite format 3")
    (tmp_path / "license.db-wal").write_bytes(b"wal")
    (tmp_path / ".hapus-data").write_text("{}")
    return tmp_path


def _klien(mount) -> TestClient:
    app = FastAPI()
    app.mount("/captures/line-1", mount)
    return TestClient(app)


def test_foto_tersaji(folder):
    r = _klien(StaticTanpaDb(directory=str(folder))).get(f"/captures/line-1/{FOTO}")
    assert r.status_code == 200 and r.content == b"RIFFwebp"


@pytest.mark.parametrize("jalur", ["outbox.db", "OUTBOX.DB", "license.db-wal", ".hapus-data", "results/%2e%2e/outbox.db"])
def test_bukan_foto_404(folder, jalur):
    assert _klien(StaticTanpaDb(directory=str(folder))).get(f"/captures/line-1/{jalur}").status_code == 404


def _bersesi(folder, hidup=frozenset({"tok"})) -> TestClient:
    return _klien(CapturesBersesi(directory=str(folder), sesi=lambda: _Sesi(set(hidup)), cookie=COOKIE))


def test_tanpa_sesi_401_dengan_kode_gerbang(folder):
    r = _bersesi(folder).get(f"/captures/line-1/{FOTO}")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == BELUM_MASUK


def test_sesi_habis_401_bukan_500(folder):
    c = _bersesi(folder, hidup=frozenset())
    c.cookies.set(COOKIE, "tok")
    assert c.get(f"/captures/line-1/{FOTO}").status_code == 401


def test_sesi_hidup_200_dan_head_jalan(folder):
    c = _bersesi(folder)
    c.cookies.set(COOKIE, "tok")
    assert c.get(f"/captures/line-1/{FOTO}").content == b"RIFFwebp"
    assert c.head(f"/captures/line-1/{FOTO}").status_code == 200


def test_sesi_hidup_tetap_tidak_mendapat_basis_data(folder):
    c = _bersesi(folder)
    c.cookies.set(COOKIE, "tok")
    assert c.get("/captures/line-1/outbox.db").status_code == 404
