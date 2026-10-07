"""Polls the live scale reading from the PLC every `SCALE_POLL_MS` (console only).

Does not exist at all while `SCALE_PLC_REGISTER` is empty (`build_timbangan_live`
returns None), so a mill without the scale wired opens no socket. The PLC client
logs a cut connection once when it starts and once when it ends (rule 33), so
this loop stays quiet.
"""

from __future__ import annotations

import asyncio
import logging

from ..core.config import Settings
from ..plc.pembaca_timbangan import PembacaTimbangan, build_pembaca_timbangan
from ..services.timbangan_live import TimbanganLive

logger = logging.getLogger(__name__)


class TimbanganLiveWorker:
    def __init__(self, pembaca: PembacaTimbangan, live: TimbanganLive, *, interval_s: float) -> None:
        self._pembaca = pembaca
        self._live = live
        self._interval_s = interval_s

    async def run_once(self) -> None:
        # pymcprotocol blocks on its socket (up to ~2 s on a cut cable): in a thread,
        # so the screen's polls and the lines' bunches keep moving.
        bacaan = await asyncio.to_thread(self._pembaca.baca)
        if bacaan is None:
            self._live.gagal()
        else:
            self._live.berhasil(bacaan)

    async def run_loop(self) -> None:
        logger.info("TimbanganLiveWorker started, every %ss", self._interval_s)
        try:
            while True:
                # Rule 6: one failing tick never ends the loop.
                try:
                    await self.run_once()
                except Exception:
                    self._live.gagal()
                    logger.exception("Live scale read failed; retrying next tick")
                await asyncio.sleep(self._interval_s)
        finally:
            await asyncio.to_thread(self._pembaca.close)


def build_timbangan_live(settings: Settings, live: TimbanganLive) -> TimbanganLiveWorker | None:
    """The worker, or None while the scale is not configured (the tile then says so)."""
    pembaca = build_pembaca_timbangan(settings)
    if pembaca is None:
        return None
    live.dipakai = True
    return TimbanganLiveWorker(pembaca, live, interval_s=max(settings.scale_poll_ms, 200) / 1000)
