"""Teks yang dibaca orang: tanpa em dash, tanpa strip sebagai jeda kalimat.

Permintaan user 2026-09-26: em dash (—) dan " - " sebagai jeda membuat teks
terasa ditulis mesin. Kalimat dipecah dengan titik, koma, titik dua, atau kurung.

Yang diperiksa hanya yang sampai ke orang: kamus dua bahasa konsol, teks statis
HTML, string JS di luar kamus, pesan exception (terminal teknisi lewat `make
operator`, dan log), dan pesan log, yang sejak batch 3 tampil di tab Log
(2026-10-01). Komentar kode dan docstring bebas.
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


_LEVEL_LOG = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def test_pesan_log_tanpa_em_dash():
    """Log messages reach the screen in the Log tab (batch 3.2): same copy rule as KAMUS."""
    ada = []
    for berkas in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(berkas.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _LEVEL_LOG and node.args):
                continue
            pesan = node.args[1] if node.func.attr == "log" and len(node.args) > 1 else node.args[0]
            for sub in ast.walk(pesan):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _ada_dash(sub.value):
                    ada.append(f"{berkas.relative_to(SRC)}:{sub.lineno} {sub.value[:80]}")
    assert not ada, ada


def test_kalimat_layar_hanya_dari_kamus():
    """Ketemu tes browser 2026-10-01: "Belum sampai ke:" di tab Setelan ditulis langsung
    di JS, jadi layar berbahasa Inggris tetap menampilkan bahasa Indonesia di situ (F6).
    Kalimat yang dibaca orang hanya boleh datang dari KAMUS; yang dicari di sini string JS
    yang terbaca seperti kalimat: kata berawalan huruf besar lalu kata biasa."""
    skrip = "\n".join(re.findall(r"<script>(.*?)</script>", HTML, re.S)).replace(KAMUS, "")
    skrip = re.sub(r"/\*.*?\*/", "", skrip, flags=re.S)
    skrip = "\n".join(re.sub(r"(^|\s)//.*$", "", b) for b in skrip.splitlines())
    literal = re.findall(r'"([^"\n]*)"|`([^`]*)`|\'([^\'\n]*)\'', skrip)
    kalimat = []
    for s in (s for grup in literal for s in grup if s):
        polos = re.sub(r"<[^>]+>", " ", re.sub(r"\$\{[^}]*\}", " ", s))
        if re.search(r"\b[A-Z][a-z]+ [a-z]{2,}\b", polos):
            kalimat.append(s.strip()[:80])
    assert not kalimat, kalimat


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_petunjuk_gerbang_keluar_menyebut_tombol_yang_ada_di_baris(bahasa):
    """Petunjuk di sisi Truk keluar menyuruh menekan tombol di baris tiket; kata yang dipakai
    harus tulisan tombol itu sendiri (`btnKeluar`), bukan kata lain yang tidak ada di layar."""
    kamus = _kamus(bahasa)
    assert kamus["btnKeluar"] in kamus["hintGerbangKeluar"], (kamus["btnKeluar"], kamus["hintGerbangKeluar"])
