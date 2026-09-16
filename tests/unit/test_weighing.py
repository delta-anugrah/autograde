"""Weighbridge + manual truck entry (plan §3.5c).

What is pinned here is the money lane: neto never arrives raw from outside, two
payloads for one ticket merge instead of overwriting each other, and the same
plate written differently stays one truck.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.plate import normalisasi_plat, truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), None)


def _kiriman(**over):
    payload = {
        "plate_number": "B 1234 XY",
        "entered_at": "2026-09-09T18:30:00+00:00",  # = 2026-09-10 01:30 WIB local
        "gross_kg": 12500,
        "tare_kg": 5000,
    }
    payload.update(over)
    return payload


# ── plate ───────────────────────────────────────────────────────────────


def test_plat_beda_tulisan_tetap_satu_truk():
    assert normalisasi_plat("B 1234 xy") == normalisasi_plat("b-1234-XY") == "B1234XY"
    assert truck_id_for("B 1234 xy") == truck_id_for("b-1234-XY")


def test_plat_kosong_ditolak():
    with pytest.raises(ValueError):
        normalisasi_plat("   -  ")


def test_truk_manual_diketik_ulang_tidak_jadi_baris_kembar(service):
    a = service.daftar_truk_manual("B 1234 XY")
    b = service.daftar_truk_manual("b1234xy")
    assert a["id"] == b["id"]
    assert [t["id"] for t in service.trucks()] == [a["id"]]


# ── weighing ────────────────────────────────────────────────────────────


def test_neto_dihitung_dan_masuk_hari_kerja_wib(service):
    row = service.catat_timbangan(_kiriman())
    assert row["net_kg"] == 7500
    # Weighed 01:30 local — still yesterday's shift? No: the working day comes
    # from the payload's own timestamp in the mill's zone, not the receive date.
    assert row["work_date"] == "2026-09-10"
    assert [r["id"] for r in service.weighings("2026-09-10")] == [row["id"]]


def test_neto_kiriman_yang_tidak_cocok_ditolak(service):
    service.catat_timbangan(_kiriman(net_kg=7500.4))  # within tolerance, passes
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(net_kg=9000))


def test_tara_lebih_besar_dari_bruto_ditolak(service):
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(gross_kg=5000, tare_kg=12500))


def test_timbang_keluar_menggabung_bukan_menimpa(service):
    # Weigh-in only has gross, weigh-out only has tare. Without COALESCE the
    # second payload wipes gross and net goes with it.
    masuk = service.catat_timbangan(_kiriman(tare_kg=None))
    assert masuk["gross_kg"] == 12500 and masuk["net_kg"] is None
    keluar = service.catat_timbangan(
        _kiriman(gross_kg=None, tare_kg=5000, exited_at="2026-09-09T21:00:00+00:00")
    )
    assert keluar["id"] == masuk["id"]
    assert (keluar["gross_kg"], keluar["tare_kg"], keluar["net_kg"]) == (12500, 5000, 7500)
    assert len(service.weighings("2026-09-10")) == 1


def test_kiriman_sama_dua_kali_tidak_jadi_dua_tiket(service):
    service.catat_timbangan(_kiriman())
    service.catat_timbangan(_kiriman())
    assert len(service.weighings("2026-09-10")) == 1


def test_ref_jadi_kunci_kalau_ada(service):
    a = service.catat_timbangan(_kiriman(ref="TKT-9"))
    b = service.catat_timbangan(_kiriman(ref="TKT-9", entered_at="2026-09-09T19:00:00+00:00"))
    assert a["id"] == b["id"]


def test_tanpa_ref_dan_tanpa_waktu_masuk_ditolak(service):
    # If this were allowed, weigh-out could not find its row and one ticket
    # would split into two.
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(entered_at=None, exited_at="2026-09-09T21:00:00+00:00"))


def test_berat_ngawur_ditolak(service):
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(gross_kg="dua belas ton"))
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(gross_kg=-1))


def test_ref_kosong_dari_layar_tidak_bikin_tiket_kembar(service):
    # The operator screen ALWAYS sends `ref`; it is empty when the ticket was
    # born in the console, not in the scale program. If "" is not treated as
    # absent, the key changes and weigh-out spawns a second row.
    masuk = service.catat_timbangan(_kiriman(tare_kg=None))
    keluar = service.catat_timbangan(_kiriman(ref="", gross_kg=None, tare_kg=5000))
    assert keluar["id"] == masuk["id"]
    assert keluar["net_kg"] == 7500
    assert len(service.weighings("2026-09-10")) == 1


def test_koma_dibaca_sebagai_desimal(service):
    row = service.catat_timbangan(_kiriman(gross_kg="12500,5", tare_kg="5000,5"))
    assert row["gross_kg"] == 12500.5
    assert row["net_kg"] == 7500.0


def test_pemisah_ribuan_ditolak_bukan_diam_diam_jadi_kecil(service):
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(gross_kg="12.500,5"))


def test_pemisah_ribuan_tanpa_desimal_ketahuan_lewat_lantai_berat(service):
    # "14.820" typed for fourteen tonnes parses cleanly as 14.82 kg - the only
    # thing that catches it is the floor.
    with pytest.raises(ValueError):
        service.catat_timbangan(_kiriman(gross_kg="14.820", tare_kg=None))
