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
    "btnTugaskanSekarang",
    "btnLewati",
    "konfirmasiLewati",
    "konfirmasiLewatiJudul",
    "sukLewati",
    "sukDitugaskanOtomatis",
    "tugaskanGagalLine",
    "tugaskanTertahan",
    "pelepasanOtomatisGabung",
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


_TOAST = """
const toasts = [];
const toastSukses = (m) => toasts.push(["sukses", m]);
const toastPeringatan = (m) => toasts.push(["peringatan", m]);
const namaKartuLine = (k) => k.replace("line-", "Line ");
const pelepasanSudahDiumumkan = new Set();
"""


def _kalimat(kunci: str, bahasa: str = "id") -> str:
    return re.search(rf"\b{kunci}:\"([^\"]*)\"", _kamus(bahasa)).group(1)


def _toast(ekspresi: str, *fungsi: str, kunci: tuple[str, ...]) -> list[list[str]]:
    """Toasts raised by `ekspresi`, with the real Indonesian sentences filled in."""
    kamus = json.dumps({k: _kalimat(k) for k in kunci})
    skrip = (
        _STUB.replace("const t = (k) => k;", f"const t = (k) => ({kamus})[k] ?? k;")
        + _TOAST + "".join(_fungsi(f) for f in fungsi)
        + f"\n{ekspresi};\nprocess.stdout.write(JSON.stringify(toasts));"
    )
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
    assert "tanyaKonfirmasi(" in blok, "Lewati harus ditanya dulu"
    assert "bahaya: true" in blok, "Lewati mengeluarkan truk dari antrean: konfirmasinya merah"


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
    for id_ in ("set-otomatis", "set-otomatis-lines", "set-penugasan-simpan"):
        assert f'id="{id_}"' in setelan
    assert "/api/console/dev/auto-assign" in _fungsi("muatPenugasan")
    assert "await muatPenugasan()" in _fungsi("muatSetelan")


def test_pesan_penugasan_jadi_toast_bukan_kotak_kuning():
    """User 2026-10-02: "Penugasan line tersimpan." as a toast, like every other save."""
    assert "set-penugasan-pesan" not in HTML


def test_simpan_penugasan_memakai_kalimatnya_sendiri():
    awal = HTML.index('$("set-penugasan-simpan").addEventListener("click"')
    blok = HTML[awal : HTML.index("\n}));", awal)]
    assert 'toastSukses(t("penugasanTersimpan"))' in blok and "setelanTersimpan" not in blok
    assert 'toastGagal(alasan(e, "gagalSetelan"))' in blok
    assert 'toastGagal(alasan(e, "gagalSetelanMuat"))' in _fungsi("muatPenugasan")
    assert "umumkanPasang(r.dipasang)" in blok, "simpan nyala bisa langsung memasang truk"
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
def test_antrean_cuma_saat_otomatis_dan_kosong_pun_bilang():
    # 2026-10-07: the right half of the truck card. Off = nothing; on and empty = the head
    # with 0 and one sentence, so the card does not jump when the first truck weighs in.
    assert _jalankan("htmlAntreanBongkar(undefined, false)", "teksMenit", "htmlAntreanBongkar") == ""
    kosong = _jalankan("htmlAntreanBongkar([], true)", "teksMenit", "htmlAntreanBongkar")
    assert 'class="antrean-jumlah">0<' in kosong and "antrean-kosong" in kosong and "antrean-truk" not in kosong


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
def test_strip_tersembunyi_saat_saklar_mati():
    """D13: saklar mati = layar sama seperti sebelum rilis ini. Jalurnya tetap ada,
    dropdown per line tetap cara manualnya."""
    html = _jalankan(
        'htmlAntreanBongkar([{weighing_id:"w1", plate_number:"BE 1 AA", menit:0}], false)',
        "teksMenit",
        "htmlAntreanBongkar",
    )
    assert html == ""
    assert "antreanBongkarManual" not in HTML


@butuh_node
def test_line_tertahan_diumumkan_dengan_plat_lama():
    daftar = json.dumps([
        {"line_code": "line-1", "plate_number": "BE 2 BB", "terpasang": True},
        {"line_code": "line-2", "plate_number": "BE 2 BB", "terpasang": False, "tertahan": True,
         "plate_lama": "BE 1 AA"},
        {"line_code": "line-3", "plate_number": "BE 2 BB", "terpasang": True},
    ])
    toasts = _toast(f"umumkanPasang({daftar})", "umumkanPasang",
                    kunci=("sukDitugaskanOtomatis", "tugaskanGagalLine", "tugaskanTertahan"))
    assert toasts == [
        ["sukses", "BE 2 BB ditugaskan ke Line 1, Line 3"],
        ["peringatan", "Line 2 masih memegang truk BE 1 AA yang sudah timbang kosong. Lepas di kartunya, lalu tugaskan BE 2 BB."],
    ]


_TIGA_PELEPASAN = json.dumps([
    {"id": i, "line_code": f"line-{i}", "plate_number": "BE 1 AA", "truck_id": "t-a"} for i in (1, 2, 3)
])


@butuh_node
def test_pelepasan_tiga_line_satu_toast_saat_saklar_nyala():
    """Timbang kosong di pabrik tiga line: sukTara, truk berikutnya ditugaskan, lalu satu
    toast pelepasan, bukan tiga (TOAST_MAKS 4 membuang toast suksesnya). Tanpa "tugaskan
    lagi": saklar nyala, menugaskan lagi menimpa truk berikutnya."""
    toasts = _toast(
        f"umumkanPelepasanOtomatis({_TIGA_PELEPASAN}, true); umumkanPelepasanOtomatis({_TIGA_PELEPASAN}, true)",
        "umumkanPelepasanOtomatis", kunci=("pelepasanOtomatis", "pelepasanOtomatisGabung"),
    )
    assert toasts == [["peringatan", "Line 1, Line 2, Line 3 dilepas otomatis karena BE 1 AA sudah timbang kosong."]]


@butuh_node
def test_pelepasan_per_line_seperti_dulu_saat_saklar_mati():
    toasts = _toast(
        f"umumkanPelepasanOtomatis({_TIGA_PELEPASAN}, false)",
        "umumkanPelepasanOtomatis", kunci=("pelepasanOtomatis", "pelepasanOtomatisGabung"),
    )
    assert [m for _, m in toasts] == [
        f"line-{i} dilepas otomatis karena BE 1 AA sudah timbang kosong. Tugaskan lagi kalau bongkarnya belum selesai."
        for i in (1, 2, 3)
    ]


def test_refresh_memberi_tahu_saklar_ke_pengumuman_pelepasan():
    awal = HTML.index("async function refresh()")
    blok = HTML[awal : HTML.index("\n}\n", awal)]
    assert "umumkanPelepasanOtomatis(s.auto_releases, Boolean(s.penugasan_otomatis && s.penugasan_otomatis.aktif))" in blok


def test_kata_langkah_lama_tidak_ada_lagi_di_kamus_id():
    """Empat scan (2026-09-30): langkah 2 dan 3 bernama Timbang isi dan Timbang kosong.
    "Timbang masuk" / "timbang keluar" tidak boleh tersisa di kalimat layar (Q5)."""
    import re
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text(encoding="utf-8")
    kamus_id = html[html.index("const KAMUS"):html.index("\n  en: {")]
    teks = " ".join(re.findall(r':"([^"]*)"', kamus_id)).lower()
    assert "timbang keluar" not in teks and "timbang masuk" not in teks
