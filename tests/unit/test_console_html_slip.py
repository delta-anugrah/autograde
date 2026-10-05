"""Printable grading slip per truck (batch 5.9): a Print button on each truck row of the
Rekap tab while support has it switched on, a slip of its own for paper (`@media print`),
and the switch in Settings.

Two layers like `test_console_html_lepas_paksa.py`: text invariants (always run) and
behaviour through node with the real KAMUS (`konsol_js`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

KUNCI = (
    "btnCetakSlip", "gagalCetakSlip", "slipJudul", "slipTanggal", "slipTruk", "slipSupplier", "slipSumber",
    "slipJam", "slipKelas", "slipJumlah", "slipRasio", "slipNeto", "slipTiket", "slipBruto", "slipTara",
    "slipMasuk", "slipKeluar", "slipDicetak", "slipTtdOperator", "slipTtdSupir", "grupSlip", "labelSlip",
    "bantuSlip", "btnSimpanSlip", "slipTersimpan", "err_slip_mati", "err_slip_tidak_ada",
)


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


# ── the Print button ──────────────────────────────────────────────────────

_TRUK = {"work_date": "2026-10-05", "truck_id": "t1", "plate_number": "BE 1 AA", "supplier_name": "KUD",
         "source_label": "External", "total": 3, "ripe": 2, "unripe": 0, "jk": 1, "tp": 0, "acc": 2, "neto_kg": 8000}
_STUB = """
const kg = (v) => (v === null || v === undefined ? KOSONG : Number(v).toLocaleString(lokal()));
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const tanggalRiwayat = (d) => d; const rasioRiwayat = () => "66%";
"""


def _baris(slip_cetak: bool, baris: dict) -> str:
    return jalankan(["barisRiwayatTruk"], f"barisRiwayatTruk({json.dumps(baris)})",
                    tambahan=_STUB + f"let slipCetak = {json.dumps(slip_cetak)};")


@butuh_node
def test_a_truck_row_offers_print_only_while_the_switch_is_on():
    nyala, mati = _baris(True, _TRUK), _baris(False, _TRUK)
    assert 'data-cetak="1"' in nyala and 'data-truk="t1"' in nyala and 'data-tanggal="2026-10-05"' in nyala
    assert "data-cetak" not in mati
    assert "data-lihat" in nyala and "data-lihat" in mati


@butuh_node
def test_bunches_with_no_truck_have_nothing_to_print():
    assert "data-cetak" not in _baris(True, {**_TRUK, "truck_id": None, "plate_number": None})


def test_the_poll_reads_the_switch_and_redraws_the_recap_when_it_changes():
    refresh = fungsi("refresh")
    assert "aturSlipCetak(s.slip_cetak)" in refresh
    kerja = fungsi("aturSlipCetak")
    assert "gambarUlangRiwayat()" in kerja and "slipCetak === baru" in kerja


def test_print_asks_the_server_inside_the_busy_helper_then_opens_the_print_dialog():
    kerja = fungsi("cetakSlip")
    assert "denganSibuk(tombol" in kerja
    assert kerja.index("/api/console/slip?") < kerja.index('tulisKalauBeda($("slip-cetak"), htmlSlip(s))') < kerja.index("window.print()")
    assert 'gagalKarena("gagalCetakSlip", e)' in kerja
    assert 'ev.target.closest("button[data-cetak]")' in HTML


# ── the slip itself ───────────────────────────────────────────────────────

_SLIP = {
    "perusahaan": "PT Sawit <Uji>", "work_date": "2026-10-05", "truck_id": "t1", "plate_number": "BE 1 AA",
    "supplier_name": "KUD A", "source_label": "External",
    "mulai": "2026-10-05T01:00:00+00:00", "selesai": "2026-10-05T02:30:00+00:00",
    "kelas": {"ripe": 2, "unripe": 0, "jk": 1, "tp": 0, "tanpa_kelas": 0, "total": 3},
    "rasio_ripe": 66.7, "neto_kg": 8000.5,
    "tiket": [{"bruto_kg": 12000.5, "tara_kg": 4000, "neto_kg": 8000.5, "masuk": "2026-10-05T07:00:00+07:00", "keluar": None}],
}
_STUB_SLIP = """
const kg = (v) => (v === null || v === undefined ? KOSONG : Number(v).toLocaleString(lokal()));
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
"""


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_the_slip_carries_what_the_plan_asks_for_in_the_screen_language(bahasa):
    html = jalankan(["waktu", "angkaSlip", "htmlSlip"], f"htmlSlip({json.dumps(_SLIP)}, 0)", bahasa=bahasa, tambahan=_STUB_SLIP)
    kata = jalankan([], "KAMUS[bahasa]", bahasa=bahasa)
    for isi in ("BE 1 AA", "KUD A", "External", "2026-10-05", kata["slipJudul"], kata["slipRasio"], kata["slipNeto"],
                kata["slipTtdOperator"], kata["slipTtdSupir"]):
        assert isi in html, isi
    assert "PT Sawit &lt;Uji&gt;" in html, "server text goes through esc()"
    angka = "66,7%" if bahasa == "id" else "66.7%"
    assert angka in html
    assert ("8.000,5" if bahasa == "id" else "8,000.5") in html


@butuh_node
def test_a_slip_without_a_rate_or_a_ticket_says_dash_not_zero():
    kosong = {**_SLIP, "rasio_ripe": None, "neto_kg": None, "tiket": []}
    html = jalankan(["waktu", "angkaSlip", "htmlSlip"], f"htmlSlip({json.dumps(kosong)}, 0)", tambahan=_STUB_SLIP)
    assert "0%" not in html and ">0 kg<" not in html


def test_the_slip_is_alone_on_paper_and_hidden_on_screen():
    assert re.search(r'<div id="toasts"[^>]*></div>\s*<div id="slip-cetak" aria-hidden="true"></div>', HTML)
    assert re.search(r"#slip-cetak\s*\{\s*display:none;\s*\}", HTML)
    cetak = HTML[HTML.index("@media print {") : HTML.index("@media print {") + 900]
    assert 'body[data-cetak="slip"] > :not(#slip-cetak) { display:none !important; }' in cetak
    assert 'body[data-cetak="slip"] #slip-cetak { display:block;' in cetak
    # The QR card print keeps working: its rules stand down only while a slip prints.
    assert 'body:not([data-cetak="slip"]) > *:not(#sec-truk) { display:none !important; }' in cetak
    kerja = fungsi("cetakSlip")
    assert 'document.body.dataset.cetak = "slip"' in kerja
    assert 'window.addEventListener("afterprint", () => { delete document.body.dataset.cetak; });' in HTML


# ── the switch in Settings ────────────────────────────────────────────────


def test_settings_load_and_save_the_switch_through_the_support_lane():
    assert "await muatSlipSetelan();" in fungsi("muatSetelan")
    assert '"/api/console/dev/slip"' in fungsi("muatSlipSetelan")
    awal = HTML.index('$("set-slip-simpan").addEventListener("click"')
    kerja = HTML[awal : HTML.index("\n}));", awal)]
    assert "denganSibuk(ev.currentTarget" in kerja and 'method: "POST"' in kerja
    assert 'toastSukses(t("slipTersimpan"))' in kerja and "await refresh()" in kerja
    assert '<input id="set-slip" type="checkbox">' in HTML
