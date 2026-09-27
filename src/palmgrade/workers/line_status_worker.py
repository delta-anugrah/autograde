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
        # Sejak kapan upload foto tiap line gagal, menurut putaran terakhir. Hanya
        # untuk mencatat putus/pulih sekali masing-masing ke tab Log.
        self._unggah_putus: dict[str, float | None] = {}

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
                # Cloud Photo di Last Sync. None dari line versi lama: konsol
                # menulisnya "tidak terbaca", bukan menganggapnya putus.
                "unggah": jawab.get("unggah"),
            }
            self._catat_unggah(line.line_code, jawab.get("unggah"))

    def _catat_unggah(self, kode: str, unggah: dict[str, Any] | None) -> None:
        """Upload foto line putus/pulih → satu WARNING, supaya masuk tab Log.

        Line tidak memasang log_sink, jadi tanpa ini alasan gagalnya cuma ada di
        `docker logs` line. Pulih baru dicatat kalau jam unggah melewati awal putus:
        line yang restart melupakan status gagalnya sampai batch berikutnya, dan itu
        bukan bukti fotonya sudah naik.
        """
        if not unggah:
            return
        sejak = unggah.get("gagal_sejak")
        lama = self._unggah_putus.get(kode)
        if sejak and not lama:
            logger.warning("Cloud Photo %s terputus: %s", kode, unggah.get("pesan") or "tanpa keterangan")
            self._unggah_putus[kode] = sejak
        elif lama and not sejak and (unggah.get("terakhir") or 0) >= lama:
            logger.warning("Cloud Photo %s tersambung lagi", kode)
            self._unggah_putus[kode] = None

    async def run_loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_s)
