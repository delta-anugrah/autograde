"""Langkah tutup satu proses line (batch 2.2): apa, urutannya, dan log-nya.

Kolaborator di-stub (Protocol); rangkaian dengan penulis, storage, dan
`PlcWorker` sungguhan ada di `tests/integration/test_tutup_line_integrasi.py`.
"""
from __future__ import annotations

import logging

import palmgrade.services.langkah_tutup_line as modul
from palmgrade.services.langkah_tutup_line import (
    BATAS_HENTI_PENULIS_S,
    BATAS_KURAS_S,
    CADANGAN_TAHAP_AKHIR_S,
    kuras_antrean_simpan,
    langkah_tutup_line,
    lepas_kamera,
    matikan_plc,
)
from palmgrade.services.penutup_line import BATAS_TUTUP_S
from palmgrade.workers.capture_save_worker import _QUEUE_MAX

LOGGER = "palmgrade.services.langkah_tutup_line"


class _Penulis:
    """`sisa_sesudah` = janjang yang masih belum tertulis sesudah dihentikan."""

    def __init__(self, *, sebelum: int, sisa_sesudah: list[tuple[str, str | None]]) -> None:
        self._belum = sebelum
        self._sisa = sisa_sesudah
        self.jejak: list = []

    @property
    def belum_selesai(self) -> int:
        return self._belum

    def tutup_pintu(self) -> None:
        self.jejak.append(("tutup_pintu",))

    def tunggu_kosong(self, timeout: float) -> bool:
        self.jejak.append(("tunggu", timeout))
        self._belum = len(self._sisa)
        return not self._sisa

    def stop(self, timeout: float) -> None:
        self.jejak.append(("stop", timeout))

    def antrean_tersisa(self) -> list[tuple[str, str | None]]:
        return list(self._sisa)


class _Kamera:
    def __init__(self) -> None:
        self.lepas = 0

    def disconnect(self) -> None:
        self.lepas += 1


class _Penjadwal:
    def __init__(self) -> None:
        self.tunggu: list[bool] = []

    def stop(self, *, tunggu: bool = True) -> None:
        self.tunggu.append(tunggu)


def test_tahap_plc_bersama_antrean_lalu_kamera_bersama_penjadwal():
    tahap = langkah_tutup_line(
        worker_threads=[], penulis=_Penulis(sebelum=0, sisa_sesudah=[]),
        kamera=_Kamera(), penjadwal=_Penjadwal(),
    )
    assert [[langkah.nama for langkah in satu] for satu in tahap] == [
        ["plc", "antrean_simpan"],
        ["kamera", "penjadwal_unggah"],
    ]


def test_penjadwal_dihentikan_tanpa_menunggu_batch_yang_jalan():
    penjadwal = _Penjadwal()
    kamera = _Kamera()
    tahap = langkah_tutup_line(
        worker_threads=[], penulis=_Penulis(sebelum=0, sisa_sesudah=[]),
        kamera=kamera, penjadwal=penjadwal,
    )
    for langkah in tahap[1]:
        langkah.jalankan()
    assert penjadwal.tunggu == [False]
    assert kamera.lepas == 1


def test_antrean_habis_dihentikan_tanpa_error(caplog):
    penulis = _Penulis(sebelum=3, sisa_sesudah=[])
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        kuras_antrean_simpan(penulis, batas_s=5.0)

    # Pintu ditutup DULU: janjang yang datang sesudah daftar hilang dibaca
    # tidak boleh diterima lalu hilang tanpa disebut.
    assert penulis.jejak == [("tutup_pintu",), ("tunggu", 5.0), ("stop", BATAS_HENTI_PENULIS_S)]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("3 janjang" in r.getMessage() for r in caplog.records)


def test_antrean_yang_tidak_habis_disebut_satu_per_satu(caplog):
    penulis = _Penulis(
        sebelum=2,
        sisa_sesudah=[
            ("2026-09-28_091432_000001", "a3f9c201-dead-beef"),
            ("2026-09-28_091433_000002", None),
        ],
    )
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        kuras_antrean_simpan(penulis, batas_s=0.5)

    error = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error) == 1
    assert "2 janjang" in error[0]
    assert "2026-09-28_091432_000001 (a3f9c201)" in error[0]
    assert "2026-09-28_091433_000002 (tanpa truk)" in error[0]


