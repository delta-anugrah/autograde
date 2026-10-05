"""Fresh data without a manual refresh, taps never lost (batch 5.3, 5.4, 5.8, 6.4).

A kiosk stays open for days and nobody touches the keyboard. So: the poll writes only what
changed (a tap that lands during a rewrite is lost), one pull at a time with a time limit,
a screen that says when its numbers are old, a page that reloads itself after an update,
and one Refresh button as a spare.

Two layers like `test_console_html_lepas_paksa.py`: text invariants (always run) and
behaviour through node with the real KAMUS (`konsol_js`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan, konstanta

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

KUNCI = ("segarPada", "basiSejak", "tombolSegarkan", "sukSegarkan", "gagalSegarkan")


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


# ── 5.4: the poll writes only what changed ────────────────────────────────


def test_the_poll_updates_a_card_through_one_function():
    refresh = fungsi("refresh")
    assert "perbaruiKartu(c, l)" in refresh
    assert ".innerHTML = isiTruk(" not in HTML, "the truck line is written only when it changes"
    assert ".outerHTML = tombolPiston(" not in HTML, "the piston button is written only when it changes"
    assert ".outerHTML = pitaBaru" not in HTML


def test_every_part_of_a_card_is_written_only_when_it_changes():
    kerja = fungsi("perbaruiKartu")
    for slot, isi in (
        (".truk", "isiTruk(l.assignment)"),
        (".slot-lepas", "tombolLepas(l)"),
        (".slot-piston", "tombolPiston(l)"),
        (".slot-pita-piston", "pitaPiston(l)"),
    ):
        assert f'tulisKalauBeda(c.querySelector("{slot}"), {isi})' in kerja, slot


def test_the_card_draws_the_piston_button_and_ribbon_inside_their_slots():
    kartu = fungsi("kartuLine")
    assert '<span class="slot-piston">${tombolPiston(l)}</span>' in kartu
    assert '<div class="slot-pita-piston">${pitaPiston(l)}</div>' in kartu


def test_the_piston_slot_takes_no_room_of_its_own():
    assert re.search(r"\.slot-piston\s*\{\s*display:contents;\s*\}", HTML)


def test_the_first_drawing_seeds_what_the_next_poll_compares_with():
    """Without the seed the first poll after a redraw rewrites every slot once more, and a
    tap that lands in that one rewrite is the tap this batch exists to keep."""
    refresh = fungsi("refresh")
    awal = refresh.index('$("lines").innerHTML = s.lines.map(')
    assert "perbaruiKartu(" in refresh[awal : refresh.index("dipasang = true;")]


def test_the_grading_table_is_written_only_when_it_changes():
    muat = fungsi("muatGrading")
    assert 'tulisKalauBeda($("recent"),' in muat
    assert '$("recent").innerHTML' not in HTML
    halaman = fungsi("segarkanHalaman")
    assert 'tulisKalauBeda($("grading-nomor"), tombolNomorHalaman())' in halaman


# ── 5.3: lists that follow the server ─────────────────────────────────────

_PILIH = ["barisPilih", "komponenPilih"]


@butuh_node
def test_the_rows_of_a_dropdown_are_built_in_one_place():
    html = jalankan(_PILIH, 'komponenPilih([{v:"",teks:"Pilih"},{v:"t1",teks:"BE 1 AA"}], "t1")')
    assert html.count('role="option"') == 2
    assert 'data-nilai="t1"' in html and 'aria-selected="true">BE 1 AA' in html
    assert "barisPilih(opsi, aktif.v)" in fungsi("komponenPilih")


_ROOT = """
function buatRoot(nilai, buka) {
  const panel = { innerHTML: "" };
  const teks = { textContent: "lama" };
  return { dataset: { nilai, buka: buka ? "1" : "" }, panel, teks,
    querySelector(s) { return s === ".pilih-panel" ? panel : teks; } };
}
"""
_ISI_ULANG = ["tulisKalauBeda", "barisPilih", "isiUlangPilih"]
_OPSI = '[{v:"",teks:"Pilih"},{v:"t1",teks:"BE 1 AA"},{v:"t2",teks:"BE 2 BB"}]'


@butuh_node
def test_a_closed_dropdown_takes_the_new_list_and_keeps_what_was_picked():
    hasil = jalankan(
        _ISI_ULANG,
        f'(() => {{ const r = buatRoot("t1", false); isiUlangPilih(r, {_OPSI});'
        " return [r.panel.innerHTML.includes('BE 2 BB'), r.dataset.nilai, r.teks.textContent]; })()",
        tambahan=_ROOT,
    )
    assert hasil == [True, "t1", "BE 1 AA"]


@butuh_node
def test_an_open_dropdown_is_never_rebuilt_under_the_finger():
    hasil = jalankan(
        _ISI_ULANG,
        f'(() => {{ const r = buatRoot("t1", true); isiUlangPilih(r, {_OPSI});'
        " return [r.panel.innerHTML, r.teks.textContent]; })()",
        tambahan=_ROOT,
    )
    assert hasil == ["", "lama"]


@butuh_node
def test_a_pick_that_left_the_list_falls_back_to_the_first_row():
    hasil = jalankan(
        _ISI_ULANG,
        f'(() => {{ const r = buatRoot("hilang", false); isiUlangPilih(r, {_OPSI});'
        " return [r.dataset.nilai, r.teks.textContent]; })()",
        tambahan=_ROOT,
    )
    assert hasil == ["", "Pilih"]


def test_the_truck_list_of_every_card_follows_the_truck_poll_and_the_state_poll():
    assert "isiUlangPilih(" in fungsi("segarkanPilihTruk")
    assert "segarkanPilihTruk()" in fungsi("isiTrucks")
    assert "segarkanPilihTruk()" in fungsi("refresh"), "a list left alone while open catches up within 2 s"
    assert "opsiTrukKartu()" in fungsi("kartuLine")


@butuh_node
@pytest.mark.parametrize(
    ("kartu", "lines", "sama"),
    [
        (["line-1", "line-2"], ["line-1", "line-2"], True),
        (["line-1", "line-2"], ["line-1", "line-2", "line-3"], False),
        (["line-1", "line-2"], ["line-1"], False),
        (["line-2", "line-1"], ["line-1", "line-2"], False),
        ([], [], True),
    ],
)
def test_a_line_added_or_removed_on_the_server_is_noticed(kartu, lines, sama):
    assert jalankan(["daftarSama"], f"daftarSama({json.dumps(kartu)}, {json.dumps(lines)})") is sama


def test_cards_are_drawn_again_when_the_lines_changed():
    refresh = fungsi("refresh")
    assert "if (!kartuSesuai(s.lines)) dipasang = false;" in refresh
    assert refresh.index("kartuSesuai(s.lines)") < refresh.index("if (!dipasang) {")
    assert "daftarSama(" in fungsi("kartuSesuai")


@butuh_node
@pytest.mark.parametrize(
    ("awal", "kini", "perlu"),
    [
        ("v1.23.0", "v1.24.0", True),
        ("v1.23.0", "v1.23.0", False),
        (None, "v1.23.0", False),
        ("v1.23.0", None, False),
        ("v1.23.0", "", False),
        ("unknown", "unknown", False),
    ],
)
def test_the_page_reloads_only_when_the_console_version_really_changed(awal, kini, perlu):
    assert jalankan(["perluMuatUlang"], f"perluMuatUlang({json.dumps(awal)}, {json.dumps(kini)})") is perlu


def test_the_reload_waits_for_an_open_dialog_a_busy_button_and_a_typed_field():
    aman = fungsi("amanMuatUlang")
    assert "dialog[open]" in aman and ".sibuk" in aman and "sedangMengetik()" in aman
    cek = fungsi("cekVersiBaru")
    assert "perluMuatUlang(versiHalaman, versi)" in cek and "amanMuatUlang()" in cek
    assert "location.reload()" in cek
    assert "cekVersiBaru(s.versi)" in fungsi("refresh")


def test_one_refresh_button_reloads_every_poll_and_the_open_tab():
    assert re.search(r'<button id="segarkan" class="tombol-ikon"[^>]*data-t-lb="tombolSegarkan"', HTML)
    kerja = fungsi("segarkanSemua")
    assert "denganSibuk(" in kerja
    for muat in ("muatTrucks()", "refresh()", "muatTimbangan()", "MUAT_TAB[tab]"):
        assert muat in kerja, muat
    assert 'toastSukses(t("sukSegarkan"))' in kerja and 'toastGagal(t("gagalSegarkan"))' in kerja


def test_a_language_flip_reloads_the_open_tab():
    """Tables drawn in JS (Rekap, Log, Status, Akun) kept the old language until reopened."""
    awal = HTML.index('$("bahasa").addEventListener("click"')
    kerja = HTML[awal : HTML.index("\n});", awal)]
    assert "muatUlangTabTerbuka()" in kerja
    assert "TAB_TANPA_MUAT_ULANG" in fungsi("muatUlangTabTerbuka")


# ── 5.8: a screen that says when its numbers are old ──────────────────────

_SEGAR = ["dataBasi", "teksSegar"]


def _tambahan_segar() -> str:
    return konstanta("GAGAL_SAMPAI_BASI") + '\nconst waktu = () => "04/10/2026 14:03:22";'


@butuh_node
@pytest.mark.parametrize(("gagal", "basi"), [(0, False), (1, False), (2, False), (3, True), (40, True)])
def test_data_is_stale_after_three_polls_in_a_row_failed(gagal, basi):
    assert jalankan(_SEGAR, f"dataBasi({gagal})", tambahan=_tambahan_segar()) is basi


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_the_label_carries_the_clock_time_of_the_last_good_poll(bahasa):
    segar, basi, kosong = jalankan(
        _SEGAR, "[teksSegar(1, false), teksSegar(1, true), teksSegar(null, false)]",
        bahasa=bahasa, tambahan=_tambahan_segar(),
    )
    pola_segar = jalankan([], "KAMUS[bahasa].segarPada", bahasa=bahasa)
    pola_basi = jalankan([], "KAMUS[bahasa].basiSejak", bahasa=bahasa)
    assert segar == pola_segar.replace("{jam}", "14:03:22")
    assert basi == pola_basi.replace("{jam}", "14:03:22")
    assert kosong == "", "nothing to claim before the first good poll"
    assert "04/10/2026" not in segar


def test_the_poll_reports_success_and_failure_to_the_indicator():
    refresh = fungsi("refresh")
    assert "catatSegar(true)" in refresh
    tangkap = refresh[refresh.index("} catch (e) {") :]
    assert 'if (e.kode !== "belum_masuk") catatSegar(false);' in tangkap, (
        "a signed-out screen is not a console that stopped answering"
    )


def test_a_stale_screen_greys_its_numbers_and_tables_not_the_cameras():
    aturan = re.search(r'body\[data-basi="1"\] :is\(([^)]*)\)\s*\{([^}]*)\}', HTML)
    assert aturan, "one rule dims everything that shows polled data"
    assert ".feed" not in aturan.group(1), "the camera picture comes from the line, not from the poll"
    assert "grayscale" in aturan.group(2) and "opacity" in aturan.group(2)
    assert 'id="segar"' in HTML and 'role="status"' in HTML[HTML.index('id="segar"') - 80 : HTML.index('id="segar"') + 80]


# ── 6.4: one pull at a time, with a time limit ────────────────────────────

_KUNCI = """
const jalan = async () => {
  const kunci = kunciAntre();
  const catatan = [];
  const kerja = async (nama, ms) => {
    const lepas = await kunci.giliran();
    catatan.push("mulai " + nama);
    await new Promise((r) => setTimeout(r, ms));
    catatan.push("selesai " + nama);
    lepas();
  };
  const a = kerja("a", 30);
  const sibukSaatJalan = kunci.sibuk();
  const b = kerja("b", 1);
  await Promise.all([a, b]);
  return [catatan, sibukSaatJalan, kunci.sibuk()];
};
"""


@butuh_node
def test_two_pulls_never_run_at_the_same_time():
    import os
    import subprocess

    skrip = fungsi("kunciAntre") + _KUNCI + "jalan().then((h) => console.log(JSON.stringify(h)));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30, env=dict(os.environ))
    assert hasil.returncode == 0, hasil.stderr[-800:]
    catatan, sibuk_saat_jalan, sibuk_sesudah = json.loads(hasil.stdout)
    assert catatan == ["mulai a", "selesai a", "mulai b", "selesai b"]
    assert sibuk_saat_jalan is True and sibuk_sesudah is False


def test_the_poll_takes_its_turn_and_always_gives_it_back():
    refresh = fungsi("refresh")
    assert refresh.index("await kunciRefresh.giliran()") < refresh.index('api("/api/console/state")')
    assert refresh.rstrip().endswith("} finally {\n    lepas();\n  }\n}")


def test_a_timer_tick_is_dropped_while_a_pull_is_in_flight():
    detak = fungsi("detakRefresh")
    assert "kunciRefresh.sibuk()" in detak and "refresh()" in detak
    assert "setInterval(detakRefresh, JEDA_REFRESH_MS)" in HTML
    assert "setInterval(refresh," not in HTML
    for muat in ("muatTrucks", "muatTimbangan"):
        assert f"setInterval({muat}," not in HTML, f"{muat} piles up the same way"
    assert "setInterval(sekaliJalan(muatTrucks)" in HTML and "setInterval(sekaliJalan(muatTimbangan)" in HTML


@butuh_node
def test_a_guarded_timer_skips_while_the_last_run_is_still_going():
    import os
    import subprocess

    skrip = fungsi("sekaliJalan") + """
