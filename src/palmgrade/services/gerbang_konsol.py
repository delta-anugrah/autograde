"""The console's side of the gate scans (2026-09-30): the arrival a weigh-in claims.

Split from `console_service.py`, which may not pass 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). A mixin, like `PenugasanOtomatis`, because
`record_weighing` and the routes call these methods on `ConsoleService`.

Gate times are statistics and the weight is what the farmer is paid, so nothing here
may ever fail a weighing: the claim logs and moves on, and a ticket without an arrival
is simply "tanpa scan 1" (D4).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, tzinfo
from typing import Any

from ..domain.gerbang import (
    JENDELA_KEDATANGAN,
    TAHAP_DATANG,
    masih_menunggu,
    menit_antara,
    pilih_kedatangan,
)
from ..domain.working_day import work_date_for
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class GerbangKonsol:
    """Provided by `ConsoleService`: `store` and `tz`."""

    store: ConsoleStore
    tz: tzinfo

    def _klaim_kedatangan(
        self, baru: bool, truck_id: str, entered_at: str | None, weighing_id: str
    ) -> None:
        """A NEW ticket takes its own truck's waiting arrival, so queue time can be read.

        Here and not in the scan lane: a ticket opened from the plate dropdown or by the
        scale program must claim it too. A re-weigh or a tare update (`baru` False) never
        claims. The store refuses another truck's arrival. Never raises.
        """
        if not (baru and entered_at):
            return
        try:
            kedatangan = pilih_kedatangan(self.store.waiting_arrivals_for_truck(truck_id), entered_at)
            if kedatangan is not None:
                self.store.claim_arrival(kedatangan["id"], weighing_id)
        except Exception:  # noqa: BLE001 - the weight is the paid number, this is a statistic
            logger.exception("Klaim kedatangan gagal untuk tiket %s; timbangan tetap tersimpan", weighing_id)

    def waiting_arrivals(self, sekarang: datetime | None = None) -> list[dict[str, Any]]:
        """Trucks that scanned in (scan 1) and are not weighed in yet, with minutes waited.

        Each row: `plate_number`, `arrived_at`, `menit`, and `tahap` ("datang", the first
        badge on the Timbangan table). Chosen by the claim window back
        from now (`masih_menunggu`), not by work date: a truck that arrived at 23:50 still
        waits at 00:10, because its weigh-in then still claims it.

        The basis is the SERVER clock (now), not the browser's: the arrival time was the
        browser's, so a PC clock that is wrong shows here, not hidden. `menit` is whole
        minutes, never negative, and `None` (not 0) when the stored time is unreadable or
        lies in the future: "0 minutes waited" would read as a truck that just arrived,
        which is a lie. `sekarang` is for tests; the route passes nothing.
        """
        nyata = sekarang or datetime.now(UTC)
        sejak_hari = work_date_for((nyata - JENDELA_KEDATANGAN).isoformat(), self.tz)
        jam = nyata.isoformat()
        return [
            {**a, "menit": menit_antara(a["arrived_at"], jam), "tahap": TAHAP_DATANG}
            for a in masih_menunggu(self.store.waiting_arrivals(sejak_hari), nyata)
        ]
