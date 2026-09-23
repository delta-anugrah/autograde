"""The console's piston button: the command is forwarded, status is read from the line.

The screen shows what the PLC confirmed, not what was just clicked. That is
why status comes from the worker that reads the line, not from the console's
own memory.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.workers.line_status_worker import LineStatusWorker


class FakeLine:
    def __init__(self, *, down: bool = False) -> None:
        self.commands: list[tuple[str, bool]] = []
        self.down = down

    async def set_piston(self, line, *, open, requested_by, requested_at):
        if self.down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        self.commands.append((line.line_code, open))

    async def status(self, line):
        if self.down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        return {"truck_id": "t-1", "ffb_source": "Internal",
                "piston": {"requested": True, "confirmed_open": True}}


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def test_piston_command_is_forwarded_to_the_line(service):
    code = service.lines[0].line_code
    asyncio.run(service.piston(code, True))
    assert service.line_client.commands == [(code, True)]


def test_a_down_line_surfaces_as_an_operator_error(service):
    service.line_client.down = True
    with pytest.raises(LineUnavailable):
        asyncio.run(service.piston(service.lines[0].line_code, True))


def test_the_worker_stores_line_status_and_state_uses_it(service):
    worker = LineStatusWorker(service.lines, service.line_client, interval_s=0)
    asyncio.run(worker.run_once())
    service.line_status = worker.snapshot

    card = next(k for k in service.state()["lines"] if k["line_code"] == service.lines[0].line_code)
    # Dicocokkan utuh, bukan per kunci: kartu line meneruskan dict ini apa
    # adanya ke layar, jadi field yang diam-diam hilang atau bertambah harus
    # terlihat di sini. `alarms` kosong karena FakeLine tidak mengirimnya —
    # line versi lama berperilaku persis begitu.
    assert card["plc"] == {
        "reachable": True, "ffb_source": "Internal",
        "piston_requested": True, "piston_open": True, "alarms": [],
    }


def test_a_down_line_does_not_bring_down_the_worker(service):
    service.line_client.down = True
    worker = LineStatusWorker(service.lines, service.line_client, interval_s=0)
    asyncio.run(worker.run_once())          # must not raise
    assert worker.snapshot()[service.lines[0].line_code]["reachable"] is False
