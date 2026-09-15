"""Pull suppliers and trucks from AutoERP into the console (contract §4.A).

AutoERP owns master data and always wins. Frappe's built-in REST is the whole
server side of this; `integrations/erp/client.py` is what speaks it.

Each DocType keeps its own cursor. They change at very different rates, and one
shared cursor would drag the quiet one back over rows it has already seen.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..domain.erp_master import operator_row, supplier_row, truck_row
from ..integrations.erp.client import ErpClient
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

# Clocks never agree to the millisecond, so re-read a little behind the cursor.
_PULL_OVERLAP = timedelta(seconds=5)
_PAGE = 500
_ERP_TIME = "%Y-%m-%d %H:%M:%S.%f"
_INTERVAL_S = 300

SUPPLIER_CURSOR_KEY = "erp_cursor_supplier"
TRUCK_CURSOR_KEY = "erp_cursor_truck"
OPERATOR_CURSOR_KEY = "erp_cursor_operator"


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
    # Sign-in accounts. `password_hash` is pulled with them: the console verifies it
    # here, offline, because the operator has to get in while the internet is down.
    # It is readable over REST on purpose — a `Password` field would live in `__Auth`,
    # which Frappe deliberately never serves, leaving nothing to pull.
    _Resource(
        doctype="AutoGrade Operator",
        fields=("name", "email", "full_name", "active", "password_hash", "peran", "modified"),
        cursor_key=OPERATOR_CURSOR_KEY,
        to_row=operator_row,
        save=ConsoleStore.upsert_operator_erp,
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
    def __init__(
        self, store: ConsoleStore, client: ErpClient, *, interval_s: int = _INTERVAL_S
    ) -> None:
        self.store = store
        self._client = client
        self._interval_s = interval_s

    async def run_loop(self) -> None:
        logger.info("MasterDataWorker started, every %ss", self._interval_s)
        while True:
            try:
                await self.pull_once()
            except Exception:
                logger.exception("Master data pull failed; retrying next tick")
            await asyncio.sleep(self._interval_s)

    async def pull_once(self) -> int:
        """Pull each DocType once. Returns how many rows landed."""
        applied = 0
        for resource in _RESOURCES:
            applied += await self._pull(resource)
        logger.info("Master data: %s rows applied", applied)
        return applied

    async def _pull(self, resource: _Resource) -> int:
        cursor = self.store.get_state(resource.cursor_key)
        docs = await self._client.list_modified_since(
            resource.doctype,
            resource.fields,
            _rewind(cursor) if cursor else None,
            limit=_PAGE,
        )

        applied, failed, newest = 0, False, cursor
        for doc in docs:
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
