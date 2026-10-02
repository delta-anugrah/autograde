"""Tab Timbangan dengan empat scan (keputusan user 2026-09-30): satu kolom per tahap,
karena konsol tidak bisa menebak ini scan ke berapa (scan 1 boleh terlewat)."""
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

KUNCI_BARU = (
    "lbDatang", "lbPergi", "phScanDatang", "phScanPergi", "btnDatang", "btnTimbangKosong",
    "btnPergi", "hintPergi", "thAntre", "thTotal", "antreKelewat", "antreKelewatJudul",
    "antreMenunggu", "jamDatang", "jamPergi", "sukDatang", "datangSudah",
    "datangMasihDiDalam", "sukPergi", "pergiBelumKosong", "pergiSudah", "pergiTakAdaTiket",
)

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const t = (k) => ({antreMenunggu: "Menunggu ({n})"}[k] || k);
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _jalankan(ekspresi: str, *fungsi: str):
    skrip = _STUB + "".join(_fungsi(f) for f in fungsi) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def _blok_alat() -> str:
    return HTML.split('<section id="sec-timbangan"', 1)[1].split('<div class="tabel">', 1)[0]


def test_empat_tahap_berurutan_dalam_satu_baris_alat():
    blok = _blok_alat()
    urutan = [blok.index(f'data-t="{k}"') for k in ("lbDatang", "lbGerbangMasuk", "lbGerbangKeluar", "lbPergi")]
    assert urutan == sorted(urutan)
    assert len(re.findall(r'class="tools\b', blok)) == 1


def test_empat_kolom_scan_tersembunyi_sampai_scanner_datang():
    blok = _blok_alat()
    for id_ in ("scan-datang", "scan-plat", "scan-keluar", "scan-pergi"):
        tag = re.search(rf'<input id="{id_}"[^>]*>', blok, re.S)
        assert tag and " hidden" in tag.group(0), f"kolom {id_} hilang atau tampil"


def test_jalan_cadangan_tanpa_scanner():
    blok = _blok_alat()
    assert 'id="plat-datang"' in blok and 'id="datang"' in blok
    assert 'data-aksi="pergi"' in _fungsi("aksiTiket")


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_placeholder_empat_scan_berbeda(bahasa):
    isi = _kamus(bahasa)
    nilai = [re.search(rf'{k}:"([^"]+)"', isi).group(1) for k in ("phScanDatang", "phScan", "phScanKeluar", "phScanPergi")]
    assert len(set(nilai)) == 4


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_baru_ada_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI_BARU:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


def test_kolom_antre_dan_total_di_kepala_tabel():
    kepala = HTML.split('<section id="sec-timbangan"', 1)[1].split("</thead>", 1)[0]
    assert kepala.index('data-t="thAntre"') < kepala.index('data-t="thLama"') < kepala.index('data-t="thTotal"')
    assert "barisKosong(11" in _fungsi("muatTimbangan")


def test_tabel_dan_antrean_timbang_ditulis_aman():
    fn = _fungsi("muatTimbangan")
    assert "tulisKalauBeda(" in fn
    assert '$("antre").textContent' in fn


def test_jalur_gerbang_dipakai_dan_terkunci():
    for nama, jalur in (("kirimDatang", "/api/console/arrivals"), ("kirimPergi", "/api/console/departures")):
        fn = _fungsi(nama)
        assert jalur in fn and "scanSibuk" in fn


def test_jam_gerbang_dari_jam_browser():
    """Sama seperti timbang masuk dan keluar: jam diambil dari browser saat ditekan."""
    for nama in ("kirimDatang", "kirimPergi"):
        assert "new Date().toISOString()" in _fungsi(nama)


def test_plat_datang_selalu_ada_karena_scan_masuk_membangunnya_ulang():
    """`kirimScan` memanggil `muatTrucks()` -> `isiTrucks()`; tanpa `#plat-datang` di
    markup, setiap scan masuk melempar TypeError."""
    assert 'id="plat-datang"' in HTML
    assert '"plat-datang"' in _fungsi("isiTrucks")


@butuh_node
def test_antre_tanpa_scan_1_ditandai_bukan_nol_menit():
    hasil = _jalankan("durasiAntre({tanpa_scan_1:true, antre_menit:null})", "teksMenit", "durasiAntre")
    assert "antreKelewat" in hasil and "0 mnt" not in hasil


@butuh_node
def test_antre_dengan_scan_1_dari_backend():
    assert _jalankan("durasiAntre({tanpa_scan_1:false, antre_menit:25})", "teksMenit", "durasiAntre") == "25 mnt"


@butuh_node
def test_antre_tanpa_angka_jadi_strip():
    assert _jalankan("durasiAntre({tanpa_scan_1:false, antre_menit:null})", "teksMenit", "durasiAntre") == "-"


@butuh_node
def test_tombol_baris_sesuai_tahap():
    assert 'data-aksi="keluar"' in _jalankan("aksiTiket({tare_kg:null})", "aksiTiket")
    assert 'data-aksi="pergi"' in _jalankan("aksiTiket({tare_kg:6000, left_at:null})", "aksiTiket")
    assert _jalankan('aksiTiket({tare_kg:6000, left_at:"2026-09-30T02:10:00Z"})', "aksiTiket") == ""


@butuh_node
def test_teks_antrean_timbang_dari_menit_backend():
    assert _jalankan('teksAntre([{plate_number:"BE 1 AA", menit:40}])', "teksMenit", "teksAntre") == "Menunggu (1): BE 1 AA (40 mnt)"
    assert _jalankan("teksAntre([])", "teksMenit", "teksAntre") == ""


@butuh_node
def test_antrean_timbang_tanpa_menit_jadi_strip_bukan_nol():
    """`menit` null = jam datang tak terbaca atau di masa depan: tidak diketahui, bukan 0."""
    hasil = _jalankan('teksAntre([{plate_number:"BE 1 AA", menit:null}])', "teksMenit", "teksAntre")
    assert hasil == "Menunggu (1): BE 1 AA (-)"
