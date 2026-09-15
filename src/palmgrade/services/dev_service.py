"""Flow behind the developer screens (support role only).

The value is not new data — `/health/detail`, the ERP queue, settings are all
already logged today. It is that they finally get a screen, instead of only
being readable with `curl`.

Flow only: HTTP to the lines lives in `LineClient`, persistence in
`ErpOutboxStore` and `LogStore`. This class just asks them and shapes the
answer for the screen.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..core.config import LineEndpoint, Settings
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..integrations.notifications.line_client import LineClient
from ..repositories.log_repository import LogStore

# Purge at most this often. A worker of its own would be one more thread a
# factory PC has to pay for, for a table that grows a few hundred rows a day.
_BUANG_INTERVAL_S = 3600.0


class DevService:
    def __init__(
        self,
        log_store: LogStore,
        *,
        line_client: LineClient | None = None,
        lines: tuple[LineEndpoint, ...] = (),
        erp_outbox: ErpOutboxStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._log = log_store
        self._buang_terakhir = 0.0
        self._line_client = line_client
        self._lines = lines
        self._erp_outbox = erp_outbox
        self._settings = settings

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

    async def diagnostik(self) -> dict[str, Any]:
        """`/health/detail` from every line, gathered concurrently.

        A line that does not answer is reported `terjangkau: False` with the
        reason, never raised — a dead line is the thing this screen most
        needs to show, and one dead line must not empty it for the other two.
        """
        hasil = await asyncio.gather(
            *(self._satu_line(line) for line in self._lines), return_exceptions=True
        )
        lines: dict[str, Any] = {}
        for line, entry in zip(self._lines, hasil, strict=True):
            # Any exception (LineUnavailable or otherwise) reads as unreachable —
            # a bug in one line's fetch must not take the other two cards down too.
            if isinstance(entry, BaseException):
                lines[line.line_code] = {"terjangkau": False, "sebab": str(entry)}
            else:
                lines[line.line_code] = {"terjangkau": True, **entry}
        return {"lines": lines}

    async def _satu_line(self, line: LineEndpoint) -> dict[str, Any]:
        return await self._line_client.health_detail(line)

    def antrean(self) -> dict[str, Any]:
        return {
            "pending": self._erp_outbox.pending_count(),
            "gagal": self._erp_outbox.failed_count(),
            "items": self._erp_outbox.daftar_gagal(limit=50),
        }

    def kirim_ulang(self) -> dict[str, Any]:
        return {"dikirim_ulang": self._erp_outbox.requeue_failed()}

    def versi(self) -> dict[str, Any]:
        """Version, machine id, environment, licence state.

        Never the webhook secret, the ERP key, or a password hash — this
        screen is read over AnyDesk, not a place for credentials.
        """
        return {
            "versi": self._settings.app_version,
            "machine_id": self._settings.machine_id,
            "environment": self._settings.environment,
            "lisensi": {
                "aktif": self._settings.lic_enabled,
                "token_terpasang": bool(self._settings.lic_token),
            },
        }
