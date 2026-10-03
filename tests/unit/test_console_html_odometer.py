"""Tally numbers roll like an odometer when they change (user 2026-10-03, NumberFlow style).

`tulisAngka(el, nilai)` writes RIPE / UNRIPE / JK / TP / TOTAL on the line cards and the day
strip. Only a real change rolls; the first write, a hidden browser tab and reduced motion
write the plain number. Rendering in a browser: `tests/browser/test_browser_odometer.py`.
"""
from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

# A fake element: counts DOM writes, keeps the one-shot animationend listener.
_EL_PALSU = """
let gerak = true;
const document = { hidden: false };
const gerakDikurangi = () => !gerak;
const buatEl = () => {
  const el = { tulis: 0, dengar: [] };
  let teks = "", html = "";
  Object.defineProperty(el, "textContent", { get: () => teks, set: (v) => { el.tulis += 1; teks = String(v); html = teks; } });
  Object.defineProperty(el, "innerHTML", { get: () => html, set: (v) => { el.tulis += 1; html = v;
    teks = (v.match(/<span class="odo-baca">(\\d+)<\\/span>/) || [, ""])[1]; } });
  el.addEventListener = (nama, fn) => { el.dengar.push([nama, fn]); };
  el.selesai = () => { const d = el.dengar; el.dengar = []; d.forEach(([, fn]) => fn()); };
  return el;
};
"""


def _jalan(ekspresi: str):
    return jalankan(["tulisAngka", "kolomOdometer"], ekspresi, tambahan=_EL_PALSU)


@butuh_node
def test_tulisan_pertama_langsung_tanpa_gulir():
    hasil = _jalan("(() => { const el = buatEl(); tulisAngka(el, 42); return [el.innerHTML, el.tulis]; })()")
    assert hasil == ["42", 1]


@butuh_node
def test_nilai_sama_tidak_menyentuh_dom():
    hasil = _jalan("(() => { const el = buatEl(); tulisAngka(el, 7); tulisAngka(el, 7); tulisAngka(el, '7');"
                   " return el.tulis; })()")
    assert hasil == 1


@butuh_node
def test_perubahan_bergulir_lalu_kembali_jadi_teks():
    hasil = _jalan(
        "(() => { const el = buatEl(); tulisAngka(el, 9); tulisAngka(el, 12);"
        " const r = [el.textContent, el.innerHTML.includes('class=\"odo\"'), el.dengar.map((d) => d[0])];"
        " el.selesai(); r.push(el.innerHTML); return r; })()"
    )
    teks, bergulir, peristiwa, akhir = hasil
    assert teks == "12" and bergulir and peristiwa == ["animationend"]
    assert akhir == "12"


@butuh_node
def test_gerak_dikurangi_dan_tab_tersembunyi_langsung():
    hasil = _jalan(
        "(() => { const el = buatEl(); tulisAngka(el, 1); gerak = false; tulisAngka(el, 2);"
        " const a = el.innerHTML; gerak = true; document.hidden = true; tulisAngka(el, 3);"
        " return [a, el.innerHTML, el.dengar.length]; })()"
    )
    assert hasil == ["2", "3", 0]


@butuh_node
def test_perubahan_baru_saat_bergulir_tidak_ditimpa_pembersih_lama():
    hasil = _jalan(
        "(() => { const el = buatEl(); tulisAngka(el, 1); tulisAngka(el, 2); tulisAngka(el, 3);"
        " el.selesai(); return el.innerHTML; })()"
    )
    assert hasil == "3"


@butuh_node
def test_kolom_rata_kanan_masuk_dan_keluar():
    kolom = _jalan("[kolomOdometer('99', '100'), kolomOdometer('100', '99'), kolomOdometer('5', '7')]")
    naik, turun, sama = kolom
    assert re.findall(r"<span ([^>]*)>", naik) == [
        'class="odo-d" data-masuk data-ke="1" style="--ke:1"',
        'class="odo-d" data-ke="0" style="--dari:9;--ke:0"',
        'class="odo-d" data-ke="0" style="--dari:9;--ke:0"',
    ]
    assert re.findall(r"<span ([^>]*)>", turun)[0] == 'class="odo-d" data-keluar data-ke="1" style="--ke:1"'
    assert sama == '<span class="odo-d" data-ke="7" style="--dari:5;--ke:7"></span>'


def test_tally_dan_kartu_menulis_lewat_odometer():
    tally = fungsi("isiTally")
    for kunci in ("tot-ripe", "tot-unripe", "tot-jk", "tot-tp", "tot-all"):
        assert f'tulisAngka($("{kunci}"),' in tally, kunci
    assert ".textContent = jml(" not in tally
    awal = HTML.index('c.querySelectorAll(".counts b[data-k]").forEach')
    assert "tulisAngka(el, l[el.dataset.k] || 0)" in HTML[awal : awal + 200]


def test_odometer_cuma_transform_dan_opacity():
    blok = HTML[HTML.index("  .odo-baca {") : HTML.index("@keyframes odo-keluar")]
    blok += HTML[HTML.index("@keyframes odo-keluar") :].split("\n", 2)[0]
    for sifat in re.findall(r"@keyframes[^{]*\{(.*)", blok):
        assert "height" not in sifat and "width" not in sifat and "top" not in sifat
    assert 'content:"0\\A 1\\A 2\\A 3\\A 4\\A 5\\A 6\\A 7\\A 8\\A 9"' in HTML
    assert "setTimeout(" not in fungsi("tulisAngka") and "requestAnimationFrame" not in fungsi("tulisAngka")


def test_kartu_yang_baru_digambar_jadi_titik_awal():
    """A card drawn by `kartuLine` already shows its numbers: the next poll rolls from them
    instead of writing plain as if it were the first write (found by the browser test)."""
    awal = HTML.index('$("lines").innerHTML = s.lines.map((l) => kartuLine(l, dipasangPada))')
    assert "el._angka = Number(el.textContent) || 0" in HTML[awal : awal + 500]
