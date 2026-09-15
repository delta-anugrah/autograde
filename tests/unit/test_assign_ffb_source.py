"""Konsol menitipkan sumber TBS truk ke line saat penugasan.

Line-lah yang memutuskan ada tidaknya pulse (domain/plc_signal.py), tapi hanya
konsol yang tahu truknya milik siapa. Yang dikirim FAKTA dari AutoERP, bukan
keputusan: aturan bisnisnya boleh berubah tanpa mengubah bentuk kontrak.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    def __init__(self) -> None:
        self.kiriman: list[dict] = []

    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None):
        self.kiriman.append({"truck_id": truck_id, "ffb_source": ffb_source})


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def test_truk_manual_belum_dikenal_erp_dikirim_tanpa_sumber(service):
    truk = service.daftar_truk_manual("B 1234 XY")
    asyncio.run(service.assign_truck(service.lines[0].line_code, truk["id"]))
    assert service._line_client.kiriman[-1]["ffb_source"] is None


def test_truk_erp_tanpa_supplier_dikirim_sebagai_internal(service):
    truk = service.daftar_truk_manual("B 1234 XY")
    service.store.link_truck(truk["id"], "TRK-0001")
    asyncio.run(service.assign_truck(service.lines[0].line_code, truk["id"]))
    assert service._line_client.kiriman[-1]["ffb_source"] == "Internal"


def test_truk_bersupplier_dikirim_sebagai_external(service):
    truk = service.daftar_truk_manual("B 1234 XY")
    service.store.link_truck(truk["id"], "TRK-0001", supplier_id="SUP-1")
    asyncio.run(service.assign_truck(service.lines[0].line_code, truk["id"]))
    assert service._line_client.kiriman[-1]["ffb_source"] == "External"


def test_melepas_truk_mengosongkan_sumber_di_line(service):
    truk = service.daftar_truk_manual("B 1234 XY")
    kode = service.lines[0].line_code
    asyncio.run(service.assign_truck(kode, truk["id"]))
    asyncio.run(service.lepas_truk(kode))
    assert service._line_client.kiriman[-1]["ffb_source"] is None
