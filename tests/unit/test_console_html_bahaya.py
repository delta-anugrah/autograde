"""Kotak Danger Zone di tab Setelan — invarian teks + render sungguhan lewat node.

Yang dijaga adalah hal-hal yang, kalau salah, membuat orang menghapus data
pabrik tanpa sengaja atau tidak tahu kenapa ditolak:

- kotaknya tertutup saat tab dibuka dan duduk di BAWAH tombol Simpan;
- Batal selalu lebih dulu dari tombol eksekusi (Enter tak sengaja = batal);
- tombol hapus mati sampai kolomnya berisi persis `HAPUS`;
- hambatan berarti tidak ada tombol eksekusi sama sekali;
- setiap kode hambatan/peringatan dari server punya kalimat di dua bahasa.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from palmgrade.domain.bahaya import KODE_HAMBATAN, KODE_PERINGATAN

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
SETELAN = HTML.split('<section id="sec-setelan"', 1)[1].split("</section>", 1)[0]

NODE = shutil.which("node")
butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

URUTAN = ["restart", "logout", "rekaman", "transaksi", "semua"]

_STUB = """
const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;","`":"&#96;" }[c]));
const lokal = () => "id-ID";
"""
# `t` palsu mengembalikan kuncinya sendiri — test membaca KUNCI mana yang
# dipilih — kecuali untuk kalimat berangka, yang diberi placeholder supaya
# angkanya ikut teruji.
_T = """
const POLA = {
  err_semua_line_menolak: "tolak: {lines}",
  bahayaAkibatRekaman: "{n} berkas {gb} GB",
  bahayaAkibatTransaksi: "{janjang} janjang {tiket} tiket",
  bahayaAkibatSemua: "{janjang} janjang {tiket} tiket {truk} truk {akun} akun",
  bahayaAkibatLogout: "{n} sesi",
};
const t = (k) => POLA[k] ?? k;
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _konstanta(nama: str) -> str:
    awal = HTML.index(f"const {nama} =")
    return HTML[awal : HTML.index(";\n", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


_FUNGSI = (
    "hapusSah", "gbBahaya", "teksKode", "akibatBahaya", "panelBahaya",
    "hasilBahaya", "hasilPerluDibaca", "daftarLineHasil", "alasanBahaya",
)


def _jalankan(ekspresi: str, *, stub: str = "", fungsi: tuple[str, ...] = ()):
    skrip = (
        _STUB
        + _T
        + stub
        + _konstanta("BAHAYA_HAPUS")
        + "\n".join(_fungsi(n) for n in _FUNGSI + fungsi)
        + f"\nconsole.log(JSON.stringify({ekspresi}));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout.strip())


# ── letak & struktur ────────────────────────────────────────────────────────


def test_kotak_ada_di_tab_setelan_dan_tertutup():
    tag = re.search(r'<details id="bahaya"[^>]*>', SETELAN)
    assert tag, "kotak Danger Zone tidak ada di tab Setelan"
    assert " open" not in tag.group(0)


def test_kotak_di_bawah_tombol_simpan_setelan():
    assert SETELAN.index('id="set-simpan"') < SETELAN.index('id="bahaya"')


def test_lima_aksi_urut_dari_ringan_ke_berat():
    assert re.findall(r'data-bahaya="([a-z]+)"', SETELAN) == URUTAN


def test_tiap_aksi_punya_panel_tersembunyi_sendiri():
    for aksi in URUTAN:
        tag = re.search(rf'<div class="bahaya-panel" data-bahaya-panel="{aksi}"[^>]*>', SETELAN)
        assert tag, aksi
        assert "hidden" in tag.group(0), aksi


def test_label_statis_ikut_bahasa():
    kotak = SETELAN.split('<details id="bahaya"', 1)[1].split("</details>", 1)[0]
    for aksi in ("Restart", "Logout", "Rekaman", "Transaksi", "Semua"):
        for bagian in ("Judul", "Teks", "Tombol"):
            assert f'data-t="bahaya{aksi}{bagian}"' in kotak, f"bahaya{aksi}{bagian}"


# ── terjemahan ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_setiap_kode_server_punya_kalimat(bahasa):
    isi = _kamus(bahasa)
    hilang = [f"hambatan_{k}" for k in KODE_HAMBATAN if f"hambatan_{k}:" not in isi]
    hilang += [f"peringatan_{k}" for k in KODE_PERINGATAN if f"peringatan_{k}:" not in isi]
    assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_kunci_layar_ada_di_dua_bahasa(bahasa):
    isi = _kamus(bahasa)
    kunci = [
        "bahayaJudul", "bahayaMemeriksa", "bahayaKetikHapus", "bahayaMenunggu",
        "bahayaTidakTersentuh", "bahayaHasilRestart", "bahayaHasilLogout",
        "bahayaHasilRekaman", "bahayaHasilHapus", "bahayaHasilGagal", "gagalBahaya",
        "peringatan_rekaman_line_merekam", "err_bahaya_ditolak", "err_konfirmasi_salah",
        "err_mode_asing",
    ]
    kunci += [f"bahayaJalankan_{a}" for a in URUTAN]
    kunci += [f"bahayaAkibat{a.capitalize()}" for a in URUTAN]
    kunci += ["err_semua_line_menolak", "bahayaHasilCatatan"]
    kunci += [
        f"lineHasil_{k}"
        for k in (
            "truk_terpasang", "sedang_merekam", "line_mati", "ditolak", "gagal",
            "versi_lama", "lisensi", "belum_mati",
        )
    ]
    hilang = [k for k in kunci if f"{k}:" not in isi]
    assert not hilang, f"KAMUS.{bahasa} kurang {hilang}"


def test_daftar_line_menolak_ada_tempatnya_di_kalimat():
    for bahasa in ("id", "en"):
        teks = re.search(r'err_semua_line_menolak:"([^"]+)"', _kamus(bahasa)).group(1)
        assert "{lines}" in teks, bahasa


def test_catatan_data_luar_tidak_tersentuh_menyebut_autoerp_dan_r2():
    for bahasa in ("id", "en"):
        teks = re.search(r'bahayaTidakTersentuh:"([^"]+)"', _kamus(bahasa)).group(1)
        assert "AutoERP" in teks and "R2" in teks, bahasa


# ── kawat ke server ─────────────────────────────────────────────────────────


def test_memanggil_rute_yang_ada():
    peta = _konstanta("BAHAYA_URL")
    for jalur in ("restart-line", "logout-semua", "hapus-rekaman", "hapus-data"):
        assert f'"{jalur}"' in peta, jalur
    assert '"/api/console/dev/bahaya"' in HTML


def test_body_dikirim_sebagai_json_string():
    """`api()` meneruskan opts ke fetch apa adanya: objek telanjang terkirim
    sebagai "[object Object]" dan dijawab 422 (terjadi di Rekam Video)."""
    assert "JSON.stringify(body)" in _fungsi("jalankanBahaya")


def test_tanpa_dialog_bawaan_browser():
    for nama in ("bukaPanelBahaya", "jalankanBahaya", "panelBahaya"):
        fn = _fungsi(nama)
        assert "confirm(" not in fn and "prompt(" not in fn and "alert(" not in fn, nama


def test_membuka_tab_setelan_menutup_kotak_danger_zone():
    """Kotaknya tertutup tiap kali tab dibuka (spec §2): panel yang tertinggal
    terbuka dengan angka lama mengundang tombol ditekan tanpa dibaca ulang."""
    fn = _fungsi("muatSetelan")
    assert '$("bahaya").open = false' in fn
    assert "tutupPanelBahaya()" in fn


def test_sesi_habis_saat_membuka_panel_menutup_panelnya():
    """Tanpa ini panel tersangkut di "Memeriksa…" di belakang gerbang login."""
    assert 'if (e.kode === "belum_masuk") return tutupPanelBahaya();' in _fungsi("bukaPanelBahaya")


def test_hasil_ditampilkan_lewat_satu_pintu():
    fn = _fungsi("jalankanBahaya")
    assert "tampilHasilBahaya(aksi, hasil)" in fn
    assert "alasanBahaya(e)" in fn
    # Toast bisa ditahan sampai ditutup (durasi 0), bukan cuma per jenisnya.
    assert "durasi = TOAST_DURASI[kind]" in _fungsi("toast")


def test_logout_dan_hapus_semua_menitipkan_hasil_ke_login_berikutnya():
    """Dua aksi itu mengakhiri sesi yang menekan: gerbang login menutup toast
    hasilnya, jadi hasilnya ditampilkan sesudah masuk lagi."""
    fn = _fungsi("jalankanBahaya")
    assert 'aksi === "logout" || aksi === "semua"' in fn and "titipHasilBahaya(aksi, hasil)" in fn
    masuk = _fungsi("kirimSandi")
    assert masuk.index("tutupGerbang(operator)") < masuk.index("tampilkanHasilTertunda()")


def test_ditolak_server_membuka_ulang_panel():
    """409 berarti keadaan berubah sejak panel dibuka: panelnya digambar ulang
    dengan hambatan terbaru, bukan cuma toast merah."""
    fn = _fungsi("jalankanBahaya")
    assert '"bahaya_ditolak"' in fn and "bukaPanelBahaya(aksi)" in fn


# ── render sungguhan ────────────────────────────────────────────────────────

_RINGKASAN = {
    "data": {"janjang": 12, "tiket": 3, "truk": 5, "akun": 4, "sesi_aktif": 2},
    "aksi": {
        "restart": {"peringatan": [{"kode": "truk_terpasang", "line": "line-2"}]},
        "logout": {"sesi_aktif": 2},
        "rekaman": {"berkas": 4, "bytes": 2_500_000_000, "peringatan": []},
        "transaksi": {"hambatan": [], "peringatan": [{"kode": "foto_belum_r2"}]},
        "semua": {
            "hambatan": [{"kode": "line_mati", "line": "<b>line-3</b>"}],
            "peringatan": [{"kode": "semua_keluar"}],
        },
    },
}


@butuh_node
def test_hapus_sah_cuma_huruf_besar():
    assert _jalankan('["HAPUS", " HAPUS ", "hapus", "", null].map(hapusSah)') == [
        True, True, False, False, False,
    ]


@butuh_node
def test_aksi_hapus_tanpa_hambatan_punya_kolom_ketik_dan_tombol_mati():
    html = _jalankan(f"panelBahaya('transaksi', {json.dumps(_RINGKASAN)})")
    assert "data-bahaya-ketik" in html
    tombol = re.search(r"<button[^>]*data-bahaya-jalankan[^>]*>", html).group(0)
    assert "disabled" in tombol


@butuh_node
def test_batal_lebih_dulu_dari_eksekusi():
    for aksi in ("restart", "transaksi"):
        html = _jalankan(f"panelBahaya('{aksi}', {json.dumps(_RINGKASAN)})")
        assert html.index("data-bahaya-batal") < html.index("data-bahaya-jalankan"), aksi


@butuh_node
def test_restart_tanpa_kolom_ketik_dan_langsung_bisa():
    html = _jalankan(f"panelBahaya('restart', {json.dumps(_RINGKASAN)})")
    assert "data-bahaya-ketik" not in html
    tombol = re.search(r"<button[^>]*data-bahaya-jalankan[^>]*>", html).group(0)
    assert "disabled" not in tombol
    assert "peringatan_truk_terpasang" in html


@butuh_node
def test_hambatan_berarti_tanpa_tombol_eksekusi_dan_nama_di_escape():
    html = _jalankan(f"panelBahaya('semua', {json.dumps(_RINGKASAN)})")
    assert "data-bahaya-jalankan" not in html
    assert "data-bahaya-ketik" not in html
    assert "data-bahaya-batal" in html
    assert "hambatan_line_mati" in html
    assert "<b>line-3</b>" not in html


@butuh_node
def test_akibat_menyebut_angka():
    r = json.dumps(_RINGKASAN)
    assert _jalankan(f"akibatBahaya('rekaman', {r})") == "4 berkas 2,5 GB"
    assert _jalankan(f"akibatBahaya('transaksi', {r})") == "12 janjang 3 tiket"
    assert _jalankan(f"akibatBahaya('semua', {r})") == "12 janjang 3 tiket 5 truk 4 akun"
    assert _jalankan(f"akibatBahaya('logout', {r})") == "2 sesi"


_HASIL = {
    "lines": [
        {"line_code": "line-1", "ok": True},
        {"line_code": "line-2", "ok": True, "kode": "belum_mati"},
        {"line_code": "line-3", "ok": False, "kode": "lisensi"},
    ]
}


@butuh_node
def test_hasil_memisahkan_line_gagal_dari_yang_perlu_dicek():
    """Line yang menerima tapi belum restart bukan kegagalan — datanya terhapus
    saat ia restart — tapi harus disebut, bukan hilang di antara yang sukses."""
    teks = _jalankan(f"hasilBahaya('transaksi', {json.dumps(_HASIL)})")
    assert teks.startswith("bahayaHasilHapus")
    assert "bahayaHasilGagal: line-3 (lineHasil_lisensi)" in teks
    assert "bahayaHasilCatatan: line-2 (lineHasil_belum_mati)" in teks
    assert "line-1" not in teks


@butuh_node
def test_hasil_yang_perlu_dibaca():
    assert _jalankan("hasilPerluDibaca({lines: [{line_code: 'line-1', ok: true}]})") is False
    assert _jalankan(f"hasilPerluDibaca({json.dumps(_HASIL)})") is True
    assert _jalankan("hasilPerluDibaca({lines: [{ok: true, kode: 'belum_mati'}]})") is True
    assert _jalankan("hasilPerluDibaca({sesi_dihapus: 3})") is False


@butuh_node
def test_hasil_yang_perlu_dibaca_tidak_hilang_sendiri():
    """Toast 5 detik lewat saat support sedang melihat ke line — line yang harus
    diulang tetap di layar sampai ditutup."""
    stub = """
const dipanggil = [];
const toast = (jenis, teks, durasi) => dipanggil.push([jenis, durasi]);
const toastSukses = (teks) => dipanggil.push(["sukses", null]);
"""
    panggil = _jalankan(
        "(tampilHasilBahaya('transaksi', " + json.dumps(_HASIL) + "),"
        " tampilHasilBahaya('restart', {lines: [{line_code: 'line-1', ok: true}]}), dipanggil)",
        stub=stub, fungsi=("tampilHasilBahaya",),
    )
    assert panggil == [["peringatan", 0], ["sukses", None]]


@butuh_node
def test_hasil_dititipkan_sekali_dan_kedaluwarsa():
    stub = """
const tersimpan = new Map();
const sessionStorage = {
  setItem: (k, v) => tersimpan.set(k, String(v)),
  getItem: (k) => (tersimpan.has(k) ? tersimpan.get(k) : null),
  removeItem: (k) => tersimpan.delete(k),
};
const tampil = [];
const tampilHasilBahaya = (aksi) => tampil.push(aksi);
"""
    fungsi = ("titipHasilBahaya", "tampilkanHasilTertunda")
    konstanta = _konstanta("HASIL_TERTUNDA") + _konstanta("TENGGAT_HASIL_MS")
    tampil = _jalankan(
        "(titipHasilBahaya('semua', {lines: []}), tampilkanHasilTertunda(),"
        " tampilkanHasilTertunda(), tampil)",
        stub=stub + konstanta, fungsi=fungsi,
    )
    assert tampil == ["semua"]  # sekali saja
    basi = _jalankan(
        "(sessionStorage.setItem(HASIL_TERTUNDA, JSON.stringify("
        "{aksi: 'logout', hasil: {}, pada: Date.now() - TENGGAT_HASIL_MS - 1})),"
        " tampilkanHasilTertunda(), tampil)",
        stub=stub + konstanta, fungsi=fungsi,
    )
    assert basi == []


@butuh_node
def test_semua_line_menolak_menyebut_alasan_tiap_line_dalam_bahasa_layar():
    stub = 'const alasan = (e) => "alasan:" + e.kode;'
    assert _jalankan(
        "alasanBahaya({kode: 'semua_line_menolak', params: {lines: 'line-1:versi_lama,line-2:lisensi'}})",
        stub=stub,
    ) == "tolak: line-1 (lineHasil_versi_lama), line-2 (lineHasil_lisensi)"
    assert _jalankan("alasanBahaya({kode: 'bahaya_ditolak', params: {}})", stub=stub) == (
        "alasan:bahaya_ditolak"
    )
