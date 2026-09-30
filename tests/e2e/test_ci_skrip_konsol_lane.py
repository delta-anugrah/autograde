"""Langkah CI "Parse console.html scripts" dijalankan persis seperti di runner (batch 4.3).

Perintahnya dibaca dari `ci.yml`, bukan disalin, lalu dijalankan sebagai proses dari akar
repo: salah ketik jalur atau nama berkas di workflow ketahuan di sini, bukan di PR
berikutnya yang kebetulan merusak konsol.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

AKAR = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada (langkah CI node tetap wajib)")


def _perintah_ci() -> list[str]:
    ci = yaml.safe_load((AKAR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    langkah = next(
        s for s in ci["jobs"]["lint-and-test"]["steps"] if "tests/cek_skrip_konsol.py" in str(s.get("run", ""))
    )
    argv = shlex.split(langkah["run"])
    assert argv[0] == "python"
    return [sys.executable, *argv[1:]]


def _jalankan(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=AKAR, capture_output=True, text=True, timeout=120)


def test_langkah_ci_lolos_untuk_console_html_sekarang():
    hasil = _jalankan(_perintah_ci())
    assert hasil.returncode == 0, hasil.stderr
    assert "OK: 1 blok <script>" in hasil.stdout


def test_langkah_ci_memerahkan_salinan_dengan_kurung_kurawal_tertinggal(tmp_path):
    """Kesalahan yang paling mungkin terjadi saat menyunting: satu `}` hilang di tingkat
    atas. Browser menolak seluruh skrip, jadi langkah ini wajib keluar bukan nol."""
    argv = _perintah_ci()
    asli = (AKAR / argv[-1]).read_text(encoding="utf-8")
    penutup = asli.rindex("</script>")
    rusak = asli[:penutup] + "if (true) {\n" + asli[penutup:]
    salinan = tmp_path / "console.html"
    salinan.write_text(rusak, encoding="utf-8")

    hasil = _jalankan([*argv[:-1], str(salinan)])
    assert hasil.returncode == 1
    assert "RUSAK: console.html blok <script> #1" in hasil.stderr
    assert "SyntaxError" in hasil.stderr
