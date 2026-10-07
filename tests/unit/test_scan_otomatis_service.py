"""The one scan field end to end on a real store (user 2026-10-06): four scans, one visit.

The live scale is a stand-in with a fixed answer; how a reading becomes fit is pinned in
`test_timbangan_live_tahan.py`. Weight still lands through `record_weighing`, gate times
through `GateService`.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import OperatorError
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.gate_service import GateService
from palmgrade.services.scan_otomatis import ScanOtomatis

PLAT = "BE 4412 OFL"


class _Live:
    def __init__(self, kg=None) -> None:
        self.kg = kg
        self.minimum = None

    def berat_layak(self, minimum):
        self.minimum = minimum
        return self.kg


@pytest.fixture
def pabrik(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, None)
    store.upsert_supplier({"id": "S1", "name": "PT Sawit Jaya", "source_group": "Petani", "status": "active"})
    service.register_manual_truck(PLAT, supplier_id="S1")
    live = _Live()
    scan = ScanOtomatis(service, GateService(store, service.tz), live)
    return scan, live, service, store


def _scan(scan, jam, qr=PLAT, konfirmasi=False):
    return asyncio.run(scan.scan(qr, jam, konfirmasi=konfirmasi))


def test_empat_scan_satu_kunjungan_dengan_timbangan_live(pabrik):
    scan, live, service, store = pabrik
    h1 = _scan(scan, "2026-10-06T01:00:00+00:00")
    assert (h1["langkah"], h1["hasil"], h1["supplier"]) == ("datang", "tercatat", "PT Sawit Jaya")

    live.kg = 14820
    h2 = _scan(scan, "2026-10-06T01:20:00+00:00")
    assert (h2["langkah"], h2["hasil"], h2["kg"]) == ("timbang_isi", "tersimpan", 14820)
    assert live.minimum == 1000
    tiket = store.weighing(h2["weighing_id"])
    assert (tiket["gross_kg"], tiket["entered_at"]) == (14820, "2026-10-06T01:20:00+00:00")
    # The weigh-in claimed the arrival: queue time is known.
    assert store.waiting_arrivals_for_truck(truck_id_for(PLAT)) == []

    live.kg = 6100
    h3 = _scan(scan, "2026-10-06T02:00:00+00:00")
    assert (h3["langkah"], h3["hasil"], h3["weighing_id"]) == ("timbang_kosong", "tersimpan", h2["weighing_id"])
    tiket = store.weighing(h2["weighing_id"])
    assert (tiket["tare_kg"], tiket["net_kg"]) == (6100, 8720)

    h4 = _scan(scan, "2026-10-06T02:05:00+00:00")
    assert (h4["langkah"], h4["hasil"]) == ("keluar", "tercatat")
    assert store.weighing(h2["weighing_id"])["left_at"] == "2026-10-06T02:05:00+00:00"

    # The next visit starts over at Datang.
    assert _scan(scan, "2026-10-06T05:00:00+00:00")["langkah"] == "datang"


def test_tanpa_timbangan_minta_berat_dan_tidak_menulis(pabrik):
    scan, _, service, store = pabrik
    _scan(scan, "2026-10-06T01:00:00+00:00")
    h2 = _scan(scan, "2026-10-06T01:20:00+00:00")
    assert (h2["langkah"], h2["hasil"]) == ("timbang_isi", "perlu_berat")
    assert service.weighings("2026-10-06") == []

    # The operator types it in the bruto box: the screen's own weigh-in lane.
    asyncio.run(service.record_weighing(
        {"plate_number": PLAT, "gross_kg": "14000", "entered_at": "2026-10-06T01:21:00+00:00"}))
    h3 = _scan(scan, "2026-10-06T02:00:00+00:00")
    assert (h3["langkah"], h3["hasil"]) == ("timbang_kosong", "perlu_berat")
    assert h3["weighing"]["plate_number"] == PLAT
    assert h3["weighing"]["entered_at"] == "2026-10-06T01:21:00+00:00"
    assert store.weighing(h3["weighing"]["id"])["tare_kg"] is None


def test_baca_ganda_sesudah_datang_ditanya_dulu(pabrik):
    scan, live, service, _ = pabrik
    live.kg = 14820
    _scan(scan, "2026-10-06T01:00:00+00:00")
    h = _scan(scan, "2026-10-06T01:00:01+00:00")
    assert (h["langkah"], h["hasil"], h["menit"]) == ("timbang_isi", "perlu_konfirmasi", 0)
    assert service.weighings("2026-10-06") == []

    h = _scan(scan, "2026-10-06T01:00:05+00:00", konfirmasi=True)
    assert (h["langkah"], h["hasil"]) == ("timbang_isi", "tersimpan")


def test_timbang_kosong_cepat_sesudah_isi_ditanya(pabrik):
    scan, live, service, store = pabrik
    live.kg = 14820
    assert _scan(scan, "2026-10-06T01:00:00+00:00")["langkah"] == "datang"
    assert _scan(scan, "2026-10-06T01:30:00+00:00")["hasil"] == "tersimpan"
    h = _scan(scan, "2026-10-06T01:31:00+00:00")
    assert (h["langkah"], h["hasil"], h["menit"]) == ("timbang_kosong", "perlu_konfirmasi", 1)
    [tiket] = service.weighings("2026-10-06")
    assert tiket["tare_kg"] is None


def test_truk_belum_terdaftar_boleh_datang_tidak_boleh_ditimbang(pabrik):
    scan, live, service, _ = pabrik
    live.kg = 14820
    h1 = _scan(scan, "2026-10-06T01:00:00+00:00", qr="BE 9999 XYZ")
    assert (h1["langkah"], h1["hasil"], h1["supplier"]) == ("datang", "tercatat", None)
    h2 = _scan(scan, "2026-10-06T01:20:00+00:00", qr="BE 9999 XYZ")
    assert (h2["langkah"], h2["hasil"]) == ("timbang_isi", "belum_terdaftar")
    assert service.weighings("2026-10-06") == []


def test_truk_nonaktif_tidak_ditimbang(pabrik):
    scan, live, service, store = pabrik
    live.kg = 14820
    store.upsert_truck({"id": truck_id_for("BE 7 OLD"), "plate_number": "BE 7 OLD", "status": "inactive"})
    _scan(scan, "2026-10-06T01:00:00+00:00", qr="BE 7 OLD")
    h2 = _scan(scan, "2026-10-06T01:20:00+00:00", qr="BE 7 OLD")
    assert h2["hasil"] == "nonaktif"


def test_dua_tiket_terbuka_tidak_ditebak(pabrik):
    scan, live, service, _ = pabrik
    for jam in ("2026-10-06T01:00:00+00:00", "2026-10-06T01:30:00+00:00"):
        asyncio.run(service.record_weighing({"plate_number": PLAT, "gross_kg": 14000, "entered_at": jam}))
    live.kg = 6000
    h = _scan(scan, "2026-10-06T02:00:00+00:00")
    assert (h["langkah"], h["hasil"]) == ("ganda", "ganda")
    assert [w["entered_at"] for w in h["pilihan"]] == ["2026-10-06T01:30:00+00:00", "2026-10-06T01:00:00+00:00"]
    assert all(w["tare_kg"] is None for w in service.weighings("2026-10-06"))


def test_bukan_plat_ditolak(pabrik):
    scan, *_ = pabrik
    with pytest.raises(OperatorError):
        _scan(scan, "2026-10-06T01:00:00+00:00", qr="https://promo.example/qr")


def test_dummy_nyala_timbang_isi_30000_tanpa_timbangan_live(pabrik):
    scan, live, service, store = pabrik
    service.simpan_timbangan_dummy(True, diubah_oleh="sp@pks.test")
    _scan(scan, "2026-10-06T01:00:00+00:00")
    h = _scan(scan, "2026-10-06T01:20:00+00:00")
    assert (h["langkah"], h["hasil"], h["kg"], h["dummy"]) == ("timbang_isi", "tersimpan", 30000.0, True)
    assert store.weighing(h["weighing_id"])["gross_kg"] == 30000.0


def test_dummy_nyala_timbang_kosong_10000(pabrik):
    scan, live, service, store = pabrik
    service.simpan_timbangan_dummy(True, diubah_oleh="sp@pks.test")
    _scan(scan, "2026-10-06T01:00:00+00:00")
    _scan(scan, "2026-10-06T01:20:00+00:00")
    h = _scan(scan, "2026-10-06T02:00:00+00:00")
    assert (h["langkah"], h["hasil"], h["kg"], h["dummy"]) == ("timbang_kosong", "tersimpan", 10000.0, True)
    tiket = store.weighing(h["weighing_id"])
    assert (tiket["gross_kg"], tiket["tare_kg"], tiket["net_kg"]) == (30000.0, 10000.0, 20000.0)


def test_dummy_mati_tetap_minta_berat(pabrik):
    scan, *_ = pabrik
    _scan(scan, "2026-10-06T01:00:00+00:00")
    h = _scan(scan, "2026-10-06T01:20:00+00:00")
    assert h["hasil"] == "perlu_berat" and "dummy" not in h


def test_dummy_mati_timbangan_live_ditandai_bukan_dummy(pabrik):
    scan, live, *_ = pabrik
    live.kg = 14820
    _scan(scan, "2026-10-06T01:00:00+00:00")
    h = _scan(scan, "2026-10-06T01:20:00+00:00")
    assert (h["kg"], h["dummy"]) == (14820, False)
