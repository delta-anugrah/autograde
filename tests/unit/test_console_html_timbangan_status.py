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
    skrip = _STUB + awal + "".join(_fungsi(f) for f in ("chipPlat", *fungsi)) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
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
def test_truk_menunggu_yang_belum_terdaftar_tidak_ditawarkan():
    """Ruling 2026-10-02: step 2 offers registered trucks only, as before. An unregistered
    arrival stays visible as a "Datang" row in the table, never as a pick here."""
    hanya_asing = _jalankan(f'opsiPlatTimbang({_TRUK}, [{{plate_number:"BE9ZZ", menit:3}}])', *_OPSI)
    assert hanya_asing == _jalankan(f"opsiPlatTimbang({_TRUK}, [])", *_OPSI)
    menunggu = '[{plate_number:"BE9ZZ", menit:3}, {plate_number:"BE 3 CC", menit:1}, {plate_number:"BE3CC", menit:0}]'
    hasil = _jalankan(f"opsiPlatTimbang({_TRUK}, {menunggu})", *_OPSI)
    assert [o["v"] for o in hasil] == ["", "BE 3 CC", "BE 1 AA", "BE 2 BB"]
    assert hasil[1]["catatan"] == "1 mnt"


@butuh_node
def test_kepala_bagian_bukan_pilihan_dan_menit_tidak_ikut_ke_tombol():
    opsi = ('[{v:"", teks:"Pilih"}, {v:"BE 1 AA", teks:"BE 1 AA", catatan:"5 mnt", grup:"Menunggu"},'
            ' {v:"BE 2 BB", teks:"BE 2 BB", grup:"Lain"}]')
    html = _jalankan(f'komponenPilih({opsi}, "BE 1 AA", "plat-timbang")', "barisPilih", "komponenPilih")
    assert html.count('class="pilih-grup"') == 2
    assert re.search(r'<div class="pilih-grup" role="presentation">Menunggu</div>', html)
    assert len(re.findall(r'role="option"', html)) == 3
    assert 'data-teks="BE 1 AA"' in html and '<span class="pilih-catatan">5 mnt</span>' in html
    assert '<span class="pilih-teks">BE 1 AA</span>' in html


def test_tombol_dropdown_memakai_teks_tanpa_menit():
    for nama in ("aturPilih", "segarkanPilih"):
        assert "dataset.teks" in _fungsi(nama), nama
    assert "panel.firstElementChild" not in _fungsi("bukaPilih"), "a section header is not an option"


def test_dropdown_timbang_isi_ikut_poll_tanpa_mengganggu_operator():
    fn = _fungsi("isiPlatTimbang")
    assert "opsiPlatTimbang(trucks, menungguTimbang)" in fn
    # Batch 5.6: the rows are refilled in place, so the trigger (and its focus) is never replaced.
    assert "isiUlangPilih(" in fn and "outerHTML" not in fn
    isi_ulang = _fungsi("isiUlangPilih")
    assert 'dataset.buka === "1"' in isi_ulang, "never rebuilt while the operator has it open"
    assert "tulisKalauBeda(" in isi_ulang, "an unchanged picker is not redrawn"
    assert "isiPlatTimbang()" in _fungsi("isiTrucks")
    assert "isiPlatTimbang()" in _fungsi("muatTimbangan")
    assert "menungguTimbang = " in _fungsi("muatTimbangan")


def test_langkah_1_tidak_berubah():
    assert 'isiUlangPilih($("plat-datang"), opsi)' in _fungsi("isiTrucks")


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_dropdown_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    harap = {"id": ("Menunggu timbang", "Truk lain"), "en": ("Waiting to weigh", "Other trucks")}[bahasa]
    assert f'grupMenungguTimbang:"{harap[0]}"' in isi
    assert f'grupTrukLain:"{harap[1]}"' in isi


# ── U5: Status badge per row, step headers in the same colours ──────────

