"""Pull suppliers and trucks from AutoERP into the console (contract §4.A).

AutoERP owns master data and always wins. Frappe's built-in REST API is the
whole server side: `GET /api/resource/<DocType>` filtered on `modified`.

Each DocType keeps its own cursor. They change at different rates, and one
shared cursor would drag the quiet one back over rows it has already seen.
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
# Clocks never agree to the millisecond, so re-read a little behind the cursor.
_PULL_OVERLAP = timedelta(seconds=5)
_PAGE = 500
_ERP_TIME = "%Y-%m-%d %H:%M:%S.%f"

SUPPLIER_CURSOR_KEY = "erp_cursor_supplier"
TRUCK_CURSOR_KEY = "erp_cursor_truck"


@dataclass(frozen=True)
class _Resource:
    doctype: str
    # Exactly the contract's list: Frappe answers 417 for a field the DocType lacks.
    fields: tuple[str, ...]
    cursor_key: str
    to_row: Callable[[dict[str, Any]], dict[str, Any]]
    save: Callable[[ConsoleStore, dict[str, Any]], None]


# Suppliers first, so a truck never arrives before its owner.
_RESOURCES = (
    _Resource(
        doctype="Supplier",
        fields=("name", "supplier_name", "supplier_group", "disabled", "modified"),
        cursor_key=SUPPLIER_CURSOR_KEY,
        to_row=supplier_row,
        save=ConsoleStore.upsert_supplier,
    ),
    _Resource(
        doctype="Truck",
        fields=("name", "plate_number", "plate_normalized", "supplier", "vehicle_class", "modified"),
        cursor_key=TRUCK_CURSOR_KEY,
        to_row=truck_row,
        save=ConsoleStore.upsert_truck,
    ),
)


def _rewind(cursor: str) -> str:
    """Cursor minus the overlap. An unparsable cursor is used as is."""
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
            logger.info("MasterDataWorker off: ERP_URL is empty")
            return
        logger.info("MasterDataWorker started, target %s", self.settings.erp_url)
        while True:
            try:
                await self.pull_once()
            except Exception:
                logger.exception("Master data pull failed; retrying next tick")
            await asyncio.sleep(self.settings.console_sync_interval_s)

    async def pull_once(self) -> int:
        """Pull each DocType once. Returns rows applied; no ERP_URL means no traffic."""
        if not self.settings.erp_url:
            return 0
        headers = {
            "Authorization": f"token {self.settings.erp_api_key}:{self.settings.erp_api_secret}"
        }
        applied = 0
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers=headers) as client:
            for resource in _RESOURCES:
                applied += await self._pull(client, resource)
        logger.info("Master data: %s rows applied", applied)
        return applied

    async def _pull(self, client: httpx.AsyncClient, resource: _Resource) -> int:
        cursor = self.store.get_state(resource.cursor_key)
        params: dict[str, Any] = {
            "fields": json.dumps(list(resource.fields)),
            "limit_page_length": _PAGE,
            "order_by": "modified asc",
        }
        if cursor:
            params["filters"] = json.dumps([["modified", ">", _rewind(cursor)]])

        res = await client.get(
            f"{self.settings.erp_url}/api/resource/{resource.doctype}", params=params
        )
        res.raise_for_status()

        applied, failed, newest = 0, False, cursor
        for doc in res.json().get("data") or []:
            try:
                resource.save(self.store, resource.to_row(doc))
            except Exception:
                logger.exception("%s %s failed to save", resource.doctype, doc.get("name"))
                failed = True
                continue
            applied += 1
            modified = doc.get("modified")
            if modified and (newest is None or modified > newest):
                newest = modified

        # Advance only when every row landed; stepping over a failed one would
        # leave the mill half-stale for good.
        if not failed and newest and newest != cursor:
            self.store.set_state(resource.cursor_key, newest)
        return applied
