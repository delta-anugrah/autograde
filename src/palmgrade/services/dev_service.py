"""Flow behind the developer screens (support role only).

The value is not new data — `/health/detail`, the ERP queue, settings are all
already logged today. It is that they finally get a screen, instead of only
being readable with `curl`.
"""

from __future__ import annotations

import time
from typing import Any

from ..repositories.log_repository import LogStore

# Purge at most this often. A worker of its own would be one more thread a
# factory PC has to pay for, for a table that grows a few hundred rows a day.
_BUANG_INTERVAL_S = 3600.0


class DevService:
    def __init__(self, log_store: LogStore) -> None:
        self._log = log_store
        self._buang_terakhir = 0.0

    def log(
        self, *, level: str | None, cari: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        self._buang_berkala()
        return self._log.baca(level=level, cari=cari, limit=limit, offset=offset)

    def _buang_berkala(self, *, now: float | None = None) -> None:
        """Sweep expired rows, tied to a read rather than its own timer."""
        sekarang = now if now is not None else time.time()
        if sekarang - self._buang_terakhir < _BUANG_INTERVAL_S:
            return
        self._buang_terakhir = sekarang
        self._log.buang_kedaluwarsa(now=sekarang)
