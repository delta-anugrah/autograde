"""The last live scale reading, held in memory for the console's 1 s poll.

Written by `TimbanganLiveWorker` and read by `GET /api/console/scale/live`, both on
the event loop, so no lock. Nothing is stored: a weight on the bridge is only true
for the second it is read, and the number that is paid for lives in `weighings`.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..domain.timbangan_live import BASI_DETIK, Bacaan, ringkas


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

    def berhasil(self, bacaan: Bacaan) -> None:
        self._bacaan = bacaan
        self._ok_pada = self._jam()

    def gagal(self) -> None:
        self._gagal_pada = self._jam()

    def snapshot(self) -> dict:
        return ringkas(
            dipakai=self.dipakai,
            bacaan=self._bacaan,
            ok_pada=self._ok_pada,
            gagal_pada=self._gagal_pada,
            sekarang=self._jam(),
            basi_s=self._basi_s,
        )
