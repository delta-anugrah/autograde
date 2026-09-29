from __future__ import annotations

import re
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from palmgrade.routes.penjaga_rahasia import penjaga_internal

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"


class _Setelan:
    def __init__(self, internal_secret: str) -> None:
        self.internal_secret = internal_secret


def _klien(secret: str) -> TestClient:
    app = FastAPI()

    @app.get("/internal/uji", dependencies=[Depends(penjaga_internal(lambda: _Setelan(secret)))])
    async def uji() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_header_benar_lolos():
    assert _klien("kunci-palsu").get("/internal/uji", headers={"x-internal-secret": "kunci-palsu"}).status_code == 200


def test_tanpa_header_atau_salah_401():
    c = _klien("kunci-palsu")
    assert c.get("/internal/uji").status_code == 401
    assert c.get("/internal/uji", headers={"x-internal-secret": "salah"}).status_code == 401


def test_secret_server_kosong_menolak_semua():
    assert _klien("").get("/internal/uji", headers={"x-internal-secret": ""}).status_code == 401


def test_tidak_ada_lagi_pembanding_secret_biasa():
    """Line (torch, tidak bisa diimpor di CI) dan lane mesin konsol dijaga sebagai teks."""
    for relatif in ("routes/internal.py", "routes/internal_bahaya.py", "routes/console_ingest.py"):
        sumber = (SRC / relatif).read_text(encoding="utf-8")
        assert not re.search(r"(!=|==)\s*[\w.]*(webhook|internal)_secret", sumber), relatif
    assert "_verify_internal_secret = penjaga_internal(get_settings)" in (SRC / "routes/internal.py").read_text()
    assert (SRC / "routes/console_ingest.py").read_text().count("rahasia_cocok(x_webhook_secret, service.settings.webhook_secret)") == 4
