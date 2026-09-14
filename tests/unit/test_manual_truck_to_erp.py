"""A truck typed at the mill goes up to AutoERP (contract §4.B, backlog AG-5).

The other half of the same rule is pinned here too: AutoERP owns a truck once it
is linked, so the console must not edit one (backlog FE-1). Before this, retyping
a linked plate wiped its supplier and the source label silently turned Internal —
on the history rows too, because the label is read from the truck.
"""
from __future__ import annotations

from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.domain.erp_master import supplier_row, truck_row
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue


def _service(tmp_path) -> tuple[ConsoleService, ErpOutboxStore]:
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"),
        store,
        None,
        erp_queue=ErpQueue(store, outbox, site=""),
    )
    return service, outbox


def _link_an_erp_truck(service: ConsoleService) -> None:
    service.store.upsert_supplier(
        supplier_row({"name": "KUD Sumber Makmur", "supplier_group": "Plasma"})
    )
    service.store.upsert_truck(
        truck_row(
            {"name": "BE 8821 KL", "plate_number": "BE 8821 KL", "supplier": "KUD Sumber Makmur"}
        )
    )


def test_a_new_manual_truck_is_queued_for_autoerp(tmp_path):
    service, outbox = _service(tmp_path)

    service.daftar_truk_manual("be 1234 xy")

    [message] = outbox.due()
    assert (message.kind, message.key) == ("truck", "BE1234XY")
    assert message.payload == {
        "plate_number": "be 1234 xy",
        "autograde_id": truck_id_for("be 1234 xy"),
    }


def test_retyping_a_truck_autoerp_owns_changes_nothing(tmp_path):
    service, outbox = _service(tmp_path)
    _link_an_erp_truck(service)

    service.daftar_truk_manual("be-8821-kl")

    [truck] = service.trucks()
    assert (truck["supplier_name"], truck["sumber_label"], truck["status"]) == (
        "KUD Sumber Makmur", "External", "active",
    )
    assert outbox.due() == [], "AutoERP already owns this truck; nothing to send"


def test_an_unlinked_truck_can_still_be_retyped(tmp_path):
    """Only AutoERP's own trucks are read-only; a borrowed one is not."""
    service, outbox = _service(tmp_path)
    service.daftar_truk_manual("BE 1 AA")

    result = service.daftar_truk_manual("BE 1 AA", capacity=8.0)

    assert result["status"] == "manual"
    assert [m.key for m in outbox.due()] == ["BE1AA"]


def test_a_console_without_the_erp_link_keeps_the_truck_local(tmp_path):
    """`ERP_URL` empty is the default; registering a truck must still work."""
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"),
        ConsoleStore(tmp_path / "console.db"),
        None,
    )

    assert service.daftar_truk_manual("BE 1 AA")["status"] == "manual"
