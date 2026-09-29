"""Satu putaran watchdog worker line (parkiran Task 4 batch 2.2, dulu cuma dijaga teks).

Watchdog 10 detik di `main.py` menghidupkan lagi thread worker yang mati. Saat urutan
tutup berjalan, penulis dan PLC SENGAJA dihentikan: menghidupkannya lagi membuka ulang
loop penulis di tengah penutupan.
"""
from __future__ import annotations

import logging

from palmgrade.workers.pengawas_worker import awasi_sekali


class _Thread:
    def __init__(self, hidup: bool) -> None:
        self.hidup = hidup

    def is_alive(self) -> bool:
        return self.hidup


class _Worker:
    def run_loop(self) -> None: ...


def _mulai_dicatat(jejak: list):
    def mulai(nama, target):
        jejak.append((nama, target))
        return _Thread(True)

    return mulai


def test_thread_mati_dihidupkan_lagi_dan_dicatat(caplog):
    worker = _Worker()
    daftar = [("capture", _Thread(True), _Worker()), ("capture_save", _Thread(False), worker)]
    jejak: list = []

    with caplog.at_level(logging.ERROR):
        lanjut = awasi_sekali(daftar, sedang_menutup=lambda: False, mulai=_mulai_dicatat(jejak))

    assert lanjut is True
    assert jejak == [("capture_save", worker.run_loop)]
    assert daftar[1][1].is_alive()
    assert any("capture_save" in r.getMessage() for r in caplog.records)


def test_semua_hidup_tidak_menyentuh_apa_pun():
    daftar = [("capture", _Thread(True), _Worker())]
    jejak: list = []

    assert awasi_sekali(daftar, sedang_menutup=lambda: False, mulai=_mulai_dicatat(jejak)) is True
    assert jejak == []


def test_saat_menutup_thread_mati_tidak_dihidupkan_dan_watchdog_berhenti():
    daftar = [("capture_save", _Thread(False), _Worker()), ("plc", _Thread(False), _Worker())]
    jejak: list = []

    assert awasi_sekali(daftar, sedang_menutup=lambda: True, mulai=_mulai_dicatat(jejak)) is False
    assert jejak == []


def test_tanda_tutup_dibaca_sesudah_thread_terlihat_mati():
    """Urutan tutup bisa mulai di antara putaran: dibaca tepat sebelum menghidupkan,
    bukan sekali di awal putaran (celah yang dijaga `test_main_penutup_wiring`)."""
    bacaan: list = []

    def sedang_menutup() -> bool:
        bacaan.append(1)
        return len(bacaan) > 1  # tutup mulai sesudah thread pertama dihidupkan

    daftar = [("a", _Thread(False), _Worker()), ("b", _Thread(False), _Worker())]
    jejak: list = []

    assert awasi_sekali(daftar, sedang_menutup=sedang_menutup, mulai=_mulai_dicatat(jejak)) is False
    assert [nama for nama, _ in jejak] == ["a"]
