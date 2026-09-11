"""Melepas truk dari line (operator lapangan).

Truk selesai bongkar lalu pergi, dan sampai ada yang bilang ke line, line terus
menempelkan truk itu ke tandan berikutnya. Yang dijaga di sini: line diberi tahu
DULU (invarian yang sama dengan `assign_truck`), layar ikut kosong, dan line yang
mati tidak boleh membuat layar berbohong.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.schemas.internal_schema import AssignmentSyncRequest
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    """Pengganti `LineClient` — service cuma tahu kolaboratornya, bukan httpx."""

    def __init__(self, *, mati: bool = False) -> None:
        self.kiriman: list[tuple[str, str, str]] = []
        self.mati = mati

    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at) -> None:
        if self.mati:
            raise LineUnavailable("line tidak menjawab")
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

    # Yang penting bukan layarnya — line-nya yang harus tahu.
    assert service._line_client.kiriman[-1] == (kode, "", "")
    assert _kartu(service, kode)["assignment"] is None


def test_lepas_truk_gagal_kalau_line_mati_layar_tetap_jujur(service):
    kode = _pasang_truk(service)
    service._line_client.mati = True

    with pytest.raises(LineUnavailable):
        asyncio.run(service.lepas_truk(kode))

    # Layar masih menampilkan truk, dan memang benar begitu: line belum tahu.
    assert _kartu(service, kode)["assignment"] is not None


def test_lepas_truk_line_tak_dikenal_ditolak(service):
    with pytest.raises(ValueError):
        asyncio.run(service.lepas_truk("line-9"))


def test_truk_kosong_sampai_di_line_sebagai_none_bukan_string_kosong():
    # "" yang lolos apa adanya ikut ke payload event, dan palmgrade-api
    # memvalidasi truck_id/assignment_id sebagai UUID → event ditolak 400.
    req = AssignmentSyncRequest(
        machine_id="m-1", assignment_id="", truck_id="", assigned_at="2026-09-11T08:00:00+07:00"
    )
    assert req.truck_id is None
    assert req.assignment_id is None
