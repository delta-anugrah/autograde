"""`make demo-off` membuang data demo, dan TIDAK menyentuh data sungguhan.

Ini yang dijaga: `wipe()` menghapus berdasarkan sepuluh plat milik seeder, bukan
berdasarkan tanda di barisnya. Jadi satu-satunya yang memisahkan data demo dari
tonase sungguhan adalah daftar plat itu. Kalau suatu hari ada yang menambah plat
pabrik ke `PLATES` — atau melebarkan `wipe()` jadi "hapus semua" — timbangan dan
janjang sungguhan ikut hilang tanpa satu pun pesan.

Jalan tanpa cv2/numpy: yang diuji cuma jalur SQL-nya.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore

AKAR = pathlib.Path(__file__).resolve().parents[2]

# Plat yang PASTI bukan milik seeder — dipakai sebagai "data sungguhan".
PLAT_ASLI = "BG 9911 ZZ"


def _muat_seeder():
    jalur = AKAR / "scripts" / "seed-console-demo.py"
    spec = importlib.util.spec_from_file_location("seed_console_demo", jalur)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture
def seeder():
    return _muat_seeder()


def _janjang(store: ConsoleStore, plate: str, event_id: str) -> None:
    store.add_inspection(
        {
            "event_id": event_id,
            "machine_id": "M1",
            "line_code": "line-1",
            "work_date": "2026-09-17",
            "timestamp": "2026-09-17T07:14:48+00:00",
            "ripeness_status": "ACC",
            "ripeness_confidence": 0.9,
            "capture_type": "auto",
            "image_path": None,
            "truck_id": truck_id_for(plate),
            "assignment_id": "a-1",
            "prediction": "Acc",
            "tp_status": None,
            "tp_confidence": 0.0,
        }
    )


def _timbangan(store: ConsoleStore, plate: str, wid: str) -> None:
    store.upsert_weighing(
        {
            "id": wid,
            "ref": None,
            "plate_number": plate,
            "plate_norm": plate.replace(" ", ""),
            "truck_id": truck_id_for(plate),
            "work_date": "2026-09-17",
            "gross_kg": 20000.0,
            "tare_kg": None,
            "net_kg": None,
            "entered_at": "2026-09-17T07:00:00+00:00",
            "exited_at": None,
        }
    )


@pytest.fixture
def store(tmp_path, seeder):
    """Satu janjang + satu timbangan untuk SETIAP plat demo, plus satu punya pabrik."""
    store = ConsoleStore(tmp_path / "console.db")
    for i, plate in enumerate(seeder.PLATES):
        _janjang(store, plate, f"demo-{i}")
        _timbangan(store, plate, f"w-demo-{i}")
    _janjang(store, PLAT_ASLI, "asli-1")
    _timbangan(store, PLAT_ASLI, "w-asli-1")
    return store


def _hitung(store: ConsoleStore, tabel: str, plate: str) -> int:
    with store._lock:  # noqa: SLF001 — membaca langsung; tidak ada API hitung-per-truk
        return store._db.execute(  # noqa: SLF001
            f"SELECT COUNT(*) FROM {tabel} WHERE truck_id = ?", (truck_id_for(plate),)
        ).fetchone()[0]


def test_wipe_membuang_setiap_plat_demo(store, seeder):
    seeder.wipe(store)

    for plate in seeder.PLATES:
        assert _hitung(store, "inspections", plate) == 0, f"janjang demo {plate} tersisa"
        assert _hitung(store, "weighings", plate) == 0, f"timbangan demo {plate} tersisa"


def test_wipe_tidak_menyentuh_truk_sungguhan(store, seeder):
    """Yang paling mahal kalau rusak: tonase sungguhan hilang tanpa pesan apa pun."""
    seeder.wipe(store)

    assert _hitung(store, "inspections", PLAT_ASLI) == 1
    assert _hitung(store, "weighings", PLAT_ASLI) == 1


def test_plat_sungguhan_tidak_boleh_masuk_daftar_demo(seeder):
    """`BG 9911 ZA` (demo) dan `BG 9911 ZZ` (pabrik) cuma beda satu huruf.

    Daftar plat ADALAH garis pemisahnya: satu plat pabrik yang tercantum di sini
    membuat `demo-off` menghapus tonase yang dibayar.
    """
    assert PLAT_ASLI not in seeder.PLATES


def test_wipe_boleh_dijalankan_dua_kali(store, seeder):
    """`make demo-off` sesudah `make demo-off` bukan error, dan tidak menghapus lebih."""
    seeder.wipe(store)
    kedua = seeder.wipe(store)

    assert kedua == 0
    assert _hitung(store, "weighings", PLAT_ASLI) == 1
