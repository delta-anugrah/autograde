"""Status tab: support sees the training photo queue, worded, never raw errors.

The queue of clean grading photos waiting for the nexio inbox (R2 bucket `autograde-training`) gets
its own Status sub-tab `training` (ruling D2). Last Sync keeps its two rows; this queue is
support-only. Two layers, like `test_console_html_teks_ramah.py`: text invariants, and the
real `muatTraining()` run through node with the real KAMUS and the real row helpers.
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest
from konsol_js import HTML, NODE, esc_asli, fungsi, kamus_asli, konstanta

KEYS = ("judulTraining", "ringkasTraining", "trainingNonaktif", "kosongTraining", "gagalTraining")
ENDPOINT = "/api/console/dev/antrean/training"
JAM = 1_789_873_200  # 2026-09-20 10:00:00 in Asia/Jakarta

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")


def _panel() -> str:
    status = HTML.split('<section id="sec-status"', 1)[1].split("</section>", 1)[0]
    return status.split('<div class="status-bagian" data-status-sub="training"', 1)[1]


def _kamus(bahasa: str) -> dict[str, str]:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', blok.group(1)))


def _esc(teks: str) -> str:
    ganti = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;"}
    return "".join(ganti.get(c, c) for c in teks)


# ── text invariants ─────────────────────────────────────────────────────


def test_markup_ids_exist_in_their_own_sub_tab():
    panel = _panel()
    for el in ("training-nonaktif", "training-ringkas", "training-baris"):
        assert f'id="{el}"' in panel, el
    assert 'id="training-nonaktif" hidden' in panel, "the not-configured message starts hidden"


def test_both_languages_have_every_key():
    for key in KEYS:
        assert len(re.findall(rf"\b{key}:", HTML)) == 2, key


def test_loaded_with_the_other_queues():
    body = HTML[HTML.index("async function muatAntrean"):HTML.index("async function muatManifest")]
    assert "muatTraining()" in body
    assert f'api("{ENDPOINT}")' in fungsi("muatTraining")


def test_rows_are_worded_by_the_shared_helper_naming_r2():
    """`barisAntrean` turns `error_kind` into a sentence; `last_error` never reaches the screen."""
    fn = fungsi("muatTraining")
    assert 'barisAntrean(x, "R2")' in fn
    assert "last_error" not in fn


def test_last_sync_does_not_show_the_training_queue():
    """Rule 27: Last Sync keeps exactly two rows; this queue is for support on Status only."""
    for nama in re.findall(r"function (\w*[Ss]ync\w*)\(", HTML):
        assert "training" not in fungsi(nama).lower(), nama


# ── behaviour through node ──────────────────────────────────────────────


def _muat(jawaban: dict | None = None, *, galat: dict | None = None, bahasa: str = "id") -> dict:
    """Run the real `muatTraining()` with `api` answering `jawaban` (or throwing `galat`)."""
    skrip = "\n".join([
        kamus_asli(),
        esc_asli(),
        f"let bahasa = {json.dumps(bahasa)};",
        'const KOSONG = "-";',
        "const t = (k) => KAMUS[bahasa][k] ?? k;",
        konstanta("dash", "barisKosong"),
        "const el = {};",
        'const $ = (id) => (el[id] ??= { hidden: id === "training-nonaktif", textContent: "awal", innerHTML: "awal" });',
        "const dipanggil = [];",
        f"const JAWABAN = {json.dumps(jawaban)};",
        f"const GALAT = {json.dumps(galat)};",
        "const api = async (url) => { dipanggil.push(url);"
        " if (GALAT) throw Object.assign(new Error(GALAT.message), GALAT); return JAWABAN; };",
        *(fungsi(n) for n in ("waktu", "jadwalAntrean", "sebabAntrean", "barisAntrean", "muatTraining")),
        "muatTraining().then(() => console.log(JSON.stringify({ el, dipanggil })));",
    ])
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30,
                           env={"PATH": "", "TZ": "Asia/Jakarta"})
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout.strip())


def _baris(kind: str, key: str, jenis: str | None, mentah: str) -> dict:
    return {"kind": kind, "key": key, "last_error": mentah, "error_kind": jenis,
            "attempts": 3, "next_attempt_at": 0}


@butuh_node
def test_not_configured_reads_as_its_own_message_not_as_zeros():
    hasil = _muat({"aktif": False})
    assert hasil["dipanggil"] == [ENDPOINT]
    assert hasil["el"]["training-nonaktif"]["hidden"] is False
    assert hasil["el"]["training-ringkas"]["textContent"] == ""
    assert hasil["el"]["training-baris"]["innerHTML"] == ""


@butuh_node
def test_failed_rows_are_worded_from_their_kind_never_the_raw_error():
    jawaban = {"aktif": True, "pending": 12, "gagal": 2, "terakhir_terkirim": JAM, "items": [
        _baris("line-1", "ev-0001", "tak_terjangkau", "Could not connect to the endpoint URL: https://x"),
        _baris("line-2", "ev-0002", "kunci_ditolak", "An error occurred (InvalidAccessKeyId) 403"),
    ]}
    hasil = _muat(jawaban)
    el = hasil["el"]
    kamus = _kamus("id")
    assert el["training-nonaktif"]["hidden"] is True
    assert el["training-ringkas"]["textContent"] == "12 menunggu · 2 gagal · terakhir terkirim 20/09/2026 10:00:00"
    html = el["training-baris"]["innerHTML"]
    assert html.count("<tr>") == 2
    for teks in ("line-1", "ev-0001", "line-2", "ev-0002"):
        assert teks in html
    assert _esc(kamus["antreanSebab_tak_terjangkau"].replace("{tujuan}", "R2")) in html
    assert _esc(kamus["antreanSebab_kunci_ditolak"].replace("{tujuan}", "R2")) in html
    for mentah in ("endpoint", "https", "InvalidAccessKeyId", "403"):
        assert mentah not in html, mentah


@butuh_node
def test_nothing_sent_yet_shows_a_dash_for_the_time():
    hasil = _muat({"aktif": True, "pending": 0, "gagal": 0, "terakhir_terkirim": None, "items": []})
    assert hasil["el"]["training-ringkas"]["textContent"] == "0 menunggu · 0 gagal · terakhir terkirim -"
    assert _esc(_kamus("id")["kosongTraining"]) in hasil["el"]["training-baris"]["innerHTML"]


@butuh_node
def test_summary_in_english():
    hasil = _muat({"aktif": True, "pending": 3, "gagal": 1, "terakhir_terkirim": JAM, "items": []}, bahasa="en")
    assert hasil["el"]["training-ringkas"]["textContent"] == "3 pending · 1 failed · last sent 20/09/2026 10:00:00"


@butuh_node
def test_unreadable_queue_says_so_without_the_raw_error_and_drops_stale_counts():
    hasil = _muat(galat={"kode": "galat_server", "message": "Traceback: sqlite3.OperationalError"})
    el = hasil["el"]
    assert el["training-nonaktif"]["hidden"] is True
    assert el["training-ringkas"]["textContent"] == ""
    html = el["training-baris"]["innerHTML"]
    assert _esc(_kamus("id")["gagalTraining"]) in html
    assert "sqlite3" not in html and "Traceback" not in html


@butuh_node
def test_logged_out_leaves_the_card_alone():
    """`belum_masuk` sends the screen to the login; the card is not repainted as a failure."""
    hasil = _muat(galat={"kode": "belum_masuk", "message": "401"})
    assert hasil["dipanggil"] == [ENDPOINT]
    assert hasil["el"] == {}, "no element of the card was touched"
