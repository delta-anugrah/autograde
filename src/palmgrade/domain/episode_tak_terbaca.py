"""Kapan line yang tidak terbaca konsol pantas jadi baris tab Log (2026-10-01).

Satu aturan untuk ketiga pembaca line di konsol (`LineStatusWorker`, kartu Diagnostik,
Antrean line), satu objek per line per pembaca:

- awal kejadian ditulis sesudah `TAK_TERBACA_POLL_BERTURUT` poll gagal berturut: satu poll
  yang lewat timeout (line sibuk inferensi) bukan kejadian;
- yang ditulis SEBAB PERTAMA kejadian itu beserta alasan mentahnya; sebab yang berganti di
  tengah kejadian tidak menulis apa pun (ruling fix wave: tiap poll yang berganti sebab dulu
  menulis satu baris);
- pulih ditulis sekali, lamanya dihitung dari poll gagal PERTAMA, dan hanya kalau awalnya
  ditulis;
- selama `TENGGANG_START_S` sesudah konsol menyala (line masih memuat model) awal tidak
  ditulis; line yang masih tidak terbaca sesudahnya ditulis biasa, dihitung dari gagal
  pertamanya.

Murni: jam disuntikkan, tidak menulis log sendiri (pola `domain/transisi.py`).
"""
from __future__ import annotations

import time
from collections.abc import Callable

#: Poll gagal berturut sebelum awal kejadian ditulis.
TAK_TERBACA_POLL_BERTURUT = 3
#: Detik sesudah konsol menyala tanpa baris "tidak terbaca": ketiga line memuat model dulu.
TENGGANG_START_S = 120.0


class EpisodeTakTerbaca:
    """Satu line di mata satu pembaca konsol."""

    def __init__(
        self,
        *,
        mulai: float,
        jam: Callable[[], float] = time.monotonic,
        ambang: int = TAK_TERBACA_POLL_BERTURUT,
        tenggang_s: float = TENGGANG_START_S,
    ) -> None:
        self._mulai = mulai
        self._jam = jam
        self._ambang = ambang
        self._tenggang_s = tenggang_s
        self._sejak: float | None = None
        self._beruntun = 0
        self._pertama: tuple[str, str] | None = None
        self._ditulis = False

    def gagal(self, sebab: str, mentah: str) -> tuple[str, str] | None:
        """Catat satu poll gagal. `(sebab, mentah)` pertama kejadian kalau awalnya pantas ditulis SEKARANG."""
        sekarang = self._jam()
        if self._sejak is None:
            self._sejak = sekarang
            self._pertama = (sebab, mentah)
        self._beruntun += 1
        if self._ditulis or self._beruntun < self._ambang:
            return None
        if sekarang - self._mulai < self._tenggang_s:
            return None
        self._ditulis = True
        return self._pertama

    def pulih(self) -> float | None:
        """Catat satu poll berhasil. Lama kejadian (dari gagal pertama) kalau awalnya tadi ditulis."""
        lama = None
        if self._ditulis and self._sejak is not None:
            lama = max(0.0, self._jam() - self._sejak)
        self._sejak = None
        self._beruntun = 0
        self._pertama = None
        self._ditulis = False
        return lama
