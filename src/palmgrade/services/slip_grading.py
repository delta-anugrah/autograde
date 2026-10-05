"""Printable grading slip (batch 5.9): the support switch and one truck's slip.

The switch is the backend guard, not only tidiness (rule 21): while it is off the slip lane
answers 403 `slip_mati`, whatever the screen shows. Stored in `console.db` (`sync_state`), so
it survives a restart; console only, the lines never read it.
"""
from __future__ import annotations

from typing import Any

from ..domain.operator_error import SLIP_MATI, SLIP_TIDAK_ADA, InvalidInput, OperatorError
from ..domain.slip_grading import KUNCI_SLIP, susun_slip
from ..repositories.console_repository import ConsoleStore
from .tampilan_baris import _with_source_label

#: Every ticket of one working day; a mill weighs far fewer trucks than this.
TIKET_SEHARI_MAKS = 500


class SlipGrading:
    def __init__(self, store: ConsoleStore, *, perusahaan: str) -> None:
        self._store = store
        self._perusahaan = perusahaan

    def aktif(self) -> bool:
        return self._store.get_state(KUNCI_SLIP) == "1"

    def atur(self, aktif: bool) -> dict[str, bool]:
        self._store.set_state(KUNCI_SLIP, "1" if aktif else "0")
        return {"aktif": self.aktif()}

    def slip(self, work_date: str, truck_id: str) -> dict[str, Any]:
        if not self.aktif():
            raise OperatorError(SLIP_MATI, "slip grading dimatikan support")
        rekap = next((r for r in self._store.truck_recap(work_date) if r.get("truck_id") == truck_id), None)
        if rekap is None:
            raise InvalidInput(SLIP_TIDAK_ADA, f"tidak ada janjang truk {truck_id} pada {work_date}")
        tiket = [t for t in self._store.weighings(work_date, limit=TIKET_SEHARI_MAKS) if t.get("truck_id") == truck_id]
        return susun_slip(_with_source_label(rekap), tiket, work_date=work_date, perusahaan=self._perusahaan)
