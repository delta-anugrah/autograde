"""Sambung ulang (reconnect camera) on every line card, for every account (user 2026-10-04).

The line already reconnects by itself; this button is the spare for when it does not.
Two layers like `test_console_html_restart.py`: text invariants (always run) and
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
    "btnSambungUlang", "sambungUlangTitle", "konfirmasiSambungUlangJudul", "konfirmasiSambungUlang",
    "sukSambungUlang", "gagalSambungUlang", "err_kamera_tanpa_sambung_ulang",
)


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_every_word_is_in_both_languages(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} misses {kunci}"


def test_the_button_sits_under_the_camera_dropped_notice():
    """User 2026-10-04: in the header it was too big; it belongs where the picture is missing,
    under "Kamera tidak tersambung", so it only shows when there is something to reconnect."""
    kartu = fungsi("kartuLine")
    kepala = kartu[kartu.index("<h2>") : kartu.index("</h2>")]
    assert "tombolSambungUlang" not in kepala
    putus = re.search(r'<div class="feed-putus"><span>\$\{esc\(t\("kameraPutus"\)\)\}</span>\$\{tombolSambungUlang\(l\)\}</div>', kartu)
    assert putus, kartu[kartu.index('<div class="feed">') :][:300]


def test_the_notice_and_button_show_only_when_the_camera_dropped():
    assert re.search(r"\n  \.feed-putus \{[^}]*display:none", HTML)
    assert re.search(r"\n  \.card\.putus \.feed-putus \{ display:flex; \}", HTML)


def test_the_button_is_a_44px_touch_target():
    aturan = re.search(r"\.feed-putus button\.sambung-ulang\s*\{([^}]*)\}", HTML).group(1).replace(" ", "")
    assert "min-height:44px" in aturan


def test_the_click_asks_first_then_locks_then_posts():
    kerja = fungsi("sambungUlangKamera")
    assert kerja.index("tanyaKonfirmasi(") < kerja.index("denganSibuk(") < kerja.index("reconnect-camera")
    assert 'method: "POST"' in kerja
    assert "toastSukses(" in kerja and 'gagalKarena("gagalSambungUlang", e)' in kerja


def test_the_card_listener_hands_the_click_to_its_own_function():
    lines = HTML[HTML.index('$("lines").addEventListener("click"') :].split("\n});", 1)[0]
    cabang = lines[lines.index('"sambung-ulang"') :]
    assert cabang.index("sambungUlangKamera(kartu)") < cabang.index("return")


@butuh_node
@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_the_button_carries_its_word_and_no_busy_mark_when_idle(bahasa):
    html = jalankan(
        ["tombolSambungUlang"], 'tombolSambungUlang({ line_code: "line-1" })',
        bahasa=bahasa, tambahan="const sambungUlangBerjalan = new Set();",
    )
    kata = jalankan([], 'KAMUS[bahasa].btnSambungUlang', bahasa=bahasa)
    assert 'data-aksi="sambung-ulang"' in html and kata in html
    assert "sibuk" not in html and "aria-busy" not in html
    assert "<svg" in html


@butuh_node
def test_a_card_redrawn_mid_request_keeps_the_busy_mark():
    """A language switch or login rebuilds every card while the request may still run."""
    html = jalankan(
        ["tombolSambungUlang"], 'tombolSambungUlang({ line_code: "line-1" })',
        tambahan='const sambungUlangBerjalan = new Set(["line-1"]);',
    )
    assert 'class="sambung-ulang sibuk"' in html and 'aria-busy="true"' in html


_DOM = """
class Kelas { constructor(a) { this.s = new Set(a); } add(c) { this.s.add(c); }
  remove(c) { this.s.delete(c); } contains(c) { return this.s.has(c); } }
const tombol = { classList: new Kelas(), atribut: {}, setAttribute(k, v) { this.atribut[k] = v; },
  removeAttribute(k) { delete this.atribut[k]; } };
