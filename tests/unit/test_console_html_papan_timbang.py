"""Timbangan board (owner 2026-10-08, reverses spec §9 Q3): four columns, Datang, Bongkar,
Timbang kosong, Selesai, above the full ticket table, which stays. Same data as the table
(`/api/console/weighings` items + waiting) and the truck card (`/api/console/state` lines +
antrean_bongkar); the buttons reuse the table's flows. No new endpoint."""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
DASH = re.search(r"^const dash = .*$", HTML, re.M).group(0) + "\n" + re.search(r"^const kg = .*$", HTML, re.M).group(0)
FUNGSI = ["chipPlat", "waktu", "jamMenit", "namaLineRingkas", "chipPapan", "kartuPapan"]

KUNCI = ("papanSubDatang", "papanSubBongkar", "papanSubKosong", "papanSubSelesai", "papanKosong",
         "papanMetaDatang", "papanMetaBongkar", "papanMetaKosong", "papanMetaSelesai", "papanDiLine",
         "papanAntrean", "papanLain", "papanNeto", "papanRincian", "timbangSemuaTiket")


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _kartu(jenis: str, w: dict, lines: list | None = None, antrean: list | None = None) -> str:
    awal = DASH + f"\nlet lineTerakhir = {json.dumps(lines or [])}; let antreanTerakhir = {json.dumps(antrean or [])};"
    return jalankan(FUNGSI, f"kartuPapan({json.dumps(jenis)}, {json.dumps(w)})", tambahan=awal, tz="UTC")


def test_board_sits_between_the_tools_and_the_table_with_four_columns():
    sec = HTML.split('<section id="sec-timbangan"', 1)[1].split('<section id="sec-rekap"', 1)[0]
    assert sec.index('class="tools timbang-alat berdiri"') < sec.index('id="papan-timbang"') < sec.index('id="timbangan"')
    papan = sec.split('id="papan-timbang"', 1)[1].split("<!-- /papan-timbang -->", 1)[0]
    assert re.findall(r'data-kolom="(\w+)"', papan) == ["datang", "bongkar", "kosong", "selesai"]
    for kolom in ("datang", "bongkar", "kosong", "selesai"):
        assert f'id="papan-isi-{kolom}"' in papan and f'id="papan-jumlah-{kolom}"' in papan


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_board_words_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


@butuh_node
def test_a_waiting_truck_offers_timbang_isi_with_its_plate():
    html = _kartu("datang", {"id": "a1", "plate_number": "BE <9> TSD", "arrived_at": "2026-10-08T09:24:00Z", "menit": 7})
    assert '<b class="plat">BE &lt;9&gt; TSD</b>' in html
    assert 'data-papan="timbang-isi"' in html and 'data-plat="BE &lt;9&gt; TSD"' in html
    assert "09:24" in html


@butuh_node
def test_an_unloading_truck_says_which_lines_hold_it():
    w = {"id": "w1", "truck_id": "t1", "plate_number": "BE 8605 TSD", "supplier_name": "KUD Rambang",
         "source_label": "External", "gross_kg": 24380, "entered_at": "2026-10-08T09:05:00Z", "ref": "R1"}
    lines = [{"line_code": "line-1", "name": "Line 1", "assignment": {"truck_id": "t1"}},
             {"line_code": "line-2", "name": "Line 2", "assignment": {"truck_id": "t1"}},
             {"line_code": "line-3", "name": "Line 3", "assignment": None}]
    html = _kartu("bongkar", w, lines)
    assert "Di Line 1, 2" in html and "24.380" in html and "KUD Rambang" in html
    assert 'data-papan="timbang-kosong"' in html and 'data-ref="R1"' in html


@butuh_node
def test_a_queued_truck_shows_its_place_in_the_queue():
    w = {"id": "w2", "truck_id": "t2", "plate_number": "BG 9911 ZA", "gross_kg": 17520, "entered_at": "2026-10-08T09:20:00Z"}
    html = _kartu("bongkar", w, [], [{"weighing_id": "w9"}, {"weighing_id": "w2"}])
    assert re.search(r"\b2\b", re.sub(r"<[^>]+>", " ", html.split('class="papan-chip', 1)[1].split("</span>", 1)[0]))


