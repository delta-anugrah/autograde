"""Perakitan penjaga AI mati (batch 2.1) di tempat yang menarik torch, dijaga
sebagai TEKS (pola `test_main_bahaya_wiring.py`): `main.py`, `routes/health.py`,
dan `internal_controller.line_status` tidak bisa dinyalakan di CI.

Yang gagal senyap kalau salah: coil ERROR tetap cuma membaca kamera, `/health`
lama yang selalu 200 masih yang terpasang, atau `/internal/status` tidak
membawa blok `ai` sehingga kartu konsol tidak pernah merah.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from palmgrade.schemas.internal_schema import LineStatusResponse

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "palmgrade"
MAIN = (SRC / "main.py").read_text(encoding="utf-8")
LIFESPAN = MAIN.split("async def lifespan(app: FastAPI):", 1)[1]


def test_satu_penjaga_dirakit_sesudah_kamera_dan_state():
    i = LIFESPAN.index("penjaga_ai = PenjagaAi(settings=settings, state=state, kamera=camera)")
    assert LIFESPAN.index("set_camera(camera)") < i
    assert LIFESPAN.index("state = get_runtime_state()") < i
    assert "state.penjaga_ai = penjaga_ai" in LIFESPAN


def test_coil_error_membaca_penjaga_bukan_kamera_saja():
    blok = LIFESPAN.split("start_plc_worker(", 1)[1].split(")", 1)[0]
    assert "health_check=penjaga_ai.sehat_untuk_plc" in blok
    assert "camera.connected" not in blok


def test_health_ringan_dipasang_dan_rute_lama_dicabut():
    assert "app.include_router(buat_router_health(get_health_service))" in MAIN
    lama = (SRC / "routes" / "health.py").read_text(encoding="utf-8")
    assert '@router.get("/health",' not in lama
    assert '@router.get("/health/detail"' in lama


def test_status_line_membawa_blok_ai():
    kontrol = (SRC / "controllers" / "internal_controller.py").read_text(encoding="utf-8")
    fungsi = kontrol.split("async def line_status(", 1)[1]
    assert "ai=ringkas_ai_dari_state(state)" in fungsi


def test_skema_status_line_menerima_ai_dan_bawaannya_none():
    """Line lama yang tidak mengirim `ai` tetap sah (konsol baru, line lama)."""
    assert LineStatusResponse(machine_id="m", truck_id=None, ffb_source=None, piston=None).ai is None


def test_healthcheck_docker_tiap_line_memanggil_health():
    """503 dari `/health` baru terbaca "unhealthy" kalau healthcheck memanggil
    rute ini. Restart policy `unless-stopped` TIDAK bereaksi pada unhealthy,
    dan tidak ada autoheal di PC pabrik: tidak ada restart loop."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for nama in ("ripe-line-1", "ripe-line-2", "ripe-line-3"):
        svc = compose["services"][nama]
        assert "/health'" in " ".join(svc["healthcheck"]["test"]), nama
        assert svc["restart"] == "unless-stopped", nama
        assert "autoheal" not in str(svc.get("labels", "")), nama


def test_hasil_sambung_kamera_saat_boot_dicatat_sebelum_penjaga_menilai():
    """Tanpa ini sambung ulang pertama sesudah boot yang gagal bisa menulis satu
    ERROR FRAME_BERHENTI palsu (tick di sela `connect()` dan pencatatan hasilnya)."""
    i = LIFESPAN.index("state.catat_sambung_kamera(berhasil=bool(getattr(camera, \"connected\", False)))")
    assert LIFESPAN.index("state = get_runtime_state()") < i
    assert i < LIFESPAN.index("penjaga_ai = PenjagaAi(settings=settings, state=state, kamera=camera)")