let jalan = 0, lepas;
const kerja = () => { jalan++; return new Promise((r) => { lepas = r; }); };
const detak = sekaliJalan(kerja);
(async () => {
  detak(); detak(); detak();
  const selama = jalan;
  lepas(); await new Promise((r) => setTimeout(r, 5));
  detak();
  console.log(JSON.stringify([selama, jalan]));
  lepas();
})();
"""
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30, env=dict(os.environ))
    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert json.loads(hasil.stdout) == [1, 2]


def test_every_request_has_a_time_limit():
    ambil = fungsi("ambil")
    assert "signal: AbortSignal.timeout(batasJawab(opts))" in ambil
    assert ambil.index("AbortSignal.timeout") < ambil.index("...opts"), "a caller's own signal still wins"


@butuh_node
@pytest.mark.parametrize(
    ("opts", "nama"),
    [("undefined", "BATAS_JAWAB_MS"), ("{}", "BATAS_JAWAB_MS"), ('{method:"GET"}', "BATAS_JAWAB_MS"),
     ('{method:"POST"}', "BATAS_JAWAB_UBAH_MS"), ('{method:"DELETE"}', "BATAS_JAWAB_UBAH_MS")],
)
def test_a_read_gives_up_sooner_than_a_write(opts, nama):
    batas = konstanta("BATAS_JAWAB_MS", "BATAS_JAWAB_UBAH_MS")
    assert jalankan(["batasJawab"], f"[batasJawab({opts}), {nama}]", tambahan=batas) == [
        {"BATAS_JAWAB_MS": 10000, "BATAS_JAWAB_UBAH_MS": 60000}[nama]
    ] * 2


def test_the_grading_table_has_one_source():
    """`/state` used to carry 20 `recent` rows nobody read while `/history` asked again."""
    assert "s.recent" not in HTML
