"""Satu urutan tutup untuk proses line: SIGTERM dan keluar atas permintaan konsol.

Sampai batch 2.2 ada dua jalan keluar yang berbeda nasibnya. SIGTERM (`docker
stop`, `autograde restart`) lewat blok sesudah `yield` di lifespan `main.py`:
coil PLC dimatikan dan antrean simpan dihabiskan dulu. `/internal/restart` dan
`/internal/hapus-data` memanggil `os._exit` langsung dan melewati keduanya:
sampai 8 janjang yang sudah dipulse PLC hilang tanpa foto, sidecar, maupun
baris di konsol, dan coil yang sedang ON tertinggal ON.

Kelas ini tidak tahu APA yang ditutup (itu `langkah_tutup_line.py`); dia cuma
menjamin tiga hal untuk kedua jalan itu:

- berurutan per tahap, dan langkah dalam satu tahap jalan BERSAMAAN: link PLC
  yang mati (tiap tulis coil menunggu timeout socket) tidak boleh menghabiskan
  waktu yang dibutuhkan antrean simpan;
- ada batas waktu untuk semuanya: disk yang macet tidak boleh membuat restart
  menggantung selamanya. Lewat batas, langkah yang belum selesai disebut di
  log ERROR dan proses tetap keluar;
- sekali jalan: SIGTERM yang datang saat restart sedang menutup menunggu
  urutan yang sama, bukan menjalankannya dua kali.

Bebas torch/cv2, jadi teruji di CI.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Batas seluruh urutan tutup, detik. Di bawah tenggang `docker stop` bawaan
#: (10 detik sebelum SIGKILL), supaya baris ERROR yang menyebut langkah macet
#: sempat tertulis di jalur SIGTERM juga.
BATAS_TUTUP_S = 9.0


@dataclass(frozen=True)
class Langkah:
    """Satu hal yang harus beres sebelum proses keluar."""

    nama: str
    jalankan: Callable[[], None]


class PenutupLine:
    def __init__(
        self,
        *,
        batas_s: float = BATAS_TUTUP_S,
        keluar: Callable[[int], None] = os._exit,
        tidur: Callable[[float], None] = time.sleep,
    ) -> None:
        self._batas_s = batas_s
        self._keluar = keluar
        self._tidur = tidur
        self._tahap: list[list[Langkah]] = []
        self._kunci = threading.Lock()
        self._mulai = threading.Event()
        self._selesai = threading.Event()
        self._berjalan: set[str] = set()

    @property
    def sedang_menutup(self) -> bool:
        """True begitu urutan tutup dimulai. Watchdog `main.py` membacanya supaya
        tidak menghidupkan lagi worker yang sengaja dihentikan."""
        return self._mulai.is_set()

    def pasang(self, tahap: Sequence[Sequence[Langkah]]) -> None:
        """Pasang urutan tutup. Dipanggil lifespan sekali, sesudah worker dibuat."""
        with self._kunci:
            if self._mulai.is_set():
                raise RuntimeError("urutan tutup line sudah berjalan, tidak bisa diganti")
            self._tahap = [list(satu) for satu in tahap]

    def tutup(self, alasan: str) -> bool:
        """Jalankan urutan tutup sekali. True = semua langkah selesai dalam batas.

        Pemanggil kedua (SIGTERM saat restart sedang menutup) tidak menjalankan
        apa pun lagi: dia menunggu urutan yang sudah berjalan.
        """
        with self._kunci:
            pertama = not self._mulai.is_set()
            self._mulai.set()
            tahap = self._tahap
        if pertama:
            logger.warning("Menutup line (%s): coil PLC dimatikan dan antrean simpan dihabiskan dulu", alasan)
            threading.Thread(
                target=self._jalankan, args=(tahap,), daemon=True, name="penutup"
            ).start()
        if self._selesai.wait(self._batas_s):
            return True
        with self._kunci:
            macet = sorted(self._berjalan)
        logger.error(
            "Tutup line (%s) melewati batas %.0f detik; belum selesai: %s. "
            "Proses keluar tanpa menunggunya.",
            alasan, self._batas_s, ", ".join(macet) or "-",
        )
        return False

    def keluar_nanti(self, jeda: float) -> None:
        """Tutup rapi lalu keluar, `jeda` detik dari sekarang, di thread sendiri.

        Menjawab lebih dulu, keluar belakangan: konsol yang melihat koneksi putus
        akan melaporkan gagal padahal berhasil. `os._exit`, bukan `sys.exit`:
        yang dituju container berhenti supaya `restart: unless-stopped` (atau
        loop `make line`) menyalakannya lagi dengan environment yang dibaca
        ulang; `sys.exit` dari thread non-utama cuma menghentikan thread itu.
        Keluar tetap terjadi walau urutan tutup melewati batas.
        """
        def jalan() -> None:
            try:
                self._tidur(jeda)
                self.tutup("permintaan konsol")
                # Tidak menyebut "Docker": jalur native dinyalakan ulang loop
                # `make line`, dan pesan yang menyebut Docker membuat orang
                # mencari container yang tidak ada.
                logger.warning("Keluar atas permintaan konsol, menunggu dinyalakan ulang")
            finally:
                self._keluar(0)

        threading.Thread(target=jalan, daemon=True, name="restart").start()

    # ── privat ──────────────────────────────────────────────────────────────

    def _jalankan(self, tahap: list[list[Langkah]]) -> None:
        try:
            for satu_tahap in tahap:
                benang = [
                    threading.Thread(
                        target=self._satu, args=(langkah,), daemon=True, name=f"tutup-{langkah.nama}"
                    )
                    for langkah in satu_tahap
                ]
                for b in benang:
                    b.start()
                for b in benang:
                    b.join()
        finally:
            self._selesai.set()

    def _satu(self, langkah: Langkah) -> None:
        with self._kunci:
            self._berjalan.add(langkah.nama)
        mulai = time.monotonic()
        try:
            langkah.jalankan()
        except Exception:
            logger.exception("Langkah tutup %r gagal; langkah lain tetap dijalankan", langkah.nama)
        finally:
            with self._kunci:
                self._berjalan.discard(langkah.nama)
            logger.info("Langkah tutup %r selesai dalam %.1f detik", langkah.nama, time.monotonic() - mulai)
