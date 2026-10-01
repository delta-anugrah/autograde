"""Pemantau sisa disk line (batch 3.7), tidak bergantung R2.

Satu objek per proses line, dirakit `main.py` dan dipasang di
`RuntimeState.pemantau_disk`. Dibaca dua jalur yang harus sepakat:
`/health/detail` (kartu Diagnostik) dan `/internal/status` (alert di layar
konsol lewat `LineStatusWorker`). Aturannya murni di `domain/kesehatan_disk.py`;
di sini cuma mengukur partisi, mengingat tingkat terakhir (untuk histeresis dan
jam `sejak`), dan mencatat transisinya ke log sekali masing-masing.

Tidak menghapus apa pun. Tanpa torch atau cv2: test-nya jalan di CI.
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..domain.kesehatan_disk import (
    GB,
    TingkatDisk,
    UkuranDisk,
    ke_kawat,
    nilai_disk,
    peringatan_menyala_terus,
    tersempit,
)

logger = logging.getLogger(__name__)


class PemantauDisk:
    def __init__(
        self,
        *,
        settings: Any,
        jalur: Sequence[Path],
        ukur: Callable[[Path], Any] = shutil.disk_usage,
        jam_dinding: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._jalur = tuple(dict.fromkeys(jalur))
        self._ukur = ukur
        self._jam_dinding = jam_dinding
        self._kunci = threading.Lock()
        self._tingkat = TingkatDisk.AMAN
        self._sejak: float | None = None
        if peringatan_menyala_terus(
            settings.disk_peringatan_gb,
            lantai_retensi_gb=settings.upload_disk_min_free_gb,
            r2_aktif=bool(settings.r2_bucket),
        ):
            logger.warning(
                "DISK_PERINGATAN_GB=%s tidak di bawah UPLOAD_DISK_MIN_FREE_GB=%s: penjaga retensi R2 "
                "menjaga sisa disk di sekitar lantainya, jadi peringatan disk akan menyala terus. "
                "Turunkan DISK_PERINGATAN_GB.",
                settings.disk_peringatan_gb, settings.upload_disk_min_free_gb,
            )

    def ringkas(self) -> dict[str, Any]:
        """Blok `disk` untuk `/health/detail` dan `/internal/status`."""
        ukuran = tersempit(self._ukur_semua())
        peringatan, kritis = self._settings.disk_peringatan_gb, self._settings.disk_kritis_gb
        with self._kunci:
            sebelumnya = self._tingkat
            if ukuran is None:
                tingkat = TingkatDisk.TIDAK_TERBACA
            else:
                tingkat = nilai_disk(
                    ukuran.bebas / GB, peringatan_gb=peringatan, kritis_gb=kritis,
                    sebelumnya=sebelumnya,
                )
            if tingkat != sebelumnya:
                self._tingkat = tingkat
                bermasalah = tingkat in (TingkatDisk.PERINGATAN, TingkatDisk.KRITIS)
                self._sejak = self._jam_dinding() if bermasalah else None
            sejak = self._sejak
        kawat = ke_kawat(tingkat, ukuran, peringatan_gb=peringatan, kritis_gb=kritis, sejak=sejak)
        if tingkat != sebelumnya:
            self._catat_transisi(tingkat, sebelumnya, kawat)
        return kawat

    def _ukur_semua(self) -> list[UkuranDisk]:
        hasil = []
        for jalur in self._jalur:
            try:
                u = self._ukur(jalur)
            except OSError as exc:
                logger.debug("Sisa disk %s tidak terbaca: %s", jalur, exc)
                continue
            hasil.append(UkuranDisk(jalur=str(jalur), total=int(u.total), bebas=int(u.free)))
        return hasil

    def _catat_transisi(self, tingkat: TingkatDisk, sebelumnya: TingkatDisk, k: dict[str, Any]) -> None:
        line = self._settings.line_code
        if tingkat is TingkatDisk.KRITIS:
            logger.error(
                "Disk %s hampir habis (kode DISK_KRITIS): sisa %s GB dari %s GB di %s, di bawah %s GB. "
                "Grading berhenti tersimpan begitu disk habis. Kosongkan sekarang: docker system prune, "
                "pindahkan rekaman video, pastikan unggah R2 jalan.",
                line, k["bebas_gb"], k["total_gb"], k["jalur"], k["ambang_kritis_gb"],
            )
        elif tingkat is TingkatDisk.PERINGATAN:
            logger.warning(
                "Disk %s hampir penuh (kode DISK_HAMPIR_PENUH): sisa %s GB dari %s GB di %s, di bawah "
                "%s GB. Jadwalkan pengosongan: docker system prune, rekaman video, unggah R2.",
                line, k["bebas_gb"], k["total_gb"], k["jalur"], k["ambang_peringatan_gb"],
            )
        elif tingkat is TingkatDisk.TIDAK_TERBACA:
            logger.warning(
                "Sisa disk %s tidak terbaca di %s: pemantau disk tidak bisa memperingatkan",
                line, ", ".join(str(j) for j in self._jalur),
            )
        elif sebelumnya is TingkatDisk.TIDAK_TERBACA:
            logger.warning("Sisa disk %s terbaca lagi: %s GB", line, k["bebas_gb"])
        else:
            logger.warning("Disk %s kembali lega: sisa %s GB", line, k["bebas_gb"])


def ringkas_disk_dari_state(state: Any) -> dict[str, Any] | None:
    """Blok `disk` dari `RuntimeState.pemantau_disk`, atau None kalau belum dipasang
    (line baru menyala, proses konsol, test yang tidak merakit pemantau)."""
    pemantau = getattr(state, "pemantau_disk", None)
    return None if pemantau is None else pemantau.ringkas()
