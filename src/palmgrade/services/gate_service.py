"""Scan 1 (truck reaches the gate) and scan 4 (truck leaves), decided 2026-09-30.

The only writer of gate times. Kept apart from `ScanService`, which stays read-only,
and from `ConsoleService.record_weighing`, which stays the only writer of weight:
gate times are statistics, weight is what the farmer is paid.

Nothing here reaches AutoERP: this service has no queue at all, and the visit message
(`domain/erp_messages.py`) picks its fields one by one. A truck that is not registered
can still arrive: the arrival keys on the truck id derived from the plate.

Failures the route turns into a 4xx: a scan that is not a plate (`BUKAN_PLAT`,
`PLAT_KOSONG`) and a clock that cannot be read (`INPUT_TIDAK_SAH`, field `at`). Both are
`OperatorError`, and `InvalidInput` is also a `ValueError`. Refusals that are not
mistakes (`masih_di_dalam`, `belum_timbang_kosong`, ...) are answers, not exceptions.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, tzinfo
from typing import Any

from ..domain.gerbang import (
    BELUM_TIMBANG_KOSONG,
    JENDELA_KEDATANGAN,
    JENDELA_KELUAR,
    MASIH_DI_DALAM,
    SUDAH_KELUAR,
    SUDAH_TERCATAT,
    TERCATAT,
    TIDAK_ADA_TIKET,
    baca_waktu,
    pilih_kedatangan,
    putuskan_keluar,
)
from ..domain.operator_error import INPUT_TIDAK_SAH, InvalidInput
from ..domain.plate import normalisasi_plat, truck_id_for
from ..domain.qr import baca_qr
from ..domain.working_day import work_date_for
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class GateService:
    """Record arrive and leave times. Never weight, never a truck, never AutoERP."""

    def __init__(self, store: ConsoleStore, tz: tzinfo) -> None:
        self.store = store
        self.tz = tz

    def _waktu(self, at: Any) -> str:
        """The browser's clock, like weigh-in and weigh-out. Server UTC only when absent.

        An unreadable or absurd clock (`jam sembilan`, year 0001 with an offset) is the
        caller's mistake: `InvalidInput`, never an `OverflowError` out of date arithmetic
        further down.
        """
        teks = str(at or "").strip()
        if not teks:
            return datetime.now(UTC).isoformat()
        try:
            dt = baca_waktu(teks)
            # Everything the domain and the store will do with it, done once here.
            work_date_for(teks, self.tz)
            dt.astimezone(UTC)
            dt - max(JENDELA_KEDATANGAN, JENDELA_KELUAR)
            dt + max(JENDELA_KEDATANGAN, JENDELA_KELUAR)
        except (ValueError, OverflowError) as exc:
            raise InvalidInput(INPUT_TIDAK_SAH, f"jam tidak terbaca: {teks!r}", field="at") from exc
        return teks

    def arrive(self, qr_text: str, at: Any = None) -> dict[str, Any]:
        plate = baca_qr(qr_text)
        waktu = self._waktu(at)
        truck_id = truck_id_for(plate)
        tampil = (self.store.truck(truck_id) or {}).get("plate_number") or plate

        # Weighed in and not out = still in the yard: a scan 1 now is the wrong field.
        if putuskan_keluar(self.store.weighings_for_truck(truck_id), waktu).hasil == BELUM_TIMBANG_KOSONG:
            logger.info("Scan datang %s: truk masih di dalam, tidak dicatat", plate)
            return {"hasil": MASIH_DI_DALAM, "plate_number": tampil}

        menunggu = pilih_kedatangan(self.store.waiting_arrivals_for_truck(truck_id), waktu)
        if menunggu:
            return {"hasil": SUDAH_TERCATAT, "plate_number": tampil, "arrived_at": menunggu["arrived_at"]}

        self.store.record_arrival({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"kedatangan:{plate}:{waktu}")),
            "plate_number": tampil,
            "plate_norm": normalisasi_plat(plate),
            "truck_id": truck_id,
            "work_date": work_date_for(waktu, self.tz),
            "arrived_at": waktu,
        })
        return {"hasil": TERCATAT, "plate_number": tampil, "arrived_at": waktu}

    def leave(
        self, qr_text: str | None = None, at: Any = None, weighing_id: str | None = None
    ) -> dict[str, Any]:
        waktu = self._waktu(at)
        if weighing_id:
            # The per-row button names its ticket: no window, nothing to search.
            row = self.store.weighing(weighing_id)
            if row is None:
                return {"hasil": TIDAK_ADA_TIKET, "plate_number": None, "weighing_id": None}
            keputusan = putuskan_keluar([row], waktu, jendela=None)
            plate = row.get("plate_number")
        else:
            plate = baca_qr(qr_text or "")
            keputusan = putuskan_keluar(self.store.weighings_for_truck(truck_id_for(plate)), waktu)

        tiket = keputusan.weighing or {}
        jawaban = {"hasil": keputusan.hasil, "plate_number": tiket.get("plate_number") or plate,
                   "weighing_id": tiket.get("id")}
        if keputusan.hasil == BELUM_TIMBANG_KOSONG:
            logger.warning("Scan keluar %s: belum timbang kosong (tiket %s)", plate, tiket.get("id"))
        if keputusan.hasil != TERCATAT:
            return jawaban
        if not self.store.set_left_at(tiket["id"], waktu):
            return {**jawaban, "hasil": SUDAH_KELUAR}  # a second read got there first
        return {**jawaban, "left_at": waktu}
