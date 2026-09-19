"""`grade_class` on the way into the console index.

The detail column is allowed to be missing or unknown; `ripeness_status` is not.
That asymmetry is the whole point: the verdict is summed into the figure the mill
is paid on, so an unknown value must stop at the door. `grade_class` only labels
a row on screen, and rejecting a bunch over a label a retrained model invented
would lose real tonnage to cosmetics.
"""
from __future__ import annotations

from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

WIB = ZoneInfo("Asia/Jakarta")


class FakeLineClient:
    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


@pytest.fixture()
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    return ConsoleService(settings, store, FakeLineClient())


def _event(svc, event_id: str, **extra):
    machine_id = svc.lines[0].machine_id
    payload = {
        "event_id": event_id,
        "machine_id": machine_id,
        "timestamp": "2026-09-16T03:00:00+00:00",
        "ripeness_status": "ACC",
        "prediction": "Acc",
        "capture_type": "auto",
        "assignment_id": "a-1",
    }
    payload.update(extra)
    svc.ingest(payload)


def _rows(svc):
    return svc.store.inspections("2026-09-16", limit=50, offset=0)


def test_the_class_is_stored_beside_the_verdict(service):
    _event(service, "e-1", grade_class="Ripe")
    assert _rows(service)[0]["grade_class"] == "Ripe"


def test_casing_from_the_model_is_normalised_on_the_way_in(service):
    _event(service, "e-1", grade_class="uNrIpE", ripeness_status="REJ", prediction="Rej")
    assert _rows(service)[0]["grade_class"] == "Unripe"


def test_an_event_without_a_class_is_still_recorded(service):
    """Manual captures never went through the model, and so does every row a
    line older than this build sends."""
    _event(service, "e-1")
    row = _rows(service)[0]
    assert row["grade_class"] is None
    assert row["ripeness_status"] == "ACC"


def test_an_unknown_class_is_dropped_but_the_bunch_is_kept(service):
    """The opposite of `ripeness_status`, deliberately — see the module docstring."""
    _event(service, "e-1", grade_class="Overripe")
    row = _rows(service)[0]
    assert row["grade_class"] is None
    assert row["ripeness_status"] == "ACC"


def test_jk_is_stored_as_jk_while_its_verdict_stays_rej(service):
    """The console must be able to say *why* a bunch was discarded; the PLC and
    AutoERP only ever learn that it was."""
    _event(service, "e-1", grade_class="JK", ripeness_status="REJ", prediction="Rej")
    row = _rows(service)[0]
    assert (row["grade_class"], row["ripeness_status"]) == ("JK", "REJ")


def test_counts_break_the_day_down_by_class(service):
    for i, (cls, status) in enumerate(
        [("Ripe", "ACC"), ("Ripe", "ACC"), ("Unripe", "REJ"), ("JK", "REJ")]
    ):
        pred = "Acc" if status == "ACC" else "Rej"
        _event(service, f"e-{i}", grade_class=cls, ripeness_status=status, prediction=pred)

    counts = service.store.grading_counts("a-1")
    assert (counts["ripe"], counts["unripe"], counts["jk"]) == (2, 1, 1)
    # The binary verdict still adds up — that is what AutoERP books.
    assert (counts["acc"], counts["rej"], counts["total"]) == (2, 2, 4)


def test_jk_is_counted_into_rej_not_into_its_own_erp_field(service):
    """Nothing named `jk` may reach AutoERP: there is no criterion for it there.
    `mentah` stays exactly the REJ count, JK included."""
    from palmgrade.domain.erp_messages import visit_message

    _event(service, "e-1", grade_class="JK", ripeness_status="REJ", prediction="Rej")
    counts = service.store.grading_counts("a-1")

    _, payload = visit_message(
        {
            "id": "v-1",
            "plate_number": "B 1234 XY",
            "truck_id": "t-1",
            "entered_at": "2026-09-16T03:00:00+00:00",
        },
        counts,
        site="PKS-1",
        emitted_at="2026-09-16T04:00:00+00:00",
    )
    sent = payload["grading"]["counts"]
    assert "jk" not in sent
    assert sent["mentah"] == sent["rej"] == 1
