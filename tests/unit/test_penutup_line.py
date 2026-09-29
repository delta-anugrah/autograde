"""Urutan tutup line (batch 2.2): berurutan per tahap, serentak di dalam tahap,
berbatas waktu, sekali jalan, dan keluar tetap terjadi apa pun yang macet.

Dulu `/internal/restart` dan `/internal/hapus-data` memanggil `os._exit`
langsung: coil PLC tertinggal ON dan sampai 8 janjang yang sudah dipulse hilang.
"""
from __future__ import annotations

import logging
import threading
import time

import pytest

from palmgrade.services.penutup_line import BATAS_TUTUP_S, Langkah, PenutupLine

LOGGER = "palmgrade.services.penutup_line"


def _catat(jejak: list, nama: str) -> Langkah:
    return Langkah(nama, lambda: jejak.append(nama))


def _pesan_error(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_tahap_dijalankan_berurutan():
    jejak: list = []
    p = PenutupLine(batas_s=5)
    p.pasang([[_catat(jejak, "a")], [_catat(jejak, "b")], [_catat(jejak, "c")]])

    assert p.tutup("uji") is True
    assert jejak == ["a", "b", "c"]


def test_plc_yang_macet_tidak_menahan_antrean_simpan():
    """Link PLC mati = tiap tulis coil menunggu timeout socket. Antrean simpan
    di tahap yang sama tetap harus selesai (Review Focus 2)."""
    plc_lepas = threading.Event()
    kuras_selesai = threading.Event()
    p = PenutupLine(batas_s=0.5)
    p.pasang([[Langkah("plc", lambda: plc_lepas.wait(5)), Langkah("antrean_simpan", kuras_selesai.set)]])
    try:
        assert p.tutup("uji") is False
        assert kuras_selesai.is_set()
    finally:
        plc_lepas.set()


def test_langkah_yang_gagal_tidak_menghentikan_yang_lain(caplog):
    jejak: list = []

    def rusak() -> None:
        raise RuntimeError("kamera tidak menjawab")

    p = PenutupLine(batas_s=5)
    p.pasang([[Langkah("kamera", rusak)], [_catat(jejak, "penjadwal_unggah")]])
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert p.tutup("uji") is True

    assert jejak == ["penjadwal_unggah"]
    assert any("kamera" in m for m in _pesan_error(caplog))


def test_melewati_batas_menyebut_langkah_yang_macet_saja(caplog):
    lepas = threading.Event()
    p = PenutupLine(batas_s=0.2)
    p.pasang([[Langkah("plc", lambda: lepas.wait(5)), Langkah("antrean_simpan", lambda: None)]])
    mulai = time.monotonic()
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            assert p.tutup("uji") is False
        assert time.monotonic() - mulai < 2
    finally:
        lepas.set()

    pesan = _pesan_error(caplog)
    assert len(pesan) == 1
    assert "plc" in pesan[0] and "antrean_simpan" not in pesan[0]


def test_melewati_batas_menyebut_langkah_yang_belum_sempat_mulai(caplog):
    """Parkiran Task 2: tahap 1 macet = kamera dan penjadwal tidak pernah dijalankan.
    ERROR-nya harus menyebut itu juga, bukan cuma langkah yang sedang jalan."""
    lepas = threading.Event()
    p = PenutupLine(batas_s=0.2)
    p.pasang([
        [Langkah("antrean_simpan", lambda: lepas.wait(5))],
        [Langkah("kamera", lambda: None), Langkah("penjadwal_unggah", lambda: None)],
    ])
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            assert p.tutup("uji") is False
    finally:
        lepas.set()

    [pesan] = _pesan_error(caplog)
    assert "belum selesai: antrean_simpan" in pesan
    assert "belum dimulai: kamera, penjadwal_unggah" in pesan


def test_nama_langkah_kembar_ditolak():
    """Langkah yang macet dicari lewat namanya: dua langkah bernama sama akan saling
    menghapus dari daftar yang disebut ERROR."""
    p = PenutupLine(batas_s=1)
    with pytest.raises(ValueError, match="plc"):
        p.pasang([[Langkah("plc", lambda: None)], [Langkah("plc", lambda: None)]])


class _SelesaiDihitung(threading.Event):
    """`_selesai` yang menghitung pemanggil yang sedang menunggunya."""

    def __init__(self) -> None:
        super().__init__()
        self.menunggu = 0

    def wait(self, timeout=None):
        self.menunggu += 1
        return super().wait(timeout)


def test_tutup_dua_kali_langkah_jalan_sekali():
    """SIGTERM yang datang saat restart sedang menutup (Review Focus 4). Langkahnya baru
    dilepas sesudah KEDUA pemanggil terbukti menunggu, bukan sesudah jeda tebakan."""
    hitung: list = []
    lepas = threading.Event()

    def lambat() -> None:
        lepas.wait(5)
        hitung.append(1)

    p = PenutupLine(batas_s=5)
    p._selesai = _SelesaiDihitung()
    p.pasang([[Langkah("antrean_simpan", lambat)]])
    hasil: list = []
    benang = [threading.Thread(target=lambda a=a: hasil.append(p.tutup(a))) for a in ("konsol", "SIGTERM")]
    for b in benang:
        b.start()
    batas = time.monotonic() + 5
    while p._selesai.menunggu < 2 and time.monotonic() < batas:
        time.sleep(0.005)
    assert p._selesai.menunggu == 2
    lepas.set()
    for b in benang:
        b.join(5)

    assert hitung == [1]
    assert hasil == [True, True]


def test_sedang_menutup_menyala_begitu_tutup_dipanggil():
    p = PenutupLine(batas_s=1)
    assert p.sedang_menutup is False
    p.tutup("uji")
    assert p.sedang_menutup is True


def test_urutan_tidak_bisa_diganti_sesudah_tutup_mulai():
    p = PenutupLine(batas_s=1)
    p.tutup("uji")
    with pytest.raises(RuntimeError):
        p.pasang([[Langkah("x", lambda: None)]])


def test_keluar_nanti_menunggu_jeda_menutup_lalu_keluar_dengan_kode_nol():
    jejak: list = []
    keluar = threading.Event()

    def catat_keluar(kode: int) -> None:
        jejak.append(("keluar", kode))
        keluar.set()

    p = PenutupLine(batas_s=5, keluar=catat_keluar, tidur=lambda s: jejak.append(("tidur", s)))
    p.pasang([[_catat(jejak, "plc")]])
    p.keluar_nanti(1.0)

    assert keluar.wait(5)
    assert jejak == [("tidur", 1.0), "plc", ("keluar", 0)]


def test_keluar_tetap_terjadi_walau_tutup_melewati_batas():
    """Disk macet tidak boleh membuat restart menggantung selamanya (Review Focus 1)."""
    lepas = threading.Event()
    keluar = threading.Event()
    kode: list = []

    def catat_keluar(k: int) -> None:
        kode.append(k)
        keluar.set()

    p = PenutupLine(batas_s=0.2, keluar=catat_keluar, tidur=lambda s: None)
    p.pasang([[Langkah("antrean_simpan", lambda: lepas.wait(5))]])
    try:
        p.keluar_nanti(0)
        assert keluar.wait(3)
        assert kode == [0]
    finally:
        lepas.set()


def test_tanpa_langkah_terpasang_tetap_keluar():
    keluar = threading.Event()
    p = PenutupLine(batas_s=1, keluar=lambda k: keluar.set(), tidur=lambda s: None)
    p.keluar_nanti(0)
    assert keluar.wait(3)


def test_pesan_keluar_tidak_menjanjikan_docker(caplog):
    """Jalur native dinyalakan ulang `make line`, bukan Docker (2026-09-21)."""
    keluar = threading.Event()
    p = PenutupLine(batas_s=1, keluar=lambda k: keluar.set(), tidur=lambda s: None)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        p.keluar_nanti(0)
        assert keluar.wait(3)
    assert caplog.records
    assert not any("Docker" in r.getMessage() for r in caplog.records)


def test_batas_di_bawah_tenggang_docker_stop():
    # `docker stop` menunggu 10 detik lalu SIGKILL: ERROR yang menyebut langkah
    # macet harus sempat tertulis sebelum itu.
    assert BATAS_TUTUP_S < 10
