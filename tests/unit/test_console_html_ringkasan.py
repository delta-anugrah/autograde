"""Summary row of the Grading view (spec 2026-10-07 §5.2): the day card with its class bar,
the live scale card (rolling digits, a 24-reading trace, a hint per backend state) and the
truck card (the truck on the lines, then the unloading queue)."""
from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
_DOM = """
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const kg = (v) => (v === null || v === undefined ? KOSONG : Number(v).toLocaleString(lokal()));
const document = { hidden: false };
const gerakDikurangi = () => false;
const JEJAK_TIMBANG_N = 24;
const buatEl = () => {
  const el = { tulis: 0 }; let teks = "", html = "";
  Object.defineProperty(el, "textContent", { get: () => teks, set: (v) => { el.tulis += 1; teks = String(v); html = teks; } });
  Object.defineProperty(el, "innerHTML", { get: () => html, set: (v) => { el.tulis += 1; html = v; teks = (v.match(/<span class="odo-baca">([^<]*)<\/span>/) || [, ""])[1]; } });
  return el;
};
"""
_FN = ["lebarKelas", "htmlBarKelas", "tulisBerat", "odometerBerat", "kolomOdometer",
       "catatJejak", "htmlJejak", "trukDiLine", "htmlTrukDiLine"]


def _js(expr):
    return jalankan(_FN, expr, tambahan=_DOM)


@butuh_node
def test_lebar_kelas_dalam_persen():
    assert _js("lebarKelas(80, 15, 5)") == [80, 15, 5]
    assert _js("lebarKelas(0, 0, 0)") == [0, 0, 0]
    assert _js("lebarKelas(1, 2, 0)") == [33.3, 66.7, 0]


@butuh_node
@pytest.mark.parametrize("v", [21640.5, -120, None])
def test_berat_bukan_bulat_positif_jadi_teks_biasa(v):
    arg = "null" if v is None else v
    hasil = _js(f"(() => {{ const el = buatEl(); tulisBerat(el, 100); tulisBerat(el, {arg});"
                " return [el.textContent, el.innerHTML]; })()")
    teks = "-" if v is None else f"{_js(f'kg({arg})')} kg"
    assert hasil[0] == teks
    assert "odo" not in hasil[1]


@butuh_node
def test_berat_bulat_bergulir_dan_teksnya_tetap_terbaca():
    html = _js("(() => { const el = buatEl(); tulisBerat(el, 0); tulisBerat(el, 21640); return el.innerHTML; })()")
    assert '<span class="odo-baca">21.640 kg</span>' in html
    assert len(re.findall(r'class="odo-d[ "]', html)) == 5 and 'data-c="kg"' in html
    # Separators and the unit are drawn by CSS (`data-c`), so they add nothing to textContent.
    assert re.search(r'<span class="odo-pisah[^"]*" data-c="\."></span>', html)


@butuh_node
def test_berat_sama_tidak_menulis_ulang():
    hasil = _js("(() => { const el = buatEl(); tulisBerat(el, 500); tulisBerat(el, 500); return el.tulis; })()")
    assert hasil == 1


@butuh_node
def test_jejak_24_bacaan_terakhir():
    j = _js("(() => { let j = []; for (let i = 0; i < 30; i++) j = catatJejak(j, { kg: i * 1000, keadaan: 'bergerak' });"
            " return j; })()")
    assert len(j) == 24 and j[-1]["kg"] == 29000
    html = _js("htmlJejak([{ kg: 15000, keadaan: 'stabil' }, { kg: null, keadaan: 'putus' }])")
    assert html.count("<span") == 24 and 'class="stabil" style="height:50%"' in html


_DUA_TRUK = """[{line_code:'line-1',name:'Line 1',assignment:{truck_id:'a',plate_number:'BE 1 A'}},
               {line_code:'line-2',name:'Line 2',assignment:{truck_id:'b',plate_number:'BE 2 B'}},
               {line_code:'line-3',name:'Line 3',assignment:{truck_id:'a',plate_number:'BE 1 A'}}]"""


@butuh_node
def test_dua_truk_berbeda_per_line_dikelompokkan_per_truk():
    grup = _js(f"trukDiLine({_DUA_TRUK}).map((g) => [g.a.truck_id, g.lines.map((l) => l.line_code)])")
    assert grup == [["a", ["line-1", "line-3"]], ["b", ["line-2"]]]
    html = _js(f"htmlTrukDiLine({_DUA_TRUK})")
    assert html.count('data-aksi="lepas-truk"') == 2
    assert 'data-lines="line-1,line-3"' in html and 'data-lines="line-2"' in html


@butuh_node
def test_tanpa_truk_bilang_belum_ada():
    html = _js("htmlTrukDiLine([{ line_code: 'line-1', assignment: null }])")
    assert _js("t('trukDiLineKosong')") in html and "lepas-truk" not in html


def test_neto_hari_ini_pindah_ke_timbangan():
    tally = re.search(r'<section id="tally">(.*?)</section>', HTML, re.S).group(1)
    assert 'id="tot-neto"' not in tally
    timbangan = re.search(r'<section id="sec-timbangan"(.*?)</section>', HTML, re.S).group(1)
    assert 'id="tot-neto"' in timbangan and 'id="tot-tiket"' in timbangan


def test_kartu_ringkasan_punya_bagian_baru():
    tally = re.search(r'<section id="tally">(.*?)</section>', HTML, re.S).group(1)
    for id_ in ("bar-kelas", "timbang-saran", "timbang-jejak", "truk-di-line", "antrean-bongkar"):
        assert f'id="{id_}"' in tally, id_


def test_tiga_kartu_ringkasan_sejajar_kartu_line():
    # Owner 2026-10-07: the three summary cards share the width equally, aligned with the line
    # cards: the same grid template and gap as `#lines`.
    assert re.search(r"#tally\s*\{[^}]*display:grid;[^}]*grid-template-columns:repeat\(auto-fit,minmax\(min\(320px,100%\),1fr\)\);[^}]*gap:12px", HTML)
    assert not re.search(r"\.ringkas-hari\s*\{\s*flex:", HTML)
