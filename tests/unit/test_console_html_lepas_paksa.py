"""Lepas paksa on a line card (2026-10-04): shown only while the line does not answer and
holds a truck, in place of Lepas, asked first, worded from codes.

Two layers like `test_console_html_sambung_ulang.py`: text invariants (always run) and
behaviour through node with the real KAMUS (`konsol_js`).
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan, kamus_asli

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

KUNCI = (
    "btnLepasPaksa", "lepasPaksaTitle", "konfirmasiLepasPaksaJudul", "konfirmasiLepasPaksa",
    "sukLepasPaksa", "gagalLepasPaksa",
)

TRUK = {"truck_id": "t-1", "plate_number": "BE 1 AA"}
MATI = {"reachable": False, "kode": "line_tidak_menjawab", "sebab_kode": "tak_terjangkau"}


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


def test_the_card_draws_the_release_button_through_one_slot():
    kartu = fungsi("kartuLine")
    assert '<span class="slot-lepas">${tombolLepas(l)}</span>' in kartu
    assert 'data-aksi="lepas"' not in kartu, "the button is drawn only by tombolLepas"


def test_the_slot_takes_no_room_of_its_own():
    assert re.search(r"\.slot-lepas\s*\{\s*display:contents;\s*\}", HTML)


def test_the_poll_redraws_the_slot_only_when_it_changes():
    assert 'tulisKalauBeda(c.querySelector(".slot-lepas"), tombolLepas(l))' in fungsi("perbaruiKartu")
    assert "perbaruiKartu(c, l)" in fungsi("refresh")


def test_the_click_asks_first_then_locks_then_posts():
    kerja = fungsi("lepasPaksa")
    assert kerja.index("tanyaKonfirmasi(") < kerja.index("denganSibuk(") < kerja.index("force-release")
    assert "bahaya: true" in kerja
    assert 'method: "POST"' in kerja
    assert 'gagalKarena("gagalLepasPaksa", e)' in kerja


def test_the_card_listener_hands_the_click_to_its_own_function():
    lines = HTML[HTML.index('$("lines").addEventListener("click"') :].split("\n});", 1)[0]
    cabang = lines[lines.index('"lepas-paksa"') :]
    assert cabang.index("lepasPaksa(kartu)") < cabang.index("return")


def _tombol(kartu: dict, *, bahasa: str = "id", berjalan: str = "") -> str:
    return jalankan(
        ["bisaLepasPaksa", "tombolLepas"], f"tombolLepas({json.dumps(kartu)})",
        bahasa=bahasa, tambahan=f"const lepasPaksaBerjalan = new Set([{berjalan}]);",
    )


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_a_silent_line_holding_a_truck_shows_force_release_in_the_final_danger_look(bahasa):
    html = _tombol({"line_code": "line-1", "assignment": TRUK, "plc": MATI}, bahasa=bahasa)
    kata = jalankan([], "KAMUS[bahasa].btnLepasPaksa", bahasa=bahasa)
    assert 'data-aksi="lepas-paksa"' in html and kata in html
    assert 'class="bahaya pekat"' in html
    assert 'data-aksi="lepas"' not in html, "in place of Lepas, which would only fail"
    assert "sibuk" not in html


@butuh_node
@pytest.mark.parametrize(
    "plc",
    [
        {"reachable": True},
        {"reachable": False, "kode": "line_menolak", "sebab_kode": "kunci_ditolak"},
        {"reachable": False, "sebab_kode": "line_galat"},
        {"reachable": False, "sebab_kode": "bukan_line"},
        {"reachable": False},
    ],
)
def test_a_line_that_answers_or_is_not_yet_read_keeps_the_normal_release(plc):
    html = _tombol({"line_code": "line-1", "assignment": TRUK, "plc": plc})
    assert 'data-aksi="lepas"' in html and "lepas-paksa" not in html
    assert " disabled" not in html


@butuh_node
def test_a_silent_line_without_a_truck_has_nothing_to_force():
    html = _tombol({"line_code": "line-1", "assignment": None, "plc": MATI})
    assert 'data-aksi="lepas"' in html and " disabled" in html
    assert "lepas-paksa" not in html


@butuh_node
def test_a_card_redrawn_mid_request_keeps_the_busy_mark():
    html = _tombol({"line_code": "line-1", "assignment": TRUK, "plc": MATI}, berjalan='"line-1"')
    assert 'class="bahaya pekat sibuk"' in html and 'aria-busy="true"' in html


_DOM = """
class Kelas { constructor(a) { this.s = new Set(a); } add(c) { this.s.add(c); }
  remove(c) { this.s.delete(c); } contains(c) { return this.s.has(c); } }
