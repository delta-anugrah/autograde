"""Tombol piston di konsol: perintah diteruskan, status dibaca dari line.

Layar menampilkan apa yang dibenarkan PLC, bukan apa yang barusan diklik.
Karena itu status datang dari worker yang membaca line, bukan dari ingatan
konsol sendiri.
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
    def __init__(self, *, mati: bool = False) -> None:
        self.perintah: list[tuple[str, bool]] = []
        self.mati = mati

    async def set_piston(self, line, *, open, requested_by, requested_at):
        if self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        self.perintah.append((line.line_code, open))

    async def status(self, line):
        if self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        return {"truck_id": "t-1", "ffb_source": "Internal",
                "piston": {"requested": True, "confirmed_open": True}}


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def test_perintah_piston_diteruskan_ke_line(service):
    kode = service.lines[0].line_code
    asyncio.run(service.piston(kode, True))
    assert service._line_client.perintah == [(kode, True)]


def test_line_mati_muncul_sebagai_error_operator(service):
    service._line_client.mati = True
    with pytest.raises(LineUnavailable):
        asyncio.run(service.piston(service.lines[0].line_code, True))


def test_worker_menyimpan_status_line_dan_state_memakainya(service):
    worker = LineStatusWorker(service.lines, service._line_client, interval_s=0)
    asyncio.run(worker.run_once())
    service.line_status = worker.snapshot

    kartu = next(k for k in service.state()["lines"] if k["line_code"] == service.lines[0].line_code)
    assert kartu["plc"] == {
        "reachable": True, "ffb_source": "Internal",
        "piston_requested": True, "piston_open": True,
    }


def test_line_mati_tidak_menjatuhkan_worker(service):
    service._line_client.mati = True
    worker = LineStatusWorker(service.lines, service._line_client, interval_s=0)
    asyncio.run(worker.run_once())          # tidak boleh raise
    assert worker.snapshot()[service.lines[0].line_code]["reachable"] is False
