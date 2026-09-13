"""What the console sends to AutoERP (contract §4).

Pure: the payload and the queue key, nothing else. The key is the natural key
AutoERP matches on, so the same truck queued twice is one message, not two.
"""
from __future__ import annotations

from typing import Any

from .plate import normalisasi_plat, truck_id_for

TRUCK = "truck"


def truck_message(plate_number: str) -> tuple[str, dict[str, Any]]:
    """Interface B: a plate first seen at the mill becomes a Truck in AutoERP.

    Supplier and vehicle class are deliberately left out. AutoERP owns them: the
    backoffice completes the truck there and the next pull brings it back down.
    """
    return normalisasi_plat(plate_number), {
        "plate_number": plate_number,
        "autograde_id": truck_id_for(plate_number),
    }
