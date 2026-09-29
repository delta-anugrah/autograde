"""Tab Status → Antrean line di console.html (batch 2.4).

Dua lapis, sama dengan `test_console_html_rapikan_support.py`:

- invarian teks, selalu jalan: tempat bagian ini, kunci kamus dua bahasa, timer,
  dan helper yang wajib dipakai (`tulisKalauBeda`, `denganSibuk`, `alasan`, `esc`);
- perilaku fungsi lewat node: fungsi yang SAMA dengan yang dipakai layar.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from palmgrade.domain.kirim_antrean_line import JEDA_SAMBUNGAN_MAKS_S

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

KUNCI_BARU = (
    "judulAntreanLine", "thMenunggu", "thTertua", "thKeadaan", "kosongAntreanLine", "gagalAntreanLine",
    "antreanLineKosong", "antreanLineMengirim", "antreanLineNonaktif", "antreanLineLamaTertinggal",
    "antreanLinePutus_tak_terjangkau", "antreanLinePutus_kunci_ditolak", "antreanLinePutus_alamat_salah",
    "antreanLinePutus_konsol_galat", "antreanLineKunciKonsol", "antreanLineTakTerjangkau",
    "antreanLineErrorLine",
    "antreanLineDikirimUlang", "antreanLineGagalKirimUlang",
    "saranKunciLine", "saranLineMati", "saranMuatUlang", "saranBukaLog",
)

# Pembantu render yang dipakai fungsi-fungsi di bawah. `t` membaca kamus kecil milik
# test (kunci lain dipulangkan apa adanya): yang diuji kunci mana yang dipilih dan
# placeholder mana yang terisi, bukan terjemahannya.
_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const KAMUS_UJI = {
  antreanLinePutus_tak_terjangkau: "putus sejak {sejak}",
  antreanLineKunciKonsol: "kunci ditolak HTTP {status}",
  antreanLineErrorLine: "line menjawab HTTP {status}",
  antreanLineGagalKirimUlang: "Kirim Ulang {line} gagal pukul {jam} (kode {kode}): {alasan}. {saran}",
};
const t = (k) => KAMUS_UJI[k] ?? k;
const alasan = (e) => e.message;
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _konstanta(nama: str) -> str:
    return re.search(rf"^const {nama} = .*?;$", HTML, re.M).group(0)


def _jalankan(ekspresi: str, *fungsi: str, konstanta: tuple[str, ...] = ()):
    skrip = (
        _STUB
        + "\n".join(_konstanta(k) for k in konstanta)
        + "\n"
        + "\n".join(_fungsi(f) for f in fungsi)
        + f"\nconsole.log(JSON.stringify({ekspresi}));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout.strip())


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


# ── invarian teks ───────────────────────────────────────────────────────


def test_bagian_antrean_line_di_antara_diagnostik_dan_antrean_erp():
    panel = HTML.split('<section id="sec-status"', 1)[1].split("</section>", 1)[0]
    posisi = [panel.index(f'id="{i}"') for i in ("diagnostik-kartu", "antrean-line-baris", "antrean-baris")]
    assert posisi == sorted(posisi)


def test_dimuat_saat_tab_status_dibuka_dan_disegarkan_5_detik():
    assert "muatAntreanLine()" in _fungsi("muatStatus")
    buka = _fungsi("bukaTabDev")
    assert "clearInterval(antreanLineTimer)" in buka
    assert 'antreanLineTimer = setInterval(muatAntreanLine, 5000)' in buka
    assert "let antreanLineTimer = null;" in HTML


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kunci_kamus_ada_di_dua_bahasa(bahasa):
    blok = _kamus(bahasa)
    hilang = [k for k in KUNCI_BARU if f"{k}:" not in blok]
    assert not hilang, hilang


def test_jeda_di_kalimat_layar_sama_dengan_jeda_worker():
    """Layar menjanjikan "tiap 30 detik"; kalau konstanta worker berubah, kalimatnya ikut."""
    assert JEDA_SAMBUNGAN_MAKS_S == 30
    assert "tiap 30 detik" in re.search(r'antreanLinePutus_tak_terjangkau:"([^"]*)"', _kamus("id")).group(1)
    assert "every 30 seconds" in re.search(r'antreanLinePutus_tak_terjangkau:"([^"]*)"', _kamus("en")).group(1)


def test_tabel_ditulis_hanya_kalau_berubah():
    """Disegarkan tiap 5 detik: tombol yang diganti di tengah ketukan menelan ketukannya."""
    muat = _fungsi("muatAntreanLine")
    assert "tulisKalauBeda(" in muat
    assert "innerHTML" not in muat


def test_kirim_ulang_memakai_denganSibuk_dan_pesan_detail():
    klik = HTML.split('$("antrean-line-baris").addEventListener("click"', 1)[1].split("\n});", 1)[0]
    assert "denganSibuk(tombol" in klik
    assert '/kirim-ulang`, { method: "POST" }' in klik
    assert "toastGagal(pesanGagalKirimUlang(e, kode, new Date()))" in klik
    assert 'e.kode !== "belum_masuk"' in klik


def test_isi_baris_selalu_lewat_esc():
    fn = _fungsi("barisAntreanLine")
    for isi in ("esc(kode)", "esc(keadaan)", "esc(pesanBaris)"):
        assert isi in fn, isi


# ── perilaku lewat node ─────────────────────────────────────────────────

_SEHAT = {"terjangkau": True, "aktif": True, "lama_tertinggal": False, "menunggu": 3, "tersambung": True}


@butuh_node
@pytest.mark.parametrize(
    "d,kunci",
    [
        ({"terjangkau": False, "kode": "line_menolak", "status": 401}, "antreanLineKunciKonsol"),
        ({"terjangkau": False, "kode": "line_tidak_menjawab"}, "antreanLineTakTerjangkau"),
        # Line-side error (a 500) or an old line answering 404: a status came back,
        # so the line itself is reachable, this is NOT "the line is down".
        ({"terjangkau": False, "kode": "line_tidak_menjawab", "status": 500}, "antreanLineErrorLine"),
        ({"terjangkau": False, "kode": "line_tidak_menjawab", "status": 404}, "antreanLineErrorLine"),
        ({**_SEHAT, "aktif": False}, "antreanLineNonaktif"),
        ({**_SEHAT, "lama_tertinggal": True}, "antreanLineLamaTertinggal"),
        ({**_SEHAT, "menunggu": 0, "tersambung": False, "sebab_putus": "kunci_ditolak"}, "antreanLineKosong"),
        ({**_SEHAT, "tersambung": False, "sebab_putus": "kunci_ditolak"}, "antreanLinePutus_kunci_ditolak"),
        ({**_SEHAT, "tersambung": False, "sebab_putus": "sebab_baru_dari_versi_lain"}, "antreanLinePutus_tak_terjangkau"),
        (_SEHAT, "antreanLineMengirim"),
        ({**_SEHAT, "tersambung": None}, "antreanLineMengirim"),
    ],
)
def test_keadaan_dipilih_dari_yang_paling_perlu_tindakan(d, kunci):
    assert _jalankan(f"keadaanAntreanLine({json.dumps(d)}).kunci", "keadaanAntreanLine") == kunci


def _baris(kode: str, d: dict, sekarang_ms: int) -> str:
    return _jalankan(
        f"barisAntreanLine({json.dumps(kode)}, {json.dumps(d)}, {sekarang_ms})",
        "keadaanAntreanLine", "barisAntreanLine", "waktu", "lamaProses",
    )


@butuh_node
def test_baris_line_sehat_punya_tombol_dan_umur_tertua():
    tertua = 1_789_873_200
    html = _baris("line-1", {**_SEHAT, "tertua_at": tertua}, (tertua + 3 * 3600 + 5 * 60) * 1000)
    assert 'data-kirim-ulang-line="line-1"' in html
    assert "<td>3 j 5 mnt</td>" in html
    assert '<td class="num">3</td>' in html


@butuh_node
def test_baris_putus_menyebut_sejak_kapan_dan_galatnya():
    d = {**_SEHAT, "tersambung": False, "sebab_putus": "tak_terjangkau", "putus_sejak": 1_789_873_200,
         "galat": "ConnectError: <refused>"}
    html = _baris("line-1", d, 1_789_873_260_000)
    assert "putus sejak " in html and "{sejak}" not in html
    assert "ConnectError: &lt;refused&gt;" in html
    assert 'class="tanda-gagal"' in html


@butuh_node
def test_baris_line_menolak_tanpa_tombol_dengan_status_dan_pesan():
    d = {"terjangkau": False, "kode": "line_menolak", "status": 403, "pesan": "line-2 refused: HTTP 403"}
    html = _baris("line-2", d, 0)
    assert "data-kirim-ulang-line" not in html
    assert "kunci ditolak HTTP 403" in html
    assert "line-2 refused: HTTP 403" in html


@butuh_node
def test_baris_line_error_500_bukan_line_mati():
    """Line-side error (500): a status came back, so this is NOT the key advice
    and NOT the unreachable wording, it is its own row."""
    d = {"terjangkau": False, "kode": "line_tidak_menjawab", "status": 500, "pesan": "line-2 did not answer: HTTP 500"}
    html = _baris("line-2", d, 0)
    assert "data-kirim-ulang-line" not in html
    assert "line menjawab HTTP 500" in html
    assert "kunci ditolak" not in html


@butuh_node
def test_baris_line_lama_404_bukan_line_mati():
    """An old line with no `/internal/outbox` answers 404: same treatment as a 500."""
    d = {"terjangkau": False, "kode": "line_tidak_menjawab", "status": 404, "pesan": "line-2 did not answer: HTTP 404"}
    html = _baris("line-2", d, 0)
    assert "line menjawab HTTP 404" in html
    assert "kunci ditolak" not in html


@butuh_node
def test_baris_kosong_tanpa_tombol():
    html = _baris("line-3", {**_SEHAT, "menunggu": 0, "tertua_at": None}, 0)
    assert "data-kirim-ulang-line" not in html
    assert 'class="tanda-ok"' in html


@butuh_node
def test_status_401_bawaan_tidak_bocor_ke_baris_lain():
    """The `{status}` default of "401" in `barisAntreanLine` must not leak into a
    key that has nothing to do with a refused key, such as antreanLineTakTerjangkau."""
    html = _baris("line-1", {"terjangkau": False, "kode": "line_tidak_menjawab"}, 0)
    assert "401" not in html


@butuh_node
def test_muatAntreanLine_tidak_tumpang_tindih_saat_masih_menunggu():
    """5 s setInterval must not start a new request while the previous one is still
    pending: a hung line can take up to 3 s plus network time. A module-level
    in-flight flag, released in `finally`, guards it."""
    skrip = (
        "let panggilan = 0; let selesaikan;\n"
        "const api = () => { panggilan++; return new Promise((res) => { selesaikan = res; }); };\n"
        "const $ = () => ({});\n"
        "const KOSONG = \"-\";\n"
        "const barisKosong = () => \"\";\n"
        "function tulisKalauBeda() {}\n"
        "let antreanLineSedangMuat = false;\n"
        "async " + _fungsi("muatAntreanLine")
        + "\n(async () => {\n"
        "  const p1 = muatAntreanLine();\n"
        "  const p2 = muatAntreanLine();\n"
        "  await new Promise((r) => setTimeout(r, 10));\n"
        "  selesaikan({ lines: {} });\n"
        "  await Promise.all([p1, p2]);\n"
        "  console.log(JSON.stringify({ panggilan }));\n"
        "})();"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    assert json.loads(hasil.stdout.strip()) == {"panggilan": 1}


@butuh_node
@pytest.mark.parametrize(
    "kode,params,saran",
    [
        ("line_menolak", {"status": 401}, "saranKunciLine"),
        # line_tidak_menjawab WITHOUT a status: truly unreachable or timed out.
        ("line_tidak_menjawab", {}, "saranLineMati"),
        # line_tidak_menjawab WITH a status: line-side error (500) or an old line
        # answering 404. Must NOT read as the line being down.
        ("line_tidak_menjawab", {"status": 500}, "saranBukaLog"),
        ("line_tidak_menjawab", {"status": 404}, "saranBukaLog"),
        ("line_tidak_dikenal", {}, "saranMuatUlang"),
        (None, {}, "saranBukaLog"),
    ],
)
def test_pesan_gagal_menyebut_line_jam_kode_dan_saran(kode, params, saran):
    e = {"kode": kode, "message": "Line 1 menolak perintah (HTTP 401)", "params": params}
    teks = _jalankan(
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        "pesanGagalKirimUlang", "waktu", konstanta=("SARAN_KIRIM_ULANG",),
    )
    assert teks.startswith("Kirim Ulang line-1 gagal pukul 28/09/2026 14:05:09")
    assert f"(kode {kode or 'http'})" in teks
    assert "Line 1 menolak perintah (HTTP 401)" in teks
    assert teks.endswith(saran)


@butuh_node
def test_kirim_ulang_500_menunjukkan_status_bukan_saran_kunci_atau_line_mati():
    """A 500 on Kirim Ulang must show the HTTP status and saranBukaLog, and must
    NOT show saranLineMati or the INTERNAL_SECRET advice (saranKunciLine)."""
    e = {"kode": "line_tidak_menjawab", "message": "line-1 did not answer: HTTP 500", "params": {"status": 500}}
    teks = _jalankan(
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        "pesanGagalKirimUlang", "waktu", konstanta=("SARAN_KIRIM_ULANG",),
    )
    assert teks.endswith("saranBukaLog")
    assert "saranLineMati" not in teks
    assert "saranKunciLine" not in teks
