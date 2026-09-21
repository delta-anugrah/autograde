"""Rute layar Support untuk sumber kamera — support saja, 400 saat cacat."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_PY = REPO_ROOT / "src" / "palmgrade" / "routes" / "console.py"


def _sumber() -> str:
    return CONSOLE_PY.read_text(encoding="utf-8")


def test_dua_rute_terdaftar():
    isi = _sumber()
    assert '@router.get("/api/console/dev/sumber-kamera")' in isi
    assert '@router.post("/api/console/dev/sumber-kamera")' in isi


def test_kedua_rute_minta_support():
    # Satu chokepoint: lane dev mana pun yang lupa `Support` membuka layar
    # developer untuk operator biasa.
    isi = _sumber()
    for nama in ("dev_sumber_kamera_baca", "dev_sumber_kamera_simpan"):
        blok = re.search(rf"async def {nama}\((.*?)\)\s*->", isi, re.S)
        assert blok, f"{nama} tidak ditemukan"
        assert "Support" in blok.group(1), f"{nama} tidak dijaga Support"


def test_simpan_menerjemahkan_sumber_tidak_sah_jadi_400():
    isi = _sumber()
    blok = re.search(r"async def dev_sumber_kamera_simpan.*?(?=\n@router|\Z)", isi, re.S)
    assert blok
    assert "SumberTidakSah" in blok.group(0)
    assert "400" in blok.group(0)
