"""Aturan berkas bukti yang utuh (batch 2.6). Murni."""
from __future__ import annotations

from palmgrade.domain.berkas_captures import boleh_disajikan
from palmgrade.domain.berkas_utuh import alasan_tidak_utuh, berkas_sementara, nama_sementara

NAMA = "2026-09-28_091432_123456_auto.webp"


def test_nama_sementara_dikenali_sebagai_sementara():
    assert berkas_sementara(nama_sementara(NAMA, "a1b2c3d4"))
    assert not berkas_sementara(NAMA)


def test_nama_sementara_tidak_pernah_cocok_dengan_pola_pembaca():
    """`_scan()` mencari `*_ripeness.json`, `list_json_files` mencari `*.json`,
    dan `/captures` menolak berkas tersembunyi."""
    sidecar = nama_sementara("2026-09-28_091432_123456_auto_ripeness.json", "a1b2c3d4")
    assert not sidecar.endswith("_ripeness.json")
    assert not sidecar.endswith(".json")
    assert not boleh_disajikan(f"results/2026-09-28/{nama_sementara(NAMA, 'a1b2c3d4')}")


def test_berkas_kosong_tidak_utuh():
    assert alasan_tidak_utuh(NAMA, 0) is not None
    assert "0 byte" in alasan_tidak_utuh(NAMA, 0)


def test_sisa_sementara_tidak_utuh_walau_berisi():
    assert alasan_tidak_utuh(nama_sementara(NAMA, "a1b2c3d4"), 4096) is not None


def test_berkas_berisi_dengan_nama_akhir_utuh():
    assert alasan_tidak_utuh(NAMA, 1) is None
