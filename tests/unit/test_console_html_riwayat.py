"""Invarian layar tab Riwayat: dijaga sebagai teks, plus render sungguhan lewat node.

Tab Riwayat (2026-09-26) membaca grading hari-hari sebelumnya: rentang tanggal
maks 31 hari, filter line/plat/hasil, ringkasan periode, tiga tampilan (per hari,
per truk, per janjang), dan unduh CSV. Operator biasa ikut melihatnya, jadi tab
ini BUKAN tab support.
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
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const kg = (v) => (v === null || v === undefined ? KOSONG : Number(v).toLocaleString(lokal()));
const tagHasil = (s, kelas) => `<span class="tag">${esc(kelas || s)}</span>`;
const waktu = (iso) => String(iso);
let riwayatOffset = 50;
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def _panel() -> str:
    return HTML.split('<section id="sec-riwayat"', 1)[1].split("</section>", 1)[0]


def _node(fungsi: list[str], ekspresi: str):
    skrip = _STUB + "\n".join(_fungsi(f) for f in fungsi) + f"\nconsole.log(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


# ── struktur ──────────────────────────────────────────────────────────────


def test_tab_riwayat_sesudah_rekap_dan_untuk_semua_operator():
    nav = HTML.split('<nav id="tabs">', 1)[1].split("</nav>", 1)[0]
    tab = re.findall(r'data-tab="([^"]+)"', nav)
    assert tab.index("riwayat") == tab.index("rekap") + 1
    tombol = next(b for b in nav.splitlines() if 'data-tab="riwayat"' in b)
    assert "data-dev" not in tombol
    tag = re.search(r'<section id="sec-riwayat"[^>]*>', HTML).group(0)
    assert "data-dev" not in tag


def test_tab_diingat_dan_dimuat_saat_dibuka():
    assert re.search(r'const TAB_SAH = \[[^\]]*"riwayat"', HTML)
    assert "riwayat: muatRiwayat" in HTML


def test_filter_lengkap_ada_di_panel():
    panel = _panel()
    for id_ in ("riwayat-dari", "riwayat-sampai"):
        tag = re.search(rf'<input[^>]*id="{id_}"[^>]*>', panel).group(0)
        assert 'type="date"' in tag, id_
    for id_ in ("riwayat-line", "riwayat-plat", "riwayat-hasil", "riwayat-tampilkan",
                "riwayat-csv", "riwayat-ringkasan", "riwayat-kepala", "riwayat-baris",
                "riwayat-per", "riwayat-prev", "riwayat-next", "riwayat-nomor", "riwayat-rentang"):
        assert f'id="{id_}"' in panel, id_
    assert re.findall(r'data-tampilan="([^"]+)"', panel) == ["hari", "truk", "janjang"]
    assert re.findall(r'data-cepat="([^"]+)"', panel) == ["kemarin", "7hari", "bulanini", "bulanlalu"]


def test_pilihan_hasil_sama_dengan_yang_diterima_server():
    """`HasilRiwayat` di routes/console.py: pilihan lain dijawab 422."""
    blok = _panel().split('id="riwayat-hasil"', 1)[1].split('class="riwayat-aksi"', 1)[0]
    assert re.findall(r'role="option"[^>]*data-nilai="([^"]*)"', blok) == ["", "ripe", "unripe", "jk", "tp"]


def test_saringan_hasil_cuma_tampil_di_tampilan_janjang():
    """Per hari dan per truk menghitung semua janjang; saringan hasil di sana akan
    diabaikan server, jadi tidak boleh terlihat seolah berlaku."""
    assert 'id="riwayat-hasil-grup"' in _panel()
    assert 'riwayatTampilan !== "janjang"' in _fungsi("segarkanTampilanRiwayat")


def test_lane_dan_tombol_yang_menunggu_server_terkunci():
    """Permintaan 2026-09-26: tombol yang butuh waktu diberi spinner dan menolak
    klik kedua. Query sebulan bisa beberapa detik."""
    assert "/api/console/riwayat?" in HTML and "/api/console/riwayat/csv?" in HTML
    for nama in ("tampilkanRiwayat", "unduhRiwayat"):
        assert "denganSibuk(" in _fungsi(nama), nama


def test_jawaban_basi_tidak_menimpa_yang_baru():
    """Klik Per truk lalu Per janjang dengan cepat: jawaban pertama boleh datang
    terakhir, dan tidak boleh menimpa tabel tampilan kedua."""
    fn = _fungsi("muatRiwayat")
    assert "riwayatMinta" in fn


def test_kunci_teks_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in (
            "judulRiwayat", "riwayatDari", "riwayatSampai", "riwayatSemuaLine", "riwayatPlat",
            "riwayatSemuaHasil", "riwayatTampilkan", "riwayatCsv", "riwayatPerHari",
            "riwayatPerTruk", "riwayatPerJanjang", "riwayatKemarin", "riwayat7Hari",
            "riwayatBulanIni", "riwayatBulanLalu", "riwayatLihatTruk", "riwayatLihatJanjang",
            "thTanggal", "thTruk", "thJanjang", "riwayatKosong", "riwayatGagal",
            "riwayatCatatanFoto", "riwayatFotoHilang", "riwayatHari", "riwayatJumlahTruk",
            "riwayatNetoLine", "riwayatMaks",
        ):
            assert f"{kunci}:" in isi, f"{bahasa}: {kunci}"


# ── render lewat node ────────────────────────────────────────────────────


_HARI = {"work_date": "2026-09-24", "total": 4, "acc": 3, "rej": 1, "ripe": 2, "unripe": 1,
         "jk": 1, "tp": 1, "tanpa_kelas": 0, "truk": 2, "neto_kg": 14500.0}


@butuh_node
def test_baris_hari_angka_rasio_neto_dan_tombol_lihat_truk():
    html = _node(["tanggalRiwayat", "rasioRiwayat", "barisRiwayatHari"],
                 f"barisRiwayatHari({json.dumps(_HARI)})")

    assert ">4<" in html and ">75%<" in html
    assert "14.500" in html
    assert 'data-lihat="truk"' in html and 'data-tanggal="2026-09-24"' in html


@butuh_node
def test_baris_hari_tanpa_neto_ditulis_kosong_bukan_nol():
    html = _node(["tanggalRiwayat", "rasioRiwayat", "barisRiwayatHari"],
                 f"barisRiwayatHari({json.dumps({**_HARI, 'neto_kg': None, 'total': 0, 'acc': 0})})")

    assert ">0 kg<" not in html
    assert html.count(">-<") >= 2  # rasio tanpa janjang dan neto kosong


@butuh_node
def test_baris_truk_escape_dan_tombol_lihat_janjang():
    truk = {**_HARI, "truck_id": "t1", "plate_number": "BE <1>", "supplier_name": "PT \"X\"",
            "source_label": "External"}
    html = _node(["tanggalRiwayat", "rasioRiwayat", "barisRiwayatTruk"],
                 f"barisRiwayatTruk({json.dumps(truk)})")

    assert "BE <1>" not in html and "BE &lt;1&gt;" in html
    assert 'data-lihat="janjang"' in html and 'data-plat="BE &lt;1&gt;"' in html


@butuh_node
def test_baris_truk_tanpa_truk_tanpa_tombol_lihat():
    truk = {**_HARI, "truck_id": None, "plate_number": None, "supplier_name": None,
            "source_label": None}
    html = _node(["tanggalRiwayat", "rasioRiwayat", "barisRiwayatTruk"],
                 f"barisRiwayatTruk({json.dumps(truk)})")

    assert "trukTanpaNama" in html
    assert "data-lihat" not in html


@butuh_node
def test_baris_janjang_bernomor_lanjut_halaman_dan_berfoto():
    j = {"event_id": "e1", "work_date": "2026-09-24", "timestamp": "2026-09-24T08:00:00+07:00",
         "line_code": "line-1", "plate_number": "BE 1", "source_label": None,
         "ripeness_status": "ACC", "grade_class": "Ripe",
         "image_url": "/captures/line-1/results/2026-09-24/e1.webp"}
    html = _node(["barisRiwayatJanjang"], f"barisRiwayatJanjang({json.dumps(j)}, 2)")

    assert '<td class="no">53</td>' in html
    assert 'class="foto"' in html and 'data-foto="/captures/line-1/results/2026-09-24/e1.webp"' in html


@butuh_node
def test_rentang_cepat_dihitung_dari_hari_kerja_server():
    hasil = _node(
        ["tambahHari", "rentangCepat"],
        """["kemarin", "7hari", "bulanini", "bulanlalu"].map((k) => rentangCepat(k, "2026-03-01"))""",
    )

    assert hasil == [
        ["2026-02-28", "2026-02-28"],
        ["2026-02-23", "2026-03-01"],
        ["2026-03-01", "2026-03-01"],
        ["2026-02-01", "2026-02-28"],
    ]


@butuh_node
def test_rentang_cepat_akhir_tahun():
    hasil = _node(["tambahHari", "rentangCepat"], 'rentangCepat("bulanlalu", "2026-01-15")')

    assert hasil == ["2025-12-01", "2025-12-31"]
