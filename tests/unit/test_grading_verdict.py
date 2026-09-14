"""The verdict of one bunch, on the way in.

`grading_counts` sums ACC and REJ out of `ripeness_status`, and that sum is what
reaches AutoERP's ledger as `grading_acc` / `grading_rej`. A status outside the
two was counted in `total` and in neither of them, so the summary the mill is
paid on did not add up — and nothing said so. The line only ever emits ACC or
REJ (`domain/vision_event.py`), so anything else is a malformed event and must
be as visible as a malformed timestamp already is.
"""
from __future__ import annotations

from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.vision_event import VERDICTS, verdict_of
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

WIB = ZoneInfo("Asia/Jakarta")
ASSIGNMENT = "a-1"


class FakeLineClient:
    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLineClient())


def _event(service, **over):
    payload = {
        "event_id": "ev-1",
        "machine_id": service.lines[0].machine_id,
        "timestamp": "2026-09-09T18:30:00+00:00",
        "ripeness_status": "ACC",
        "ripeness_confidence": 0.91,
        "capture_type": "auto",
        "assignment_id": ASSIGNMENT,
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------------- the rule


def test_verdict_only_knows_acc_and_rej():
    assert VERDICTS == ("ACC", "REJ")


def test_verdict_is_upper_cased():
    # A manual capture is written as "rej" (core/constants.py), so the lane has
    # to keep accepting lower case.
    assert verdict_of("rej") == "REJ"
    assert verdict_of("  acc  ") == "ACC"


@pytest.mark.parametrize("status", ["MATANG", "MENTAH", "TANGKAI_PANJANG", "Acc ok", "", None])
def test_verdict_refuses_anything_else(status):
    with pytest.raises(ValueError):
        verdict_of(status)


# ------------------------------------------------------------- the lane


def test_ingest_refuses_a_bunch_without_a_verdict(service):
    # Ripeness classes are not verdicts. Sending one used to be accepted and
    # then counted as neither accepted nor rejected.
    with pytest.raises(ValueError):
        service.ingest(_event(service, ripeness_status="MATANG"))


def test_a_refused_bunch_is_not_stored(service):
    with pytest.raises(ValueError):
        service.ingest(_event(service, ripeness_status="MATANG"))
    assert service.store.grading_counts(ASSIGNMENT) is None


def test_ingest_refuses_a_prediction_that_contradicts_the_verdict(service):
    # `prediction` is carried as the line sent it and never re-derived, so the
    # two agreeing is the only thing that keeps AutoERP's Acc/Rej and our
    # counts telling the same story.
    with pytest.raises(ValueError):
        service.ingest(_event(service, ripeness_status="ACC", prediction="Rej"))


def test_ingest_keeps_taking_a_prediction_that_agrees(service):
    service.ingest(_event(service, ripeness_status="REJ", prediction="Rej"))
    assert service.store.grading_counts(ASSIGNMENT)["rej"] == 1


def test_a_bunch_with_no_prediction_is_still_taken(service):
    # The console never required it; only a contradicting one is a fault.
    service.ingest(_event(service, prediction=None))
    assert service.store.grading_counts(ASSIGNMENT)["acc"] == 1


def test_the_grading_summary_always_adds_up(service):
    """What the whole rule exists for: the numbers AutoERP is sent reconcile."""
    for n, status in enumerate(["ACC", "REJ", "acc", "REJ", "ACC"], start=1):
        service.ingest(_event(service, event_id=f"ev-{n}", ripeness_status=status))

    counts = service.store.grading_counts(ASSIGNMENT)
    assert counts["acc"] + counts["rej"] == counts["total"] == 5
