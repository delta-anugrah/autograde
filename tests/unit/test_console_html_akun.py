"""Invarian layar Akun (support): dijaga sebagai teks, plus render sungguhan lewat node.

Sejak 2026-09-26 akun LOKAL bisa dibuat dan diurus dari sini (tambah, ganti sandi,
matikan/aktifkan, ubah role). Akun AutoERP tetap baca saja: yang punya AutoERP,
dan tarikan berikutnya akan membatalkan perubahan apa pun. Server yang menjaga
(`require_support`, `OperatorAdmin`); test di sini memastikan layar tidak
menawarkan tombol yang pasti ditolak.
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
const t = (k) => k;
const lokal = () => "id-ID";
let emailSaya = "saya@pks.id";
"""


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def _baris(akun: dict) -> str:
    skrip = (
        _STUB
        + _fungsi("tanggalAkun")
        + "\n"
        + _fungsi("aksiAkun")
        + "\n"
        + _fungsi("barisAkun")
        + f"\nconsole.log(JSON.stringify(barisAkun({json.dumps(akun)})));"
    )
    return json.loads(
        subprocess.run(
            [NODE, "-e", skrip], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
    )


_AKUN = {
    "email": "ani@pks.id",
    "nama": "Ani <script>",
    "role": "support",
    "asal": "erp",
    "keadaan": "aktif",
    "terkunci_detik": 0,
    "sedang_masuk": True,
    "dibuat": 1_758_000_000,
}


def test_tab_akun_ada_dan_ditandai_dev():
    baris = [b for b in HTML.splitlines() if 'data-tab="akun"' in b]
    assert baris, "tombol tab Akun tidak ada"
    assert 'data-dev="1"' in baris[0]


def test_setelan_tetap_tab_paling_kanan():
    """Permintaan operator 2026-09-18: Setelan paling kanan, tab yang paling
    mahal kalau tersenggol. Tab baru masuk SEBELUM Setelan."""
    nav = HTML.split('<nav id="tabs">', 1)[1].split("</nav>", 1)[0]
    tab = re.findall(r'data-tab="([^"]+)"', nav)
    assert tab[-1] == "setelan"
    assert tab.index("akun") == tab.index("status") + 1


def test_panel_akun_ditandai_dev():
    tag = re.search(r'<section id="sec-akun"[^>]*>', HTML)
    assert tag, "panel sec-akun tidak ada"
    assert 'data-dev="1"' in tag.group(0)


def test_dimuat_saat_tab_dibuka():
    assert "akun: muatAkun" in HTML
    assert '"/api/console/dev/akun"' in HTML


def test_kunci_i18n_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in (
            "judulAkun", "thNama", "thEmail", "thRole", "thAsal", "thSedangMasuk",
            "thDibuat", "akunAktif", "akunMati", "akunTerkunci", "asalLokal",
            "asalErp", "akunYa", "akunCatatanSandi", "kosongAkun", "gagalAkun",
        ):
            assert f"{kunci}:" in isi, f"{bahasa}: {kunci}"


def _panel() -> str:
    return HTML.split('<section id="sec-akun"', 1)[1].split("</section>", 1)[0]


def test_form_tambah_akun_tersembunyi_sampai_tombolnya_ditekan():
    panel = _panel()
    assert 'id="akun-tambah-buka"' in panel
    form = re.search(r'<form id="akun-tambah"[^>]*>', panel)
    assert form, "form tambah akun tidak ada"
    # `novalidate`: pesan salah isian datang dari server sebagai kode yang
    # diterjemahkan layar, bukan tooltip browser dalam bahasa sistem.
    assert "hidden" in form.group(0) and "novalidate" in form.group(0)
    for id_ in ("akun-nama", "akun-email", "akun-sandi", "akun-sandi-ulang"):
        assert f'id="{id_}"' in panel, id_


def test_kolom_sandi_tidak_pernah_terlihat_atau_diisi_otomatis_browser():
    panel = _panel()
    for id_ in ("akun-sandi", "akun-sandi-ulang"):
        tag = re.search(rf'<input[^>]*id="{id_}"[^>]*>', panel).group(0)
        assert 'type="password"' in tag, id_
        # Tanpa ini Firefox menawarkan sandi support yang sedang login untuk
        # akun orang lain.
        assert 'autocomplete="new-password"' in tag, id_


def test_pilihan_role_cuma_operator_dan_support_dengan_operator_bawaan():
    panel = _panel()
    pilih = panel[panel.index('<div class="pilih" id="akun-role" data-nilai="operator">') :].split("</div></div>", 1)[0]
    nilai = re.findall(r'role="option" tabindex="-1" data-nilai="([^"]+)"', pilih)
    assert nilai == ["operator", "support"]
    assert 'aturPilih($("akun-role"), "operator")' in HTML, "a closed form goes back to Operator"


def test_catatan_menyebut_akun_lokal_tidak_masuk_autoerp():
    """Pertanyaan user 2026-09-26: akun yang dibuat di sini masuk ke AutoERP?
    Tidak. Jawabannya ditulis di form, bukan cuma di dokumen."""
    for bahasa in ("id", "en"):
        catatan = re.search(r'akunTambahCatatan:"([^"]+)"', _kamus(bahasa)).group(1)
        assert "AutoERP" in catatan, bahasa


def test_catatan_sandi_menyebut_dua_tempat_ganti():
    """Pertanyaan pertama yang datang ke layar ini: "user lupa sandi, bisa
    dilihat?". Jawabannya ditulis di layar: tidak, dan gantinya di mana:
    AutoERP untuk akun AutoERP, tombol Ganti sandi di sini untuk akun lokal."""
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        catatan = re.search(r'akunCatatanSandi:"([^"]+)"', isi).group(1)
        tombol = re.search(r'akunGantiSandi:"([^"]+)"', isi).group(1)
        assert "AutoERP" in catatan, bahasa
        assert tombol in catatan, bahasa


def test_empat_aksi_memanggil_lane_support_dan_terkunci_selama_jalan():
    for path in (
        '"/api/console/dev/akun"',
        '"/api/console/dev/akun/sandi"',
        '"/api/console/dev/akun/status"',
        '"/api/console/dev/akun/role"',
    ):
        assert path in HTML, path
    kirim = HTML[HTML.index("async function kirimAkun("):]
    kirim = kirim[: kirim.index("\n}") + 2]
    assert "denganSibuk(" in kirim and 'method: "POST"' in kirim


def test_kunci_aksi_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in (
            "akunTambahTombol", "akunTambahCatatan", "akunGantiSandi", "akunMatikan",
            "akunAktifkan", "akunJadikanSupport", "akunJadikanOperator", "akunDiaturErp",
            "akunSaya", "thAksi", "lbSandi", "lbSandiUlang", "akunSandiJudul",
            "akunSandiDiriSendiri", "akunMatikanTanya", "akunAktifkanTanya",
            "akunSupportTanya", "akunOperatorTanya", "akunYaMatikan", "akunYaAktifkan",
            "akunYaUbah", "akunDibuat", "akunSandiDiganti", "akunSandiDigantiSendiri",
            "akunDimatikan", "akunDiaktifkan", "akunRoleDiubah",
        ):
            assert f"{kunci}:" in isi, f"{bahasa}: {kunci}"


@butuh_node
def test_nama_dan_email_di_escape():
    html = _baris(_AKUN)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@butuh_node
def test_keadaan_diberi_label_dan_warna():
    aktif = _baris(_AKUN)
    assert "akunAktif" in aktif and 'class="tag ok"' in aktif
    mati = _baris({**_AKUN, "keadaan": "mati"})
    assert "akunMati" in mati and 'class="tag"' in mati
    kunci = _baris({**_AKUN, "keadaan": "terkunci", "terkunci_detik": 125})
    assert "akunTerkunci" in kunci and 'class="tag no"' in kunci


@butuh_node
def test_asal_dan_sedang_masuk():
    html = _baris(_AKUN)
    assert "asalErp" in html
    assert "akunYa" in html
    lokal = _baris({**_AKUN, "asal": "lokal", "sedang_masuk": False})
    assert "asalLokal" in lokal
    assert "akunYa" not in lokal


@butuh_node
def test_akun_autoerp_tanpa_tombol_ubah():
    html = _baris(_AKUN)
    assert "data-akun-aksi" not in html
    assert "akunDiaturErp" in html


@butuh_node
def test_akun_lokal_orang_lain_dapat_tiga_tombol():
    html = _baris({**_AKUN, "asal": "lokal", "role": "operator"})
    aksi = re.findall(r'data-akun-aksi="([^"]+)"', html)
    assert aksi == ["sandi", "status", "role"]
    assert "akunMatikan" in html and "akunJadikanSupport" in html
    assert 'data-email="ani@pks.id"' in html


@butuh_node
def test_tombol_status_dan_role_mengikuti_keadaan_akunnya():
    mati = _baris({**_AKUN, "asal": "lokal", "keadaan": "mati", "role": "support"})
    assert "akunAktifkan" in mati and "akunMatikan" not in mati
    assert "akunJadikanOperator" in mati
    terkunci = _baris({**_AKUN, "asal": "lokal", "keadaan": "terkunci", "terkunci_detik": 60})
    assert "akunMatikan" in terkunci


@butuh_node
def test_baris_sendiri_cuma_bisa_ganti_sandi():
    """Server menolak mematikan atau menurunkan akun sendiri. Layar tidak
    menawarkan tombol yang pasti ditolak."""
    html = _baris({**_AKUN, "asal": "lokal", "email": "Saya@PKS.id"})
    assert re.findall(r'data-akun-aksi="([^"]+)"', html) == ["sandi"]
    assert "akunSaya" in html


@butuh_node
def test_email_di_tombol_di_escape():
    html = _baris({**_AKUN, "asal": "lokal", "email": 'x"><img src=x>@pks.id'})
    assert "<img src=x>" not in html
    assert "&quot;&gt;&lt;img" in html


# ── umpan balik tes staging 2026-09-28 ─────────────────────────────────────


def _aturan_css(selektor: str) -> str:
    cocok = re.search(re.escape(selektor) + r"\s*\{([^}]*)\}", HTML)
    assert cocok, f"aturan {selektor!r} tidak ada"
    return cocok.group(1)


@butuh_node
def test_tombol_aksi_akun_berwarna_menurut_akibatnya():
    """Dulu abu-abu kusam dan menyatu dengan tabel, tidak terbaca sebagai tombol."""
    def kelas(html: str) -> list[str]:
        return re.findall(r'<button[^>]*class="([a-z-]+)"', html)

    aktif = _baris({**_AKUN, "asal": "lokal", "role": "operator"})
    mati = _baris({**_AKUN, "asal": "lokal", "keadaan": "mati", "role": "support"})

    # Matikan memakai varian bahaya (F11, user 2026-10-03), bukan warna satu-satu.
    assert kelas(aktif) == ["aksi-sandi", "bahaya", "aksi-role"]
    assert kelas(mati) == ["aksi-sandi", "aksi-aktifkan", "aksi-role"]
    assert "aksi-matikan" not in HTML
    assert "--acc-bg" in _aturan_css(".akun-tombol button.aksi-sandi")
    assert "background:var(--acc)" in _aturan_css(".akun-tombol button.aksi-aktifkan").replace(" ", "")
    assert "--warn" in _aturan_css(".akun-tombol button.aksi-role")


def test_kolom_sandi_tambah_akun_punya_tombol_lihat():
    panel = _panel()
    for id_ in ("akun-sandi", "akun-sandi-ulang"):
        kotak = re.search(
            rf'<span class="sandi-baris">\s*<input[^>]*id="{id_}"[^>]*>\s*<button[^>]*data-lihat-sandi', panel
        )
        assert kotak, id_


@butuh_node
def test_panel_ganti_sandi_juga_punya_tombol_lihat():
    skrip = _STUB + _fungsi("panelAkun") + (
        '\nconsole.log(JSON.stringify(panelAkun("sandi", {email: "ani@pks.id", nama: "Ani"})));'
    )
    html = json.loads(subprocess.run([NODE, "-e", skrip], capture_output=True, text=True,
                                     check=True, timeout=30).stdout)

    assert len(re.findall(r'<span class="sandi-baris">\s*<input[^>]*type="password"[^>]*>\s*<button[^>]*data-lihat-sandi',
                          html)) == 2


@butuh_node
def test_tombol_lihat_membalik_jenis_kolom_dan_labelnya_bolak_balik():
    skrip = _STUB + _fungsi("balikLihatSandi") + """
const tombol = { a: {}, setAttribute(k, v) { this.a[k] = v; }, textContent: "" };
const kolom = { type: "password" };
const jejak = [];
balikLihatSandi(tombol, kolom); jejak.push([kolom.type, tombol.a["aria-pressed"], tombol.textContent]);
balikLihatSandi(tombol, kolom); jejak.push([kolom.type, tombol.a["aria-pressed"], tombol.textContent]);
console.log(JSON.stringify(jejak));
"""
    jejak = json.loads(subprocess.run([NODE, "-e", skrip], capture_output=True, text=True,
                                      check=True, timeout=30).stdout)

    assert jejak == [["text", "true", "sembunyikanSingkat"], ["password", "false", "lihatSingkat"]]


def test_sandi_tertutup_lagi_saat_form_ditutup_dan_saat_ganti_bahasa():
    """Sandi yang sedang terlihat tidak boleh tertinggal terlihat untuk isian berikutnya."""
    assert "tutupLihatSandi(" in _fungsi("tutupFormAkun")
    assert "tutupLihatSandi(" in _fungsi("terapkanBahasa")


# ── permintaan operator 2026-09-29: semua tombol aksi tab Akun selebar sama ──

_KELOMPOK_TOMBOL_AKUN = (".akun-alat", ".akun-form-tombol", ".akun-tombol", ".akun-panel")


def _aturan_lebar_tombol_akun() -> str:
    cocok = re.search(r"#sec-akun :is\(([^)]*)\) button:not\(\.sandi-lihat\)\s*\{([^}]*)\}", HTML)
    assert cocok, "aturan lebar tombol tab Akun tidak ada"
    kelompok = tuple(k.strip() for k in cocok.group(1).split(","))
    assert kelompok == _KELOMPOK_TOMBOL_AKUN
    return cocok.group(2).replace(" ", "")


def test_semua_tombol_aksi_akun_satu_lebar_tetap_tanpa_membungkus():
    """Satu aturan CSS untuk tombol per baris, form Tambah akun, tombol Tambah akun,
    dan panel konfirmasi: lebarnya dipatok (rem, bukan menurut label), dan label
    terpanjang dua bahasa ("Jadikan operator", "Yes, switch off") tidak membungkus."""
    aturan = _aturan_lebar_tombol_akun()
    lebar = re.search(r"width:(var\(--lebar-tombol-akun\)|[\d.]+rem)", aturan)
    assert lebar, aturan
    assert "flex:00var(--lebar-tombol-akun)" in aturan  # spasi dibuang
    assert "white-space:nowrap" in aturan
    assert re.search(r"#sec-akun\s*\{[^}]*--lebar-tombol-akun:\s*[\d.]+rem", HTML)
    # Tombol Lihat di kolom sandi bukan tombol aksi: tetap selebar labelnya.
    assert ":not(.sandi-lihat)" in HTML


def test_lebar_lama_per_kelompok_dicabut():
    """Dulu empat lebar berbeda (12rem, 10rem, 8rem, dan selebar label). Aturan
    kelompok yang tersisa tidak boleh menyetel lebar sendiri lagi."""
    assert ".akun-panel button {" not in HTML
    for selektor in (".akun-alat button", ".akun-form-tombol button", ".akun-tombol button"):
        for cocok in re.finditer(re.escape(selektor) + r"\s*\{([^}]*)\}", HTML):
            isi = cocok.group(1).replace(" ", "")
            assert "width" not in isi and "flex:" not in isi, (selektor, isi)


def test_tombol_tab_akun_ada_di_kelompok_yang_dilebarkan():
    """Tombol yang tidak berada di salah satu kelompok tidak ikut dilebarkan."""
    assert '<div class="akun-alat">\n    <button type="button" id="akun-tambah-buka"' in HTML
    form = HTML.split('<div class="akun-form-tombol">', 1)[1].split("</div>", 1)[0]
    assert 'id="akun-tambah-simpan"' in form and 'id="akun-tambah-batal"' in form
    assert '<span class="akun-tombol">' in _fungsi("aksiAkun")
    panel = _fungsi("panelAkun")
    assert panel.count('<div class="akun-panel') == 2
    assert "data-akun-jalankan" in panel and "data-akun-batal" in panel
