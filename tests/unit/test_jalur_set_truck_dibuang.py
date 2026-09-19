"""Penjaga: jalur HTTP legacy tanpa auth tidak boleh kembali.

Dua rantai, dibuang dengan alasan yang sama dan dijaga bersama: `/api/set_truck`
(2026-09-20) dan `/api/capture_reject` (2026-09-20).

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
    # /api/set_truck
    SRC / "routes" / "truck.py",
    SRC / "controllers" / "truck_controller.py",
    SRC / "services" / "truck_service.py",
    SRC / "schemas" / "truck_schema.py",
    # /api/capture_reject — pola identik: nol pemanggil, dan `internal_controller`
    # sudah memanggil `CaptureService.capture_manual_reject()` langsung lewat
    # `/internal/manual-reject`, yang pakai webhook secret.
    SRC / "routes" / "capture.py",
    SRC / "controllers" / "capture_controller.py",
    SRC / "schemas" / "capture_schema.py",
)

# Yang HARUS tetap ada — supaya tes ini tidak terbaca seperti izin membuang semuanya.
BERKAS_TETAP = (
    SRC / "repositories" / "truck_repository.py",  # dipakai CaptureService
    SRC / "workers" / "runtime_state.py",  # menyimpan current_truck_id
    SRC / "services" / "capture_service.py",  # capture_manual_reject dipakai /internal
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


def test_tidak_ada_rute_publik_tanpa_auth_yang_dihidupkan_lagi():
    """Menangkap endpoint yang dihidupkan lagi di berkas lain, dengan nama lain."""
    bocor = []
    for py in SRC.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        pola = r"""["']/?api/(set_truck|capture_reject)|set_truck_route|capture_reject_route"""
        if re.search(pola, py.read_text(encoding="utf-8")):
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


def test_manual_reject_tetap_ada_lewat_jalur_internal():
    """Yang dibuang rute publiknya, bukan kemampuannya.

    Tolak manual tetap bisa dipicu — lewat `/internal/manual-reject`, yang meminta
    webhook secret. Kalau ini merah, operator kehilangan tombol Tolak.
    """
    internal = (SRC / "controllers" / "internal_controller.py").read_text(encoding="utf-8")

    assert "capture_manual_reject" in internal, "jalur tolak manual ikut terbuang"
