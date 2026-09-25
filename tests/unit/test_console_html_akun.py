"""Invarian layar Akun (support) — dijaga sebagai teks, plus render sungguhan lewat node.

Layar ini cuma MEMBACA: tidak ada tombol tambah akun, ganti sandi, atau matikan.
Akun lokal dibuat lewat `scripts/console-operator.py` di PC itu, akun AutoERP di
AutoERP (aturan 19 CLAUDE.md: tidak ada lane web untuk membuat akun).
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
const t = (k) => k;
const lokal = () => "id-ID";
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def _baris(akun: dict) -> str:
    skrip = (
        _STUB
        + _fungsi("tanggalAkun")
        + "\n"
        + _fungsi("barisAkun")
        + f"\nconsole.log(JSON.stringify(barisAkun({json.dumps(akun)})));"
    )
    return json.loads(
        subprocess.run(
            [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
    )


_AKUN = {
    "email": "ani@pks.id",
    "nama": "Ani <script>",
    "role": "support",
    "asal": "erp",
    "keadaan": "aktif",
    "terkunci_detik": 0,
    "sedang_masuk": True,
    "dibuat": 1_758_000_000,
}


def test_tab_akun_ada_dan_ditandai_dev():
    baris = [b for b in HTML.splitlines() if 'data-tab="akun"' in b]
    assert baris, "tombol tab Akun tidak ada"
    assert 'data-dev="1"' in baris[0]


def test_setelan_tetap_tab_paling_kanan():
    """Permintaan operator 2026-09-18: Setelan paling kanan, tab yang paling
    mahal kalau tersenggol. Tab baru masuk SEBELUM Setelan."""
    nav = HTML.split('<nav id="tabs">', 1)[1].split("</nav>", 1)[0]
    tab = re.findall(r'data-tab="([^"]+)"', nav)
    assert tab[-1] == "setelan"
    assert tab.index("akun") == tab.index("versi") + 1


def test_panel_akun_ditandai_dev():
    tag = re.search(r'<section id="sec-akun"[^>]*>', HTML)
    assert tag, "panel sec-akun tidak ada"
    assert 'data-dev="1"' in tag.group(0)


def test_dimuat_saat_tab_dibuka():
    assert "akun: muatAkun" in HTML
    assert '"/api/console/dev/akun"' in HTML


def test_kunci_i18n_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in (
            "judulAkun", "thNama", "thEmail", "thRole", "thAsal", "thSedangMasuk",
            "thDibuat", "akunAktif", "akunMati", "akunTerkunci", "asalLokal",
            "asalErp", "akunYa", "akunCatatanSandi", "kosongAkun", "gagalAkun",
        ):
            assert f"{kunci}:" in isi, f"{bahasa}: {kunci}"


def test_layar_tidak_punya_aksi_tulis():
    """Baca saja. Tombol di layar ini akan jadi lane web untuk mengubah akun —
    persis yang sengaja tidak ada."""
    panel = HTML.split('<section id="sec-akun"', 1)[1].split("</section>", 1)[0]
    assert "<button" not in panel
    assert "<input" not in panel


def test_catatan_sandi_menyebut_dua_tempat_ganti():
    """Pertanyaan pertama yang datang ke layar ini: "user lupa sandi, bisa
    dilihat?". Jawabannya ditulis di layar: tidak, dan gantinya di mana."""
    for bahasa in ("id", "en"):
        catatan = re.search(r'akunCatatanSandi:"([^"]+)"', _kamus(bahasa)).group(1)
        assert "AutoERP" in catatan, bahasa
        assert "console-operator.py" in catatan, bahasa


@butuh_node
def test_nama_dan_email_di_escape():
    html = _baris(_AKUN)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@butuh_node
def test_keadaan_diberi_label_dan_warna():
    aktif = _baris(_AKUN)
    assert "akunAktif" in aktif and 'class="tag ok"' in aktif
    mati = _baris({**_AKUN, "keadaan": "mati"})
    assert "akunMati" in mati and 'class="tag"' in mati
    kunci = _baris({**_AKUN, "keadaan": "terkunci", "terkunci_detik": 125})
    assert "akunTerkunci" in kunci and 'class="tag no"' in kunci


@butuh_node
def test_asal_dan_sedang_masuk():
    html = _baris(_AKUN)
    assert "asalErp" in html
    assert "akunYa" in html
    lokal = _baris({**_AKUN, "asal": "lokal", "sedang_masuk": False})
    assert "asalLokal" in lokal
    assert "akunYa" not in lokal