_TAHAP = {  # stage from the backend -> CSS class, KAMUS key
    "datang": ("tahap-datang", "tahapDatang"),
    "bongkar": ("tahap-bongkar", "tahapBongkar"),
    "timbang_kosong": ("tahap-kosong", "tahapTimbangKosong"),
    "selesai": ("tahap-selesai", "tahapSelesai"),
}
_LANGKAH = {"lbDatang": "tahap-datang", "lbGerbangMasuk": "tahap-bongkar",
            "lbGerbangKeluar": "tahap-kosong", "lbPergi": "tahap-selesai"}


def _kepala_tabel() -> str:
    return HTML.split('<section id="sec-timbangan"', 1)[1].split("</thead>", 1)[0].split("<thead>", 1)[1]


def test_kolom_status_paling_kiri_dua_belas_kolom():
    kepala = _kepala_tabel()
    assert len(re.findall(r"<th\b", kepala)) == 12
    assert re.search(r"<tr><th data-t=\"thStatus\">", kepala), "Status is the FIRST column"
    assert "barisKosong(12" in _fungsi("muatTimbangan") and "barisKosong(11" not in _fungsi("muatTimbangan")


@butuh_node
@pytest.mark.parametrize("tahap", sorted(_TAHAP))
def test_lencana_tahap_berwarna_dan_berkata(tahap):
    kelas, kunci = _TAHAP[tahap]
    html = _jalankan(f'lencanaTahap("{tahap}")', "lencanaTahap")
    assert f'class="lencana {kelas}"' in html and f">{kunci}<" in html


@butuh_node
def test_lencana_membawa_keempat_kata_untuk_lebar_yang_sama():
    """User 2026-10-03: every Status badge as wide as the widest word, in the screen's language.
    The four words ride in `data-ukur`, one per line, drawn by an invisible zero-height
    `::after`; the badge's own text stays the one word."""
    html = _jalankan('lencanaTahap("selesai")', "lencanaTahap")
    ukur = re.search(r'data-ukur="([^"]*)"', html).group(1)
    assert ukur.split("\n") == ["tahapDatang", "tahapBongkar", "tahapTimbangKosong", "tahapSelesai"]
    assert html.endswith(">tahapSelesai</span>")


def test_lencana_lebar_dari_pseudo_elemen_tak_terlihat():
    aturan = re.search(r"\.lencana::after \{([^}]*)\}", HTML)
    assert aturan, "no .lencana::after rule"
    isi = aturan.group(1).replace(" ", "")
    for sifat in ("content:attr(data-ukur)", "height:0", "visibility:hidden", "white-space:pre"):
        assert sifat in isi, sifat
    lencana = re.search(r"\n  \.lencana \{([^}]*)\}", HTML).group(1).replace(" ", "")
    assert "align-items:center" in lencana


@butuh_node
def test_tahap_tak_dikenal_jadi_strip_bukan_tebakan():
    assert _jalankan('lencanaTahap("aneh")', "lencanaTahap") == "-"
    assert _jalankan("lencanaTahap(undefined)", "lencanaTahap") == "-"


@butuh_node
def test_baris_tiket_diawali_lencana_dua_belas_sel():
    awal = "const waktu = (x) => x; const kg = (x) => String(x ?? '-'); const lamaProses = () => null;"
    html = _jalankan(
        '[barisTimbangan({id:"w1", plate_number:"BE 1 AA", tahap:"bongkar", tare_kg:null, gross_kg:14000}),'
        ' barisMenunggu({plate_number:"BE 2 BB", arrived_at:"2026-10-02T01:00:00Z", menit:7, tahap:"datang"})]',
        "barisTimbangan", "durasiAntre", "teksMenit", "aksiTiket", "tandaErp", "lencanaTahap", "barisMenunggu",
        awal=awal,
    )
    for baris, kelas in zip(html, ("tahap-bongkar", "tahap-datang"), strict=True):
        sel = re.findall(r"<td\b[^>]*>(.*?)</td>", baris, re.S)
        assert len(sel) == 12, baris
        assert kelas in sel[0]
    menunggu = re.findall(r"<td\b[^>]*>(.*?)</td>", html[1], re.S)
    assert menunggu[3] == "7 mnt" and menunggu[6] == '<b class="plat">BE 2 BB</b>'
    # No ticket yet: no weighing button and no ticket id. Its one button is Batal datang (2026-10-03).
    assert re.findall(r"data-aksi=\"([\w-]+)\"", html[1]) == ["batal-datang"] and "data-id" not in html[1]


