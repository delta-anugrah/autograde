"""Timbangan rows for Batal datang and "tanpa scan 4" (user 2026-10-03).

A DATANG row carries a red "Batal datang" button that asks once more before it cancels
(like the import undo); a weighed-out visit finished without its Keluar shows a yellow
TANPA SCAN 4 tag where its Keluar button was. The server decides both (standard L4).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const t = (k) => k;
const waktu = (s) => String(s);
"""
KUNCI = ("btnBatalDatang", "batalDatangYakin", "sukBatalDatang", "batalDatangTakAda", "tanpaScan4", "tanpaScan4Judul")


def _fungsi(nama: str) -> str:
    awal = re.search(rf"(async )?function {nama}\(", HTML).start()
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> dict[str, str]:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)
    return dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', blok))


def _jalankan(ekspresi: str, *fungsi: str):
    skrip = _STUB + "".join(_fungsi(f) for f in ("chipPlat", *fungsi)) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_baru_ada_di_kedua_bahasa(bahasa):
    kamus = _kamus(bahasa)
    assert all(kamus.get(k) for k in KUNCI), [k for k in KUNCI if not kamus.get(k)]
    assert "{plat}" in kamus["sukBatalDatang"]


def test_kata_tombol_dan_toast_bahasa_indonesia():
    kamus = _kamus("id")
    assert kamus["btnBatalDatang"] == "Batal datang"
    assert kamus["batalDatangYakin"] == "Yakin? Klik lagi"
    assert kamus["sukBatalDatang"] == "Kedatangan {plat} dibatalkan"
    assert kamus["tanpaScan4"] == "tanpa scan 4"


@butuh_node
def test_baris_datang_membawa_tombol_batal_merah_dengan_id_kedatangan():
    hasil = _jalankan(
        'barisMenunggu({id:"a\\"1<x>", plate_number:"BE 1 AA", arrived_at:"2026-10-03T01:00:00Z",'
        ' menit:5, tahap:"datang"})',
        "teksMenit", "lencanaTahap", "barisMenunggu",
    )
    tombol = re.search(r"<button\b[^>]*>[^<]*</button>", hasil).group(0)
    assert 'class="bahaya"' in tombol and 'data-aksi="batal-datang"' in tombol
    assert 'data-arrival="a&quot;1&lt;x&gt;"' in tombol  # escaped, F7
    assert ">btnBatalDatang<" in tombol


@butuh_node
def test_tiket_tanpa_scan_4_berlabel_kuning_tanpa_tombol_keluar():
    hasil = _jalankan(
        'aksiTiket({tare_kg:6000, left_at:null, tanpa_scan_4:true})', "aksiTiket")
    assert 'class="tag peringatan"' in hasil and ">tanpaScan4<" in hasil
    assert 'title="tanpaScan4Judul"' in hasil
    assert "<button" not in hasil


@butuh_node
def test_tiket_bertara_belum_keluar_tetap_bertombol_keluar():
    hasil = _jalankan('aksiTiket({tare_kg:6000, left_at:null, tanpa_scan_4:false})', "aksiTiket")
    assert 'data-aksi="pergi"' in hasil


def test_batal_datang_dua_klik_sibuk_dan_toast():
    fungsi = _fungsi("batalDatang")
    assert 'classList.add("yakin", "pekat")' in fungsi
    assert 't("batalDatangYakin")' in fungsi
    assert "denganSibuk(" in fungsi
    assert "/api/console/arrivals/${encodeURIComponent(tombol.dataset.arrival)}/cancel" in fungsi
    assert "toastSukses(" in fungsi and "toastPeringatan(" in fungsi
    assert "muatTimbangan()" in fungsi


def test_klik_tabel_menjalankan_batal_datang():
    awal = HTML.index('$("timbangan").addEventListener("click"')
    pemasang = HTML[awal : HTML.index("\n});", awal)]
    assert "button[data-aksi='batal-datang']" in pemasang and "batalDatang(" in pemasang
