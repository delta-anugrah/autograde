"""What the console puts on the queue for AutoERP (contract §4.B and §4.C).

`ErpQueue` is the one place that turns console rows into AutoERP messages, so
the daily resend and the live triggers can never drift apart.
"""
from __future__ import annotations

from palmgrade.domain.erp_master import supplier_row, truck_row
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.erp_queue import ErpQueue

PLATE = "BE 8821 KL"
SITE = "PT Sawit Rambang Lestari"


def _queue(tmp_path, site: str = SITE) -> tuple[ErpQueue, ConsoleStore, ErpOutboxStore]:
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    return ErpQueue(store, outbox, site=site), store, outbox


def _linked_truck(store: ConsoleStore) -> None:
    store.upsert_supplier(supplier_row({"name": "KUD Sumber Makmur", "supplier_group": "Plasma"}))
    store.upsert_truck(truck_row({"name": PLATE, "plate_number": PLATE, "supplier": "KUD Sumber Makmur"}))


def _weighing(store: ConsoleStore, **over) -> str:
    row = {
        "id": "w1",
        "ref": "SCL-1",
        "plate_number": PLATE,
        "plate_norm": "BE8821KL",
        "truck_id": truck_id_for(PLATE),
        "tanggal_kerja": "2026-09-13",
        "bruto_kg": 14560.0,
        "tara_kg": None,
        "neto_kg": None,
        "waktu_masuk": "2026-09-13T07:41:00+07:00",
        "waktu_keluar": None,
    } | over
    store.upsert_weighing(row)
    return row["id"]


def test_a_truck_typed_at_the_mill_is_queued(tmp_path):
    queue, _, outbox = _queue(tmp_path)

    queue.truck("be 1234 xy")

    [message] = outbox.due()
    assert (message.kind, message.key) == ("truck", "BE1234XY")


def test_a_weighing_becomes_a_visit_carrying_the_trucks_owner(tmp_path):
    """AutoERP matches the supplier by its own name, so the link has to come
    from the pulled master data, not from anything the console invents."""
    queue, store, outbox = _queue(tmp_path)
    _linked_truck(store)
    _weighing(store)

    queue.visit("w1")

    [message] = outbox.due()
    assert (message.kind, message.key) == ("visit", "w1")
    assert message.payload["supplier_erp_name"] == "KUD Sumber Makmur"
    assert message.payload["truck"]["plate_number"] == PLATE
    assert message.payload["stage"] == "gate"
    assert message.payload["site"] == SITE


def test_the_grading_of_the_assignment_the_visit_is_linked_to_rides_along(tmp_path):
    """The link is stored when the truck leaves the line, so a second ticket the
    same day cannot inherit the first one's bunches."""
    queue, store, outbox = _queue(tmp_path)
    _linked_truck(store)
    _weighing(store)
    _grade(store, assignment_id="a1", acc=3, rej=1, long_stalk=2, manual=1)
    store.link_weighing_to_assignment("w1", "a1")

    queue.visit("w1")

    [message] = outbox.due()
    grading = message.payload["grading"]
    assert grading["assignment_id"] == "a1"
    assert grading["counts"] == {
        "total": 4, "acc": 3, "rej": 1, "mentah": 1, "tangkai_panjang": 2, "manual_reject": 1,
    }
    assert message.payload["stage"] == "grading"


def test_the_visit_carries_the_erp_truck_name_once_autoerp_knows_the_truck(tmp_path):
    """The whole path: a pull stored `erp_name`, the visit query picks it up, the payload
    sends it. AutoERP then resolves the truck by its own id instead of re-normalising a
    plate text the backoffice may have corrected upstream."""
    queue, store, outbox = _queue(tmp_path)
    _linked_truck(store)
    _weighing(store)

    queue.visit("w1")

    [message] = outbox.due()
    assert message.payload["truck"]["erp_name"] == PLATE


def test_a_truck_autoerp_has_never_seen_sends_no_erp_name(tmp_path):
    """Omitted, not null — that is the owner-less Truck interface B creates."""
    queue, store, outbox = _queue(tmp_path)
    _weighing(store)

    queue.visit("w1")

    [message] = outbox.due()
    assert "erp_name" not in message.payload["truck"]


def test_a_visit_with_no_weighing_row_is_not_queued(tmp_path):
    """`weighing.time_in` dates the ticket; AutoERP refuses a visit without it."""
    queue, _, outbox = _queue(tmp_path)

    assert queue.visit("does-not-exist") is False
    assert outbox.due() == []


def test_a_day_of_visits_can_be_queued_again(tmp_path):
    """The daily resend: idempotent upserts make it free and it closes any gap
    the outbox left."""
    queue, store, outbox = _queue(tmp_path)
    _linked_truck(store)
    _weighing(store)
    _weighing(store, id="w2", ref="SCL-2", waktu_masuk="2026-09-13T09:00:00+07:00")

    assert queue.visits_on("2026-09-13") == 2
    assert sorted(m.key for m in outbox.due()) == ["w1", "w2"]


def _grade(store: ConsoleStore, *, assignment_id: str, acc: int, rej: int, long_stalk: int, manual: int) -> None:
    """Bunches as the lines report them: REJ is mentah, a long stalk is an ACC
    with tp_confidence above 0.8, and the operator's own reject is a manual capture."""
    n = 0

    def add(status: str, tp: float | None, capture: str) -> None:
        nonlocal n
        n += 1
        store.add_inspection(
            {
                "event_id": f"{assignment_id}-{n}",
                "machine_id": "m1",
                "line_code": "line-1",
                "tanggal_kerja": "2026-09-13",
                "timestamp": f"2026-09-13T08:0{n}:00+07:00",
                "ripeness_status": status,
                "ripeness_confidence": 0.9,
                "capture_type": capture,
                "image_path": None,
                "truck_id": truck_id_for(PLATE),
                "assignment_id": assignment_id,
                "prediction": "Acc" if status == "ACC" else "Rej",
                "tp_status": "PASS" if tp else None,
                "tp_confidence": tp,
            }
        )

    for _ in range(acc - long_stalk):
        add("ACC", None, "auto")
    for _ in range(long_stalk):
        add("ACC", 0.91, "auto")
    for i in range(rej):
        add("REJ", None, "manual" if i < manual else "auto")
