"""Aturan pilihan model per line dan pemeriksaan kelas model.

Dua-duanya domain murni (tanpa torch/cv2), jadi ikut CI ringan.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.grade_class import periksa_kelas
from palmgrade.domain.pilihan_model import (
    ModelTidakSah,
    bersihkan_nama_model,
    bersihkan_pilihan_model,
)


def test_periksa_kelas_empat_kelas_cocok_tanpa_peduli_huruf():
    assert periksa_kelas(["jk", "Ripe", "TP", "UNRIPE"]) == ([], [])


def test_periksa_kelas_model_lama_menyebut_yang_asing_dan_yang_hilang():
    asing, hilang = periksa_kelas(["ACC", "Rej", "TP"])
    assert asing == ["ACC", "Rej"]
    assert hilang == ["JK", "Ripe", "Unripe"]


def test_periksa_kelas_kosong_berarti_semua_hilang():
    assert periksa_kelas([]) == ([], ["JK", "Ripe", "TP", "Unripe"])


def test_pilihan_sah_dan_bawaan():
    pilihan = {"line-1": "best.pt", "line-2": "", "line-3": " coba.pt "}
    assert bersihkan_pilihan_model(pilihan) == {
        "line-1": "best.pt",
        "line-2": "",
        "line-3": "coba.pt",
    }


@pytest.mark.parametrize(
    "nama", ["../best.pt", "a/b.pt", "a\\b.pt", "best.onnx", "x\n.pt", "x\r.pt", "..pt", ".pt", 5, None]
)
def test_nama_berbahaya_ditolak(nama):
    with pytest.raises(ModelTidakSah):
        bersihkan_nama_model(nama)


def test_nama_kosong_berarti_bawaan():
    assert bersihkan_nama_model("   ") == ""


def test_line_kurang_ditolak():
    with pytest.raises(ModelTidakSah, match="line-2"):
        bersihkan_pilihan_model({"line-1": "", "line-3": ""})


def test_line_asing_ditolak():
    with pytest.raises(ModelTidakSah, match="line-9"):
        bersihkan_pilihan_model({"line-1": "", "line-2": "", "line-3": "", "line-9": ""})


def test_payload_bukan_objek_ditolak():
    with pytest.raises(ModelTidakSah):
        bersihkan_pilihan_model(["best.pt"])


def test_nama_berbahaya_di_dalam_payload_menyebut_line():
    with pytest.raises(ModelTidakSah, match="line-3"):
        bersihkan_pilihan_model({"line-1": "", "line-2": "", "line-3": "../x.pt"})
