"""The console carries its own fonts (F1: no network), as woff2 data URIs written by
`scripts/tanam_font.py` from `assets/fonts/` (spec 2026-10-07 §3)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

AKAR = Path(__file__).resolve().parents[2]
HTML = (AKAR / "src/palmgrade/static/console.html").read_text(encoding="utf-8")
_spec = importlib.util.spec_from_file_location("tanam_font", AKAR / "scripts/tanam_font.py")
tanam_font = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tanam_font)


def test_font_tertanam_sama_dengan_berkasnya():
    assert tanam_font.tanam(HTML) == HTML, "jalankan scripts/tanam_font.py"


def test_empat_font_face_tanpa_jaringan():
    assert HTML.count("@font-face") == 4
    assert "fonts.googleapis" not in HTML and "gstatic" not in HTML


def test_token_font_memakai_font_tertanam():
    root = re.search(r":root\s*\{([^}]*)\}", HTML).group(1)
    assert re.search(r'--font:\s*"Plus Jakarta Sans"', root)
    assert re.search(r'--angka:\s*"Barlow Condensed"', root)
    assert re.search(r'--kode:\s*"DejaVu Sans Mono"', root)
    assert "var(--mono)" not in HTML


def test_lisensi_ofl_ikut_repo():
    for nama in ("OFL-PlusJakartaSans.txt", "OFL-BarlowCondensed.txt"):
        assert "SIL OPEN FONT LICENSE" in (AKAR / "assets/fonts" / nama).read_text(encoding="utf-8").upper()
