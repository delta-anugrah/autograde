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
        "const gagal = []; const t = (k) => k;\n"
        "const popupScanGagal = (m) => gagal.push(m);\n"
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


def _keluar(ekspresi: str) -> str:
    return f"process.stdout.write(JSON.stringify({ekspresi}));"


@butuh_node
def test_ketikan_10_ms_lalu_enter_mengirim_scan():
    assert _jalankan('ketik("AB 12", 10); const e = tekan("Enter");' + _keluar("[kirim, e.dicegah === true]")) == [
        ["AB 12"], True]


@butuh_node
def test_satu_jeda_60_ms_tetap_satu_scan_utuh():
    assert _jalankan('ketik("B 19", 10); ahora += 50; ketik("95 SME", 10); tekan("Enter");'
                     + _keluar("kirim")) == ["B 1995 SME"]


@butuh_node
def test_enter_300_ms_sesudah_karakter_terakhir_tetap_terkirim():
    assert _jalankan('ketik("AB 12", 10); ahora += 290; tekan("Enter");' + _keluar("kirim")) == ["AB 12"]


@butuh_node
def test_jeda_150_ms_di_tengah_plat_gagal_dan_enter_ditahan():
    assert _jalankan('ketik("B 19", 10); ahora += 140; ketik("95 SME", 10); const e = tekan("Enter");'
                     + _keluar("[kirim, gagal, e.dicegah === true]")) == [[], ["scanTakTerbaca"], True]


@butuh_node
def test_tanda_gagal_hilang_sesudah_1_detik_diam():
    assert _jalankan('ketik("B 19", 10); ahora += 140; ketik("95", 10); ahora += 1200;'
                     'ketik("AB 12", 10); tekan("Enter");' + _keluar("[kirim, gagal]")) == [["AB 12"], []]


@butuh_node
def test_ketikan_orang_150_ms_tidak_mengirim_dan_enter_tidak_ditahan():
    assert _jalankan('ketik("abc", 150); const e = tekan("Enter");'
                     + _keluar("[kirim, gagal, e.dicegah === true]")) == [[], [], False]


@butuh_node
def test_tombol_ditahan_tidak_masuk_buffer():
    assert _jalankan('tekan(" "); for (let i = 0; i < 5; i++) { ahora += 10; tekan(" ", true); }'
                     + _keluar("[penangkapScan.teks, ledakanScan()]")) == ["", False]


@butuh_node
@pytest.mark.parametrize("awal", [" ", "p"])
def test_spasi_atau_p_lalu_1_oleh_orang_bukan_ledakan(awal):
    # Even a person 40 ms apart has only two characters: the shortcut must still fire.
    assert _jalankan(f'tekan("{awal}"); ahora += 40; tekan("1");' + _keluar("ledakanScan()")) is False


@butuh_node
def test_plat_berspasi_adalah_ledakan_dan_saklar_mati_mengabaikan():
    assert _jalankan('ketik("B 1", 10);' + _keluar("ledakanScan()")) is True
    assert _jalankan('ketik("BP1", 10);' + _keluar("ledakanScan()")) is True
    assert _jalankan('scannerQrAktif = false; ketik("AB 12", 10); tekan("Enter");' + _keluar("kirim")) == []


@butuh_node
def test_tombol_bukan_cetak_di_tengah_ledakan_menjatuhkan_buffer():
    assert _jalankan('ketik("AB", 10); tekan("Tab"); ahora += 10; ketik("12", 10); tekan("Enter");'
                     + _keluar("kirim")) == []


def _badan(awal: str) -> str:
    mulai = HTML.index(awal)
    return HTML[mulai : HTML.index("\n});", mulai)]


def test_penjaga_ledakan_ada_di_handler_spasi_dan_p():
    spasi = _badan('document.addEventListener("keydown", (ev) => {\n  // The gate owns')
    p = _badan('document.addEventListener("keydown", (ev) => {\n  if (ev.target.closest && ev.target.closest("input, textarea, .pilih")) return;\n  if (ev.code === "KeyP")')
    assert "ledakanScan()" in spasi and "B 1995 SME" in spasi
    assert "ledakanScan()" in p and "B 1995 SME" in p
