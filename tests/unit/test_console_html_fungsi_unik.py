"""Every top-level function in console.html has its own name.

A second `function x(` declaration silently replaces the first one for every caller in the
file: no error, no warning. Found 2026-10-03 when two branches each added `namaLineDari`
(one code to a card name, and a list of codes through a map); the auto-assignment toasts
would have called the wrong one and thrown.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def test_tidak_ada_dua_fungsi_bernama_sama():
    nama = re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", HTML, re.M)
    assert len(nama) > 100, "the pattern no longer finds the script's functions"
    ganda = sorted(n for n, jumlah in Counter(nama).items() if jumlah > 1)
    assert not ganda, f"declared more than once (the last one wins silently): {ganda}"
