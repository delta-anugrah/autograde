"""Dokumen markdown repo ini: tanpa em dash, dan frontmatter-nya tetap YAML yang sah.

Permintaan user 2026-09-26, lanjutan aturan teks layar (`test_console_copy.py`):
em dash membuat tulisan terasa ditulis mesin. Blok kode dan kode inline tidak
diperiksa: di sana ada kutipan log dan kode yang harus tetap persis.

Frontmatter ikut dijaga karena pengganti em dash yang paling wajar, titik dua,
merusak YAML: `description: A: B` gagal di-parse, dan skill dengan frontmatter
rusak berhenti termuat tanpa satu pun galat di repo ini (hampir terjadi di tiga
skill waktu dokumen disapu).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

AKAR = Path(__file__).resolve().parents[2]
KODE_INLINE = re.compile(r"(`+)(?:(?!\1).)+?\1")


def _markdown() -> list[Path]:
    keluar = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=AKAR, capture_output=True, text=True, check=True
    ).stdout.split()
    return [AKAR / f for f in keluar if not (AKAR / f).is_symlink()]


BERKAS = _markdown()


def _em_dash_di_luar_kode(teks: str) -> list[str]:
    ada, dalam_kode = [], False
    for baris in teks.split("\n"):
        if baris.lstrip().startswith("```"):
            dalam_kode = not dalam_kode
            continue
        if not dalam_kode and "—" in KODE_INLINE.sub("", baris):
            ada.append(baris.strip()[:100])
    return ada


def test_ada_dokumen_yang_diperiksa():
    assert len(BERKAS) > 20


@pytest.mark.parametrize("berkas", BERKAS, ids=lambda p: str(p.relative_to(AKAR)))
def test_tanpa_em_dash(berkas):
    ada = _em_dash_di_luar_kode(berkas.read_text())
    assert not ada, ada


@pytest.mark.parametrize(
    "berkas",
    [p for p in BERKAS if p.read_text().startswith("---\n")],
    ids=lambda p: str(p.relative_to(AKAR)),
)
def test_frontmatter_tetap_yaml_sah(berkas):
    frontmatter = berkas.read_text().split("---\n", 2)[1]
    assert isinstance(yaml.safe_load(frontmatter), dict)
