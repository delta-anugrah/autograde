"""Pita "kunci ditolak" per kartu line di console.html — sama pola dengan
`test_console_html_alarm.py`.

INTERNAL_SECRET yang berbeda antara konsol dan satu line membuat line itu
HIDUP tapi menolak `x-internal-secret`. Tanpa pita ini layar cuma bilang
"Offline" (dari jalur terpisah, cek `/api/video_feed` + `/health`), padahal
line bisa saja tetap menggrading dan mengirim event lewat WEBHOOK_SECRET.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def _kamus_blok(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    import re

    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def test_kartu_line_menggambar_pita_kunci():
    fn = HTML.split("function kartuLine(", 1)[1].split("\n}\n", 1)[0]
    assert "pitaKunciDitolak(l)" in fn


def test_pita_kunci_diterjemahkan_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        assert "kartuKunciDitolak:" in _kamus_blok(bahasa), f"KAMUS.{bahasa} belum menerjemahkan kartuKunciDitolak"


def test_pita_kunci_memakai_esc_bukan_innerhtml_mentah():
    fn = HTML.split("function pitaKunciDitolak(", 1)[1].split("\n}\n", 1)[0]
    assert "esc(" in fn


# ── perilaku pitaKunciDitolak: butuh node, skip di CI ──────────────────────

NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _esc_stub() -> str:
    return "const esc = (s) => String(s);\n"


def _jalankan(kartu: dict) -> str:
    import json

    skrip = (
        "const KAMUS={id:{kartuKunciDitolak:'Kunci ditolak. Panggil teknisi.'}};"
        "let bahasa='id'; const t=(k)=>KAMUS[bahasa][k] ?? k;\n"
        + _esc_stub()
        + _fungsi("pitaKunciDitolak")
        + f"\nconsole.log(pitaKunciDitolak({json.dumps(kartu)}));"
    )
    return subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()


@butuh_node
def test_kunci_ditolak_menampilkan_pita():
    hasil = _jalankan({"plc": {"reachable": False, "kode": "line_menolak", "status": 401}})
    assert "pita-kunci" in hasil
    # Tanpa kode HTTP (keputusan user 2026-10-01): WARNING-nya di tab Log.
    assert "401" not in hasil and "HTTP" not in hasil


@butuh_node
def test_line_mati_biasa_tidak_menampilkan_pita():
    hasil = _jalankan({"plc": {"reachable": False, "kode": "line_tidak_menjawab"}})
    assert hasil == ""


@butuh_node
def test_line_sehat_tidak_menampilkan_pita():
    hasil = _jalankan({"plc": {"reachable": True}})
    assert hasil == ""


@butuh_node
def test_line_tanpa_plc_tidak_melempar():
    assert _jalankan({}) == ""
