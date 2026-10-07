"""Line cards of the new look (spec 2026-10-07 §5.2, §6.3): the camera on top, never cropped;
a strip of the line's last photos; today's counts with a class bar; Reject and Piston on the
card, and a "more" menu for Tugaskan, Lepas and the card order."""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
_DOM = 'const waktu = (iso) => String(iso).slice(11, 19);'


def test_kartu_line_punya_strip_bar_dan_menu_lain():
    kartu = fungsi("kartuLine")
    for bagian in ('class="strip-foto"', 'class="strip-jam"', 'class="bar-kelas"', '<details class="lagi"',
                   'data-aksi="tugaskan"', 'class="slot-lepas"', 'data-aksi="geser"', 'data-aksi="tolak"',
                   'class="slot-piston"', 'data-k="ripe"', 'data-k="total"'):
        assert bagian in kartu, bagian
    # Tugaskan, Lepas and the order arrows live in the "more" menu; Reject and Piston stay out.
    lagi = kartu[kartu.index('<details class="lagi"'):]
    assert 'data-aksi="tugaskan"' in lagi and 'data-aksi="geser"' in lagi
    assert 'data-aksi="tolak"' not in lagi and "slot-piston" not in lagi


def test_kamera_dan_foto_tidak_dipotong_dan_tidak_gepeng():
    assert re.search(r"\.feed img\s*\{[^}]*object-fit:contain", HTML)
    assert re.search(r"\.strip-foto img\s*\{[^}]*object-fit:contain", HTML)


def test_bar_kelas_kartu_ikut_poll():
    assert 'tulisKalauBeda(c.querySelector(".bar-kelas"), htmlBarKelas(l))' in fungsi("refresh")


@butuh_node
def test_strip_empat_terbaru_per_line():
    items = [{"line_code": "line-1" if i % 2 else "line-2", "image_url": f"/f/{i}.jpg",
              "timestamp": f"2026-10-07T16:00:0{i}Z"} for i in range(9)]
    hasil = jalankan(["stripPerLine"], f"stripPerLine({json.dumps(items)}, 'line-1').map((r) => r.image_url)",
                     tambahan="const STRIP_N = 4;")
    assert hasil == ["/f/1.jpg", "/f/3.jpg", "/f/5.jpg", "/f/7.jpg"]


@butuh_node
def test_strip_tanpa_foto_dilewati():
    items = [{"line_code": "line-1", "image_url": None}, {"line_code": "line-1", "image_url": "/f/a.jpg"}]
    hasil = jalankan(["stripPerLine"], f"stripPerLine({json.dumps(items)}, 'line-1').length",
                     tambahan="const STRIP_N = 4;")
    assert hasil == 1


@butuh_node
def test_tombol_strip_membuka_foto_besar_lewat_pendengar_yang_ada():
    html = jalankan(["htmlStrip", "judulFoto"],
                    "htmlStrip([{ line_code: 'line-1', image_url: '/f/a.jpg', thumb_url: '/t/a.jpg',"
                    " grade_class: 'JK', timestamp: '2026-10-07T16:00:00Z' }])", tambahan=_DOM)
    assert 'class="foto strip-item"' in html and 'data-kelas="jk"' in html
    assert 'data-foto="/f/a.jpg"' in html and 'src="/t/a.jpg"' in html and 'data-penuh="/f/a.jpg"' in html


def test_strip_minta_empat_terbaru_per_line_lepas_dari_tabel():
    # Page 1 of the day can hold one line only (a busy line fills 25 rows), so each card asks
    # for its own newest four, unfiltered by the table (spec §5.2, ruling 2026-10-07).
    refresh = fungsi("refresh")
    assert "gambarStrip(await ambilStrip(s.lines.map((l) => l.line_code)))" in refresh
    assert 'paramGrading(STRIP_N, 0, { line: kode, truk: "" })' in fungsi("ambilStrip")


def test_pil_sinkron_tetap_pil_sesudah_diisi():
    assert "el.className = `sinkron-baris pil ${b.kelas}`" in fungsi("isiSinkron")


def test_tabel_hasil_punya_judul_dan_foto_utuh():
    grading = re.search(r'<section id="sec-grading"(.*?)</section>', HTML, re.S).group(1)
    assert 'data-t="judulHasilGrading"' in grading and 'data-t="ketHasilGrading"' in grading
    assert re.search(r"button\.foto img\s*\{[^}]*object-fit:contain", HTML)


def test_baris_baru_berkedip_sekali_di_halaman_pertama():
    muat = fungsi("muatGrading")
    assert 'classList.add("baris-baru")' in muat and "barisAtasGrading" in muat
    assert re.search(r"tr\.baris-baru\s*\{[^}]*animation:baris-baru", HTML)


def test_gerak_dimatikan_untuk_gerak_dikurangi():
    # One rule switches off every animation and transition (`*, *::before, *::after`), so the
    # strip slide, the row flash, the scale trace and the live dots go with it.
    assert re.search(r"@media \(prefers-reduced-motion:reduce\)\s*\{\s*\*, \*::before, \*::after\s*\{\s*animation:none !important;"
                     r" transition:none !important;", HTML)


def test_jam_strip_tanpa_tanggal_dan_titik_kelas_berwarna():
    # The strip is today's photos only: the time is enough. The class dots in a card's counts
    # must win over the grey default (same specificity, later rule loses otherwise).
    assert 'waktu(daftar[0].timestamp).split(" ").pop()' in fungsi("gambarStrip")
    for kelas, warna in (("acc", "ripe"), ("rej", "unripe"), ("jk", "jk"), ("tp", "tp")):
        assert re.search(rf"\.counts > span\.{kelas} \.lb::before\s*\{{\s*background:var\(--{warna}\)", HTML), kelas
