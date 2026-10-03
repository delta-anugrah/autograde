"""Riwayat Batal datang on the Timbangan tab (round 4, user 2026-10-03).

A collapsible panel under the Timbangan table: "Kedatangan dibatalkan (n)", hidden when n
is 0; open it shows Plat, Jam datang, Jam dibatalkan, Oleh. The rows come from
`GET /api/console/weighings` (`dibatalkan`); the screen only formats the times (L4), writes
through `tulisKalauBeda` (F9) and escapes every server string (F7). The `<details>` element
itself is never rewritten, so its open state survives the 15 s poll.
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

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const t = (k) => k;
"""
KUNCI = ("riwayatBatalJudul", "thJamDatang", "thJamBatal", "thOleh", "thPlat")


def _fungsi(nama: str) -> str:
    awal = re.search(rf"(async )?function {nama}\(", HTML).start()
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> dict[str, str]:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)
    return dict(re.findall(r'(\w+):\s*"((?:[^"\\]|\\.)*)"', blok))


def _jalankan(ekspresi: str, *fungsi: str):
    skrip = _STUB + "".join(_fungsi(f) for f in fungsi) + f"\nprocess.stdout.write(JSON.stringify({ekspresi}));"
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def _panel() -> str:
    awal = HTML.index('<details id="riwayat-batal"')
    return HTML[awal : HTML.index("</details>", awal)]


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kata_panel_ada_di_kedua_bahasa(bahasa):
    kamus = _kamus(bahasa)
    assert all(kamus.get(k) for k in KUNCI), [k for k in KUNCI if not kamus.get(k)]
    assert "{n}" in kamus["riwayatBatalJudul"]


def test_kata_panel_dua_bahasa_persis():
    id_, en = _kamus("id"), _kamus("en")
    assert (id_["riwayatBatalJudul"], en["riwayatBatalJudul"]) == (
        "Kedatangan dibatalkan ({n})", "Cancelled arrivals ({n})")
    assert (id_["thJamDatang"], id_["thJamBatal"], id_["thOleh"]) == ("Jam datang", "Jam dibatalkan", "Oleh")
    assert (en["thJamDatang"], en["thJamBatal"], en["thOleh"]) == ("Arrived at", "Cancelled at", "By")


def test_panel_di_bawah_tabel_timbangan_tersembunyi_sampai_ada_isi():
    tab = HTML[HTML.index('<section id="sec-timbangan"') : HTML.index('<section id="sec-rekap"')]
    assert tab.index('<tbody id="timbangan">') < tab.index('<details id="riwayat-batal"')
    assert re.search(r'<details id="riwayat-batal"[^>]*\shidden[\s>]', HTML)
    panel = _panel()
    assert '<summary id="riwayat-batal-judul"' in panel
    assert '<tbody id="riwayat-batal-isi">' in panel
    kolom = re.findall(r'<th[^>]*data-t="(\w+)"', panel)
    assert kolom == ["thPlat", "thJamDatang", "thJamBatal", "thOleh"]


def test_muat_timbangan_menggambar_riwayat_dari_payload():
    assert "gambarRiwayatBatal(data.dibatalkan)" in _fungsi("muatTimbangan")


def test_poll_tidak_menulis_ulang_details_hanya_judul_dan_isi():
    fungsi = _fungsi("gambarRiwayatBatal")
    assert 'tulisKalauBeda($("riwayat-batal-judul")' in fungsi
    assert 'tulisKalauBeda($("riwayat-batal-isi")' in fungsi
    assert ".hidden" in fungsi
    # The <details> element keeps its `open` attribute only while nobody rebuilds it.
    assert "innerHTML" not in fungsi and "outerHTML" not in fungsi and ".open" not in fungsi


def test_kolom_terakhir_riwayat_tidak_ikut_dipaku():
    """Round 3 trap: a global rule (`.jam { display:flex }`) reshaped a table cell. Here the
    one that reaches in is `#sec-timbangan td:last-child` (the pinned row-button column): the
    history's Oleh column must stay a plain cell."""
    css = HTML[HTML.index("<style") : HTML.index("</style>")]
    aturan = re.search(r"#sec-timbangan \.riwayat-batal th:last-child,\s*"
                       r"#sec-timbangan \.riwayat-batal td:last-child:not\(\.kosong\)\s*\{([^}]*)\}", css)
    assert aturan, "no override for the pinned last column"
    assert "position:static" in aturan.group(1) and "border-left:0" in aturan.group(1)


@butuh_node
def test_baris_riwayat_meloloskan_teks_server_lewat_esc():
    hasil = _jalankan(
        'barisBatal({plate_number:"BE<1>", arrived_at:"bukan jam <b>", cancelled_at:null,'
        ' cancelled_by:"op\\"@x<y>"})',
        "waktu", "waktuDuaBaris", "barisBatal",
    )
    assert "<1>" not in hasil and "BE&lt;1&gt;" in hasil
    assert "<b>" not in hasil and "&lt;b&gt;" in hasil
    assert "op&quot;@x&lt;y&gt;" in hasil
    assert hasil.count("<td") == 4


@butuh_node
def test_baris_riwayat_jam_dua_baris_seperti_tabel_timbangan():
    hasil = _jalankan(
        'barisBatal({plate_number:"BE 1 AA", arrived_at:"2026-10-03T01:00:00Z",'
        ' cancelled_at:"2026-10-03T01:05:00Z", cancelled_by:"op@pks.test"})',
        "waktu", "waktuDuaBaris", "barisBatal",
    )
    assert hasil.count('class="sel-waktu"') == 2 and hasil.count('class="tgl"') == 2
    assert 'class="key">BE 1 AA<' in hasil and ">op@pks.test<" in hasil


@butuh_node
def test_oleh_menampilkan_nama_dan_email_jadi_title():
    """Oleh = the stored name (user 2026-10-03); the email is the cell's `title`. No stored
    name (an older row, an empty name) = the email, as before."""
    dasar = 'plate_number:"BE 1 AA", arrived_at:null, cancelled_at:null, cancelled_by:"op@pks.test"'
    nama = _jalankan(f'barisBatal({{{dasar}, cancelled_by_name:"Budi Santoso"}})',
                     "waktu", "waktuDuaBaris", "barisBatal")
    assert '<td title="op@pks.test">Budi Santoso</td>' in nama and ">op@pks.test<" not in nama
    for kosong in ("null", '""', "undefined"):
        tanpa = _jalankan(f"barisBatal({{{dasar}, cancelled_by_name:{kosong}}})",
                          "waktu", "waktuDuaBaris", "barisBatal")
        assert "<td>op@pks.test</td>" in tanpa and "title=" not in tanpa, kosong


@butuh_node
def test_nama_dan_email_lolos_esc():
    hasil = _jalankan(
        'barisBatal({plate_number:"BE 1 AA", arrived_at:null, cancelled_at:null,'
        ' cancelled_by:"a\\"b<c>@x", cancelled_by_name:"<img src=x onerror=1>"})',
        "waktu", "waktuDuaBaris", "barisBatal",
    )
    assert "<img" not in hasil and "&lt;img src=x onerror=1&gt;" in hasil
    assert 'title="a&quot;b&lt;c&gt;@x"' in hasil and hasil.count("<td") == 4
