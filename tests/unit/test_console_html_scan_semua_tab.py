"""Scan a truck QR from any tab (2026-10-07): a capturing keydown listener collects keys typed
at scanner speed, and Space+1..3 / P+1..3 stay quiet during such a burst (`B 1995 SME`
contains " 1"). The timing rules run in node with a fake clock."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text(
    encoding="utf-8"
)
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

_AWAL = "const JEDA_KETIK_SCANNER_MS"
_AKHIR = 'document.addEventListener("keydown", tangkapScan, true);'


def _blok() -> str:
    return HTML[HTML.index(_AWAL) : HTML.index(_AKHIR)]


def _jalankan(aksi: str):
    skrip = (
        "let ahora = 0; Date.now = () => ahora;\n"
        "const kirim = [];\n"
        "const kirimScanOtomatis = (q) => kirim.push(q);\n"
        "const el = { gerbang: { hidden: true }, 'tirai-pembaruan': { hidden: true } };\n"
        "const $ = (id) => el[id];\n"
        "const document = { querySelector: () => null };\n"
        + _blok()
        + "\nscannerQrAktif = true;\n"
        "const tekan = (key, repeat = false) => { const ev = { key, repeat, target: { closest: () => null },"
        " preventDefault() { this.dicegah = true; } }; tangkapScan(ev); return ev; };\n"
        "const ketik = (teks, jeda) => { for (const c of teks) { tekan(c); ahora += jeda; } };\n"
        + aksi
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
def test_ketikan_10_ms_lalu_enter_mengirim_scan():
    assert _jalankan('ketik("AB 12", 10); const e = tekan("Enter");'
                     "process.stdout.write(JSON.stringify([kirim, e.dicegah === true]));") == [["AB 12"], True]


@butuh_node
def test_ketikan_120_ms_tidak_mengirim_apa_apa():
    assert _jalankan('ketik("AB 12", 120); tekan("Enter");'
                     "process.stdout.write(JSON.stringify(kirim));") == []


@butuh_node
def test_tombol_ditahan_tidak_masuk_buffer():
    assert _jalankan('tekan(" "); for (let i = 0; i < 5; i++) { ahora += 10; tekan(" ", true); }'
                     "process.stdout.write(JSON.stringify([penangkapScan.teks, ledakanScan()]));") == ["", False]


@butuh_node
def test_spasi_lalu_1_oleh_orang_bukan_ledakan():
    assert _jalankan('tekan(" "); ahora += 300; tekan("1");'
                     "process.stdout.write(JSON.stringify(ledakanScan()));") is False


@butuh_node
def test_plat_berspasi_adalah_ledakan_dan_saklar_mati_mengabaikan():
    assert _jalankan('ketik("B 1", 10); process.stdout.write(JSON.stringify(ledakanScan()));') is True
    assert _jalankan('scannerQrAktif = false; ketik("AB 12", 10); tekan("Enter");'
                     "process.stdout.write(JSON.stringify(kirim));") == []


def test_penjaga_ledakan_ada_di_handler_spasi_dan_p():
    assert HTML.count("ledakanScan()") >= 3
    assert "B 1995 SME" in HTML