const kartu = { dataset: { line: "line-1" }, querySelector: (s) => (s === ".nama" ? { textContent: " Line 1 " } : tombol) };
const $ = () => ({ querySelectorAll: () => [kartu] });
const sambungUlangBerjalan = new Set();
const dicatat = { tanya: 0, api: [], sukses: [], gagal: [] };
let jawabTanya = true, gagalApi = null, sibukSaatApi = null;
const tanyaKonfirmasi = async (o) => { dicatat.tanya++; dicatat.judul = o.judul; return jawabTanya; };
const api = async (url, o) => {
  sibukSaatApi = tombol.classList.contains("sibuk") && sambungUlangBerjalan.has("line-1");
  dicatat.api.push([url, o.method]);
  if (gagalApi) throw gagalApi;
  return { status: "requested" };
};
const toastSukses = (x) => dicatat.sukses.push(x);
const toastGagal = (x) => dicatat.gagal.push(x);
const gagalKarena = (k, e) => t(k) + ": " + e.kode;
"""


def _jalan(skenario: str) -> dict:
    """Run `skenario` (async) against the real three functions and the real KAMUS."""
    skrip = "\n".join([
        kamus_asli(), 'let bahasa = "id";', "const t = (k) => KAMUS[bahasa][k] ?? k;", _DOM,
        fungsi("denganSibuk"), fungsi("tombolSambungUlangDi"), fungsi("sambungUlangKamera"),
        f"(async () => {{ {skenario}",
        "console.log(JSON.stringify({ ...dicatat, sibukSaatApi, sisa: [...sambungUlangBerjalan],"
        " sibukSesudah: tombol.classList.contains('sibuk') })); })();",
    ])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


@butuh_node
def test_cancel_sends_nothing():
    hasil = _jalan("jawabTanya = false; await sambungUlangKamera(kartu);")
    assert (hasil["tanya"], hasil["api"], hasil["sukses"]) == (1, [], [])


@butuh_node
def test_yes_posts_once_with_the_lock_on_then_toasts():
    hasil = _jalan("await sambungUlangKamera(kartu);")
    assert hasil["api"] == [["/api/console/lines/line-1/reconnect-camera", "POST"]]
    assert hasil["judul"] == "Sambung ulang kamera Line 1?"
    assert hasil["sibukSaatApi"] is True
    assert hasil["sukses"] and "Line 1" in hasil["sukses"][0]
    assert (hasil["sisa"], hasil["sibukSesudah"]) == ([], False)


@butuh_node
def test_a_second_press_while_the_first_runs_is_ignored():
    hasil = _jalan("const p = sambungUlangKamera(kartu); await sambungUlangKamera(kartu); await p;")
    assert len(hasil["api"]) == 1


@butuh_node
def test_a_refusal_is_worded_from_its_code_and_the_lock_comes_off():
    hasil = _jalan(
        'gagalApi = Object.assign(new Error("x"), { kode: "kamera_tanpa_sambung_ulang" });'
        " await sambungUlangKamera(kartu);"
    )
    assert hasil["gagal"] == ["Sambung ulang kamera gagal: kamera_tanpa_sambung_ulang"]
    assert (hasil["sukses"], hasil["sisa"], hasil["sibukSesudah"]) == ([], [], False)


def test_the_header_no_longer_needs_a_narrow_layout_for_the_button():
    assert "button.sambung-ulang > span { display:none; }" not in HTML
    assert ".card h2 button.sambung-ulang" not in HTML

def test_a_camera_that_stopped_sending_also_gets_the_button():
    """FRAME_BERHENTI: the camera is open but silent, the last frame stays on screen, and the
    browser never marks the card `putus`. That is the case the button exists for."""
    assert re.search(r"\n  \.card\.frame-berhenti \.feed-putus \{ display:flex; \}", HTML)
    kartu = fungsi("kartuLine")
    assert '${frameBerhenti(l) ? " frame-berhenti" : ""}' in kartu
    berhenti = fungsi("frameBerhenti")
    assert 'keadaan === "frame_berhenti"' in berhenti and "reachable" in berhenti
