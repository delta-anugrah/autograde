"""The one scan field on the Timbangan tab (user 2026-10-06): scan, and the next step is recorded.

The operator no longer picks which of four fields to scan into. The step comes from the
truck's state (`putuskan_langkah`), so this reverses nothing of rule 20: the QR still carries
only the plate, and the step is read from what the console already knows, not guessed.

Nothing here writes on its own:

- datang and keluar go through `GateService`, the only writer of gate times;
- timbang isi and timbang kosong go through `ConsoleService.record_weighing`, the only writer
  of weight (`net_kg` computed, `MINIMUM_WEIGHT_KG` checked, rule 15).

The weight comes from the live scale only when it is fit (`TimbanganLive.berat_layak`);
otherwise the answer is `perlu_berat` and the screen opens the typed box it always had. A scan
this soon after the truck's previous step is answered `perlu_konfirmasi` and writes nothing
until the operator says yes: a scanner that reads one QR twice must not record two steps.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..domain.gerbang import (
    GANDA,
    LANGKAH_DATANG,
    LANGKAH_ISI,
    LANGKAH_KELUAR,
    LANGKAH_KOSONG,
    perlu_konfirmasi,
    putuskan_langkah,
)
from ..domain.plate import truck_id_for
from .console_service import MINIMUM_WEIGHT_KG, ConsoleService
from .gate_service import GateService
from .timbangan_live import TimbanganLive

logger = logging.getLogger(__name__)

TERSIMPAN = "tersimpan"
PERLU_BERAT = "perlu_berat"
PERLU_KONFIRMASI = "perlu_konfirmasi"
BELUM_TERDAFTAR = "belum_terdaftar"
NONAKTIF = "nonaktif"


def _tiket_ringkas(row: dict[str, Any]) -> dict[str, Any]:
    """What the screen needs to save a typed tare for this ticket, like the row button sends."""
    return {k: row.get(k) for k in ("id", "plate_number", "ref", "entered_at")}


class ScanOtomatis:
    def __init__(self, console: ConsoleService, gate: GateService, live: TimbanganLive) -> None:
        self.console = console
        self.store = console.store
        self.gate = gate
        self.live = live
        # One scan at a time: two reads of one QR must not both decide "timbang isi" and open
        # two tickets (their browser times differ, so their ticket ids differ too).
        self._kunci = asyncio.Lock()

    async def scan(self, qr: str, at: Any = None, konfirmasi: bool = False) -> dict[str, Any]:
        """One scan → the step it records, or why it records nothing yet (`hasil`).

        Raises `OperatorError` for a scan that is not a plate and a clock that cannot be read,
        and `ValueError` from `record_weighing` (a tare above the gross); the route makes both 400.
        """
        plate = self.gate.baca_plat(qr)
        waktu = self.gate.baca_jam(at)
        async with self._kunci:
            return await self._scan(plate, waktu, konfirmasi)

    async def _scan(self, plate: str, waktu: str, konfirmasi: bool) -> dict[str, Any]:
        truck_id = truck_id_for(plate)
        truk = self.store.truck(truck_id)
        langkah = putuskan_langkah(
            self.store.weighings_for_truck(truck_id),
            self.store.waiting_arrivals_for_truck(truck_id),
            waktu,
            kembali=self.gate.kembali(truck_id, waktu),
        )
        dasar = {
            "langkah": langkah.nama,
            "plate_number": (truk or {}).get("plate_number") or plate,
            "supplier": self.store.nama_supplier_truk(truck_id),
        }
        if langkah.nama == GANDA:
            logger.info("Scan %s: %d tiket terbuka, operator memilih", plate, len(langkah.pilihan))
            return {**dasar, "hasil": GANDA, "pilihan": [_tiket_ringkas(w) for w in langkah.pilihan]}

        menit = perlu_konfirmasi(langkah, waktu)
        if menit is not None and not konfirmasi:
            return {**dasar, "hasil": PERLU_KONFIRMASI, "menit": menit}

        if langkah.nama == LANGKAH_DATANG:
            return {**dasar, **self.gate.arrive(plate, waktu)}
        if langkah.nama == LANGKAH_KELUAR:
            hasil = self.gate.leave(at=waktu, weighing_id=langkah.weighing["id"])
            return {**dasar, **{k: v for k, v in hasil.items() if v is not None}}
        if langkah.nama == LANGKAH_ISI:
            return await self._timbang_isi(dasar, truk, waktu)
        if langkah.nama == LANGKAH_KOSONG:
            return await self._timbang_kosong(dasar, langkah.weighing["id"], waktu)
        raise AssertionError(f"langkah tak dikenal: {langkah.nama}")

    async def _timbang_isi(self, dasar: dict[str, Any], truk: dict[str, Any] | None, waktu: str) -> dict[str, Any]:
        # A weight only for a truck the plate picker would offer: an arrival may be any
        # plate-shaped QR, a ticket may not (the old scan lane's rule).
        if truk is None:
            return {**dasar, "hasil": BELUM_TERDAFTAR}
        if truk.get("status") == "inactive":
            return {**dasar, "hasil": NONAKTIF}
        kg = self.live.berat_layak(MINIMUM_WEIGHT_KG)
        if kg is None:
            return {**dasar, "hasil": PERLU_BERAT}
        row = await self.console.record_weighing(
            {"plate_number": dasar["plate_number"], "gross_kg": kg, "entered_at": waktu}
        )
        logger.info("Scan timbang isi %s: %s kg dari timbangan live", dasar["plate_number"], kg)
        return {**dasar, "hasil": TERSIMPAN, "kg": kg, "weighing_id": row.get("id"),
                "dipasang": row.get("dipasang")}

    async def _timbang_kosong(self, dasar: dict[str, Any], weighing_id: str, waktu: str) -> dict[str, Any]:
        tiket = self.store.weighing(weighing_id) or {"id": weighing_id}
        kg = self.live.berat_layak(MINIMUM_WEIGHT_KG)
        if kg is None:
            return {**dasar, "hasil": PERLU_BERAT, "weighing": _tiket_ringkas(tiket)}
        # The same fields the tare box sends, so the ticket id derives the same way.
        row = await self.console.record_weighing({
            "plate_number": tiket.get("plate_number"), "ref": tiket.get("ref"),
            "entered_at": tiket.get("entered_at"), "tare_kg": kg, "exited_at": waktu,
        })
        logger.info("Scan timbang kosong %s: %s kg dari timbangan live", dasar["plate_number"], kg)
        return {**dasar, "hasil": TERSIMPAN, "kg": kg, "weighing_id": row.get("id"),
                "dipasang": row.get("dipasang")}
