"""Line yang tidak terbaca konsol, ditulis ke tab Log satu baris per kejadian (2026-10-01).

Dipakai ketiga pembaca line di konsol: `LineStatusWorker` (`/internal/status` tiap detik),
`DevService.diagnostics` (`/health/detail`, kartu Diagnostik) dan `PantauAntreanLine`
(`/internal/outbox`, Antrean line). Layar cuma menulis kalimat ramah dari `sebab_kode` dan
menunjuk ke tab Log; di sinilah alasan mentahnya tertulis. Aturannya
`domain/episode_tak_terbaca.py`, satu objek per line; `sumber` membedakan pembacanya.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ..domain.episode_tak_terbaca import TENGGANG_START_S, EpisodeTakTerbaca
from ..domain.line_tak_terbaca import SEBAB_KUNCI_DITOLAK
from ..domain.transisi import teks_lama

#: Jam monotonic saat modul ini dimuat, yaitu saat konsol menyala: tenggang start dihitung
#: dari sini, bukan dari permintaan pertama yang membuat DevService atau PantauAntreanLine.
_PROSES_MULAI = time.monotonic()


class JejakTakTerbaca:
    def __init__(
        self,
        logger: logging.Logger,
        sumber: str,
        *,
        jam: Callable[[], float] = time.monotonic,
        mulai: float | None = None,
        tenggang_s: float = TENGGANG_START_S,
    ) -> None:
        self._logger = logger
        self._sumber = sumber
        self._jam = jam
        self._mulai = _PROSES_MULAI if mulai is None else mulai
        self._tenggang_s = tenggang_s
        self._per_line: dict[str, EpisodeTakTerbaca] = {}

    def _episode(self, line_code: str) -> EpisodeTakTerbaca:
        if line_code not in self._per_line:
            self._per_line[line_code] = EpisodeTakTerbaca(
                mulai=self._mulai, jam=self._jam, tenggang_s=self._tenggang_s
            )
        return self._per_line[line_code]

    def gagal(self, line_code: str, sebab: str, mentah: str) -> None:
        """Satu bacaan gagal; WARNING dengan sebab dan alasan mentah PERTAMA saat kejadian pantas ditulis."""
        awal = self._episode(line_code).gagal(sebab, mentah)
        if awal is None:
            return
        sebab_awal, mentah_awal = awal
        if sebab_awal == SEBAB_KUNCI_DITOLAK:
            self._logger.warning(
                "%s menolak kunci konsol (%s): INTERNAL_SECRET di line itu beda dari yang dipakai konsol (%s)",
                line_code, self._sumber, mentah_awal,
            )
        else:
            self._logger.warning(
                "%s tidak terbaca oleh konsol (%s, %s): %s", line_code, self._sumber, sebab_awal, mentah_awal
            )

    def pulih(self, line_code: str) -> None:
        """Satu bacaan berhasil; WARNING dengan lamanya kalau awal kejadiannya tadi ditulis."""
        lama = self._episode(line_code).pulih()
        if lama is not None:
            self._logger.warning(
                "%s terbaca lagi oleh konsol (%s) sesudah %s, sudah pulih", line_code, self._sumber, teks_lama(lama)
            )
