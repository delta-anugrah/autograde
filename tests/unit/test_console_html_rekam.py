"""Invarian HTML layar Rekam Video — dijaga sebagai teks, seperti tetangganya.

Konsol tidak punya test runner JS, jadi yang bisa dijaga di CI adalah bahwa
elemen, kunci i18n, dan endpoint yang dipakai skrip benar-benar ada di berkas
yang sama. Itu menangkap kesalahan yang paling sering: rute diganti namanya di
Python dan HTML-nya tertinggal.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(
    encoding="utf-8"
)


def _blok_css(selector: str) -> str:
    """Isi satu blok CSS, tanpa spasi — supaya perbandingannya tidak goyah
    karena pembungkusan baris."""
    cocok = re.search(rf"{re.escape(selector)}\s*\{{[^}}]*\}}", HTML, re.S)
    assert cocok is not None, f"blok {selector} tidak ketemu"
    return cocok.group(0).replace(" ", "").replace("\n", "")


def test_tab_rekam_ada_dan_ditandai_dev():
    assert 'data-tab="rekam"' in HTML
    baris = [b for b in HTML.splitlines() if 'data-tab="rekam"' in b][0]
    # `data-dev="1"` yang membuat tab ini hilang untuk operator. Kerapian, bukan
    # pengaman — backend yang menolak — tapi tanpa itu operator melihat menu
    # yang selalu dijawab 403.
    assert 'data-dev="1"' in baris


def test_panel_rekam_ada():
    assert 'id="sec-rekam"' in HTML


def test_endpoint_rekam_dipanggil():
    assert "/api/console/dev/rekam" in HTML


def test_kunci_i18n_ada_di_dua_bahasa():
    """Dua kamus. Kunci yang cuma ada di satu membuat layar menampilkan nama
    kunci mentah saat bahasa lain dipilih."""
    for kunci in (
        "judulRekamVideo",
        "rekamMulai",
        "rekamStop",
        "rekamSedangMerekam",
        "rekamMati",
        "rekamTakTerbaca",
        "rekamDiskBebas",
        "rekamSetelanJudul",
        "rekamSimpanSetelan",
        "rekamCatatanRetensi",
    ):
        assert HTML.count(f"{kunci}:") == 2, kunci


def test_kolom_setelan_cuma_lebar_dan_tinggi():
    """FPS dan Bitrate dibuang dari layar 2026-09-25 — dua-duanya tidak pernah
    sampai ke berkas. FPS ikut laju kamera sejak v1.13.2 (angka layar cuma
    dipakai kalau `CAMERA_FPS=0`), dan bitrate tidak pernah diteruskan ke
    `cv2.VideoWriter`, yang memang tidak menerima bitrate. Kolom yang diisi
    tanpa efek apa pun lebih buruk daripada tidak ada kolom — support
    menyetelnya lalu heran kenapa berkasnya tidak berubah, jenis setelan mandul
    yang dulu membuat `CAMERA_FPS` terbaca sebagai bug berbulan-bulan."""
    for el in ("rekam-width", "rekam-height"):
        assert f'id="{el}"' in HTML, el
    for el in ("rekam-fps", "rekam-bitrate"):
        assert f'id="{el}"' not in HTML, el
        assert f'$("{el}")' not in HTML, el


def test_kunci_i18n_fps_dan_bitrate_ikut_dibuang():
    for kunci in ("rekamFps", "rekamBitrate", "rekamBantuFps"):
        assert f"{kunci}:" not in HTML, kunci


def test_simpan_cuma_mengirim_lebar_dan_tinggi():
    blok = HTML[HTML.index('"/api/console/dev/rekam/setelan"'):][:600]
    assert "width:" in blok and "height:" in blok
    assert "fps:" not in blok
    assert "bitrate_kbps:" not in blok


def test_peringatan_retensi_manual_disebut():
    """Rekaman TIDAK dihapus otomatis. Support yang tidak tahu itu akan
    meninggalkannya menumpuk sampai disk pabrik penuh."""
    assert "rekamCatatanRetensi" in HTML


def test_tidak_ada_referensi_https():
    """Konsol harus hidup saat internet putus — nol referensi https://."""
    assert "https://" not in HTML


def test_polling_berhenti_saat_tab_ditutup():
    """Polling yang jalan terus di tab lain membebani tiga line tanpa guna."""
    assert re.search(r"rekamTimer|hentikanPollingRekam", HTML) is not None


def test_setelan_dikirim_sebagai_string_json():
    """`api()` meneruskan opts ke fetch apa adanya, jadi body WAJIB string.

    Objek telanjang dikirim sebagai "[object Object]" dan dijawab 422. Gejalanya
    menyesatkan: toast merah memang muncul, tapi bunyinya "gagal menyimpan"
    sementara penyebabnya bentuk payload — dan setelan diam-diam tetap lama.
    Ketemu di browser 2026-09-22.
    """
    blok = HTML[HTML.index('"/api/console/dev/rekam/setelan"'):][:600]
    assert "JSON.stringify" in blok


def test_tombol_menunjukkan_sedang_bekerja():
    """Stop menahan ~2 detik (line menunggu encoder menutup berkas). Tanpa
    tulisan yang berubah, jeda itu terbaca seperti tombol yang tidak bereaksi."""
    assert HTML.count("rekamMenunggu:") == 2
    assert 'el.textContent = t("rekamMenunggu")' in HTML


# ── UI: status berwarna dan toast lokasi berkas ─────────────────────────────


