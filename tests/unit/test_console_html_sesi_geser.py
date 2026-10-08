"""Sliding session on the screen (batch 5.7): a touch keeps the operator in, a ribbon warns
15 minutes before the end, and the screen's own polls never count as a touch.

Two layers like `test_console_html_lepas_paksa.py`: text invariants (always run) and
behaviour through node with the real KAMUS (`konsol_js`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan, konstanta

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

KUNCI = ("sesiAkanHabis", "btnPerpanjangSesi", "sukPerpanjangSesi", "gagalPerpanjangSesi")
MENIT = 60 * 1000


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


def _batas() -> str:
    return konstanta("JEDA_PERPANJANG_MS", "PERINGATAN_SESI_MS")


@butuh_node
@pytest.mark.parametrize(
    ("sisa", "peringatan"),
    [(None, False), (60 * MENIT, False), (15 * MENIT + 1, False), (15 * MENIT, True), (1, True), (0, True)],
)
def test_the_warning_starts_fifteen_minutes_before_the_end(sisa, peringatan):
    hasil = jalankan(["dalamPeringatan"], f"dalamPeringatan({json.dumps(sisa)})", tambahan=_batas())
    assert hasil is peringatan


@butuh_node
@pytest.mark.parametrize(
    ("aktif", "lalu_ms", "sisa_ms", "perlu"),
    [
        (False, 60 * MENIT, 10 * MENIT, False),   # no touch: never renewed, even in the warning
        (True, 1 * MENIT, 6 * 60 * MENIT, False),  # a touch, but renewed a minute ago
        (True, 5 * MENIT, 6 * 60 * MENIT, True),   # a touch, last renew 5 minutes ago
        (True, 1 * MENIT, 10 * MENIT, True),       # a touch in the warning: at once
    ],
)
def test_a_touch_renews_at_most_every_five_minutes_and_at_once_near_the_end(aktif, lalu_ms, sisa_ms, perlu):
    hasil = jalankan(
        ["dalamPeringatan", "perluPerpanjang"],
        f"perluPerpanjang({{ aktif: {json.dumps(aktif)}, terakhir: 1000000, sekarang: {1000000 + lalu_ms},"
        f" sisaMs: {sisa_ms} }})",
        tambahan=_batas(),
    )
    assert hasil is perlu


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
@pytest.mark.parametrize(("sisa_ms", "menit"), [(14 * MENIT + 1, 15), (60_000, 1), (5_000, 1)])
def test_the_ribbon_counts_whole_minutes_and_never_says_zero(bahasa, sisa_ms, menit):
    teks = jalankan(["teksSesi"], f"teksSesi({sisa_ms})", bahasa=bahasa)
    pola = jalankan([], "KAMUS[bahasa].sesiAkanHabis", bahasa=bahasa)
    assert teks == pola.replace("{menit}", str(menit))


def test_a_touch_or_a_key_marks_activity_and_polls_do_not():
    assert re.search(
        r'\["pointerdown", "keydown"\]\.forEach\(\(jenis\) => document\.addEventListener\(jenis, tandaiAktif, \{ capture: true, passive: true \}\)\)',
        HTML,
    )
    for poll in ("refresh", "muatTrucks", "muatTimbangan", "api", "ambil"):
        assert "session/renew" not in fungsi(poll), poll
        assert "tandaiAktif" not in fungsi(poll), poll


def test_the_renew_posts_inside_the_busy_helper_and_reads_the_new_end():
    kerja = fungsi("perpanjangSesi")
    assert "denganSibuk(tombol" in kerja
    assert '"/api/console/session/renew", { method: "POST" }' in kerja
    assert "aturSisaSesi(r.sisa_detik)" in kerja
    assert 'gagalKarena("gagalPerpanjangSesi", e)' in kerja


def test_the_watch_runs_every_second_and_renews_in_the_background_one_at_a_time():
    assert "setInterval(pantauSesi, 1000)" in HTML
    pantau = fungsi("pantauSesi")
    assert "perluPerpanjang(" in pantau and "perpanjangLatar()" in pantau
    assert "const perpanjangLatar = sekaliJalan(() => perpanjangSesi(null));" in HTML


def test_the_end_asks_the_server_before_the_gate_comes_down():
    """Another tab of the same browser may have renewed the same cookie."""
    pantau = fungsi("pantauSesi")
    assert "sisa <= 0" in pantau and "cekSesiLatar()" in pantau
    assert "const cekSesiLatar = sekaliJalan(cekSesi);" in HTML


def test_sign_in_and_the_session_check_start_the_countdown_and_the_gate_stops_it():
    assert "aturSisaSesi(sisa_detik)" in fungsi("kirimSandi")
    assert "perpanjangTerakhir = Date.now();" in fungsi("kirimSandi"), "a sign-in counts as a renew"
    assert "aturSisaSesi(sisa_detik)" in fungsi("cekSesi")
    assert "aturSisaSesi(null)" in fungsi("bukaGerbang")


def test_the_ribbon_has_its_button_and_reads_as_a_status():
    pita = HTML[HTML.index('<div id="pita-sesi"') : HTML.index("</div>", HTML.index('<div id="pita-sesi"'))]
    assert 'role="status"' in pita and " hidden" in pita
    assert re.search(r'<button type="button" id="pita-sesi-perpanjang" class="utama" data-t="btnPerpanjangSesi"[ >]', pita)
    assert '$("pita-sesi-perpanjang").addEventListener("click", (ev) => perpanjangSesi(ev.currentTarget));' in HTML
    assert re.search(r"#pita-sesi\[hidden\]\s*\{\s*display:none;", HTML)
