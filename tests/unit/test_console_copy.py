"""Teks yang dibaca orang: tanpa em dash, tanpa strip sebagai jeda kalimat.

Permintaan user 2026-09-26: em dash (—) dan " - " sebagai jeda membuat teks
terasa ditulis mesin. Kalimat dipecah dengan titik, koma, titik dua, atau kurung.

Yang diperiksa hanya yang sampai ke orang: kamus dua bahasa konsol, teks statis
HTML, string JS di luar kamus, dan pesan exception (jawaban HTTP yang ditampilkan
layar apa adanya, dan terminal teknisi lewat `make operator`). Komentar kode,
docstring, dan log bebas.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

AKAR = Path(__file__).resolve().parents[2]
SRC = AKAR / "src/palmgrade"
HTML = (SRC / "static/console.html").read_text()
KAMUS = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
DASH = ("—", "–")


def _kamus(bahasa: str) -> dict[str, str]:
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", KAMUS, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', blok.group(1)))


def _ada_dash(teks: str) -> bool:
    return any(d in teks for d in DASH)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kamus_tanpa_em_dash(bahasa):
    ada = {k: v for k, v in _kamus(bahasa).items() if _ada_dash(v)}
    assert not ada, ada


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kamus_tanpa_strip_sebagai_jeda(bahasa):
    ada = {k: v for k, v in _kamus(bahasa).items() if " - " in v}
    assert not ada, ada


def test_teks_statis_html_tanpa_em_dash():
    tampil = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", "", HTML, flags=re.S)
    ada = [b.strip() for b in re.sub(r"<[^>]+>", "\n", tampil).splitlines() if _ada_dash(b)]
    assert not ada, ada


def test_string_js_di_luar_kamus_tanpa_em_dash():
    skrip = "\n".join(re.findall(r"<script>(.*?)</script>", HTML, re.S)).replace(KAMUS, "")
    skrip = re.sub(r"/\*.*?\*/", "", skrip, flags=re.S)
    skrip = "\n".join(re.sub(r"(^|\s)//.*$", "", b) for b in skrip.splitlines())
    literal = re.findall(r'"([^"\n]*)"|`([^`]*)`|\'([^\'\n]*)\'', skrip)
    ada = [s for grup in literal for s in grup if s and _ada_dash(s)]
    assert not ada, ada


def test_pesan_exception_tanpa_em_dash():
    ada = []
    for berkas in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(berkas.read_text())):
            if not (isinstance(node, ast.Raise) and node.exc is not None):
                continue
            for sub in ast.walk(node.exc):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _ada_dash(sub.value):
                    ada.append(f"{berkas.relative_to(SRC)}:{sub.lineno} {sub.value[:80]}")
    assert not ada, ada


def test_pesan_lain_yang_tampil_tanpa_em_dash():
    """Dua pesan yang tidak lewat `raise`: galat yang dibawa exception Danger
    Zone sendiri, dan alasan model yang ditulis di tabel Model Deteksi."""
    from palmgrade.domain.bahaya import HapusBerjalan
    from palmgrade.services.model_library import _alasan

    assert not _ada_dash(str(HapusBerjalan()))
    assert not _ada_dash(_alasan(None))
