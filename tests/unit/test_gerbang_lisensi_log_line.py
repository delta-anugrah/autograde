"""Gerbang lisensi line membuka `/internal/log` PERSIS, bukan awalannya (batch 3.2).

Jalur lain di `_ALWAYS_ALLOWED` dicocokkan dengan awalan (`/captures/...`). Kalau
`/internal/log` ikut cara itu, rute `/internal/log...` apa pun yang kelak ditambah
(misalnya hapus log) ikut lolos saat lisensi habis tanpa ada yang sadar.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.license.guard import LicenseGuardMiddleware
from palmgrade.license.types import EffectiveLicense


class _LisensiHabis:
    async def get_effective_license(self) -> EffectiveLicense:
        return EffectiveLicense(status="EXPIRED", reason="uji", payload=None, warning=None)


def _klien() -> TestClient:
    app = FastAPI()
    for jalur in ("/internal/log", "/internal/logs", "/internal/log/hapus", "/health", "/captures/a.webp"):
        app.add_api_route(jalur, lambda: {"ok": True})
    app.add_middleware(LicenseGuardMiddleware, manager=_LisensiHabis())
    return TestClient(app)


def test_log_line_terbuka_saat_lisensi_habis_termasuk_dengan_kueri():
    klien = _klien()
    assert klien.get("/internal/log").status_code == 200
    assert klien.get("/internal/log?setelah=3&generasi=g&batas=100").status_code == 200


def test_rute_lain_berawalan_internal_log_tetap_ditutup():
    klien = _klien()
    assert klien.get("/internal/logs").status_code == 403
    assert klien.get("/internal/log/hapus").status_code == 403


def test_jalur_awalan_lain_tetap_seperti_semula():
    klien = _klien()
    assert klien.get("/health").status_code == 200
    assert klien.get("/captures/a.webp").status_code == 200
