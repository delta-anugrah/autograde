"""The console hands the line the truck's plate along with the assignment.

Vision only ever receives `truck_id`, and that is a uuid5 *derived from* the
plate (`domain/plate.py`) — it cannot be reversed. Without this field a capture
folder can only be named after an opaque id, which defeats the point of naming
it after a truck at all.

The plate is a label, never an identifier: `truck_id` remains the key, so a
missing or malformed plate costs readability and nothing else.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.schemas.internal_schema import AssignmentSyncRequest
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    def __init__(self) -> None:
        self.kiriman: list[dict] = []

    async def assign_truck(
        self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None
    ):
        self.kiriman.append(
            {"truck_id": truck_id, "plate": plate, "assignment_id": assignment_id}
        )


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def test_assigning_a_truck_sends_its_plate(service):
    truck = service.register_manual_truck("B 1234 XY")

    asyncio.run(service.assign_truck(service.lines[0].line_code, truck["id"]))

    assert service.line_client.kiriman[-1]["plate"] == "B 1234 XY"


def test_releasing_a_truck_clears_the_plate(service):
    """The line must stop labelling folders with a truck that already left."""
    truck = service.register_manual_truck("B 1234 XY")
    line_code = service.lines[0].line_code
    asyncio.run(service.assign_truck(line_code, truck["id"]))

    asyncio.run(service.release_truck(line_code))

    assert service.line_client.kiriman[-1]["plate"] is None


def test_an_unknown_truck_id_still_assigns(service):
    """Readability is optional; grading is not. A truck row the console cannot
    read must never block the line from being assigned.
    """
    asyncio.run(service.assign_truck(service.lines[0].line_code, "truck-not-in-store"))

    sent = service.line_client.kiriman[-1]
    assert sent["truck_id"] == "truck-not-in-store"
    assert sent["plate"] is None


# ------------------------------------------------------- the receiving end


def test_the_line_accepts_a_payload_without_a_plate():
    """An older console does not send the field. It must not 422 the line —
    that would stop assignment entirely across a partial upgrade.
    """
    request = AssignmentSyncRequest(
        machine_id="m1",
        assignment_id="a1",
        truck_id="t1",
        assigned_at="2026-09-08T09:14:32+07:00",
    )

    assert request.plate is None


def test_an_empty_plate_becomes_none():
    """Release sends empty strings; `""` must not become a folder name."""
    request = AssignmentSyncRequest(
        machine_id="m1",
        assignment_id="",
        truck_id="",
        assigned_at="2026-09-08T09:14:32+07:00",
        plate="",
    )

    assert request.plate is None
