"""`LineStatusWorker` hands every answered status to one hook (Lepas paksa, 2026-10-04).

The hook is how the console notices a line that was cut off, not dead: once it answers,
its status says which truck it still holds. A line that does not answer reaches no hook,
and a hook that fails never stops the poll for the other lines.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.workers import line_status_worker
from palmgrade.workers.line_status_worker import LineStatusWorker


class FakeClient:
    def __init__(self, mati: set[str]) -> None:
        self.mati = mati

    async def status(self, line) -> dict:
        if line.line_code in self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "no answer", line=line.name)
        return {"truck_id": f"truk-{line.line_code}", "piston": {}, "alarms": []}


def _lines():
    return replace(Settings()).console_lines


def test_every_answered_status_reaches_the_hook_and_a_silent_line_does_not():
    dilihat: list[tuple[str, str | None]] = []

    async def hook(kode: str, status: dict) -> None:
        dilihat.append((kode, status.get("truck_id")))

    worker = LineStatusWorker(_lines(), FakeClient({"line-2"}), sesudah_terbaca=hook)
    asyncio.run(worker.run_once())

    assert dilihat == [("line-1", "truk-line-1"), ("line-3", "truk-line-3")]


def test_a_failing_hook_is_logged_and_the_other_lines_are_still_read(caplog):
    async def hook(kode: str, status: dict) -> None:
        if kode == "line-1":
            raise RuntimeError("boom")

    worker = LineStatusWorker(_lines(), FakeClient(set()), sesudah_terbaca=hook)
    with caplog.at_level(logging.ERROR, logger=line_status_worker.__name__):
        asyncio.run(worker.run_once())

    assert worker.snapshot()["line-3"]["reachable"] is True
    assert any("line-1" in r.getMessage() for r in caplog.records)


def test_without_a_hook_the_worker_runs_as_before():
    worker = LineStatusWorker(_lines(), FakeClient(set()))
    asyncio.run(worker.run_once())
    assert worker.snapshot()["line-1"]["reachable"] is True