@butuh_node
def test_a_weighed_out_truck_shows_neto_and_the_erp_ticket_and_offers_keluar():
    w = {"id": "w3", "plate_number": "BE 5585 TSE", "gross_kg": 27310, "tare_kg": 9860, "net_kg": 17450,
         "exited_at": "2026-10-08T09:18:00Z", "erp_ticket": "WB-2026-00041", "tanpa_scan_4": False}
    html = _kartu("kosong", w)
    assert "17.450" in html and "27.310" in html and "9.860" in html and "WB-2026-00041" in html
    assert 'data-papan="pergi"' in html and 'data-id="w3"' in html


@butuh_node
def test_a_finished_truck_has_no_button():
    w = {"id": "w4", "plate_number": "BE 9874 TSE", "gross_kg": 21620, "tare_kg": 6640, "net_kg": 14980,
         "left_at": "2026-10-08T08:51:00Z", "erp_ticket": None}
    html = _kartu("selesai", w)
    assert "14.980" in html and "<button" not in html and "AutoERP" not in html


def test_the_finished_column_is_capped_and_points_to_rekap():
    kerja = re.search(r"function gambarPapan\(\) \{(.*?)\n\}", HTML, re.S).group(1)
    assert "PAPAN_SELESAI_MAKS" in kerja and 'data-papan="rekap"' in kerja


@butuh_node
def test_line_names_with_one_prefix_are_shortened():
    w = {"id": "w1", "truck_id": "t1", "plate_number": "BE 1", "gross_kg": 20000, "entered_at": "2026-10-08T09:05:00Z"}
    lines = [{"line_code": f"line-{n}", "name": f"Line {n}", "assignment": {"truck_id": "t1"}} for n in (1, 2, 3)]
    assert "Di Line 1, 2, 3" in _kartu("bongkar", w, lines)


@butuh_node
def test_unloading_column_puts_the_truck_on_the_lines_first_then_the_queue_in_order():
    items = [{"id": "w3", "truck_id": "t3", "tahap": "bongkar"}, {"id": "w2", "truck_id": "t2", "tahap": "bongkar"},
             {"id": "w1", "truck_id": "t1", "tahap": "bongkar"}]
    lines = [{"line_code": "line-1", "name": "Line 1", "assignment": {"truck_id": "t1"}}]
    antrean = [{"weighing_id": "w2"}, {"weighing_id": "w3"}]
    awal = f"let lineTerakhir = {json.dumps(lines)}; let antreanTerakhir = {json.dumps(antrean)};"
    urut = jalankan(["urutBongkar"], f"urutBongkar({json.dumps(items)}).map((w) => w.id)", tambahan=awal)
    assert urut == ["w1", "w2", "w3"]


def test_the_step_strip_is_gone_and_its_parts_moved():
    """Owner 2026-10-08: the strip above the forms doubled the board's columns."""
    sec = HTML.split('<section id="sec-timbangan"', 1)[1].split('<section id="sec-rekap"', 1)[0]
    assert 'class="timbang-langkah"' not in sec and "langkah-ruas" not in sec
    # The forms name themselves (aria-labelledby kept) and the waiting count rides on form 1.
    form1 = sec.split('<div class="timbang-form ruas-datang"', 1)[1].split('id="scan-datang-pesan"', 1)[0]
    assert 'id="lb-langkah-datang"' in form1 and 'id="antre"' in form1
    form2 = sec.split('<div class="timbang-form ruas-bongkar timbang-isi"', 1)[1].split("bruto-petunjuk", 1)[0]
    assert 'id="lb-langkah-isi"' in form2
    papan = sec.split('id="papan-timbang"', 1)[1].split("<!-- /papan-timbang -->", 1)[0]
    # The tara bar lights column 3; the exit message sits in column 4.
    assert re.search(r'data-kolom="kosong" id="ruas-kosong"', papan)
    assert 'id="scan-pergi-pesan"' in papan.split('data-kolom="selesai"', 1)[1]
