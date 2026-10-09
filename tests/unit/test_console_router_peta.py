"""Peta rute konsol, dikunci sebelum routes/console.py dipecah (batch 1, 2026-09-28).

Memindah kode antar modul tidak boleh menambah, menghapus, atau mengganti satu
rute pun. Daftar ini diambil dari `router` dan `ingest_router` SEBELUM dipecah.
"""
from __future__ import annotations

from pathlib import Path

from palmgrade.routes import console, console_deps
from palmgrade.routes.console_ingest import ingest_router

RUTE_OPERATOR = [
    ("GET", "/console"),
    ("GET", "/api/console/operators"),
    ("POST", "/api/console/login"),
    ("POST", "/api/console/logout"),
    ("GET", "/api/console/me"),
    ("POST", "/api/console/session/renew"),
    ("GET", "/api/console/slip"),
    ("GET", "/api/console/dev/slip"),
    ("POST", "/api/console/dev/slip"),
    ("GET", "/api/console/dev/shift"),
    ("POST", "/api/console/dev/shift"),
    ("GET", "/api/console/state"),
    ("GET", "/api/console/history"),
    ("GET", "/api/console/riwayat"),
    ("GET", "/api/console/riwayat/csv"),
    ("GET", "/api/console/trucks"),
    ("POST", "/api/console/trucks"),
    ("POST", "/api/console/scan"),
    ("POST", "/api/console/scan/keluar"),
    ("POST", "/api/console/arrivals"),
    ("POST", "/api/console/arrivals/{arrival_id}/cancel"),
    ("POST", "/api/console/departures"),
    ("POST", "/api/console/scan/auto"),
    ("GET", "/api/console/trucks/{plate_number}/qr.png"),
    ("GET", "/api/console/weighings"),
    ("GET", "/api/console/recap"),
    ("POST", "/api/console/weighings"),
    ("POST", "/api/console/lines/{line_code}/assign-truck"),
    ("POST", "/api/console/lines/{line_code}/release-truck"),
    ("POST", "/api/console/lines/{line_code}/force-release"),
    ("POST", "/api/console/unloading-queue/{weighing_id}/assign"),
    ("POST", "/api/console/unloading-queue/{weighing_id}/skip"),
    ("POST", "/api/console/lines/{line_code}/manual-reject"),
    ("POST", "/api/console/lines/{line_code}/piston"),
    ("POST", "/api/console/lines/{line_code}/reconnect-camera"),
    ("GET", "/api/console/dev/camera-settings"),
    ("GET", "/api/console/update"),
    ("POST", "/api/console/update/install"),
    ("GET", "/api/console/dev/ping"),
    ("GET", "/api/console/dev/log"),
    ("GET", "/api/console/dev/diagnostik"),
    ("GET", "/api/console/dev/antrean"),
    ("POST", "/api/console/dev/antrean/kirim-ulang"),
    ("GET", "/api/console/dev/antrean/manifest"),
    ("GET", "/api/console/dev/versi"),
    ("GET", "/api/console/dev/akun"),
    ("POST", "/api/console/dev/akun"),
    ("POST", "/api/console/dev/akun/sandi"),
    ("POST", "/api/console/dev/akun/status"),
    ("POST", "/api/console/dev/akun/role"),
    ("GET", "/api/console/dev/setelan"),
    ("POST", "/api/console/dev/setelan"),
    ("GET", "/api/console/dev/auto-assign"),
    ("POST", "/api/console/dev/auto-assign"),
    ("GET", "/api/console/dev/scanner-qr"),
    ("POST", "/api/console/dev/scanner-qr"),
    ("GET", "/api/console/dev/timbangan-dummy"),
    ("POST", "/api/console/dev/timbangan-dummy"),
    ("GET", "/api/console/dev/rekam"),
    ("POST", "/api/console/dev/rekam/setelan"),
    ("POST", "/api/console/dev/rekam/{line_code}/mulai"),
    ("POST", "/api/console/dev/rekam/{line_code}/stop"),
    ("GET", "/api/console/dev/sumber-kamera"),
    ("POST", "/api/console/dev/sumber-kamera"),
    ("GET", "/api/console/dev/model-deteksi"),
    ("POST", "/api/console/dev/model-deteksi"),
    ("GET", "/api/console/dev/bahaya"),
    ("POST", "/api/console/dev/bahaya/restart-line"),
    ("POST", "/api/console/dev/bahaya/logout-semua"),
    ("POST", "/api/console/dev/bahaya/hapus-rekaman"),
    ("POST", "/api/console/dev/bahaya/hapus-data"),
    ("POST", "/api/console/dev/riwayat/impor/periksa"),
    ("POST", "/api/console/dev/riwayat/impor"),
    ("GET", "/api/console/dev/riwayat/impor"),
    ("POST", "/api/console/dev/riwayat/impor/{batch_id}/batal"),
    ("GET", "/api/console/dev/plc/{line_code}"),
    ("POST", "/api/console/dev/plc/{line_code}/coil"),
    ("GET", "/demo/{nama}"),
]

RUTE_MESIN = [
    ("POST", "/internal/vision/events"),
    ("GET", "/internal/setelan"),
    ("GET", "/internal/penugasan"),
    ("POST", "/internal/scale/weighing"),
]

DITIMPA_TEST = (
    "SESSION_COOKIE", "get_console_service", "get_auth_service", "get_scan_service", "get_gate_service",
    "get_dev_service", "get_bahaya_service", "get_operator_admin", "get_riwayat_service",
    "get_impor_grading_service", "require_operator", "require_support", "_operator_error",
)


def _peta(router) -> list[tuple[str, str]]:
    return [(sorted(r.methods)[0], r.path) for r in router.routes]


def test_rute_operator_tidak_berubah():
    assert _peta(console.router) == RUTE_OPERATOR


def test_rute_mesin_tidak_berubah():
    assert _peta(ingest_router) == RUTE_MESIN


def test_yang_ditimpa_test_tetap_objek_yang_sama():
    for nama in DITIMPA_TEST:
        assert getattr(console, nama) is getattr(console_deps, nama), nama


def test_rakitan_dan_lane_mesin_tidak_lagi_di_modul_rute():
    sumber = Path(console.__file__).read_text(encoding="utf-8")
    assert "def get_console_service" not in sumber
    assert "ingest_router" not in sumber
