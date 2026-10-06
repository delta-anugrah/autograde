"""The last live scale reading, held in memory for the console's 1 s poll.

Written by `TimbanganLiveWorker` and read by `GET /api/console/scale/live` and the one
scan field (`berat_layak`, 2026-10-06), all on the event loop, so no lock. Nothing is stored: a weight on the bridge is only true
for the second it is read, and the number that is paid for lives in `weighings`.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..domain.timbangan_live import BASI_DETIK, Bacaan, berat_layak, ringkas


class TimbanganLive:
    def __init__(
        self, *, dipakai: bool, jam: Callable[[], float] = time.monotonic, basi_s: float = BASI_DETIK
    ) -> None:
        self.dipakai = dipakai
        self._jam = jam
        self._basi_s = basi_s
        self._bacaan: Bacaan | None = None
        self._ok_pada: float | None = None
        self._gagal_pada: float | None = None
        # Since when the kilograms have read the same, unbroken by a cut (`berat_layak`).
        self._sama_sejak: float | None = None

    def berhasil(self, bacaan: Bacaan) -> None:
        sekarang = self._jam()
        if self._sama_sejak is None or self._bacaan is None or self._bacaan.kg != bacaan.kg:
            self._sama_sejak = sekarang
        self._bacaan = bacaan
        self._ok_pada = sekarang

    def gagal(self) -> None:
        self._gagal_pada = self._jam()
        # The same number after a cut is one read old, not as old as before the cut.
        self._sama_sejak = None

    def snapshot(self) -> dict:
        return ringkas(
            dipakai=self.dipakai,
            bacaan=self._bacaan,
            ok_pada=self._ok_pada,
            gagal_pada=self._gagal_pada,
            sekarang=self._jam(),
            basi_s=self._basi_s,
        )

    def berat_layak(self, minimum: float) -> int | float | None:
        """The kilograms a scan may save now, or None (the operator types the weight)."""
        tahan = None if self._sama_sejak is None else self._jam() - self._sama_sejak
        return berat_layak(self.snapshot(), tahan, minimum)
