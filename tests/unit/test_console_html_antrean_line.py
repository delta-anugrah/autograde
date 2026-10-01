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
    "antreanLinePutus_konsol_galat", "antreanLineGalatTerakhir", "antreanLineDitolak",
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
  antreanLineDitolak: "{jumlah} ditolak pukul {jam}",
  antreanLineGalatTerakhir: "galat terakhir {jam}",
  antreanLineGagalKirimUlang: "Kirim Ulang {line} gagal pukul {jam}: {alasan}. {saran}",
  lineSebab_tak_terjangkau: "line tidak menjawab", lineSebab_bukan_line: "bukan line AutoGrade",
  lineSebab_kunci_ditolak: "kunci konsol ditolak", lineSebab_line_galat: "line galat",
  lineSebab_lain: "line tidak terbaca",
};
const bahasa = "id";
const KAMUS = { id: KAMUS_UJI };
const t = (k) => KAMUS_UJI[k] ?? k;
// Stand-ins for the real helpers (their own tests: test_console_html_teks_ramah.py).
const kodeDikenal = (e) => Boolean(e.kode);
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
        # A line the console cannot read: the backend's `sebab_kode` picks the sentence the
        # Diagnostik card uses too (2026-10-01), never the HTTP status.
        ({"terjangkau": False, "kode": "line_menolak", "status": 401, "sebab_kode": "kunci_ditolak"},
         "lineSebab_kunci_ditolak"),
        ({"terjangkau": False, "kode": "line_tidak_menjawab", "sebab_kode": "tak_terjangkau"},
         "lineSebab_tak_terjangkau"),
        # Line-side error (a 500) or something answering 404: a status came back, so this
        # is NOT "the line is down".
        ({"terjangkau": False, "kode": "line_tidak_menjawab", "status": 500, "sebab_kode": "line_galat"},
         "lineSebab_line_galat"),
        ({"terjangkau": False, "kode": "line_tidak_menjawab", "status": 404, "sebab_kode": "bukan_line"},
         "lineSebab_bukan_line"),
        # A console older than the code: the generic sentence, never a guess from the status.
        ({"terjangkau": False, "kode": "line_tidak_menjawab", "status": 404}, "lineSebab_lain"),
        ({**_SEHAT, "aktif": False}, "antreanLineNonaktif"),
        ({**_SEHAT, "lama_tertinggal": True}, "antreanLineLamaTertinggal"),
        ({**_SEHAT, "menunggu": 0, "tersambung": False, "sebab_putus": "kunci_ditolak"}, "antreanLineKosong"),
        ({**_SEHAT, "tersambung": False, "sebab_putus": "kunci_ditolak"}, "antreanLinePutus_kunci_ditolak"),
        ({**_SEHAT, "tersambung": False, "sebab_putus": "sebab_baru_dari_versi_lain"}, "antreanLinePutus_tak_terjangkau"),
        (_SEHAT, "antreanLineMengirim"),
        ({**_SEHAT, "tersambung": None}, "antreanLineMengirim"),
        # Final review konsol I1: baris yang ditolak konsol dicoba terus, jadi dulu
        # terbaca "Sedang dikirim ke konsol" selamanya.
        ({**_SEHAT, "ditolak": 2}, "antreanLineDitolak"),
        ({**_SEHAT, "ditolak": 0}, "antreanLineMengirim"),
        # Konsol putus lebih mendesak: tidak ada yang sampai sama sekali.
        ({**_SEHAT, "ditolak": 2, "tersambung": False, "sebab_putus": "tak_terjangkau"},
         "antreanLinePutus_tak_terjangkau"),
    ],
)
def test_keadaan_dipilih_dari_yang_paling_perlu_tindakan(d, kunci):
    assert _jalankan(f"keadaanAntreanLine({json.dumps(d)}).kunci", "kunciSebabTakTerbaca", "keadaanAntreanLine") == kunci


def _baris(kode: str, d: dict, sekarang_ms: int) -> str:
    return _jalankan(
        f"barisAntreanLine({json.dumps(kode)}, {json.dumps(d)}, {sekarang_ms})",
        "kunciSebabTakTerbaca", "keadaanAntreanLine", "barisAntreanLine", "waktu", "lamaProses",
    )


@butuh_node
def test_baris_line_sehat_punya_tombol_dan_umur_tertua():
    tertua = 1_789_873_200
    html = _baris("line-1", {**_SEHAT, "tertua_at": tertua}, (tertua + 3 * 3600 + 5 * 60) * 1000)
    assert 'data-kirim-ulang-line="line-1"' in html
    assert "<td>3 j 5 mnt</td>" in html
    assert '<td class="num">3</td>' in html