def test_yang_menunggu_jadi_baris_paling_atas():
    fn = _fungsi("muatTimbangan")
    assert re.search(r"menungguTimbang\.map\(barisMenunggu\)[\s\S]*items\.map\(barisTimbangan\)", fn)


@pytest.mark.parametrize("kunci, kelas", sorted(_LANGKAH.items()))
def test_judul_langkah_berwarna_seperti_lencananya(kunci, kelas):
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split('<div class="tabel">', 1)[0]
    label = re.search(rf'<label class="([^"]*)"[^>]*data-t="{kunci}"', blok)
    assert label and kelas in label.group(1).split(), kunci


def test_warna_tahap_dari_token_tema_dua_tema():
    for kelas, token in (("tahap-datang", "--muted"), ("tahap-bongkar", "--warn"),
                         ("tahap-kosong", "--info"), ("tahap-selesai", "--acc")):
        aturan = re.search(rf"\.{kelas}\s*\{{([^}}]*)\}}", HTML)
        assert aturan and f"color:var({token})" in aturan.group(1).replace(" ", ""), kelas
    terang = HTML.split(":root { color-scheme:light;", 1)[1].split("}", 1)[0]
    gelap = HTML.split(':root[data-theme="dark"] { color-scheme:dark;', 1)[1].split("}", 1)[0]
    for blok in (terang, gelap):
        assert "--info:" in blok and "--info-bg:" in blok


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_status_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    harap = {
        "id": {"thStatus": "Status", "tahapDatang": "Datang", "tahapBongkar": "Bongkar",
               "tahapTimbangKosong": "Timbang kosong", "tahapSelesai": "Selesai"},
        "en": {"thStatus": "Status", "tahapDatang": "Arrived", "tahapBongkar": "Unloading",
               "tahapTimbangKosong": "Weighed out", "tahapSelesai": "Done"},
    }[bahasa]
    for kunci, teks in harap.items():
        assert f'{kunci}:"{teks}"' in isi, kunci


def test_petunjuk_desimal_di_bawah_kedua_form_dan_di_kolom_bruto():
    """User 2026-10-03: di dalam form 2 petunjuk itu membuat form 2 lebih tinggi dari form 1.
    Kini satu baris di bawah kedua form, dan `title` kolom Bruto."""
    blok = HTML.split('<section id="sec-timbangan"', 1)[1].split('<div class="tabel">', 1)[0]
    assert blok.count('data-t="hintDesimal"') == 1
    form = blok.split('class="timbang-form ruas-bongkar', 1)[1].split('<p class="catatan timbang-kaki', 1)[0]
    assert 'data-t="hintDesimal"' not in form
    bruto = re.search(r'<input id="bruto"[^>]*>', blok).group(0)
    assert 'data-t-title="hintDesimal"' in bruto and 'aria-describedby="bruto-petunjuk"' in bruto
    assert re.search(r'<span\s+id="bruto-petunjuk" data-t="hintDesimal"', blok)
    assert 'querySelectorAll("[data-t-title]")' in HTML


def test_escape_operator_tidak_melempar_galat():
    """`#plc-konfirmasi` sits in the support-only Line tab, removed for an operator."""
    awal = HTML.index('document.addEventListener("keydown", (ev) => {\n  const dialog = $("plc-konfirmasi");')
    blok = HTML[awal : HTML.index("\n});", awal)]
    assert "dialog && !dialog.hidden" in blok
    assert '!$("plc-konfirmasi").hidden' not in HTML