def test_error_tidak_memastikan_janjang_yang_masih_dipegang_penulis_hilang(caplog):
    """Final review line M6: sesudah batas, penulis bisa masih menyelesaikan janjang yang
    sedang dipegangnya sebelum proses keluar (`keluar_nanti` menunggu `os._exit`). ERROR
    yang bilang semuanya "hilang" salah ke arah yang aman, tapi tetap salah: support
    mencari foto yang sebenarnya ada."""
    penulis = _Penulis(sebelum=1, sisa_sesudah=[("2026-09-28_091432_000001", None)])
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        kuras_antrean_simpan(penulis, batas_s=0.3)

    [error] = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert "1 janjang TIDAK tertulis" in error
    assert "hilang bersama proses" not in error
    assert "mungkin masih selesai" in error


def test_plc_dicari_saat_menutup_bukan_saat_dipasang(monkeypatch):
    """Watchdog bisa sudah mengganti thread PLC dengan yang baru."""
    dimatikan: list = []
    monkeypatch.setattr(modul, "shutdown_plc_worker", dimatikan.append)
    threads: list = [("plc", "thread-lama", object())]
    tahap = langkah_tutup_line(
        worker_threads=threads, penulis=_Penulis(sebelum=0, sisa_sesudah=[]),
        kamera=_Kamera(), penjadwal=_Penjadwal(),
    )
    threads[0] = ("plc", "thread-baru", object())

    tahap[0][0].jalankan()
    assert dimatikan == ["thread-baru"]


def test_tanpa_plc_tetap_aman(monkeypatch):
    dimatikan: list = []
    monkeypatch.setattr(modul, "shutdown_plc_worker", dimatikan.append)
    matikan_plc([("capture", "t", object())])
    assert dimatikan == [None]


def test_batas_kuras_muat_dalam_batas_tutup():
    """Kuras + henti penulis + tahap kamera/penjadwal harus muat di `BATAS_TUTUP_S`:
    lewat dari itu `os._exit` memotong ERROR yang menyebut janjang hilang."""
    assert BATAS_KURAS_S + BATAS_HENTI_PENULIS_S + CADANGAN_TAHAP_AKHIR_S <= BATAS_TUTUP_S


def test_batas_kuras_cukup_untuk_antrean_penuh():
    """Antrean penuh + satu yang dipegang penulis, ~0,59 detik per janjang (PC Lampung
    2026-09-17) ditambah ~0,04 detik fsync tulisan atomik batch 2.6 (diukur 2026-09-29,
    lihat komentar `BATAS_KURAS_S`): semuanya sudah dipulse PLC, jadi harus sempat ditulis."""
    assert (_QUEUE_MAX + 1) * (0.59 + 0.04) <= BATAS_KURAS_S


def test_batas_di_bawah_satu_detik_tidak_ditulis_nol(caplog):
    penulis = _Penulis(sebelum=1, sisa_sesudah=[("2026-09-28_091432_000001", None)])
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        kuras_antrean_simpan(penulis, batas_s=0.3)
    teks = " ".join(r.getMessage() for r in caplog.records)
    assert "0.3 detik" in teks
    assert "0 detik" not in teks


class _Pengambil:
    def __init__(self, jejak: list) -> None:
        self._jejak = jejak

    def berhenti(self) -> None:
        self._jejak.append("capture berhenti")


class _KameraDicatat:
    def __init__(self, jejak: list) -> None:
        self._jejak = jejak

    def disconnect(self) -> None:
        self._jejak.append("kamera dilepas")


def test_langkah_kamera_menghentikan_capture_dulu_baru_melepas_kamera():
    """Parkiran Task 3: thread capture yang masih berputar sesudah kamera dilepas
    menyambungkannya lagi lewat `_try_reconnect`."""
    jejak: list = []
    threads: list = [("capture", "t", object())]
    tahap = langkah_tutup_line(
        worker_threads=threads, penulis=_Penulis(sebelum=0, sisa_sesudah=[]),
        kamera=_KameraDicatat(jejak), penjadwal=_Penjadwal(),
    )
    threads[0] = ("capture", "thread-baru", _Pengambil(jejak))  # watchdog mengganti

    [langkah] = [lk for lk in tahap[1] if lk.nama == "kamera"]
    langkah.jalankan()

    assert jejak == ["capture berhenti", "kamera dilepas"]


def test_lepas_kamera_tanpa_worker_capture_tetap_melepas():
    jejak: list = []
    lepas_kamera([("plc", "t", object())], _KameraDicatat(jejak))
    assert jejak == ["kamera dilepas"]
