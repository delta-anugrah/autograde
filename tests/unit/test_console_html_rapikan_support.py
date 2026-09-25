"""Invarian layar support yang dirapikan 2026-09-25: Diagnostik, Versi, Uji PLC.

Dua lapis, sama seperti `test_console_html_alarm.py`:

- **invarian teks**, selalu jalan (juga di CI tanpa node): kelas, kunci i18n,
  dan baris yang di-comment benar-benar ada di berkas.
- **perilaku fungsi**, dijalankan sungguhan lewat node kalau ada: fungsi yang
  SAMA dengan yang dipakai layar, bukan salinannya — disalin ke test, dia akan
  terus lulus setelah yang di layar diubah.
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

# Pembantu yang dipakai fungsi-fungsi render. `t` sengaja mengembalikan
# kuncinya sendiri: test membaca KUNCI mana yang dipilih, bukan terjemahannya.
_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const KOSONG = "-";
const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));
const t = (k) => k;
"""


def _fungsi(nama: str) -> str:
    """Isi satu fungsi tingkat atas, sampai baris pertama yang menutupnya."""
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _jalankan(skrip: str):
    keluaran = subprocess.run(
        [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    return json.loads(keluaran)


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def _blok_css(selector: str) -> str:
    cocok = re.search(rf"{re.escape(selector)}\s*\{{[^}}]*\}}", HTML, re.S)
    assert cocok is not None, f"blok {selector} tidak ketemu"
    return cocok.group(0).replace(" ", "").replace("\n", "")


# ── Diagnostik: worker ke bawah, centang hijau, silang merah ───────────────

_LINE_SEHAT = {
    "terjangkau": True,
    "camera_connected": False,
    "gpu_available": True,
    "gpu_device": "NVIDIA GeForce RTX 3060",
    "plc": {"inputs": []},
    "workers": [
        {"name": "capture", "alive": True},
        {"name": "display", "alive": True},
        {"name": "processing", "alive": False},
    ],
    "outbox_pending": 0,
    "outbox_failed": 0,
}


def _kartu(data: dict) -> str:
    skrip = (
        _STUB
        + _fungsi("tanda")
        + "\n"
        + _fungsi("kartuDiagnostik")
        + f"\nconsole.log(JSON.stringify(kartuDiagnostik('line-1', {json.dumps(data)})));"
    )
    return _jalankan(skrip)


def test_worker_tidak_lagi_digabung_jadi_satu_baris():
    """Enam worker dalam satu baris terpotong `…` di kartu selebar 280 px, dan
    worker yang mati justru yang paling mungkin jatuh di bagian terpotong."""
    fn = _fungsi("kartuDiagnostik")
    assert '.join(" ")' not in fn


@butuh_node
def test_satu_baris_per_worker_berurutan():
    html = _kartu(_LINE_SEHAT)
    nama = re.findall(r'<dt class="diag-worker">([^<]+)</dt>', html)
    assert nama == ["capture", "display", "processing"]


@butuh_node
def test_worker_hidup_hijau_mati_merah():
    html = _kartu(_LINE_SEHAT)
    baris = re.findall(r'<dt class="diag-worker">([^<]+)</dt><dd>(.*?)</dd>', html)
    tanda = {n: isi for n, isi in baris}
    assert 'class="tanda-ok"' in tanda["capture"]
    assert "✓" in tanda["capture"]
    assert 'class="tanda-gagal"' in tanda["processing"]
    assert "✗" in tanda["processing"]


@butuh_node
def test_ringkasan_worker_menyebut_berapa_yang_hidup():
    """Baris judul Workers memberi hitungan, jadi satu worker mati terbaca dari
    jauh tanpa menyisir daftarnya."""
    html = _kartu(_LINE_SEHAT)
    judul = re.search(r"<dt>thWorkers</dt><dd>(.*?)</dd>", html)
    assert judul, html
    assert "2/3" in judul.group(1)
    assert "tanda-gagal" in judul.group(1)


@butuh_node
def test_kamera_putus_merah_plc_hidup_hijau():
    html = _kartu(_LINE_SEHAT)
    kamera = re.search(r"<dt>thKamera</dt><dd>(.*?)</dd>", html).group(1)
    plc = re.search(r"<dt>thPlc</dt><dd>(.*?)</dd>", html).group(1)
    assert 'class="tanda-gagal"' in kamera
    assert 'class="tanda-ok"' in plc


@butuh_node
def test_plc_mati_tetap_strip_bukan_silang():
    """`plc: null` artinya PLC memang dimatikan di line itu, bukan rusak —
    silang merah di situ akan dikejar teknisi sebagai kerusakan."""
    html = _kartu({**_LINE_SEHAT, "plc": None})
    plc = re.search(r"<dt>thPlc</dt><dd>(.*?)</dd>", html).group(1)
    assert plc == "-"


@butuh_node
def test_line_tanpa_worker_tidak_menulis_baris_kosong():
    html = _kartu({**_LINE_SEHAT, "workers": []})
    assert 'class="diag-worker"' not in html
    judul = re.search(r"<dt>thWorkers</dt><dd>(.*?)</dd>", html).group(1)
    assert judul == "-"


def test_warna_tanda_memakai_token_tema():
    """Token tema, bukan hex: dua tema (terang/gelap) punya hijau dan merah
    sendiri-sendiri, dan hex yang dipatok cuma terbaca di salah satunya."""
    assert "color:var(--acc)" in _blok_css(".tanda-ok")
    assert "color:var(--rej)" in _blok_css(".tanda-gagal")


# ── Versi: Machine ID di-comment, lisensi mati menyebut penyebabnya ────────


def test_baris_machine_id_di_comment():
    """Permintaan 2026-09-25: disembunyikan dulu, kodenya tetap ada supaya
    menghidupkannya lagi cukup membuang `//`."""
    fn = _fungsi("muatVersi")
    baris = [b.strip() for b in fn.splitlines() if 'barisVersi(t("labelMachineId")' in b]
    assert baris, "baris Machine ID hilang sama sekali — yang diminta cuma di-comment"
    assert all(b.startswith("//") for b in baris), baris


def test_kunci_saklar_mati_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        assert "lisensiSaklarMati:" in _kamus(bahasa), bahasa


@butuh_node
def test_lisensi_mati_dengan_token_menyebut_saklar():
    """Token sampai tapi `LICENSE_ENABLED` tidak — gejala Lampung 2026-09-22.
    "Inactive" saja terbaca seperti langganan yang tidak ada."""
    skrip = (
        _STUB
        + _fungsi("ringkasLisensi")
        + "\nconsole.log(JSON.stringify(["
        + "ringkasLisensi({aktif:false, token_terpasang:true}),"
        + "ringkasLisensi({aktif:false, token_terpasang:false})]));"
    )
    assert _jalankan(skrip) == ["lisensiSaklarMati", "lisensiMati"]


# ── Uji PLC: peta alamat jadi kartu, tombol Error beda warna ───────────────


def test_peta_alamat_dibungkus_kartu():
    """Peta alamat dulu teks lepas di pojok kiri dengan sisa layar kosong;
    sekarang satu kartu dengan gaya yang sama dengan kartu line di atasnya."""
    tag = re.search(r'<div id="plc-peta"[^>]*>', HTML)
    assert tag, "elemen plc-peta hilang"
    assert 'class="card"' in tag.group(0)


def test_dua_tabel_peta_mengisi_lebar_kartu():
    assert "width:100%" in _blok_css("#plc-peta table")
    assert "display:grid" in _blok_css("#plc-peta .peta-grid")


def test_tabel_pendek_tidak_ditarik_setinggi_tetangganya():
    """Grid menarik anaknya setinggi sel terpanjang; tabel 10 baris di samping
    tabel 12 baris jadi punya baris yang melar dan tidak sejajar lagi.
    Ketemu di screenshot 2026-09-25."""
    assert "align-items:start" in _blok_css("#plc-peta .peta-grid")


def test_judul_peta_tetap_ikut_bahasa():
    peta = HTML.split('id="plc-peta"', 1)[1].split("</section>", 1)[0]
    assert 'data-t="petaJudul"' in peta


def test_tombol_error_punya_warna_sendiri():
    """NG dan Error dulu sama-sama merah dan berdampingan — dua tombol yang
    terlihat kembar di depan panel. Error memakai warna peringatan."""
    css = _blok_css("button.uji-coil.error")
    assert "var(--warn)" in css
