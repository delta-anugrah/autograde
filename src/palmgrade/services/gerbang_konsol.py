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
from datetime import UTC, datetime
from typing import Any

from ..domain.gerbang import menit_antara, pilih_kedatangan
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class GerbangKonsol:
    """Provided by `ConsoleService`: `store`."""

    store: ConsoleStore

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

    def waiting_arrivals(self, work_date: str) -> list[dict[str, Any]]:
        """Trucks that scanned in (scan 1) and are not weighed in yet, with minutes waited.

        Each row: `plate_number`, `arrived_at`, `menit` (whole minutes, never negative).
        """
        sekarang = datetime.now(UTC).isoformat()
        return [
            {**a, "menit": menit_antara(a["arrived_at"], sekarang) or 0}
            for a in self.store.waiting_arrivals(work_date)
        ]