@butuh_node
def test_baris_putus_menyebut_sejak_kapan_tanpa_galat_mentah():
    """The worker's raw error belongs to the Log tab (user decision 2026-10-01)."""
    d = {**_SEHAT, "tersambung": False, "sebab_putus": "tak_terjangkau", "putus_sejak": 1_789_873_200,
         "galat": "ConnectError: <refused>", "galat_at": 1_789_873_200}
    html = _baris("line-1", d, 1_789_873_260_000)
    assert "putus sejak " in html and "{sejak}" not in html
    assert "ConnectError" not in html and "refused" not in html
    assert "galat terakhir " in html
    assert 'class="tanda-gagal"' in html


@butuh_node
def test_baris_ditolak_menyebut_jumlah_dan_jam_tanpa_alasan_mentah():
    """What (how many bunches) and when; the why is the console's own answer, which the
    Log tab keeps. Line in the first column, advice in the KAMUS sentence (MANUAL §7)."""
    d = {**_SEHAT, "ditolak": 2, "ditolak_at": 1_789_873_200, "ditolak_alasan": "HTTP 400: <timestamp cacat>",
         "galat": "HTTP 400: <timestamp cacat>", "galat_at": 1_789_873_200}
    html = _baris("line-2", d, 1_789_873_260_000)
    assert "2 ditolak pukul " in html and "{jam}" not in html
    assert "timestamp cacat" not in html and "HTTP" not in html
    assert 'class="tanda-gagal"' in html
    assert 'data-kirim-ulang-line="line-2"' in html


@butuh_node
def test_alasan_penolakan_tidak_pernah_masuk_baris():
    """It used to be written through `replace` (with a function, for "$&"); now not at all."""
    d = {**_SEHAT, "ditolak": 1, "ditolak_at": 1_789_873_200, "ditolak_alasan": "HTTP 400: harga $& $1"}
    html = _baris("line-1", d, 1_789_873_260_000)
    assert "harga" not in html and "$&" not in html


@butuh_node
def test_galat_terakhir_disertai_jamnya():
    """Final review konsol M2: galat lama tanpa jam terbaca seperti masalah sekarang."""
    d = {**_SEHAT, "galat": "ConnectError: refused", "galat_at": 1_789_873_200}
    html = _baris("line-1", d, 1_789_873_260_000)
    jam = _jalankan("waktu(1789873200000)", "waktu")
    assert f"galat terakhir {jam}" in html
    assert "ConnectError" not in html


@butuh_node
def test_galat_lama_tidak_ditampilkan_saat_antrean_kosong():
    """Final review konsol M2: sesudah konsol restart (tiap hari upgrade) baris "Kosong"
    dulu bersanding dengan "Connection refused" sampai line itu direstart."""
    d = {**_SEHAT, "menunggu": 0, "galat": "ConnectError: refused", "galat_at": 1_789_873_200}
    html = _baris("line-1", d, 1_789_873_260_000)
    assert "ConnectError" not in html


@butuh_node
def test_baris_line_menolak_tanpa_tombol_tanpa_status_dan_pesan_mentah():
    d = {"terjangkau": False, "kode": "line_menolak", "status": 403, "pesan": "line-2 refused: HTTP 403",
         "sebab_kode": "kunci_ditolak"}
    html = _baris("line-2", d, 0)
    assert "data-kirim-ulang-line" not in html
    assert "kunci konsol ditolak" in html
    assert "403" not in html and "refused" not in html


@butuh_node
def test_baris_line_error_500_bukan_line_mati():
    """Line-side error (500): a status came back, so this is NOT the key advice
    and NOT the unreachable wording, it is its own row."""
    d = {"terjangkau": False, "kode": "line_tidak_menjawab", "status": 500,
         "pesan": "line-2 did not answer: HTTP 500", "sebab_kode": "line_galat"}
    html = _baris("line-2", d, 0)
    assert "data-kirim-ulang-line" not in html
    assert "line galat" in html
    assert "kunci konsol ditolak" not in html and "line tidak menjawab" not in html
    assert "500" not in html


@butuh_node
def test_baris_404_bukan_line_mati():
    """Something answering 404 at the line's address (not an AutoGrade line, or too old)."""
    d = {"terjangkau": False, "kode": "line_tidak_menjawab", "status": 404,
         "pesan": "line-2 did not answer: HTTP 404", "sebab_kode": "bukan_line"}
    html = _baris("line-2", d, 0)
    assert "bukan line AutoGrade" in html
    assert "kunci konsol ditolak" not in html and "404" not in html


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


def _jalankan_muat(badan: str) -> dict:
    skrip = (
        "let panggilan = 0; let aktif = 0; let aktifMaks = 0; const selesaikan = [];\n"
        "const api = () => { panggilan++; aktif++; aktifMaks = Math.max(aktif, aktifMaks);\n"
        "  return new Promise((res) => selesaikan.push(() => { aktif--; res({ lines: {} }); })); };\n"
        "const $ = () => ({});\n"
        "const KOSONG = \"-\";\n"
        "const barisKosong = () => \"\";\n"
        "function tulisKalauBeda() {}\n"
        "let antreanLineSedangMuat = false;\n"
        "let antreanLineSusulan = false;\n"
        "const jeda = () => new Promise((r) => setTimeout(r, 10));\n"
        "async " + _fungsi("muatAntreanLine")
        + "\n(async () => {\n" + badan
        + "  console.log(JSON.stringify({ panggilan, aktifMaks }));\n"
        "})();"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout.strip())