def test_status_punya_kelas_warna_sendiri():
    """Tiga keadaan yang butuh tindakan berbeda harus bisa dibedakan dari jauh.

    Layar ini dibaca support lewat AnyDesk, sering sambil mengerjakan hal lain:
    teks abu seragam membuat "sedang merekam" dan "line mati" terlihat sama.
    """
    for kelas in ("rekam-merekam", "rekam-mati", "rekam-putus"):
        assert f'"{kelas}"' in HTML or f".{kelas}" in HTML, kelas


def test_status_ditulis_kata_bukan_cuma_warna():
    """Warna saja tidak cukup: sebagian teknisi buta warna, dan layar pabrik
    kena matahari langsung. Kata-katanya tetap yang membawa artinya."""
    for kunci in ("rekamSedangMerekam", "rekamMati", "rekamTakTerbaca"):
        assert HTML.count(f"{kunci}:") == 2, kunci


def test_toast_selesai_menyebut_lokasi_berkas():
    """Selesai merekam tanpa memberi tahu di mana berkasnya membuat support
    menebak — dan folder `videos/` tidak muncul di layar mana pun."""
    assert HTML.count("rekamSelesai:") == 2


def test_toast_selesai_menyebut_nama_folder():
    """Nama foldernya harus tertulis, bukan cuma nama berkas: yang membuka
    lewat AnyDesk perlu tahu ke mana harus pergi."""
    ind = HTML[HTML.index("rekamSelesai:"):][:220]
    assert "videos/" in ind


def test_toast_selesai_dipakai_saat_stop():
    assert 't("rekamSelesai")' in HTML


def test_folder_rekaman_ikut_dikirim_backend():
    """Layar tidak boleh mengarang jalurnya: di PC pabrik folder itu
    `/opt/palmgrade/autograde/videos/`, bukan `videos/` relatif."""
    assert "folder" in HTML[HTML.index('"/api/console/dev/rekam"'):][:2000]


def test_baris_kosong_selebar_jumlah_kolom():
    """`colspan` yang tertinggal saat kolom berubah membuat baris "belum ada
    line" kependekan — tabelnya terlihat rusak, tanpa satu pun galat. Jebakan
    yang sudah pernah kena di repo ini (kolom Lama di tab Timbangan).

    Dihitung dari `<thead>` panel rekam saja: jendela karakter sebelum
    `<tbody>` ikut menangkap `<th>` milik tabel tetangga, dan test yang salah
    hitung lebih buruk daripada tidak ada test.
    """
    panel = HTML[HTML.index('id="sec-rekam"'):]
    kepala = panel[panel.index("<thead>"):panel.index("</thead>")]
    # `"<th"` juga cocok dengan `<thead>` sendiri — dihitung `"<th "` dan
    # `"<th>"` supaya yang terhitung benar-benar sel kepala.
    jumlah_th = kepala.count("<th ") + kepala.count("<th>")
    assert jumlah_th == 5, f"kepala punya {jumlah_th} kolom, harap perbarui colspan"
    assert f'barisKosong({jumlah_th},' in HTML


def test_header_aksi_punya_nama_untuk_pembaca_layar():
    """Header kolom tombol tidak perlu terlihat, tapi header tabel yang
    benar-benar kosong membuat pembaca layar menyebut "kolom 5" alih-alih
    namanya."""
    assert '<span class="sr-only" data-t="thAksi">' in HTML


def test_toast_sukses_bertahan_lima_detik():
    """Tiga detik terlalu singkat untuk pesan yang isinya jalur berkas.

    Toast rekaman membawa jalur penuh — puluhan karakter yang harus dibaca,
    bukan dikenali sekilas seperti "Line 1 ditugaskan". Disamakan dengan
    `peringatan`, yang sudah 5 detik dengan alasan yang sama.
    """
    blok = HTML.split("const TOAST_DURASI", 1)[1].split("\n", 1)[0]
    assert "sukses: 5000" in blok, blok


def test_toast_gagal_tetap_menunggu_ditutup():
    """Kontrol negatif: menaikkan durasi sukses tidak boleh ikut memberi
    tenggat pada kegagalan, yang harus bertahan sampai operator menutupnya."""
    blok = HTML.split("const TOAST_DURASI", 1)[1].split("\n", 1)[0]
    assert "gagal: 0" in blok, blok


# ── tabel selebar layar, tombol di kanan ────────────────────────────────────


def test_tabel_rekam_selebar_panelnya():
    """`width:auto` membuat tabel menciut ke kiri dan menyisakan dua pertiga
    layar kosong — persis keluhan yang membuat kolomnya dipadatkan dulu, cuma
    berpindah sisi. Lebar penuh, dengan kolom yang diatur satu per satu.
    """
    blok = _blok_css("#sec-rekam table")
    assert "width:100%" in blok, blok


def test_kolom_penyerap_sudah_tidak_dipakai():
    """Kolom kosong di kanan itu cara menahan tabel `width:auto`. Begitu
    tabelnya selebar panel, ia cuma jadi sel hantu yang membuat `colspan` dan
    pembaca layar ikut salah hitung."""
    assert "rekam-sisa" not in HTML


def test_tombol_record_di_kolom_paling_kanan():
    """Tombolnya rata KANAN di kolom terakhir: mata menyusuri baris dari kiri
    (line → status → angka) dan berakhir pada aksinya."""
    blok = _blok_css("#sec-rekam td.rekam-aksi, #sec-rekam th.rekam-aksi")
    assert "text-align:right" in blok, blok
