"""Scan a QR at the weighbridge gate: one plate in, one truck out.

Two scan stages, both at the gate, both replacing **typing that genuinely
happens**: weigh-in and weigh-out. The sorting stage is not scanned — knowing
the hopper is empty is the line operator's call, not the driver's who just
carries a phone, and the button is already right in front of the operator.

This layer **only searches**. It never creates a truck and never touches weight:

- if scanning also created trucks, one misread QR adds a ghost truck to master
  data, and that truck rides up to AutoERP through interface B
- if scanning also wrote weight, there would be two places that can write the
  figure the farmer is paid on. Recording weight stays `ConsoleService.record_weighing`

An unregistered (borrowed) truck is answered "not found", and the screen
offers manual entry. That is the one lane still typed by hand, and it has to
stay: a cracked screen, a dark one, or one in direct sun are real cases at the
factory gate.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.plate import truck_id_for
from ..domain.qr import baca_qr
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class ScanService:
    """Look up a truck from a scan. Never writes anything."""

    def __init__(self, store: ConsoleStore) -> None:
        self.store = store

    def search(self, qr_text: str) -> dict[str, Any]:
        """A scanner read → the truck already on file, or "not found".

        The id is derived from the plate, same as `record_weighing` — not a
        separate plate-column query. One rule for both lanes: if the search
        here used a different rule, one visit could land on a different
        truck than the one used while weighing.
        """
        plate = baca_qr(qr_text)  # rejects anything that is not a plate
        truck = self.store.truck(truck_id_for(plate))

        if truck is None:
            logger.info("Scan %s: truck not yet registered", plate)
            return {"ditemukan": False, "plate_number": plate, "truck": None}

        return {"ditemukan": True, "plate_number": plate, "truck": truck}

    def open_ticket(self, qr_text: str, work_date: str) -> dict[str, Any]:
        """Second scan, at the exit gate: which ticket is waiting for its tare.

        The operator scans the plate and the system finds the ticket — instead
        of the operator combing the table for that truck's row among dozens
        for the day.

        **Two open tickets are refused, not guessed** (operator's decision,
        2026-09-15): guessing here can attach the tare to the wrong visit and
        mix two visits' tonnage — the same shape as the ticket-adoption bug
        reported to AutoERP. The screen shows both and the operator picks.
        """
        plate = baca_qr(qr_text)
        open_weighings = self.store.open_weighings_for_truck(truck_id_for(plate), work_date)

        if len(open_weighings) == 1:
            return {"ditemukan": True, "plate_number": plate, "weighing": open_weighings[0]}

        if len(open_weighings) > 1:
            logger.info("Scan keluar %s: %d open tickets, asking the operator to choose",
                        plate, len(open_weighings))
            return {
                "ditemukan": False, "ganda": True,
                "plate_number": plate, "choices": open_weighings,
            }

        logger.info("Scan keluar %s: no open ticket today", plate)
        return {"ditemukan": False, "plate_number": plate, "weighing": None}
