"""Releasing a truck from a line (field operator).

The truck finishes unloading and leaves, and until someone tells the line, the
line keeps stamping it onto the next bunches. Guarded here: the line is told
FIRST (same invariant as `assign_truck`), the screen clears with it, and a dead
line must never make the screen lie.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.schemas.internal_schema import AssignmentSyncRequest
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    """Stands in for `LineClient` — the service only knows the collaborator, not httpx."""

    def __init__(self, *, mati: bool = False) -> None:
        self.kiriman: list[tuple[str, str, str]] = []
        self.mati = mati

    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at) -> None:
        if self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        self.kiriman.append((line.line_code, assignment_id, truck_id))


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def _kartu(service, line_code):
    return next(k for k in service.state()["lines"] if k["line_code"] == line_code)


def _pasang_truk(service):
    kode = service.lines[0].line_code
    truk = service.daftar_truk_manual("B 1234 XY")
    asyncio.run(service.assign_truck(kode, truk["id"]))
    assert _kartu(service, kode)["assignment"]["truck_id"] == truk["id"]
    return kode


def test_lepas_truk_memberi_tahu_line_lalu_mengosongkan_layar(service):
    kode = _pasang_truk(service)

    asyncio.run(service.lepas_truk(kode))

    # The screen is not the point — the line is what has to know.
    assert service._line_client.kiriman[-1] == (kode, "", "")
    assert _kartu(service, kode)["assignment"] is None


def test_lepas_truk_gagal_kalau_line_mati_layar_tetap_jujur(service):
    kode = _pasang_truk(service)
    service._line_client.mati = True

    with pytest.raises(LineUnavailable):
        asyncio.run(service.lepas_truk(kode))

    # The screen still shows the truck, and rightly so: the line does not know yet.
    assert _kartu(service, kode)["assignment"] is not None


def test_lepas_truk_line_tak_dikenal_ditolak(service):
    with pytest.raises(ValueError):
        asyncio.run(service.lepas_truk("line-9"))


def test_truk_kosong_sampai_di_line_sebagai_none_bukan_string_kosong():
    # "" passed through as-is rides into the event payload, and palmgrade-api
    # validates truck_id/assignment_id as UUIDs → event rejected 400.
    req = AssignmentSyncRequest(
        machine_id="m-1", assignment_id="", truck_id="", assigned_at="2026-09-11T08:00:00+07:00"
    )
    assert req.truck_id is None
    assert req.assignment_id is None


def test_ffb_source_ikut_di_penugasan_dan_kosong_kalau_tidak_dikirim():
    # palmgrade-api tidak mengirim field ini; tanpa field artinya sortir normal.
    lama = AssignmentSyncRequest(
        machine_id="m-1", assignment_id="a-1", truck_id="t-1", assigned_at="2026-09-15T08:00:00+07:00"
    )
    assert lama.ffb_source is None

    internal = AssignmentSyncRequest(
        machine_id="m-1", assignment_id="a-1", truck_id="t-1",
        assigned_at="2026-09-15T08:00:00+07:00", ffb_source="Internal",
    )
    assert internal.ffb_source == "Internal"


def test_ffb_source_asing_ditolak_bukan_diam_diam_dianggap_kosong():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AssignmentSyncRequest(
            machine_id="m-1", assignment_id="a-1", truck_id="t-1",
            assigned_at="2026-09-15T08:00:00+07:00", ffb_source="internal",
        )
