"""Antrean bongkar di atas kartu line, toast penugasan, dan saklar di Setelan (2026-10-01).

Antrean bongkar = truk yang sudah timbang isi tapi belum di line. Bukan "antrean line"
(kiriman line ke konsol di tab Status, `test_console_html_antrean_line.py`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

KUNCI_BARU = (
    "grupPenugasan",
    "labelOtomatis",
    "bantuOtomatis",
    "labelLineOtomatis",
    "btnSimpanPenugasan",
    "penugasanTersimpan",
    "antreanBongkarOtomatis",
    "antreanBongkarManual",
    "btnTugaskanSekarang",
    "btnLewati",
    "konfirmasiLewati",
    "sukLewati",
    "sukDitugaskanOtomatis",
    "tugaskanGagalLine",
)

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const t = (k) => k;
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _jalankan(ekspresi: str, *fungsi: str):
    skrip = _STUB + "".join(_fungsi(f) for f in fungsi) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def _blok(jangkar: str) -> str:
    awal = HTML.index(jangkar)
    return HTML[awal : HTML.index("\n}", awal + len(jangkar))]


def test_strip_antrean_di_antara_pita_dan_kartu_line():
    assert HTML.index('id="pita-disk"') < HTML.index('id="antrean-bongkar"') < HTML.index('id="lines"')
    assert re.search(r'<div id="antrean-bongkar"[^>]*hidden', HTML)


def test_refresh_menggambar_antrean():
    awal = HTML.index("async function refresh()")
    blok = HTML[awal : HTML.index("\n}\n", awal)]
    assert "gambarAntreanBongkar(s.antrean_bongkar, s.penugasan_otomatis)" in blok


def test_strip_ditulis_lewat_tulis_kalau_beda():
    assert "tulisKalauBeda(" in _fungsi("gambarAntreanBongkar")


def test_tombol_antrean_memakai_jalur_baru_dan_terkunci():
    awal = HTML.index('$("antrean-bongkar").addEventListener("click"')
    blok = HTML[awal : HTML.index("\n});", awal)]
    assert "/api/console/unloading-queue/" in blok and "/assign" in blok and "/skip" in blok
    assert "denganSibuk(" in blok
    assert "confirm(" in blok, "Lewati harus ditanya dulu"


def test_jawaban_timbang_tara_dan_lepas_diumumkan():
    for jangkar in (
        '$("masuk").addEventListener("click"',
        "async function simpanTara()",
        '$("lines").addEventListener("click"',
    ):
        assert "umumkanPasang(" in _blok(jangkar), f"{jangkar} tidak mengumumkan penugasan otomatis"


def test_tidak_ada_dipasang_baru_di_tingkat_atas():
    # `let dipasang` sudah berarti "kartu line sudah digambar" (refresh); jawaban server
    # yang bernama sama dibaca lewat `r.dipasang`, tidak pernah jadi variabel global.
    assert len(re.findall(r"^(?:let|const|var) dipasang\b", HTML, re.M)) == 1
    assert not re.search(r"^\s*dipasang\s*=\s*r\.", HTML, re.M)


def test_saklar_penugasan_di_setelan_dengan_tombol_sendiri():
    setelan = HTML.split('<section id="sec-setelan"', 1)[1].split("</section>", 1)[0]
    for id_ in ("set-otomatis", "set-otomatis-lines", "set-penugasan-simpan", "set-penugasan-pesan"):
        assert f'id="{id_}"' in setelan
    assert "/api/console/dev/auto-assign" in _fungsi("muatPenugasan")
    assert "await muatPenugasan()" in _fungsi("muatSetelan")


def test_pesan_penugasan_bergaya_seperti_pesan_setelan():
    assert re.search(r"#set-pesan:not\(:empty\),\s*#set-penugasan-pesan:not\(:empty\)", HTML)


def test_simpan_penugasan_memakai_kalimatnya_sendiri():
    awal = HTML.index('$("set-penugasan-simpan").addEventListener("click"')
    blok = HTML[awal : HTML.index("\n}));", awal)]
    assert 't("penugasanTersimpan")' in blok and "setelanTersimpan" not in blok
    assert "denganSibuk(" in blok


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_baru_ada_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    for kunci in KUNCI_BARU:
        assert f"{kunci}:" in isi, f"KAMUS.{bahasa} belum punya {kunci}"


def test_kata_antrean_bongkar_bukan_antrean_line():
    assert "Antrean bongkar" in _kamus("id") and "Unloading queue" in _kamus("en")


@butuh_node
def test_teks_menit_seperti_kolom_lama():
    assert _jalankan(
        "[teksMenit(0), teksMenit(25), teksMenit(60), teksMenit(105), teksMenit(null), teksMenit(-3)]",
        "teksMenit",
    ) == ["0 mnt", "25 mnt", "1 j", "1 j 45 mnt", None, None]


@butuh_node
def test_strip_kosong_tanpa_antrean():
    assert _jalankan("htmlAntreanBongkar([], true)", "teksMenit", "htmlAntreanBongkar") == ""
    assert _jalankan("htmlAntreanBongkar(undefined, false)", "teksMenit", "htmlAntreanBongkar") == ""


@butuh_node
def test_strip_menyebut_plat_menit_dan_dua_tombol():
    html = _jalankan(
        'htmlAntreanBongkar([{weighing_id:"w<1>", plate_number:"BE 1 AA", menit:12}], true)',
        "teksMenit",
        "htmlAntreanBongkar",
    )
    assert "antreanBongkarOtomatis" in html and "BE 1 AA" in html and "12 mnt" in html
    assert 'data-aksi="pasang"' in html and 'data-aksi="lewati"' in html
    assert "w&lt;1&gt;" in html, "id tiket harus lewat esc()"


@butuh_node
def test_strip_manual_saat_saklar_mati():
    html = _jalankan(
        'htmlAntreanBongkar([{weighing_id:"w1", plate_number:"BE 1 AA", menit:0}], false)',
        "teksMenit",
        "htmlAntreanBongkar",
    )
    assert "antreanBongkarManual" in html and "antreanBongkarOtomatis" not in html
    assert "0 mnt" in html
