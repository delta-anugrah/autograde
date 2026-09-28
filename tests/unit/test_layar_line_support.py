"""Tiga layar Support tab Line dipindah ke mixin tanpa mengubah cara memanggilnya."""
from __future__ import annotations

from palmgrade.services.console_service import ConsoleService
from palmgrade.services.layar_line_support import LayarLineSupport

METODE = (
    "setelan_rekam", "simpan_setelan_rekam", "rekam_mulai", "rekam_stop",
    "rekam_status_semua", "sumber_kamera", "simpan_sumber_kamera", "model_deteksi",
    "model_deteksi_async", "simpan_model_deteksi", "_buktikan_berkas", "_restart_yang_berubah",
)


def test_console_service_tetap_punya_metode_layar_line():
    for nama in METODE:
        assert callable(getattr(ConsoleService, nama)), nama


def test_metodenya_tinggal_di_mixin_bukan_di_console_service():
    assert issubclass(ConsoleService, LayarLineSupport)
    for nama in METODE:
        assert nama in vars(LayarLineSupport), nama
        assert nama not in vars(ConsoleService), nama


def test_mixin_tidak_punya_konstruktor_sendiri():
    assert "__init__" not in vars(LayarLineSupport)
