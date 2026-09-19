"""Penjaga: jalur legacy `/api/set_truck` tidak boleh kembali.

Dihapus 2026-09-20 sesudah dibuktikan mati di dua sisi: `useSetTruckId` di
palmgrade-frontend tidak pernah di-import satu berkas pun, jadi endpoint-nya tidak
pernah dipanggil dari mana pun.

Kenapa dijaga, bukan cukup dihapus: endpoint itu **tanpa auth** dan line jalan
dengan `network_mode: host`, jadi begitu PC pabrik dapat internet dia ikut terbuka
(`docs/SETUP.md` §10, dan L4 di TODO). Menghidupkannya lagi tanpa sadar berarti
memasang kembali jalur tulis tanpa auth ke `current_truck_id` — dan itu tidak akan
kelihatan salah di layar mana pun.

Ada juga alasan kebenaran data. Jalur lama cuma menyentuh `current_truck_id`;
penggantinya `/internal/assignment` menetapkan **`current_assignment_id` juga**.
Janjang yang digrading lewat jalur lama tercatat tanpa assignment, jadi tautan ke
kunjungan truk di rekap AutoERP putus — tonase mendarat di "Tanpa truk".

⚠️ Yang dijaga cuma jalur HTTP-nya. `RuntimeState.current_truck_id` dan
`TruckRepository` **tetap dipakai** (`internal_controller`, `frame_processing_worker`,
`CaptureService`), jadi tes ini sengaja tidak menyentuh keduanya.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"

# Berkas yang dibuang. Ada lagi salah satunya = rantainya dirakit ulang.
BERKAS_DIBUANG = (
    SRC / "routes" / "truck.py",
    SRC / "controllers" / "truck_controller.py",
    SRC / "services" / "truck_service.py",
    SRC / "schemas" / "truck_schema.py",
)

# Yang HARUS tetap ada — supaya tes ini tidak terbaca seperti izin membuang semuanya.
BERKAS_TETAP = (
    SRC / "repositories" / "truck_repository.py",  # dipakai CaptureService
    SRC / "workers" / "runtime_state.py",  # menyimpan current_truck_id
)


@pytest.mark.parametrize("berkas", BERKAS_DIBUANG, ids=lambda p: p.name)
def test_berkas_jalur_lama_tidak_ada(berkas: Path):
    assert not berkas.exists(), (
        f"{berkas.name} hidup lagi — jalur `/api/set_truck` dirakit ulang. "
        "Penggantinya `/api/console/lines/{line}/assign-truck`."
    )


@pytest.mark.parametrize("berkas", BERKAS_TETAP, ids=lambda p: p.name)
def test_yang_dipakai_jalur_aktif_tetap_ada(berkas: Path):
    """Pembersihan ini sengaja berhenti di jalur HTTP-nya."""
    assert berkas.exists(), f"{berkas.name} ikut terbuang; jalur aktif memakainya"


def test_tidak_ada_rute_set_truck_di_seluruh_kode():
    """Menangkap endpoint yang dihidupkan lagi di berkas lain, dengan nama lain."""
    bocor = []
    for py in SRC.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if re.search(r"""["']/?api/set_truck|set_truck_route""", py.read_text(encoding="utf-8")):
            bocor.append(str(py.relative_to(SRC)))

    assert not bocor, f"rute set_truck muncul lagi di: {bocor}"


def test_current_truck_id_masih_ditulis_jalur_internal():
    """Kalau ini merah, yang terbuang bukan cuma jalur lamanya.

    `/internal/assignment` adalah satu-satunya penulis `current_truck_id` yang
    tersisa; tanpa dia tidak ada truk yang pernah terpasang ke line sama sekali.
    """
    internal = (SRC / "controllers" / "internal_controller.py").read_text(encoding="utf-8")

    assert "current_truck_id" in internal, "jalur /internal/assignment ikut terbawa"
    assert "current_assignment_id" in internal, (
        "assignment id hilang — ini yang membedakan jalur baru dari yang dibuang"
    )
