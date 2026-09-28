"""APA yang ditutup proses line sebelum keluar, dan dalam urutan apa (batch 2.2).

Mesinnya `penutup_line.PenutupLine`; di sini cuma daftar langkahnya, dipakai
SIGTERM (lifespan `main.py`) dan `/internal/restart` + `/internal/hapus-data`
tanpa beda satu pun:

1. serentak: coil PLC dimatikan, dan antrean simpan dihabiskan. Serentak karena
   keduanya sumber daya berbeda (jaringan vs disk): link PLC yang mati tidak
   boleh memakan waktu yang dibutuhkan disk, dan sebaliknya;
2. serentak: kamera dilepas, penjadwal upload R2 dihentikan TANPA menunggu
   batch yang sedang jalan (batch itu aman diputus: manifest SQLite,
   `test_batch_upload_crash.py`; menunggunya bisa memakan menit).

Janjang yang digrading SESUDAH coil dimatikan tidak lagi dipulse; yang sempat
masuk antrean tetap ditulis. Yang tidak sempat ditulis disebut satu per satu di
log ERROR, bukan hilang diam-diam.

Bebas torch/cv2 (kolaborator lewat Protocol), jadi teruji di CI.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from ..plc import shutdown_plc_worker
from .penutup_line import Langkah

logger = logging.getLogger(__name__)

#: Detik untuk menghabiskan antrean simpan. Delapan janjang (antrean penuh) x
#: ~0,6 detik per janjang (PC Lampung 2026-09-17) = 4,8 detik: antrean penuh
#: masih muat, disk yang macet tidak menahan restart selamanya.
BATAS_KURAS_S = 5.0

#: Detik menunggu thread penulis keluar sesudah diminta berhenti. Loop-nya
#: memeriksa tanda berhenti tiap 0,5 detik.
BATAS_HENTI_PENULIS_S = 1.0


class PenulisBukti(Protocol):
    """Irisan `CaptureSaveWorker` yang dibutuhkan untuk menutup."""

    @property
    def belum_selesai(self) -> int: ...
    def tunggu_kosong(self, timeout: float) -> bool: ...
    def stop(self, timeout: float) -> None: ...
    def antrean_tersisa(self) -> list[tuple[str, str | None]]: ...


class Kamera(Protocol):
    def disconnect(self) -> None: ...


class PenjadwalUnggah(Protocol):
    def stop(self, *, tunggu: bool = True) -> None: ...


def matikan_plc(worker_threads: Sequence[tuple[str, Any, Any]]) -> None:
    """Coil OK/NG/ERROR/alive/manual ke OFF, lewat `shutdown_plc_worker`.

    Thread PLC dicari SAAT menutup, bukan saat urutan dipasang: watchdog 10
    detik bisa sudah menggantinya dengan thread baru.
    """
    thread = next((t for nama, t, _ in worker_threads if nama == "plc"), None)
    shutdown_plc_worker(thread)


def _sebut(janjang: list[tuple[str, str | None]]) -> str:
    return ", ".join(
        f"{stempel} ({assignment[:8] if assignment else 'tanpa truk'})" for stempel, assignment in janjang
    )


def kuras_antrean_simpan(penulis: PenulisBukti, *, batas_s: float = BATAS_KURAS_S) -> None:
    """Tulis semua janjang yang masih antre, maksimal `batas_s` detik, lalu hentikan penulis."""
    menunggu = penulis.belum_selesai
    if menunggu:
        logger.warning(
            "Tutup line: menulis %d janjang yang masih antre sebelum keluar (batas %.0f detik)",
            menunggu, batas_s,
        )
    penulis.tunggu_kosong(timeout=batas_s)
    penulis.stop(timeout=BATAS_HENTI_PENULIS_S)
    hilang = penulis.belum_selesai
    if hilang:
        logger.error(
            "Tutup line: %d janjang TIDAK tertulis dan hilang bersama proses ini: %s. "
            "Antrean simpan tidak habis dalam %.0f detik (disk lambat atau macet). "
            "Janjang ini tidak punya foto, sidecar, maupun baris di konsol.",
            hilang, _sebut(penulis.antrean_tersisa()) or "-", batas_s,
        )


def langkah_tutup_line(
    *,
    worker_threads: Sequence[tuple[str, Any, Any]],
    penulis: PenulisBukti,
    kamera: Kamera,
    penjadwal: PenjadwalUnggah,
    batas_kuras_s: float = BATAS_KURAS_S,
) -> list[list[Langkah]]:
    """Tahap-tahap tutup satu proses line, untuk `PenutupLine.pasang`."""
    return [
        [
            Langkah("plc", lambda: matikan_plc(worker_threads)),
            Langkah("antrean_simpan", lambda: kuras_antrean_simpan(penulis, batas_s=batas_kuras_s)),
        ],
        [
            Langkah("kamera", kamera.disconnect),
            Langkah("penjadwal_unggah", lambda: penjadwal.stop(tunggu=False)),
        ],
    ]
