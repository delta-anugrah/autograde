"""Berkas yang sudah dipecah karena lewat 1.000 baris tidak boleh tumbuh lagi
(standar mutu batch 1: task yang menyentuh berkas besar memecahnya dulu)."""
from __future__ import annotations

from pathlib import Path

import pytest

AKAR = Path(__file__).resolve().parents[2]
BATAS = 1000
DIJAGA = (
    "src/palmgrade/routes/console.py",
    "src/palmgrade/services/console_service.py",
    "src/palmgrade/repositories/console_repository.py",
)


@pytest.mark.parametrize("relatif", DIJAGA)
def test_berkas_yang_dipecah_tetap_di_bawah_batas(relatif):
    baris = (AKAR / relatif).read_text(encoding="utf-8").count("\n")
    assert baris <= BATAS, f"{relatif}: {baris} baris, pecah dulu sebelum menambah"
