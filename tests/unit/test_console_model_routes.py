"""Rute layar Support untuk model deteksi — support saja, 400 saat cacat."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_PY = REPO_ROOT / "src" / "palmgrade" / "routes" / "console.py"


def _sumber() -> str:
    return CONSOLE_PY.read_text(encoding="utf-8")


def test_dua_rute_terdaftar():
    isi = _sumber()
    assert '@router.get("/api/console/dev/model-deteksi")' in isi
    assert '@router.post("/api/console/dev/model-deteksi")' in isi


def test_kedua_rute_minta_support():
    isi = _sumber()
    for nama in ("dev_model_deteksi_baca", "dev_model_deteksi_simpan"):
        blok = re.search(rf"async def {nama}\((.*?)\)\s*->", isi, re.S)
        assert blok, f"{nama} tidak ditemukan"
        assert "Support" in blok.group(1), f"{nama} tidak dijaga Support"


def test_simpan_menerjemahkan_model_tidak_sah_jadi_400():
    isi = _sumber()
    blok = re.search(r"async def dev_model_deteksi_simpan.*?(?=\n@router|\Z)", isi, re.S)
    assert blok
    assert "ModelTidakSah" in blok.group(0)
    assert "400" in blok.group(0)
