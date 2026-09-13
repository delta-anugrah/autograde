"""Pull master data (suppliers + trucks) from AutoERP into the console.

One direction, AutoERP always wins (§3.4): it owns suppliers, trucks, prices and
deductions, and the console only renders what it is given. Frappe's own REST is
the entire server side of this — there is nothing to build over there.

This replaces a pull from palmgrade-api in the cloud. That API is being switched
off (plan §6), and a mill pulling from two masters would end up with two
versions of the same truck.

Each resource carries its own cursor. Suppliers and trucks change at very
different rates, and one shared cursor would keep dragging the quiet resource
back over rows it has already seen.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..core.config import Settings
from ..domain.erp_master import supplier_row, truck_row
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15
# Edge and ERP clocks never agree to the millisecond, so a row written in the
# same second as the cursor would otherwise never be pulled again.
_PULL_OVERLAP = timedelta(seconds=5)
_PAGE = 500
_ERP_TIME = "%Y-%m-%d %H:%M:%S.%f"

SUPPLIER_CURSOR_KEY = "erp_cursor_supplier"
TRUCK_CURSOR_KEY = "erp_cursor_truck"


@dataclass(frozen=True)
class _Resource:
    doctype: str
    fields: tuple[str, ...]
    cursor_key: str
    map: Callable[[dict[str, Any]], dict[str, Any]]
    simpan: Callable[[ConsoleStore, dict[str, Any]], None]


# Suppliers first: a truck row points at a supplier id, and the operator should
# never see a truck whose owner has not arrived yet.
_RESOURCES = (
    _Resource(
        "Supplier",
        ("name", "supplier_name", "supplier_group", "disabled", "modified"),
        SUPPLIER_CURSOR_KEY,
        supplier_row,
        ConsoleStore.upsert_supplier,
    ),
    _Resource(
        "Truck",
        ("name", "plate_number", "plate_normalized", "supplier", "disabled", "modified"),
        TRUCK_CURSOR_KEY,
        truck_row,
        ConsoleStore.upsert_truck,
    ),
)


def _mundur(cursor: str) -> str:
    """The cursor, minus the overlap. An unparsable one is used as it is."""
    for fmt in (_ERP_TIME, "%Y-%m-%d %H:%M:%S"):
        try:
            return (datetime.strptime(cursor, fmt) - _PULL_OVERLAP).strftime(_ERP_TIME)
        except ValueError:
            continue
    return cursor


class MasterDataWorker:
    def __init__(self, settings: Settings, store: ConsoleStore) -> None:
        self.settings = settings
        self.store = store

    async def run_loop(self) -> None:
        if not self.settings.erp_url:
            logger.info("MasterDataWorker off — ERP_URL kosong")
            return
        logger.info("MasterDataWorker started — target: %s", self.settings.erp_url)
        while True:
            try:
                await self.pull_once()
            except Exception:
                logger.exception("MasterDataWorker pull gagal — coba lagi tick berikutnya")
            await asyncio.sleep(self.settings.console_sync_interval_s)

    async def pull_once(self) -> int:
        """Return how many rows landed. No ERP configured means no traffic."""
        if not self.settings.erp_url:
            return 0
        headers = {
            "Authorization": f"token {self.settings.erp_api_key}:{self.settings.erp_api_secret}"
        }
        applied = 0
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers=headers) as client:
            for resource in _RESOURCES:
                applied += await self._pull_resource(client, resource)
        logger.info("Master data: %s baris diterapkan", applied)
        return applied

    async def _pull_resource(self, client: httpx.AsyncClient, resource: _Resource) -> int:
        cursor = self.store.get_state(resource.cursor_key)
        params: dict[str, Any] = {
            "fields": json.dumps(list(resource.fields)),
            "limit_page_length": _PAGE,
            "order_by": "modified asc",
        }
        if cursor:
            params["filters"] = json.dumps([["modified", ">", _mundur(cursor)]])

        res = await client.get(
            f"{self.settings.erp_url}/api/resource/{resource.doctype}", params=params
        )
        res.raise_for_status()

        applied, gagal, terbaru = 0, False, cursor
        for doc in res.json().get("data") or []:
            try:
                resource.simpan(self.store, resource.map(doc))
            except Exception:
                logger.exception("%s gagal disimpan: %s", resource.doctype, doc.get("name"))
                gagal = True
                continue
            applied += 1
            modified = doc.get("modified")
            if modified and (terbaru is None or modified > terbaru):
                terbaru = modified

        # The cursor only moves when EVERY row landed. Stepping over one that
        # failed leaves the mill on a half-stale matrix forever — including the
        # truck revocations the ERP has already made.
        if not gagal and terbaru and terbaru != cursor:
            self.store.set_state(resource.cursor_key, terbaru)
        return applied
