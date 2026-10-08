"""Shell of the new look (spec 2026-10-07 §5.1): left rail with icons, a hide button kept per
browser, a header with the view title and status pills, ribbons under the header, the
cameras hidden (never removed) off Grading."""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, jalankan


def test_tab_jadi_rel_kiri_dengan_ikon():
    rel = re.search(r'<nav id="tabs"[^>]*>(.*?)</nav>', HTML, re.S).group(1)
    for tab in ("grading", "truk", "timbangan", "rekap", "log", "status", "akun", "line", "setelan"):
        tombol = re.search(rf'<button data-tab="{tab}"[^>]*>(.*?)</button>', rel, re.S).group(1)
        assert "<svg" in tombol and 'data-t="judul' in tombol, tab
    # The Support divider leaves the DOM with the support tabs for an operator account.
    assert re.search(r'class="rel-pisah"[^>]*data-dev="1"', rel)


def test_tombol_sembunyikan_menu_di_kepala():
    kepala = re.search(r'<header id="topbar">(.*?)</header>', HTML, re.S).group(1)
    assert 'id="menu-samping"' in kepala and 'aria-controls="tabs"' in kepala
    for id_ in ("judul-tampilan", "hari-kerja", "perusahaan", "sinkron-erp", "sinkron-cloud", "info-sistem"):
        assert f'id="{id_}"' in kepala, id_


def test_pita_tepat_di_bawah_kepala():
    for pita in ("pita-pembaruan", "pita-alarm", "pita-disk", "pita-sesi"):
        assert HTML.index(f'id="{pita}"') < HTML.index('<section id="tally">'), pita


def test_lines_disembunyikan_bukan_dibuang_di_tampilan_lain():
    assert re.search(r'body:not\(\[data-tab="grading"\]\)\s*:is\([^)]*#lines[^)]*\)\s*\{\s*display:none', HTML)
    assert 'document.body.dataset.tab = tab' in HTML


def test_menu_samping_diingat_per_browser():
    assert 'baca("menuSamping"' in HTML and 'simpan("menuSamping"' in HTML


def test_tanpa_pil_plc_sampai_line_mengirim_sambungan_plc():
    # Review 2026-10-07: the line status carries piston_requested only, never whether the PLC
    # socket is up, so a "PLC 3/3" pill stayed green with the cable out. No pill until it does.
    assert 'id="pil-plc"' not in HTML and "ringkasPlc" not in HTML


def test_judul_autograde_tanpa_logo_biru():
    # Owner 2026-10-07: the header title is the product, not the view; no blue logo tile.
    kepala = re.search(r'<header id="topbar">(.*?)</header>', HTML, re.S).group(1)
    assert re.search(r'<h1 id="judul-tampilan">AutoGrade</h1>', kepala)
    assert "logo-rel" not in HTML and "logo-kecil" not in HTML
    assert '$("judul-tampilan").textContent' not in HTML


def test_jumlah_kelas_hari_ini_bagi_rata_selebar_kartu():
    assert re.search(r"\.kelas-baris\s*\{[^}]*display:grid;[^}]*grid-template-columns:repeat\(4, minmax\(0, 1fr\)\)", HTML)


def test_tooltip_tombol_menu_tidak_terpotong_di_kiri():
    assert re.search(r'id="menu-samping"[^>]*data-tip-sisi="awal"', HTML)
    assert re.search(r'\[data-tip\]\[data-tip-sisi="awal"\]:is\(:hover, :focus-visible\)::after\s*\{\s*left:0; transform:none;', HTML)


# Owner 2026-10-07: the header in one row. The account (initials, name) and Keluar stand at the
# foot of the rail, as in the mockup; refresh, language and theme are round icon buttons.
def test_akun_dan_keluar_di_kaki_rel():
    rel = re.search(r'<nav id="tabs"[^>]*>(.*?)</nav>', HTML, re.S).group(1)
    kaki = rel[rel.index('class="rel-akun"'):]
    for id_ in ("operator-inisial", "operator-aktif", "keluar"):
        assert f'id="{id_}"' in kaki, id_
    kepala = re.search(r'<header id="topbar">(.*?)</header>', HTML, re.S).group(1)
    assert 'id="keluar"' not in kepala and 'id="operator-aktif"' not in kepala


def test_tombol_kepala_ringkas():
    assert re.search(r'<span id="tema-teks" class="sr-only">', HTML)
    assert re.search(r'<label class="lb sr-only" for="kolom-tombol"', HTML)
    # Only the view buttons get the rail look; Keluar keeps the danger colours (F11).
    assert 'document.querySelectorAll("#tabs button[data-tab]")' in HTML


@pytest.mark.parametrize(("nama", "hasil"), [
    ("Operator Line", "OL"), ("support autograde", "SA"), ("Budi", "BU"), ("  ", ""), (None, ""),
    ("Siti Nur Aisyah", "SN"),
])
def test_inisial_nama(nama, hasil):
    if NODE is None:
        pytest.skip("node tidak ada")
    assert jalankan(["inisialNama"], f"inisialNama({json.dumps(nama)})") == hasil


def test_hidden_rail_leaves_the_tab_order():
    """Review #256: a rail slid to 0 px still took Tab presses. `visibility:hidden` takes its
    buttons out of the Tab order once the slide ends."""
    css = re.search(r"body\.menu-tutup #tabs \{([^}]*)\}", HTML).group(1)
    assert "visibility:hidden" in css


@pytest.mark.parametrize("pemilih", [".truk-grup button", ".antrean-aksi button"])
def test_truck_card_buttons_are_44px(pemilih):
    """Review #256: Lepas on the truck card and the queue buttons were 34-36 px."""
    aturan = re.search(re.escape(pemilih) + r" \{([^}]*)\}", HTML).group(1)
    assert "min-height:44px" in aturan


def test_escape_closes_the_more_menu():
    kerja = re.search(r"function tutupMenuLagi\(\) \{(.*?)\n\}", HTML, re.S).group(1)
    assert 'details.lagi[open]' in kerja and "open = false" in kerja
    assert re.search(r'ev\.key === "Escape" && tutupMenuLagi\(\)', HTML)
