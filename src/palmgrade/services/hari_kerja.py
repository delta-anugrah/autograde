"""The working day of the console, with the support-set cutoff (batch 5.11).

The only place a service computes a working date: ingest, weighing, gate scans and "today"
all go through `untuk` / `kini`, so one setting moves them together. Read from `console.db`
on every call (one indexed `sync_state` read), so a saved cutoff applies to the next row
without a restart. A stored value that is not a cutoff runs as midnight, logged once.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, tzinfo

from ..domain.operator_error import OperatorError
from ..domain.working_day import CUTOFF_BAWAAN, baca_cutoff, hari_kerja_kini, teks_cutoff, work_date_for
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

#: `setelan_` keeps it through the Danger Zone wipes (`domain/bahaya.py`).
KUNCI_CUTOFF = "setelan_cutoff_shift"


class HariKerja:
    def __init__(self, store: ConsoleStore, tz: tzinfo) -> None:
        self._store = store
        self.tz = tz
        self._rusak_dilaporkan: str | None = None

    def cutoff(self) -> time:
        teks = self._store.get_state(KUNCI_CUTOFF)
        try:
            return baca_cutoff(teks)
        except OperatorError:
            # Logged once per bad value, not on every bunch: ingest calls this per event.
            if teks != self._rusak_dilaporkan:
                logger.warning("Cutoff hari kerja tersimpan tidak sah (%r); dipakai 00:00", teks)
                self._rusak_dilaporkan = teks
            return CUTOFF_BAWAAN

    def atur(self, teks: str | None, oleh: str = "") -> dict[str, str]:
        cutoff = baca_cutoff(teks)
        lama = teks_cutoff(self.cutoff())
        self._store.set_state(KUNCI_CUTOFF, teks_cutoff(cutoff))
        # The only record of when the working day boundary moved (factory PC: AnyDesk only).
        logger.warning("Cutoff hari kerja diubah %s -> %s oleh %s", lama, teks_cutoff(cutoff), oleh or "-")
        return {"cutoff": teks_cutoff(cutoff)}

    def untuk(self, timestamp_iso: str) -> str:
        return work_date_for(timestamp_iso, self.tz, self.cutoff())

    def kini(self, sekarang: datetime) -> str:
        return hari_kerja_kini(sekarang, self.tz, self.cutoff())
