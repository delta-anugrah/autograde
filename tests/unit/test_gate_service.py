"""Scan 1 (datang) dan scan 4 (keluar gerbang): cuma jam, tidak pernah berat, tidak
pernah truk baru, dan tidak pernah naik ke AutoERP."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.operator_error import BUKAN_PLAT, INPUT_TIDAK_SAH, PLAT_KOSONG, OperatorError
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.gate_service import GateService

WIB = ZoneInfo("Asia/Jakarta")
PLAT = "BE 4412 OFL"
LAIN = "BE 7001 XY"
JAM_NGAWUR = ("jam sembilan", "0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00", "2026-09-30T01:00:00+99:00")


@pytest.fixture
def store(tmp_path):
    return ConsoleStore(tmp_path / "console.db")


@pytest.fixture
def gate(store):
    return GateService(store, WIB)


def _tiket(store, id_, *, masuk, tara=None, keluar=None, plat=PLAT):
    store.upsert_weighing({
        "id": id_, "ref": None, "plate_number": plat, "plate_norm": plat.replace(" ", ""),
        "truck_id": truck_id_for(plat), "work_date": "2026-09-30", "gross_kg": 14000.0,
        "tare_kg": tara, "net_kg": None if tara is None else 14000.0 - tara,
        "entered_at": masuk, "exited_at": keluar,
    })


def _selesai(store, id_, masuk, keluar, plat=PLAT):
    _tiket(store, id_, masuk=masuk, tara=6000.0, keluar=keluar, plat=plat)


# ── scan 1 ───────────────────────────────────────────────────────────────────


def test_datang_tercatat_dengan_hari_kerja_wib(gate, store):
    h = gate.arrive(PLAT, "2026-09-30T17:30:00+00:00")  # 00:30 WIB 1 Oktober
    assert h["hasil"] == "tercatat"
    [baris] = store.waiting_arrivals_for_truck(truck_id_for(PLAT))
    assert baris["work_date"] == "2026-10-01"


def test_datang_dua_kali_tetap_satu_baris(gate, store):
    gate.arrive(PLAT, "2026-09-30T01:00:00+00:00")
    h = gate.arrive(PLAT, "2026-09-30T01:20:00+00:00")
    assert (h["hasil"], h["arrived_at"]) == ("sudah_tercatat", "2026-09-30T01:00:00+00:00")
    assert len(store.waiting_arrivals_for_truck(truck_id_for(PLAT))) == 1


def test_datang_lagi_sesudah_jendela_dicatat_baru(gate, store):
    gate.arrive(PLAT, "2026-09-29T01:00:00+00:00")
    assert gate.arrive(PLAT, "2026-09-30T01:00:00+00:00")["hasil"] == "tercatat"
    assert len(store.waiting_arrivals_for_truck(truck_id_for(PLAT))) == 2


def test_datang_truk_lain_tidak_dianggap_sudah_tercatat(gate, store):
    gate.arrive(PLAT, "2026-09-30T01:00:00+00:00")
    assert gate.arrive(LAIN, "2026-09-30T01:05:00+00:00")["hasil"] == "tercatat"
    assert len(store.waiting_arrivals_for_truck(truck_id_for(LAIN))) == 1


def test_datang_padahal_masih_di_dalam_ditolak(gate, store):
    _tiket(store, "w1", masuk="2026-09-30T01:00:00+00:00")
    assert gate.arrive(PLAT, "2026-09-30T01:30:00+00:00")["hasil"] == "masih_di_dalam"
    assert store.waiting_arrivals_for_truck(truck_id_for(PLAT)) == []


def test_datang_sesudah_timbang_kosong_dicatat(gate, store):
    """Kunjungan sebelumnya sudah selesai di timbangan: truk yang datang lagi itu kunjungan baru."""
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    assert gate.arrive(PLAT, "2026-09-30T03:00:00+00:00")["hasil"] == "tercatat"


def test_truk_belum_terdaftar_tetap_dicatat_tanpa_membuat_truk(gate, store):
    assert gate.arrive("BE 9999 ZZ", "2026-09-30T01:00:00+00:00")["hasil"] == "tercatat"
    assert store.trucks() == []


def test_plat_terdaftar_ditampilkan_seperti_terdaftar(gate, store):
    store.upsert_truck({"id": truck_id_for(PLAT), "plate_number": PLAT, "status": "active"})
    assert gate.arrive("be-4412-ofl", "2026-09-30T01:00:00+00:00")["plate_number"] == PLAT


@pytest.mark.parametrize("isi", ["https://promo.example/qr", "1234", "TRK0042"])
def test_datang_bukan_plat_ditolak_tanpa_menulis(gate, store, isi):
    with pytest.raises(OperatorError) as e:
        gate.arrive(isi, "2026-09-30T01:00:00+00:00")
    assert e.value.code == BUKAN_PLAT
    assert store.waiting_arrivals("2026-09-30") == []


def test_datang_kosong_ditolak(gate):
    with pytest.raises(OperatorError) as e:
        gate.arrive("   ", "2026-09-30T01:00:00+00:00")
    assert e.value.code == PLAT_KOSONG


@pytest.mark.parametrize("jam", JAM_NGAWUR)
def test_datang_jam_ngawur_jadi_galat_isian_bukan_500(gate, store, jam):
    with pytest.raises(ValueError) as e:
        gate.arrive(PLAT, jam)
    assert isinstance(e.value, OperatorError)
    assert (e.value.code, e.value.params) == (INPUT_TIDAK_SAH, {"field": "at"})
    assert store.waiting_arrivals_for_truck(truck_id_for(PLAT)) == []


def test_tanpa_jam_memakai_jam_server(gate, store):
    assert gate.arrive(PLAT)["hasil"] == "tercatat"
    [baris] = store.waiting_arrivals_for_truck(truck_id_for(PLAT))
    assert baris["arrived_at"]


# ── scan 4 ───────────────────────────────────────────────────────────────────


def test_keluar_menutup_tiket_yang_sudah_timbang_kosong(gate, store):
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    h = gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert (h["hasil"], h["weighing_id"], h["left_at"]) == ("tercatat", "w1", "2026-09-30T02:10:00+00:00")
    assert store.weighing("w1")["left_at"] == "2026-09-30T02:10:00+00:00"


def test_keluar_sebelum_timbang_kosong_ditolak_tanpa_menulis(gate, store):
    _tiket(store, "w1", masuk="2026-09-30T01:00:00+00:00")
    h = gate.leave(PLAT, "2026-09-30T01:30:00+00:00")
    assert (h["hasil"], h["weighing_id"]) == ("belum_timbang_kosong", "w1")
    assert "left_at" not in h
    assert store.weighing("w1")["left_at"] is None


def test_keluar_dua_kali_dijawab_sudah_keluar(gate, store):
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert gate.leave(PLAT, "2026-09-30T02:11:00+00:00")["hasil"] == "sudah_keluar"
    assert store.weighing("w1")["left_at"] == "2026-09-30T02:10:00+00:00"


def test_keluar_tanpa_tiket(gate):
    h = gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert (h["hasil"], h["weighing_id"]) == ("tidak_ada_tiket", None)


def test_keluar_dua_tiket_selesai_menutup_yang_terbaru_saja(gate, store):
    _selesai(store, "lama", "2026-09-30T00:00:00+00:00", "2026-09-30T00:50:00+00:00")
    _selesai(store, "baru", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    h = gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert (h["hasil"], h["weighing_id"]) == ("tercatat", "baru")
    assert store.weighing("lama")["left_at"] is None


def test_keluar_dua_tiket_satu_masih_terbuka_ditolak_dan_tidak_ada_yang_ditulis(gate, store):
    _selesai(store, "lama", "2026-09-30T00:00:00+00:00", "2026-09-30T00:50:00+00:00")
    _tiket(store, "baru", masuk="2026-09-30T01:00:00+00:00")
    h = gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert (h["hasil"], h["weighing_id"]) == ("belum_timbang_kosong", "baru")
    assert store.weighing("lama")["left_at"] is None
    assert store.weighing("baru")["left_at"] is None


def test_keluar_truk_lain_tidak_tersentuh(gate, store):
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    _selesai(store, "w2", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00", plat=LAIN)
    gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert store.weighing("w2")["left_at"] is None


def test_tombol_baris_menutup_tiket_yang_ditunjuk(gate, store):
    _selesai(store, "lama", "2026-09-30T00:00:00+00:00", "2026-09-30T00:50:00+00:00")
    _selesai(store, "baru", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    assert gate.leave(None, "2026-09-30T02:10:00+00:00", weighing_id="lama")["hasil"] == "tercatat"
    assert store.weighing("baru")["left_at"] is None


def test_tombol_baris_tiket_belum_timbang_kosong_ditolak(gate, store):
    _tiket(store, "w1", masuk="2026-09-30T01:00:00+00:00")
    assert gate.leave(None, "2026-09-30T01:30:00+00:00", weighing_id="w1")["hasil"] == "belum_timbang_kosong"
    assert store.weighing("w1")["left_at"] is None


def test_tombol_baris_tiket_tak_dikenal(gate):
    assert gate.leave(None, "2026-09-30T02:10:00+00:00", weighing_id="x")["hasil"] == "tidak_ada_tiket"


def test_keluar_bukan_plat_ditolak_tanpa_menulis(gate, store):
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    with pytest.raises(OperatorError) as e:
        gate.leave("https://promo.example/qr", "2026-09-30T02:10:00+00:00")
    assert e.value.code == BUKAN_PLAT
    assert store.weighing("w1")["left_at"] is None


def test_keluar_tanpa_plat_dan_tanpa_tiket_ditolak(gate):
    with pytest.raises(OperatorError) as e:
        gate.leave(None, "2026-09-30T02:10:00+00:00")
    assert e.value.code == PLAT_KOSONG


@pytest.mark.parametrize("jam", JAM_NGAWUR)
def test_keluar_jam_ngawur_jadi_galat_isian_bukan_500(gate, store, jam):
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    with pytest.raises(ValueError) as e:
        gate.leave(PLAT, jam)
    assert (e.value.code, e.value.params) == (INPUT_TIDAK_SAH, {"field": "at"})
    with pytest.raises(OperatorError):
        gate.leave(None, jam, weighing_id="w1")
    assert store.weighing("w1")["left_at"] is None


def test_gerbang_tidak_pernah_menyentuh_berat(gate, store):
    _selesai(store, "w1", "2026-09-30T01:00:00+00:00", "2026-09-30T02:00:00+00:00")
    sebelum = {k: store.weighing("w1")[k] for k in ("gross_kg", "tare_kg", "net_kg")}
    gate.arrive(PLAT, "2026-09-30T03:00:00+00:00")
    gate.leave(PLAT, "2026-09-30T02:10:00+00:00")
    assert {k: store.weighing("w1")[k] for k in ("gross_kg", "tare_kg", "net_kg")} == sebelum
