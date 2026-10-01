"""Integrasi penugasan line otomatis dan antrean bongkar, tanpa tiruan di tengah.

`ConsoleService` + `ConsoleStore` (berkas SQLite sungguhan) + `LineClient` sungguhan ke
tiga line palsu: line-1 menerima, line-2 menolak (503), line-3 mati (tidak ada app di
portnya). Yang dibuktikan: satu line yang tidak menjawab tidak pernah menggagalkan
timbangan, truk berikutnya menunggu sampai truk sebelumnya timbang kosong, dan Lewati
mengeluarkan truk dari antrean.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from antrean_line_rakit import LinePerPort
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import InvalidInput
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

SECRET = "kunci-internal-palsu"
WIB = ZoneInfo("Asia/Jakarta")
PLAT_A, PLAT_B, PLAT_C = "BE 1101 AA", "BE 1102 AA", "BE 1103 AA"


class LineMenerima:
    def __init__(self) -> None:
        self.diterima: list[dict] = []
        self.app = FastAPI()

        @self.app.post("/internal/assignment")
        async def penugasan(request: Request) -> dict:
            assert request.headers["x-internal-secret"] == SECRET
            self.diterima.append(await request.json())
            return {"status": "ok"}


class LineMenolak:
    def __init__(self) -> None:
        self.app = FastAPI()

        @self.app.post("/internal/assignment")
        async def penugasan() -> JSONResponse:
            return JSONResponse({"detail": "sibuk"}, status_code=503)


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(
        Settings(), factory_tz="Asia/Jakarta", internal_secret=SECRET, console_line_host="http://line"
    )
    store = ConsoleStore(tmp_path / "console.db")
    line_1 = LineMenerima()
    klien = LineClient(
        settings, transport=LinePerPort({8001: line_1.app, 8002: LineMenolak().app})
    )
    service = ConsoleService(settings, store, klien)
    service.simpan_penugasan_otomatis(True, ["line-1", "line-2", "line-3"], diubah_oleh="sp@pks.test")
    return service, store, line_1


def _isi(service, plat: str) -> dict:
    return asyncio.run(service.record_weighing({
        "ref": plat, "plate_number": plat, "gross_kg": 14000,
        "entered_at": datetime.now(WIB).replace(microsecond=0).isoformat(),
    }))


def _kosong(service, plat: str) -> dict:
    return asyncio.run(service.record_weighing({
        "ref": plat, "plate_number": plat, "tare_kg": 5000,
        "exited_at": datetime.now(WIB).replace(microsecond=0).isoformat(),
    }))


def _terpasang(hasil: dict) -> dict[str, bool]:
    return {d["line_code"]: d["terpasang"] for d in hasil["dipasang"]}


def _antrean(service) -> list[str]:
    return [a["plate_number"] for a in service.antrean_bongkar()]


def test_line_yang_tidak_menjawab_tidak_menggagalkan_timbangan(pabrik):
    service, store, line_1 = pabrik

    hasil = _isi(service, PLAT_A)

    assert _terpasang(hasil) == {"line-1": True, "line-2": False, "line-3": False}
    assert store.weighing(hasil["id"])["gross_kg"] == 14000, "tiket tetap tersimpan"
    assert store.assignments()["line-1"]["truck_id"] == truck_id_for(PLAT_A)
    assert not (store.assignments().get("line-2") or {}).get("truck_id")
    assert [d["truck_id"] for d in line_1.diterima] == [truck_id_for(PLAT_A)]
    assert _antrean(service) == [], "truk A sudah ditangani, bukan antre"


def test_truk_berikutnya_menunggu_lalu_naik_saat_truk_pertama_timbang_kosong(pabrik):
    service, store, line_1 = pabrik
    _isi(service, PLAT_A)

    hasil_b = _isi(service, PLAT_B)

    assert hasil_b["dipasang"] == []
    assert _antrean(service) == [PLAT_B]
    assert store.assignments()["line-1"]["truck_id"] == truck_id_for(PLAT_A)

    hasil_keluar = _kosong(service, PLAT_A)

    assert _terpasang(hasil_keluar) == {"line-1": True, "line-2": False, "line-3": False}
    assert store.assignments()["line-1"]["truck_id"] == truck_id_for(PLAT_B)
    assert _antrean(service) == []
    # Line-1 mendengar: A masuk, A dilepas (kosong), B masuk.
    assert [d["truck_id"] for d in line_1.diterima] == [truck_id_for(PLAT_A), "", truck_id_for(PLAT_B)]


def test_lewati_mengeluarkan_truk_dari_antrean(pabrik):
    service, store, _ = pabrik
    _isi(service, PLAT_A)
    _isi(service, PLAT_B)
    _isi(service, PLAT_C)
    antrean = service.antrean_bongkar()
    assert [a["plate_number"] for a in antrean] == [PLAT_B, PLAT_C]

    service.lewati_antrean(antrean[0]["weighing_id"], oleh="op@pks.test")

    assert _antrean(service) == [PLAT_C]
    with pytest.raises(InvalidInput) as galat:
        service.lewati_antrean(antrean[0]["weighing_id"], oleh="op@pks.test")
    assert galat.value.code == "bukan_antrean"
    # Truk A keluar: yang naik adalah C, B sudah dilewati.
    _kosong(service, PLAT_A)
    assert store.assignments()["line-1"]["truck_id"] == truck_id_for(PLAT_C)
    assert _antrean(service) == []
