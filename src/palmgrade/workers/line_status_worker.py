"""Cache status ketiga line untuk layar operator.

`/api/console/state` dipanggil tiap 2 detik oleh layar, sementara satu line yang
sekarat bisa menggantung sampai timeout. Kalau state memanggil line langsung,
satu line mati membekukan seluruh konsol. Jadi yang memanggil line adalah worker
ini, di latar, dan state cuma membaca hasil terakhirnya.

Hidup terlepas dari AutoERP: konsol tanpa `ERP_URL` tetap butuh tombol piston.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LineStatusWorker:
    def __init__(self, lines, line_client, *, interval_s: float = 1.0) -> None:
        self._lines = list(lines)
        self._client = line_client
        self._interval_s = interval_s
        self._state: dict[str, dict[str, Any]] = {}

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._state)

    async def run_once(self) -> None:
        for line in self._lines:
            try:
                jawab = await self._client.status(line)
            except Exception as exc:                      # line mati bukan alasan berhenti
                logger.debug("Status %s tidak terbaca: %s", line.line_code, exc)
                self._state[line.line_code] = {"reachable": False}
                continue
            piston = jawab.get("piston") or {}
            self._state[line.line_code] = {
                "reachable": True,
                "ffb_source": jawab.get("ffb_source"),
                "piston_requested": piston.get("requested"),
                "piston_open": piston.get("confirmed_open"),
                # `or []`: line versi lama tidak mengirim field ini, dan None
                # di layar akan membuat pita alarm gagal merender.
                "alarms": jawab.get("alarms") or [],
            }

    async def run_loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_s)
