"""INTERNAL_SECRET harus sampai ke keempat container, di kedua berkas compose.

Override Compose MENGGANTI blok `environment:` (Lampung, Compose v2.40.3), jadi
service yang punya blok environment di `prod` wajib menyebutnya sendiri. Line
dan konsol yang menerima nilai berbeda saling menolak (401) di tiap perintah.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

AKAR = Path(__file__).resolve().parents[2]
BARIS = "- INTERNAL_SECRET=${INTERNAL_SECRET:-}"


def _blok_environment(berkas: Path, service: str) -> list[str] | None:
    baris = berkas.read_text(encoding="utf-8").splitlines()
    mulai = next(n for n, b in enumerate(baris) if re.match(rf"^\s{{2}}{re.escape(service)}:\s*$", b))
    indent = len(baris[mulai]) - len(baris[mulai].lstrip())
    isi: list[str] | None = None
    for b in baris[mulai + 1:]:
        if b.strip() and (len(b) - len(b.lstrip())) <= indent:
            break
        if re.match(r"^\s+environment:", b):
            isi = []
            continue
        if isi is not None:
            if b.strip() and not b.strip().startswith(("-", "#")):
                break
            isi.append(b.strip())
    return isi


@pytest.mark.parametrize("service", ["ripe-line-1", "ripe-line-2", "ripe-line-3", "console"])
def test_compose_dasar_meneruskan_internal_secret(service):
    assert BARIS in (_blok_environment(AKAR / "docker-compose.yml", service) or [])


@pytest.mark.parametrize("service", ["ripe-line-1", "ripe-line-2", "ripe-line-3", "console"])
def test_prod_yang_mengganti_environment_ikut_menyebutnya(service):
    blok = _blok_environment(AKAR / "docker-compose.prod.yml", service)
    if blok is not None:
        assert BARIS in blok


def test_env_example_menjelaskan_internal_secret():
    contoh = (AKAR / ".env.example").read_text(encoding="utf-8")
    assert "\nINTERNAL_SECRET=\n" in contoh
