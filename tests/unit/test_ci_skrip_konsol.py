"""CI memparse seluruh `<script>` `console.html` dan suite unit melaporkan alasan skip (batch 4.3).

Test konsol lain menyalin satu fungsi lalu menjalankannya di node, jadi syntax error di luar
fungsi itu lolos semua test sementara browser menolak seluruh skrip dan layar operator kosong.
"""
from __future__ import annotations

from pathlib import Path

import yaml

CI = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
)
LANGKAH_CI = CI["jobs"]["lint-and-test"]["steps"]


def _indeks_langkah(awalan_run: str) -> int:
    return next(i for i, s in enumerate(LANGKAH_CI) if str(s.get("run", "")).startswith(awalan_run))


def test_ci_memparse_seluruh_skrip_console_html():
    langkah = LANGKAH_CI[_indeks_langkah("python tests/cek_skrip_konsol.py")]
    assert langkah["run"] == "python tests/cek_skrip_konsol.py src/palmgrade/static/console.html"


def test_parse_skrip_jalan_sebelum_pytest_unit():
    """Satu detik, jadi layar yang pasti kosong ketahuan sebelum menunggu suite unit."""
    assert _indeks_langkah("python tests/cek_skrip_konsol.py") < _indeks_langkah("pytest tests/unit/")


def test_pytest_unit_melaporkan_alasan_skip():
    assert LANGKAH_CI[_indeks_langkah("pytest tests/unit/")]["run"] == "pytest tests/unit/ -rs"


def test_main_py_diperiksa_nama_tak_terdefinisi():
    """Batch 3 menyunting blok impor `main.py` dari tiga cabang: impor yang hilang saat merge
    mematikan tiap line saat boot sementara CI hijau. Sejak batch 4.4 ruff memeriksa seluruh
    `src/` dengan aturan `F` (termasuk F821, nama tak terdefinisi), sebelum suite unit."""
    langkah = LANGKAH_CI[_indeks_langkah("ruff check")]
    assert langkah["run"].startswith("ruff check src/ tests/")
    assert _indeks_langkah("ruff check") < _indeks_langkah("pytest tests/unit/")
