"""Timbangan tab polish (user 2026-10-02, after a manual test of PR #214).

TANPA SCAN 1 in the warning colour, a Status badge per row coloured like its step header,
waiting arrivals as rows at the top and as their own section in step 2's plate picker.
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
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _jalankan(ekspresi: str, *fungsi: str, awal: str = ""):
    skrip = _STUB + awal + "".join(_fungsi(f) for f in fungsi) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


# ── U4: TANPA SCAN 1 in the warning colour ──────────────────────────────


def test_tag_tanpa_scan_1_berwarna_peringatan():
    assert re.search(r'class="tag peringatan"', _fungsi("durasiAntre"))
    aturan = re.search(r"\.tag\.peringatan\s*\{([^}]*)\}", HTML)
    assert aturan, "no .tag.peringatan rule"
    for sifat in ("color:var(--warn)", "background:var(--warn-bg)", "border-color:var(--warn)"):
        assert sifat in aturan.group(1).replace(" ", "")


@butuh_node
def test_tag_tanpa_scan_1_tetap_berkata_bukan_cuma_warna():
    hasil = _jalankan("durasiAntre({tanpa_scan_1:true, antre_menit:null})", "teksMenit", "durasiAntre")
    assert 'class="tag peringatan"' in hasil and ">antreKelewat<" in hasil


# ── U2: "2. Timbang isi" picker, waiting trucks first ───────────────────

_TRUK = '[{plate_number:"BE 1 AA"},{plate_number:"BE 2 BB"},{plate_number:"BE 3 CC"}]'
_OPSI = ("opsiPlatTimbang", "kunciPlat", "teksMenit")


@butuh_node
def test_tanpa_truk_menunggu_dropdown_seperti_dulu():
    hasil = _jalankan(f"opsiPlatTimbang({_TRUK}, [])", *_OPSI)
    assert hasil == [{"v": "", "teks": "pilihTruk"}] + [
        {"v": p, "teks": p} for p in ("BE 1 AA", "BE 2 BB", "BE 3 CC")]


@butuh_node
def test_truk_menunggu_di_atas_dengan_menitnya_lalu_truk_lain():
    """Backend order is kept (oldest arrival first); a plate stored normalised (unregistered
    at scan 1, registered since) still finds its truck; no truck is listed twice."""
    menunggu = '[{plate_number:"BE3CC", menit:40}, {plate_number:"BE 1 AA", menit:null}]'
    hasil = _jalankan(f"opsiPlatTimbang({_TRUK}, {menunggu})", *_OPSI)
    assert hasil == [
        {"v": "", "teks": "pilihTruk"},
        {"v": "BE 3 CC", "teks": "BE 3 CC", "catatan": "40 mnt", "grup": "grupMenungguTimbang"},
        {"v": "BE 1 AA", "teks": "BE 1 AA", "catatan": "-", "grup": "grupMenungguTimbang"},
        {"v": "BE 2 BB", "teks": "BE 2 BB", "grup": "grupTrukLain"},
    ]


@butuh_node
def test_truk_menunggu_yang_belum_di_daftar_tetap_muncul_sekali():
    menunggu = '[{plate_number:"BE9ZZ", menit:3}, {plate_number:"BE9ZZ", menit:1}]'
    hasil = _jalankan(f"opsiPlatTimbang({_TRUK}, {menunggu})", *_OPSI)
    assert [o["v"] for o in hasil] == ["", "BE9ZZ", "BE 1 AA", "BE 2 BB", "BE 3 CC"]
    assert hasil[1]["catatan"] == "3 mnt"


@butuh_node
def test_kepala_bagian_bukan_pilihan_dan_menit_tidak_ikut_ke_tombol():
    opsi = ('[{v:"", teks:"Pilih"}, {v:"BE 1 AA", teks:"BE 1 AA", catatan:"5 mnt", grup:"Menunggu"},'
            ' {v:"BE 2 BB", teks:"BE 2 BB", grup:"Lain"}]')
    html = _jalankan(f'komponenPilih({opsi}, "BE 1 AA", "plat-timbang")', "komponenPilih")
    assert html.count('class="pilih-grup"') == 2
    assert re.search(r'<div class="pilih-grup" role="presentation">Menunggu</div>', html)
    assert len(re.findall(r'role="option"', html)) == 3
    assert 'data-teks="BE 1 AA"' in html and '<span class="pilih-catatan">5 mnt</span>' in html
    assert '<span class="pilih-teks">BE 1 AA</span>' in html


def test_tombol_dropdown_memakai_teks_tanpa_menit():
    for nama in ("pilihNilai", "segarkanPilih"):
        assert "dataset.teks" in _fungsi(nama), nama
    assert "panel.firstElementChild" not in _fungsi("bukaPilih"), "a section header is not an option"


def test_dropdown_timbang_isi_ikut_poll_tanpa_mengganggu_operator():
    fn = _fungsi("isiPlatTimbang")
    assert "opsiPlatTimbang(trucks, menungguTimbang)" in fn
    assert 'dataset.buka === "1"' in fn, "never rebuilt while the operator has it open"
    assert "platTimbangTerakhir" in fn, "an unchanged picker is not redrawn"
    assert "isiPlatTimbang()" in _fungsi("isiTrucks")
    assert "isiPlatTimbang()" in _fungsi("muatTimbangan")
    assert "menungguTimbang = " in _fungsi("muatTimbangan")


def test_langkah_1_tidak_berubah():
    assert 'komponenPilih(opsi, datang.dataset.nilai, "plat-datang")' in _fungsi("isiTrucks")


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_dropdown_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    harap = {"id": ("Menunggu timbang", "Truk lain"), "en": ("Waiting to weigh", "Other trucks")}[bahasa]
    assert f'grupMenungguTimbang:"{harap[0]}"' in isi
    assert f'grupTrukLain:"{harap[1]}"' in isi
