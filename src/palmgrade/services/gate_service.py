"""Scan 1 (truck reaches the gate) and scan 4 (truck leaves), decided 2026-09-30.

The only writer of gate times. Kept apart from `ScanService`, which stays read-only,
and from `ConsoleService.record_weighing`, which stays the only writer of weight:
gate times are statistics, weight is what the farmer is paid.

Nothing here reaches AutoERP: this service has no queue at all, and the visit message
(`domain/erp_messages.py`) picks its fields one by one. A truck that is not registered
can still arrive: the arrival keys on the truck id derived from the plate.

Failures the route turns into a 4xx: a scan that is neither plate-shaped nor a registered
truck (`BUKAN_PLAT`, `PLAT_KOSONG`) and a clock that cannot be read (`INPUT_TIDAK_SAH`,
field `at`). Both are `OperatorError`, and `InvalidInput` is also a `ValueError`. Refusals that are not
mistakes (`masih_di_dalam`, `belum_timbang_kosong`, ...) are answers, not exceptions.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from ..domain.gerbang import (
    BELUM_TIMBANG_KOSONG,
    DIBATALKAN,
    JENDELA_KEDATANGAN,
    JENDELA_KELUAR,
    JENDELA_TANPA_KELUAR,
    MASIH_DI_DALAM,
    SUDAH_KELUAR,
    SUDAH_TERCATAT,
    TERCATAT,
    TIDAK_ADA,
    TIDAK_ADA_TIKET,
    baca_waktu,
    pilih_kedatangan,
    putuskan_keluar,
)
from ..domain.operator_error import BUKAN_PLAT, INPUT_TIDAK_SAH, InvalidInput
from ..domain.plate import normalisasi_plat, truck_id_for
from ..domain.qr import baca_qr
from ..repositories.console_repository import ConsoleStore
from .hari_kerja import HariKerja

logger = logging.getLogger(__name__)

#: The furthest back any gate decision reads, plus a day of slack for the work date that
#: only narrows the trail read (`jejak_truk`): the browser's clock stamped it.
_JANGKAUAN = max(JENDELA_KEDATANGAN, JENDELA_KELUAR, JENDELA_TANPA_KELUAR) + timedelta(days=1)


class GateService:
    """Record arrive and leave times. Never weight, never a truck, never AutoERP."""

    def __init__(self, store: ConsoleStore, tz: tzinfo, hari_kerja: HariKerja | None = None) -> None:
        self.store = store
        self.tz = tz
        # The console passes its own (`get_gate_service`); built here for tests that do not.
        self.hari_kerja = hari_kerja or HariKerja(store, tz)
        # One lock around each check-then-write. The routes are plain `def`, so two scans
        # of one QR run on two pool threads: without it both could read "nobody waiting"
        # (browser times differ, so the ids differ) and insert two waiting arrivals, or
        # both close one ticket. One instance per process (`get_gate_service`).
        self._kunci = threading.Lock()

    def baca_jam(self, at: Any) -> str:
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
            self.hari_kerja.untuk(teks)
            dt.astimezone(UTC)
            self.hari_kerja.untuk((dt - _JANGKAUAN).isoformat())
            dt + _JANGKAUAN
        except (ValueError, OverflowError) as exc:
            raise InvalidInput(INPUT_TIDAK_SAH, f"jam tidak terbaca: {teks!r}", field="at") from exc
        return teks

    def baca_plat(self, qr_text: str) -> str:
        """The scan as a normalised plate. A REGISTERED truck is accepted whatever its shape.

        `baca_qr` refuses what is not plate-shaped, so a stray QR never adds a ghost truck.
        A registered truck with an odd plate (service plate, old plate, approved in
        AutoERP) is no ghost: it can be weighed in from the same dropdown, so refusing its
        arrival would make it "tanpa scan 1" forever (finding Q2). Rule 20 holds: the QR
        still carries only the plate. Unknown and not plate-shaped stays `BUKAN_PLAT`.
        """
        try:
            return baca_qr(qr_text)
        except InvalidInput as exc:
            if exc.code != BUKAN_PLAT:
                raise
            plat = normalisasi_plat(qr_text)
            if self.store.truck(truck_id_for(plat)) is None:
                raise
            return plat

    def arrive(self, qr_text: str, at: Any = None) -> dict[str, Any]:
        plate = self.baca_plat(qr_text)
        waktu = self.baca_jam(at)
        with self._kunci:
            return self._datang(plate, waktu)

    def _datang(self, plate: str, waktu: str) -> dict[str, Any]:
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
            "work_date": self.hari_kerja.untuk(waktu),
            "arrived_at": waktu,
        })
        return {"hasil": TERCATAT, "plate_number": tampil, "arrived_at": waktu}

    def cancel_arrival(self, arrival_id: str, oleh: str, nama: str | None = None) -> dict[str, Any]:
        """"Batal datang" (2026-10-03): the truck will not be weighed (wrong truck picked, or
        turned away at the gate). Only a waiting arrival; otherwise `tidak_ada`, an answer.

        The row is kept with who cancelled it and when (round 4): the Timbangan tab lists it.
        The time is the server's: the button sends no clock, and nothing is computed from it.
        `oleh` is the operator's email (identity), `nama` the display name as the session
        knows it now; stored as a snapshot so the history outlives a renamed or deleted account.
        """
        with self._kunci:
            row = self.store.cancel_arrival(
                arrival_id, cancelled_at=datetime.now(UTC).isoformat(), cancelled_by=oleh,
                cancelled_by_name=" ".join(str(nama or "").split()) or None,
            )
        if row is None:
            return {"hasil": TIDAK_ADA}
        logger.info("Batal datang %s oleh %s (kedatangan %s, jam %s)",
                    row["plate_number"], oleh, arrival_id, row["arrived_at"])
        return {"hasil": DIBATALKAN, "plate_number": row["plate_number"]}

    def kembali(self, truck_id: str | None, waktu: str) -> list[str]:
        """When this truck was seen again (waiting arrivals, weigh-ins): a weighed-out ticket
        it left behind is then finished "tanpa scan 4" and a new Keluar never closes it."""
        if not truck_id:
            return []
        sejak_hari = self.hari_kerja.untuk((baca_waktu(waktu) - _JANGKAUAN).isoformat())
        return self.store.jejak_truk([truck_id], sejak_hari).get(truck_id, [])

    def leave(
        self, qr_text: str | None = None, at: Any = None, weighing_id: str | None = None
    ) -> dict[str, Any]:
        waktu = self.baca_jam(at)
        with self._kunci:
            return self._keluar(qr_text, waktu, weighing_id)

    def _keluar(self, qr_text: str | None, waktu: str, weighing_id: str | None) -> dict[str, Any]:
        if weighing_id:
            # The per-row button names its ticket: no window, nothing to search.
            row = self.store.weighing(weighing_id)
            if row is None:
                return {"hasil": TIDAK_ADA_TIKET, "plate_number": None, "weighing_id": None}
            keputusan = putuskan_keluar([row], waktu, jendela=None, kembali=self.kembali(row.get("truck_id"), waktu))
            plate = row.get("plate_number")
        else:
            plate = self.baca_plat(qr_text or "")
            truck_id = truck_id_for(plate)
            keputusan = putuskan_keluar(
                self.store.weighings_for_truck(truck_id), waktu, kembali=self.kembali(truck_id, waktu)
            )

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
