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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from ..domain.gerbang import (
    JENDELA_KEDATANGAN,
    TAHAP_DATANG,
    masih_menunggu,
    menit_antara,
    pilih_kedatangan,
    selesai_tanpa_scan_4,
)
from ..domain.working_day import JENDELA_TANPA_KELUAR_DETIK, awal_kunjungan, work_date_for
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

#: How far before the visit window the carried-visit read looks by work date (see
#: `kunjungan_terbawa`): the read stays on two or three days of the day index.
KELONGGARAN_HARI = timedelta(days=1)


class GerbangKonsol:
    """Provided by `ConsoleService`: `store` and `tz`."""

    store: ConsoleStore
    tz: tzinfo
    today: Callable[[], str]

    def sekarang(self) -> datetime:
        """The console's clock for "now": the work date, the visit window, the waiting
        list. One method, so a test can stand the whole console just after midnight."""
        return datetime.now(UTC)

    def kunjungan_terbawa(self, work_date: str) -> list[dict[str, Any]]:
        """Yesterday's visits still in the yard, for TODAY's Timbangan table only (2026-10-02).

        A truck weighed in at 23:50 is weighed out at 00:10: a table read by work date
        alone lost its row, and with it the Timbang kosong and Keluar buttons, at 00:00.
        Carried while not left and inside the visit window; never moved to today, so day
        totals, Rekap, Riwayat, CSV and AutoERP stay on its own day. A past day's table
        carries nothing.
        """
        if work_date != self.today():
            return []
        sekarang = self.sekarang()
        sejak = awal_kunjungan(sekarang)
        # A ticket with its tare waits 24 h for its Keluar, one without keeps 12 h
        # (`JENDELA_TANPA_KELUAR_DETIK` says why); the domain then drops a carried visit that
        # is finished "tanpa scan 4" because its truck came back.
        sejak_tara = sekarang.timestamp() - JENDELA_TANPA_KELUAR_DETIK
        # The work date only narrows the read; a day of slack, because it was stamped from
        # the weigh-in text while the window reads the real instant (a PC clock off at
        # weigh-in must not hide a truck still in the yard).
        sejak_hari = work_date_for(
            (datetime.fromtimestamp(min(sejak, sejak_tara), UTC) - KELONGGARAN_HARI).isoformat(), self.tz
        )
        rows = self.store.weighings_terbawa(work_date, sejak, sejak_hari, sejak_tara)
        return [row for row in self.tandai_tanpa_scan_4(rows, sekarang) if not row["tanpa_scan_4"]]

    def tandai_tanpa_scan_4(
        self, rows: list[dict[str, Any]], sekarang: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Set `tanpa_scan_4` on every Timbangan row (user 2026-10-03, standard L4).

        True for a weighed-out ticket that never got its Keluar and now counts as finished:
        24 h after its weigh-out, or once its truck arrived or weighed in again
        (`selesai_tanpa_scan_4`). `tahap_tiket` and `durasi_kunjungan` read the flag. Only the
        tared, not-left rows need the truck's trail, read once for all of them.
        """
        nyata = sekarang or self.sekarang()
        cek = [r for r in rows if r.get("tare_kg") is not None and not r.get("left_at") and r.get("truck_id")]
        jejak = (
            self.store.jejak_truk({r["truck_id"] for r in cek}, min(r["work_date"] for r in cek)) if cek else {}
        )
        for row in rows:
            row["tanpa_scan_4"] = selesai_tanpa_scan_4(row, nyata, jejak.get(row.get("truck_id"), ()))
        return rows

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

        Each row: `id` (named by "Batal datang"), `plate_number`, `arrived_at`, `menit`, and
        `tahap` ("datang", the first badge on the Timbangan table). Chosen by the claim window
        back from now (`masih_menunggu`), not by work date: a truck that arrived at 23:50 still
        waits at 00:10, because its weigh-in then still claims it.

        The basis is the SERVER clock (now), not the browser's: the arrival time was the
        browser's, so a PC clock that is wrong shows here, not hidden. `menit` is whole
        minutes, never negative, and `None` (not 0) when the stored time is unreadable or
        lies in the future: "0 minutes waited" would read as a truck that just arrived,
        which is a lie. `sekarang` is for tests; the route passes nothing.
        """
        nyata = sekarang or self.sekarang()
        sejak_hari = work_date_for((nyata - JENDELA_KEDATANGAN).isoformat(), self.tz)
        jam = nyata.isoformat()
        return [
            {**a, "menit": menit_antara(a["arrived_at"], jam), "tahap": TAHAP_DATANG}
            for a in masih_menunggu(self.store.waiting_arrivals(sejak_hari), nyata)
        ]

    def kedatangan_dibatalkan(self, work_date: str) -> list[dict[str, Any]]:
        """The day's "Batal datang" history (round 4, 2026-10-03), newest first: plate, arrival
        time, cancel time and the operator's email, as stored. The screen formats the times."""
        return self.store.cancelled_arrivals(work_date)
