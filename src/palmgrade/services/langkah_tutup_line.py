"""APA yang ditutup proses line sebelum keluar, dan dalam urutan apa (batch 2.2).

Mesinnya `penutup_line.PenutupLine`; di sini cuma daftar langkahnya, dipakai
SIGTERM (lifespan `main.py`) dan `/internal/restart` + `/internal/hapus-data`
tanpa beda satu pun:

1. serentak: coil PLC dimatikan, dan antrean simpan dihabiskan. Serentak karena
   keduanya sumber daya berbeda (jaringan vs disk): link PLC yang mati tidak
   boleh memakan waktu yang dibutuhkan disk, dan sebaliknya;
2. serentak: thread capture dihentikan lalu kamera dilepas (tanpa itu thread
   capture menyambungkan kamera lagi lewat `_try_reconnect`), penjadwal upload R2
   dihentikan TANPA menunggu
   batch yang sedang jalan (batch itu aman diputus: manifest SQLite,
   `test_batch_upload_crash.py`; menunggunya bisa memakan menit).

Janjang yang digrading SESUDAH coil dimatikan tidak lagi dipulse; yang sempat
masuk antrean tetap ditulis. Begitu pengurasan mulai, penulis berhenti menerima
janjang baru (`tutup_pintu`): yang datang sesudahnya ditolak dan disebut di log
ERROR saat itu juga. Yang tidak sempat ditulis disebut satu per satu, bukan
hilang diam-diam.

Bebas torch/cv2 (kolaborator lewat Protocol), jadi teruji di CI.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from ..plc import shutdown_plc_worker
from ..workers.capture_save_worker import sebut_janjang
from .penutup_line import BATAS_TUTUP_S, Langkah

logger = logging.getLogger(__name__)

#: Detik menunggu thread penulis keluar sesudah diminta berhenti. Loop-nya
#: memeriksa tanda berhenti tiap 0,5 detik.
BATAS_HENTI_PENULIS_S = 1.0

#: Sisa untuk tahap 2 (lepas kamera, hentikan penjadwal tanpa menunggu: paling
#: lama beberapa ratus milidetik) dan baris ERROR yang menyebut janjang hilang.
CADANGAN_TAHAP_AKHIR_S = 1.0

#: Detik untuk menghabiskan antrean simpan: semua yang tersisa dari batas tutup.
#: Antrean penuh = 8 antre + 1 dipegang penulis, x ~0,59 detik per janjang (PC
#: Lampung 2026-09-17) = 5,3 detik; semuanya sudah dipulse PLC, jadi harus muat.
#: Angka 0,59 itu SEBELUM tulisan atomik batch 2.6 (fsync berkas + folder). Diukur
#: ulang 2026-09-29 di MacBook (APFS, frame 2448x2048 yang diburamkan supaya encode
#: WebP-nya mirip kamera, ~0,56 dtk per janjang tanpa fsync): 13,7 fsync per janjang,
#: dan dengan flush sungguhan (`F_FULLFSYNC`, setara fsync Linux) 9 janjang naik dari
#: 5,05 ke 5,35-5,39 detik, +33-38 ms per janjang. Dengan angka Lampung: 9 x (0,59 +
#: 0,04) = 5,7 detik, masih muat di 6 detik, jadi batas ini TIDAK diubah. Sisa
#: ruangnya tipis (0,3 detik); angka `tulis ... ms` dari WARNING `Simpan janjang ...
#: lambat` di Lampung sesudah rilis yang menentukan apakah perlu diturunkan ulang.
#: Diturunkan dari `BATAS_TUTUP_S`, bukan angka lepas, supaya tidak ada janjang
#: yang dibuang selagi waktu masih tersisa.
BATAS_KURAS_S = BATAS_TUTUP_S - BATAS_HENTI_PENULIS_S - CADANGAN_TAHAP_AKHIR_S


class PenulisBukti(Protocol):
    """Irisan `CaptureSaveWorker` yang dibutuhkan untuk menutup."""

    @property
    def belum_selesai(self) -> int: ...
    def tutup_pintu(self) -> None: ...
    def tunggu_kosong(self, timeout: float) -> bool: ...
    def stop(self, timeout: float) -> None: ...
    def antrean_tersisa(self) -> list[tuple[str, str | None]]: ...


class Kamera(Protocol):
    def disconnect(self) -> None: ...


class PengambilFrame(Protocol):
    """Irisan `FrameCaptureWorker` yang dibutuhkan untuk menutup."""

    def berhenti(self) -> None: ...


class PenjadwalUnggah(Protocol):
    def stop(self, *, tunggu: bool = True) -> None: ...


def matikan_plc(worker_threads: Sequence[tuple[str, Any, Any]]) -> None:
    """Coil OK/NG/ERROR/alive/manual ke OFF, lewat `shutdown_plc_worker`.

    Thread PLC dicari SAAT menutup, bukan saat urutan dipasang: watchdog 10
    detik bisa sudah menggantinya dengan thread baru.
    """
    thread = next((t for nama, t, _ in worker_threads if nama == "plc"), None)
    shutdown_plc_worker(thread)


def lepas_kamera(worker_threads: Sequence[tuple[str, Any, Any]], kamera: Kamera) -> None:
    """Hentikan thread capture DULU, baru lepas kamera: thread yang masih berputar
    melihat frame kosong dan menyambungkan kamera lagi. Dicari saat menutup, sama
    dengan PLC. Tidak ditunggu: loop-nya selesai sendiri di putaran berikutnya."""
    pengambil: PengambilFrame | None = next((w for nama, _t, w in worker_threads if nama == "capture"), None)
    if pengambil is not None:
        pengambil.berhenti()
    kamera.disconnect()


def _sebut(janjang: list[tuple[str, str | None]]) -> str:
    return ", ".join(sebut_janjang(stempel, assignment) for stempel, assignment in janjang)


def kuras_antrean_simpan(penulis: PenulisBukti, *, batas_s: float = BATAS_KURAS_S) -> None:
    """Tulis semua janjang yang masih antre, maksimal `batas_s` detik, lalu hentikan penulis.

    Pintu ditutup DULU: janjang yang diserahkan sesudah daftar hilang dibaca
    akan diterima, tidak ditulis siapa pun, dan tidak disebut di mana pun.
    """
    penulis.tutup_pintu()
    menunggu = penulis.belum_selesai
    if menunggu:
        logger.warning(
            "Tutup line: menulis %d janjang yang masih antre sebelum keluar (batas %g detik)",
            menunggu, batas_s,
        )
    penulis.tunggu_kosong(timeout=batas_s)
    penulis.stop(timeout=BATAS_HENTI_PENULIS_S)
    hilang = penulis.belum_selesai
    if hilang:
        logger.error(
            "Tutup line: %d janjang TIDAK tertulis: %s. "
            "Antrean simpan tidak habis dalam %g detik (disk lambat atau macet). "
            "Janjang yang sedang dipegang penulis mungkin masih selesai sebelum proses keluar; "
            "yang lain tidak punya foto, sidecar, maupun baris di konsol.",
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
            Langkah("kamera", lambda: lepas_kamera(worker_threads, kamera)),
            Langkah("penjadwal_unggah", lambda: penjadwal.stop(tunggu=False)),
        ],
    ]
