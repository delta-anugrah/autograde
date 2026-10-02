"""The stage of a ticket, for the Status badge on the Timbangan table (user 2026-10-02).

Decided in the domain and sent by the backend (standard L4): the screen only colours it.
Datang = scan 1 and not weighed in (the `waiting` list), Bongkar = weighed in without a
tare, Timbang kosong = tare and not left, Selesai = left (scan 4 or the row button).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.gerbang import (
    TAHAP_BONGKAR,
    TAHAP_DATANG,
    TAHAP_SELESAI,
    TAHAP_TIMBANG_KOSONG,
    tahap_tiket,
)
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

MASUK = "2026-10-02T01:00:00Z"


@pytest.mark.parametrize(
    "tiket, tahap",
    [
        ({"entered_at": MASUK, "gross_kg": 14000.0, "tare_kg": None, "left_at": None}, TAHAP_BONGKAR),
        ({"entered_at": MASUK, "gross_kg": 14000.0, "tare_kg": 6000.0, "left_at": None}, TAHAP_TIMBANG_KOSONG),
        ({"entered_at": MASUK, "gross_kg": 14000.0, "tare_kg": 6000.0, "left_at": "2026-10-02T02:00:00Z"},
         TAHAP_SELESAI),
        # The scale program may send a tare of 0 kg: still weighed out, not "no tare".
        ({"entered_at": MASUK, "gross_kg": 14000.0, "tare_kg": 0.0, "left_at": None}, TAHAP_TIMBANG_KOSONG),
        # Only what the ticket holds: keys missing from an old row read as empty.
        ({"entered_at": MASUK, "gross_kg": 14000.0}, TAHAP_BONGKAR),
    ],
    ids=["bongkar", "timbang_kosong", "selesai", "tara_nol", "baris_lama"],
)
def test_tahap_dari_isi_tiket(tiket, tahap):
    assert tahap_tiket(tiket) == tahap


def test_empat_tahap_empat_kata_berbeda():
    """The screen picks a badge colour and a KAMUS word per value: four, never two alike."""
    assert len({TAHAP_DATANG, TAHAP_BONGKAR, TAHAP_TIMBANG_KOSONG, TAHAP_SELESAI}) == 4


def _konsol(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    return ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None), store


def _tiket(store, wid, plat, *, tara=None, pergi=None):
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": plat, "plate_norm": plat.replace(" ", ""),
        "truck_id": truck_id_for(plat), "work_date": "2026-10-02", "gross_kg": 14000.0,
        "tare_kg": tara, "net_kg": None if tara is None else 14000.0 - tara,
        "entered_at": MASUK, "exited_at": None,
    })
    if pergi:
        assert store.set_left_at(wid, pergi)


def test_tampilan_timbangan_membawa_tahap_tiap_tiket(tmp_path):
    service, store = _konsol(tmp_path)
    _tiket(store, "w1", "BE 1 AA")
    _tiket(store, "w2", "BE 2 BB", tara=6000.0)
    _tiket(store, "w3", "BE 3 CC", tara=6000.0, pergi="2026-10-02T02:00:00Z")
    tahap = {w["plate_number"]: w["tahap"] for w in service.weighings("2026-10-02")}
    assert tahap == {"BE 1 AA": TAHAP_BONGKAR, "BE 2 BB": TAHAP_TIMBANG_KOSONG, "BE 3 CC": TAHAP_SELESAI}


def test_yang_menunggu_bertahap_datang(tmp_path):
    service, store = _konsol(tmp_path)
    jam = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    store.record_arrival({"id": "a1", "plate_number": "BE 9 ZZ", "plate_norm": "BE9ZZ",
                          "truck_id": truck_id_for("BE 9 ZZ"), "work_date": jam[:10], "arrived_at": jam})
    [baris] = service.waiting_arrivals()
    assert baris["tahap"] == TAHAP_DATANG