@butuh_node
def test_muatAntreanLine_tidak_tumpang_tindih_saat_masih_menunggu():
    """5 s setInterval must not start a new request while the previous one is still
    pending: a hung line can take up to 3 s plus network time. A module-level
    in-flight flag, released in `finally`, guards it."""
    hasil = _jalankan_muat(
        "  const p1 = muatAntreanLine();\n"
        "  const p2 = muatAntreanLine();\n"
        "  await jeda(); selesaikan.shift()();\n"
        "  await Promise.all([p1, p2]);\n"
    )
    assert hasil == {"panggilan": 1, "aktifMaks": 1}


@butuh_node
def test_muat_susulan_sesudah_kirim_ulang_tidak_tertelan():
    """Final review konsol M3: Kirim Ulang yang jatuh saat muatan timer 5 detik masih
    di jalan dulu ditelan penjaga, jadi barisnya basi sampai 5 detik sesudah toast
    berhasil. Permintaan susulan diingat dan jalan SESUDAH yang di jalan selesai,
    tetap tanpa tumpang tindih; tiga susulan jadi satu."""
    hasil = _jalankan_muat(
        "  const p1 = muatAntreanLine();\n"
        "  const susulan = [muatAntreanLine(true), muatAntreanLine(true), muatAntreanLine(true)];\n"
        "  await jeda(); selesaikan.shift()();\n"
        "  await jeda(); selesaikan.shift()();\n"
        "  await Promise.all([p1, ...susulan]);\n"
    )
    assert hasil == {"panggilan": 2, "aktifMaks": 1}


def test_kirim_ulang_meminta_muat_susulan():
    klik = HTML.split('$("antrean-line-baris").addEventListener("click"', 1)[1].split("\n});", 1)[0]
    assert "await muatAntreanLine(true)" in klik


@butuh_node
@pytest.mark.parametrize(
    "kode,params,saran",
    [
        ("line_menolak", {"status": 401}, "saranKunciLine"),
        # line_tidak_menjawab WITHOUT a status: truly unreachable or timed out.
        ("line_tidak_menjawab", {}, "saranLineMati"),
        # line_tidak_menjawab WITH a status: line-side error (500) or something answering
        # 404. Must NOT read as the line being down.
        ("line_tidak_menjawab", {"status": 500}, "saranBukaLog"),
        ("line_tidak_menjawab", {"status": 404}, "saranBukaLog"),
        ("line_tidak_dikenal", {}, "saranMuatUlang"),
    ],
)
def test_pesan_gagal_menyebut_line_jam_alasan_dan_saran_tanpa_kode(kode, params, saran):
    """What failed, on which line, when, why (the KAMUS sentence from alasan) and what to do.
    No error code since 2026-10-01 (user decision: no codes outside the Log tab)."""
    e = {"kode": kode, "message": "ALASAN", "params": params}
    teks = _jalankan(
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        "pesanGagalKirimUlang", "waktu", konstanta=("SARAN_KIRIM_ULANG",),
    )
    assert teks == f"Kirim Ulang line-1 gagal pukul 28/09/2026 14:05:09: ALASAN. {saran}"
    assert "kode" not in teks


@butuh_node
def test_kode_asing_tanpa_saran_tambahan():
    """An unknown code gets the generic sentence, which already says what to do."""
    e = {"kode": None, "message": "ALASAN", "params": {}}
    teks = _jalankan(
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        "pesanGagalKirimUlang", "waktu", konstanta=("SARAN_KIRIM_ULANG",),
    )
    assert teks == "Kirim Ulang line-1 gagal pukul 28/09/2026 14:05:09: ALASAN."


@butuh_node
def test_kirim_ulang_500_menyarankan_tab_log_bukan_kunci_atau_line_mati():
    """A 500 on Kirim Ulang ends with saranBukaLog, and must NOT give saranLineMati or
    the key advice (saranKunciLine)."""
    e = {"kode": "line_tidak_menjawab", "message": "ALASAN", "params": {"status": 500}}
    teks = _jalankan(
        f"pesanGagalKirimUlang({json.dumps(e)}, 'line-1', new Date(2026, 8, 28, 14, 5, 9))",
        "pesanGagalKirimUlang", "waktu", konstanta=("SARAN_KIRIM_ULANG",),
    )
    assert teks.endswith("saranBukaLog")
    assert "saranLineMati" not in teks
    assert "saranKunciLine" not in teks
