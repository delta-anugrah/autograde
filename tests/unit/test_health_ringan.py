"""`GET /health` line (batch 2.1): 503 hanya saat AI mati, teruji tanpa torch.

Pembacanya dua dan sama-sama memakai kode status, bukan isi: healthcheck
compose (`urllib.request.urlopen` gagal di 4xx/5xx) dan `autograde.sh`
(`curl -f`, yang MEMUNDURKAN versi baru yang tidak menjawab 200).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from ai_palsu import JAM_DINDING, LinePalsu
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.routes.health_ringan import buat_router_health
from palmgrade.services.health_service import HealthService


class _Outbox:
    def pending_count(self):
        return 0

    def failed_count(self):
        return 0


def _klien(line: LinePalsu) -> TestClient:
    app = FastAPI()
    svc = HealthService(settings=line.settings, state=line.state, camera=line.kamera, outbox=_Outbox())
    app.include_router(buat_router_health(lambda: svc))
    return TestClient(app)


def test_line_baru_mulai_200():
    line = LinePalsu()
    line.mulai()
    line.jalan(5, deteksi=False)
    res = _klien(line).get("/health")
    assert res.status_code == 200
    assert res.json()["ai"]["keadaan"] == "memulai"


def test_ai_mati_503_dengan_badan_yang_masih_terbaca():
    line = LinePalsu()
    line.mulai()
    line.pipeline.galat = RuntimeError("CUDA error")
    line.jalan(31)
    line.capture.run_once()

    res = _klien(line).get("/health")

    assert res.status_code == 503
    badan = res.json()
    assert badan["ai"]["kode"] == "AI_MATI"
    assert badan["ai"]["sejak"] == JAM_DINDING
    assert badan["version"]
    assert "CUDA" not in res.text, "galat mentah cuma untuk /health/detail"


def test_pulih_kembali_200():
    line = LinePalsu()
    line.mulai()
    line.pipeline.galat = RuntimeError("CUDA error")
    line.jalan(31)
    line.pipeline.galat = None
    line.jalan(1)
    assert _klien(line).get("/health").status_code == 200


def test_kamera_putus_tetap_200():
    """Kamera putus saat start itu normal di pabrik (kabel, MVS terbuka); 503 di
    sini akan membuat `autograde.sh` memundurkan versi yang tidak salah apa-apa."""
    line = LinePalsu()
    line.mulai()
    line.kamera.connected = False
    line.jam.sekarang += 60          # kamera putus: tidak ada frame untuk diambil
    res = _klien(line).get("/health")
    assert (res.status_code, res.json()["ai"]["keadaan"]) == (200, "kamera_putus")


def test_tanpa_penjaga_tetap_200_seperti_dulu():
    """Sebelum lifespan memasang penjaga (dan di test lama): `ai: null`, 200."""
    app = FastAPI()
    svc = HealthService(settings=replace(Settings()), state=None, camera=None, outbox=_Outbox())
    app.include_router(buat_router_health(lambda: svc))
    res = TestClient(app).get("/health")
    assert (res.status_code, res.json()["ai"]) == (200, None)


def test_router_tidak_menarik_torch_cv2_atau_ultralytics():
    src = Path(__file__).resolve().parents[2] / "src"
    skrip = (
        "import sys\n"
        "for m in ('torch', 'cv2', 'ultralytics'):\n"
        "    sys.modules[m] = None\n"
        "import palmgrade.routes.health_ringan\n"
    )
    hasil = subprocess.run(
        [sys.executable, "-c", skrip], capture_output=True, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]