const tombol = { classList: new Kelas(), atribut: {}, setAttribute(k, v) { this.atribut[k] = v; },
  removeAttribute(k) { delete this.atribut[k]; } };
const kartu = { dataset: { line: "line-1" }, querySelector: (s) => (
  s === ".nama" ? { textContent: " Line 1 " } : s === ".truk .plat" ? { textContent: " BE 1 AA " } : tombol) };
const $ = () => ({ querySelectorAll: () => [kartu] });
const lepasPaksaBerjalan = new Set();
const dicatat = { tanya: [], api: [], sukses: [], peringatan: [], gagal: [], pasang: [], segar: 0 };
let jawabTanya = true, gagalApi = null, jawabApi = { paksa: true, dipasang: [] }, sibukSaatApi = null;
const tanyaKonfirmasi = async (o) => { dicatat.tanya.push(o); return jawabTanya; };
const api = async (url, o) => {
  sibukSaatApi = tombol.classList.contains("sibuk") && lepasPaksaBerjalan.has("line-1");
  dicatat.api.push([url, o.method]);
  if (gagalApi) throw gagalApi;
  return jawabApi;
};
const refresh = async () => { dicatat.segar++; };
const umumkanPasang = (d) => dicatat.pasang.push(d);
const toastSukses = (x) => dicatat.sukses.push(x);
const toastPeringatan = (x) => dicatat.peringatan.push(x);
const toastGagal = (x) => dicatat.gagal.push(x);
const gagalKarena = (k, e) => t(k) + ": " + e.kode;
"""


def _jalan(skenario: str) -> dict:
    skrip = "\n".join([
        kamus_asli(), 'let bahasa = "id";', "const t = (k) => KAMUS[bahasa][k] ?? k;", _DOM,
        fungsi("denganSibuk"), fungsi("tombolLepasPaksaDi"), fungsi("lepasPaksa"),
        f"(async () => {{ {skenario}",
        "console.log(JSON.stringify({ ...dicatat, sibukSaatApi, sisa: [...lepasPaksaBerjalan],"
        " sibukSesudah: tombol.classList.contains('sibuk') })); })();",
    ])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
def test_cancel_sends_nothing():
    hasil = _jalan("jawabTanya = false; await lepasPaksa(kartu);")
    assert (len(hasil["tanya"]), hasil["api"]) == (1, [])


@butuh_node
def test_the_question_says_what_happens_and_is_red():
    tanya = _jalan("jawabTanya = false; await lepasPaksa(kartu);")["tanya"][0]
    assert tanya["judul"] == "Lepas paksa truk dari Line 1?"
    assert "BE 1 AA" in tanya["pesan"] and "tidak menjawab" in tanya["pesan"]
    assert tanya["bahaya"] is True and tanya["ya"] == "Lepas paksa"


@butuh_node
def test_a_forced_release_posts_once_locked_then_warns_it_reached_the_console_only():
    hasil = _jalan("await lepasPaksa(kartu);")
    assert hasil["api"] == [["/api/console/lines/line-1/force-release", "POST"]]
    assert hasil["sibukSaatApi"] is True
    assert hasil["sukses"] == [] and len(hasil["peringatan"]) == 1
    assert "Line 1" in hasil["peringatan"][0]
    assert hasil["segar"] == 1 and hasil["pasang"] == [[]]
    assert (hasil["sisa"], hasil["sibukSesudah"]) == ([], False)


@butuh_node
def test_a_line_that_answered_after_all_is_a_plain_release_toast():
    hasil = _jalan("jawabApi = { paksa: false, dipasang: [] }; await lepasPaksa(kartu);")
    assert hasil["peringatan"] == [] and hasil["sukses"] == ["Truk dilepas dari Line 1"]


@butuh_node
def test_a_second_press_while_the_first_runs_is_ignored():
    hasil = _jalan("const p = lepasPaksa(kartu); await lepasPaksa(kartu); await p;")
    assert len(hasil["api"]) == 1


@butuh_node
def test_a_refusal_is_worded_from_its_code_and_the_lock_comes_off():
    hasil = _jalan(
        'gagalApi = Object.assign(new Error("x"), { kode: "line_menolak" }); await lepasPaksa(kartu);'
    )
    assert hasil["gagal"] == ["Lepas paksa gagal: line_menolak"]
    assert (hasil["sukses"], hasil["peringatan"], hasil["sisa"], hasil["sibukSesudah"]) == ([], [], [], False)
