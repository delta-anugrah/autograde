"""Tab Log di console.html (batch 3.2 + 3.5): asal line, waktu pertama, traceback, lapor Discord.

Dua lapis, seperti `test_console_html_antrean_line.py`: invarian teks (kunci kamus dua
bahasa, markup, helper yang wajib dipakai) dan perilaku fungsi lewat node dengan
KAMUS asli (`tests/konsol_js.py`).
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

KUNCI_BARU = (
    "logKonsol", "logPertama", "discordMati", "discordUrlSalah", "discordAktif",
    "discordTertahan", "discordDitolak", "discordRusak",
)
FUNGSI = ["waktu", "waktuLog", "sumberLog", "pesanLog", "barisLog", "teksLaporDiscord"]
#: 2026-09-30 10:00:00 WIB
T = 1790737200


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kunci_baru_ada_di_dua_bahasa(bahasa):
    blok = _kamus(bahasa)
    for kunci in KUNCI_BARU:
        assert re.search(rf"\b{kunci}:", blok), f"{kunci} hilang di {bahasa}"


def test_markup_keadaan_discord_di_atas_tabel_log():
    sec = HTML.split('<section id="sec-log"', 1)[1].split("</section>", 1)[0]
    assert sec.index('id="log-discord"') < sec.index('id="log-baris"')


def test_muat_log_ikut_memuat_keadaan_discord():
    fungsi = HTML.split("async function muatLog() {", 1)[1].split("\n}", 1)[0]
    assert "muatLaporDiscord();" in fungsi
    assert '"/api/console/dev/lapor-discord"' in HTML


def test_semua_teks_baris_log_lewat_esc():
    for nama in ("sumberLog", "pesanLog"):
        badan = HTML.split(f"function {nama}(", 1)[1].split("\n}", 1)[0]
        assert "${esc(" in badan and "${r." not in badan


@butuh_node
def test_baris_line_membawa_tag_line_dan_baris_konsol_tag_konsol():
    hasil = jalankan(FUNGSI, '[sumberLog({line_code:"line-2", source:"palmgrade.x"}), sumberLog({line_code:null, source:"palmgrade.y"})]')
    assert hasil == [
        '<span class="log-asal">line-2</span>palmgrade.x',
        '<span class="log-asal">konsol</span>palmgrade.y',
    ]


@butuh_node
def test_traceback_bisa_dibuka_dan_di_escape():
    hasil = jalankan(FUNGSI, 'pesanLog({message:"grab <gagal>", detail:"Traceback\\nRuntimeError: <x>"})')
    assert hasil == (
        '<details class="log-detail"><summary>grab &lt;gagal&gt;</summary>'
        "<pre>Traceback\nRuntimeError: &lt;x&gt;</pre></details>"
    )
    assert jalankan(FUNGSI, 'pesanLog({message:"polos", detail:null})') == "polos"


@butuh_node
def test_waktu_pertama_tampil_hanya_untuk_baris_gabungan():
    gabungan = jalankan(FUNGSI, f"waktuLog({{logged_at:{T}, last_seen_at:{T + 600}}})")
    tunggal = jalankan(FUNGSI, f"waktuLog({{logged_at:{T}, last_seen_at:{T}.4}})")
    assert gabungan == '30/09/2026 10:10:00<div class="muted log-pertama">pertama 30/09/2026 10:00:00</div>'
    assert tunggal == "30/09/2026 10:00:00"


@butuh_node
@pytest.mark.parametrize(
    "data,kelas,potongan",
    [
        ({"keadaan": "mati"}, "muted", "mati (DISCORD_WEBHOOK_URL kosong)"),
        ({"keadaan": "url_salah"}, "gagal", "tidak diawali https"),
        ({"keadaan": "aktif", "terkirim_terakhir_at": T, "menunggu_kejadian": 3},
         "muted", "Terakhir terkirim 30/09/2026 10:00:00. 3 galat menunggu"),
        ({"keadaan": "tertahan", "galat": "Discord tidak terjangkau (ConnectError)", "galat_at": T, "kiriman": 2},
         "peringatan", "tertahan sejak 30/09/2026 10:00:00: Discord tidak terjangkau (ConnectError). 2 pesan"),
        ({"keadaan": "ditolak", "status_http": 404, "galat_at": T, "kiriman": 1},
         "gagal", "DITOLAK pukul 30/09/2026 10:00:00 (HTTP 404)"),
        ({"keadaan": "rusak", "galat": "lapor_discord.db tidak bisa dibuka (OSError)"},
         "gagal", "lapor_discord.db tidak bisa dibuka (OSError)"),
    ],
)
def test_kalimat_keadaan_discord_detail(data, kelas, potongan):
    hasil = jalankan(FUNGSI, f"teksLaporDiscord({json.dumps(data)})")
    assert hasil["kelas"] == kelas
    assert potongan in hasil["teks"]
    assert "{" not in hasil["teks"]


@butuh_node
def test_rusak_tanpa_field_lain_tidak_melempar():
    hasil = jalankan(FUNGSI, 'teksLaporDiscord({keadaan:"rusak", galat:"berkas rusak"})')
    assert hasil["kelas"] == "gagal"
    assert "berkas rusak" in hasil["teks"]
    assert "{" not in hasil["teks"]


@butuh_node
def test_rusak_tanpa_galat_tidak_melempar():
    hasil = jalankan(FUNGSI, 'teksLaporDiscord({keadaan:"rusak"})')
    assert hasil["kelas"] == "gagal"
    assert "{" not in hasil["teks"]


@butuh_node
def test_ditolak_menyebut_tindakan():
    hasil = jalankan(FUNGSI, 'teksLaporDiscord({keadaan:"ditolak", status_http:401, galat_at:1, kiriman:1})')
    assert "Periksa DISCORD_WEBHOOK_URL di .env PC ini, lalu autograde restart" in hasil["teks"]
