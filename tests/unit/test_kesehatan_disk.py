"""Aturan sisa disk (batch 3.7), murni tanpa I/O.

Dua arah yang mahal kalau salah: diam sampai disk habis (grading berhenti
tersimpan), dan alert yang muncul-hilang tiap menit di sekitar ambang (alarm
yang diajari untuk diabaikan). Tiap sisi punya test sendiri.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.kesehatan_disk import (
    GB,
    HISTERESIS_GB,
    KODE_DISK_HAMPIR_PENUH,
    KODE_DISK_KRITIS,
    KRITIS_BAWAAN_GB,
    PERINGATAN_BAWAAN_GB,
    TingkatDisk,
    UkuranDisk,
    gb_dari_teks,
    ke_kawat,
    nilai_disk,
    peringatan_menyala_terus,
    tersempit,
)

A, P, K = TingkatDisk.AMAN, TingkatDisk.PERINGATAN, TingkatDisk.KRITIS


def _nilai(bebas_gb: float, sebelumnya: TingkatDisk = A) -> TingkatDisk:
    return nilai_disk(bebas_gb, peringatan_gb=15, kritis_gb=5, sebelumnya=sebelumnya)


def test_bawaan_di_bawah_lantai_retensi_r2():
    """Penjaga retensi R2 menjaga sisa disk di sekitar 20 GB: peringatan bawaan
    harus di bawahnya, kalau tidak alert menyala terus di keadaan normal."""
    assert KRITIS_BAWAAN_GB < PERINGATAN_BAWAAN_GB < 20


@pytest.mark.parametrize(
    ("bebas", "tingkat"),
    [(232, A), (15, A), (14.9, P), (5, P), (4.9, K), (0, K)],
)
def test_tingkat_dari_sisa_disk(bebas, tingkat):
    assert _nilai(bebas) is tingkat


def test_keluar_dari_peringatan_butuh_histeresis():
    assert _nilai(15.5, sebelumnya=P) is P
    assert _nilai(15 + HISTERESIS_GB, sebelumnya=P) is A


def test_keluar_dari_kritis_butuh_histeresis_dan_turun_ke_peringatan_dulu():
    assert _nilai(5.5, sebelumnya=K) is K
    assert _nilai(6.0, sebelumnya=K) is P
    assert _nilai(15.5, sebelumnya=K) is P
    assert _nilai(16.0, sebelumnya=K) is A


def test_ambang_nol_mematikan_tingkatnya():
    assert nilai_disk(1, peringatan_gb=0, kritis_gb=0, sebelumnya=A) is A
    assert nilai_disk(10, peringatan_gb=0, kritis_gb=5, sebelumnya=A) is A
    assert nilai_disk(4, peringatan_gb=0, kritis_gb=5, sebelumnya=A) is K


def test_partisi_tersempit_yang_dinilai():
    lega = UkuranDisk("/app/artifacts", total=500 * GB, bebas=200 * GB)
    sempit = UkuranDisk("/app/state", total=50 * GB, bebas=3 * GB)
    assert tersempit([lega, sempit]) is sempit
    assert tersempit([]) is None


def test_kawat_peringatan():
    u = UkuranDisk("/app/artifacts", total=468 * GB, bebas=int(12.34 * GB))
    kawat = ke_kawat(P, u, peringatan_gb=15, kritis_gb=5, sejak=1_790_000_000.0)
    assert kawat == {
        "tingkat": "peringatan", "kode": KODE_DISK_HAMPIR_PENUH, "bebas_gb": 12.3,
        "total_gb": 468.0, "persen_bebas": 2.6, "jalur": "/app/artifacts",
        "ambang_peringatan_gb": 15, "ambang_kritis_gb": 5, "sejak": 1_790_000_000.0,
    }


def test_kawat_kritis_dan_aman():
    u = UkuranDisk("/app/artifacts", total=468 * GB, bebas=2 * GB)
    assert ke_kawat(K, u, peringatan_gb=15, kritis_gb=5, sejak=1.0)["kode"] == KODE_DISK_KRITIS
    assert ke_kawat(A, u, peringatan_gb=15, kritis_gb=5, sejak=None)["kode"] is None


def test_kawat_tidak_terbaca_tanpa_angka():
    kawat = ke_kawat(TingkatDisk.TIDAK_TERBACA, None, peringatan_gb=15, kritis_gb=5, sejak=None)
    assert (kawat["tingkat"], kawat["bebas_gb"], kawat["persen_bebas"], kawat["kode"]) == (
        "tidak_terbaca", None, None, None
    )


@pytest.mark.parametrize(
    ("teks", "gb"),
    [(None, 15.0), ("", 15.0), ("  ", 15.0), ("30", 30.0), ("7.5", 7.5), ("7,5", 7.5),
     ("0", 0.0), ("-1", None), ("lima belas", None), ("15GB", None)],
)
def test_gb_dari_env(teks, gb):
    assert gb_dari_teks(teks, 15.0) == gb


def test_peringatan_menyala_terus_hanya_kalau_r2_dan_ambang_setinggi_lantai():
    assert peringatan_menyala_terus(20, lantai_retensi_gb=20, r2_aktif=True) is True
    assert peringatan_menyala_terus(15, lantai_retensi_gb=20, r2_aktif=True) is False
    assert peringatan_menyala_terus(30, lantai_retensi_gb=20, r2_aktif=False) is False
    assert peringatan_menyala_terus(30, lantai_retensi_gb=0, r2_aktif=True) is False
