"""Invarian HTML layar Sumber Kamera — dijaga sebagai teks, seperti tetangganya.

Konsol tidak punya test runner JS, jadi yang bisa dijaga di CI adalah bahwa
elemen dan endpoint yang dipakai skrip benar-benar ada di berkas yang sama.
Itu menangkap kesalahan yang paling sering: rute diganti namanya di Python dan
HTML-nya tertinggal.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(encoding="utf-8")


def test_panel_ada():
    assert 'id="sumber-kamera-panel"' in HTML


def test_tiga_line_punya_blok():
    for n in (1, 2, 3):
        assert f'data-sumber-line="line-{n}"' in HTML


def test_empat_pilihan_tiap_line():
    for pilihan in ("hikrobot", "webcam", "video", "foto"):
        assert f'value="{pilihan}"' in HTML


def test_endpoint_dipanggil():
    assert "/api/console/dev/sumber-kamera" in HTML


def test_peringatan_restart_disebut():
    # Support harus tahu menyimpan memutus grading sebentar, sebelum menekan.
    assert "restart" in HTML.lower()


def test_tombol_simpan_ada():
    assert 'id="sumber-simpan"' in HTML


def test_nol_referensi_web():
    # Konsol wajib jalan tanpa internet — CDN, web font, atau alamat https apa
    # pun di panel ini akan mengunci layar support di PC pabrik yang offline.
    assert "https://" not in HTML


def test_picker_berkas_ada_untuk_tiap_line():
    for n in (1, 2, 3):
        assert f'data-berkas="line-{n}"' in HTML


def test_ulang_terus_ada_untuk_tiap_line():
    for n in (1, 2, 3):
        assert f'data-ulang="line-{n}"' in HTML


def test_tab_terdaftar_di_muat_tab():
    # Tab yang tidak masuk MUAT_TAB terbuka tapi tidak pernah memuat data -
    # layar kosong tanpa satu pun error.
    assert '"sumber-kamera": muatSumberKamera' in HTML


def test_tab_sah_memuat_sumber_kamera():
    # Tab yang tidak ada di TAB_SAH tidak bisa dipulihkan dari localStorage
    # saat halaman dibuka ulang — diam-diam kembali ke tab Grading.
    assert '"sumber-kamera"' in HTML


def test_dropdown_berkas_punya_lebar_dan_boleh_menciut():
    """Dropdown berkas harus `width:100%` DAN `min-width:0`, dua-duanya.

    `.sumber-berkas` itu `display:grid`, dan kolom grid bawaannya
    `minmax(auto, …)` — `<select>` menciut ke lebar isi terpendeknya, nama
    berkas panjang terpotong habis, dan di layar terbaca sebagai dropdown
    KOSONG. Persis seperti folder media yang memang tidak berisi, tanpa satu
    pun galat yang membantah. Terjadi 2026-09-21: diukur 0 px di kartu yang
    barisnya baru dibuka.
    """
    blok = HTML.split(".sumber-berkas select", 1)
    assert len(blok) == 2, "aturan `.sumber-berkas select` hilang dari CSS"
    aturan = blok[1].split("}", 1)[0]
    assert "width:100%" in aturan
    assert "min-width:0" in aturan


def test_login_memuat_ulang_tab_dev_yang_sudah_terbuka():
    """Sesudah login, tab developer yang sudah aktif harus dimuat ulang.

    Tab dipulihkan dari localStorage saat halaman dibuka — SEBELUM login. Saat
    itu pemuatannya ditolak 401 dan ditelan diam-diam (`belum_masuk` bukan
    galat untuk dilaporkan). `kirimSandi` lalu cuma memuat Trucks / refresh /
    Timbangan / Rekap, tidak tab yang sedang terbuka, jadi layar dev itu tetap
    kosong sampai diklik ulang. Di Sumber Kamera gejalanya dropdown berkas
    tanpa isi DAN tanpa keterangan — persis seperti fitur rusak. Direproduksi
    2026-09-21 lewat Playwright: `sumberKameraTerakhir` tetap null sesudah
    login, nol panggilan API.

    Dijaga sebagai teks karena konsol tidak punya test runner JS: yang bisa
    dipastikan adalah baris pemuatan ulang itu ada DI DALAM `kirimSandi`, bukan
    cuma di init — dua tempat yang keduanya harus memakai rumus yang sama.
    """
    awal = HTML.find("async function kirimSandi")
    assert awal != -1, "kirimSandi tidak ditemukan"
    # Badan fungsi berakhir di `}` pertama pada kolom nol sesudahnya.
    akhir = HTML.find("\n}\n", awal)
    kirim_sandi = HTML[awal:akhir]
    assert "bukaTabDev(tab)" in kirim_sandi, (
        "login tidak memuat ulang tab dev yang sedang terbuka — layar dev yang "
        "dipulihkan sebelum login tetap kosong sesudahnya"
    )
    # Rumusnya harus SAMA dengan pemulihan tab di init, bukan varian sendiri.
    rumus = (
        'if (MUAT_TAB[tab] && document.querySelector(`button[data-tab="${tab}"]`)) '
        "await bukaTabDev(tab);"
    )
    assert rumus in kirim_sandi
    assert HTML.count(rumus) >= 2, "init dan kirimSandi harus memakai rumus yang sama"
    # `$` di berkas ini adalah getElementById; diberi selector CSS ia selalu null,
    # jadi bentuk lama ini adalah kondisi yang diam-diam tidak pernah benar.
    assert '$(`button[data-tab=' not in HTML, (
        "pemulihan tab memakai $() dengan selector CSS — selalu null, tab dev "
        "tidak pernah memuat data saat dipulihkan"
    )
