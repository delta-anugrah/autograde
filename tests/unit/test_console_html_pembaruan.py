"""Batch 4.6 screen: badge, Pembaruan section, Update now button. Real KAMUS through node."""

from __future__ import annotations

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")
FUNGSI = ["teksBadgePembaruan", "pitaPembaruan", "teksHasilPembaruan", "tombolPasang", "htmlPembaruan", "namaLineDari", "teksTrukDilepas"]
IKON = "const IKON_UNDUH = '<svg></svg>';"


def _j(ekspresi: str, bahasa: str = "id"):
    return jalankan(FUNGSI, ekspresi, bahasa=bahasa, tambahan=IKON)


@butuh_node
def test_badge_cuma_saat_ada_versi_siap():
    assert _j("teksBadgePembaruan({terpasang:true, siap:'v1.22.1', berjalan:false})") == "Versi v1.22.1 siap dipasang"
    assert _j("teksBadgePembaruan({terpasang:true, siap:null, berjalan:false})") == ""
    assert _j("teksBadgePembaruan({terpasang:true, siap:'v1.22.1', berjalan:true})") == ""
    assert _j("teksBadgePembaruan({terpasang:false, siap:'v1.22.1', berjalan:false})") == ""
    assert _j("teksBadgePembaruan(null)") == ""


@butuh_node
def test_tombol_membawa_versi_yang_dilihat_operator():
    html = _j("htmlPembaruan({terpasang:true, siap:'v1.22.1', berjalan:false, hasil:null}, false)")
    assert 'class="pembaruan-pasang utama" data-target="v1.22.1"' in html
    assert "<svg" in html
    assert "Lepas semua truk dulu" not in html


@butuh_node
def test_tanpa_tombol_saat_sedang_memasang_atau_sudah_terbaru():
    berjalan = _j("htmlPembaruan({terpasang:true, siap:null, berjalan:true, hasil:null}, false)")
    assert "pembaruan-pasang" not in berjalan and "Sedang memasang" in berjalan
    terbaru = _j("htmlPembaruan({terpasang:true, siap:null, berjalan:false, hasil:null}, false)")
    assert "pembaruan-pasang" not in terbaru and "Sudah versi terbaru" in terbaru


@butuh_node
def test_layar_penanda_basi():
    teks = _j("teksHasilPembaruan({state:'timeout', target:'v1.22.1', installed:null})")
    assert teks == "Pembaruan v1.22.1 tidak selesai. Panggil teknisi."


@butuh_node
def test_rollback_tidak_terbaca_berhasil():
    teks = _j("teksHasilPembaruan({state:'rolled_back', target:'v1.22.1', installed:'v1.22.0'})")
    assert "v1.22.0" in teks and "gagal" in teks


@butuh_node
def test_hasil_ditandai_supaya_gagal_terbaca_merah():
    html = _j(
        "htmlPembaruan({terpasang:true, siap:null, berjalan:false,"
        " hasil:{state:'rolled_back', target:'v1.22.1', installed:'v1.22.0'}}, false)"
    )
    assert 'class="pembaruan-hasil" data-state="rolled_back"' in html


@butuh_node
def test_operator_tidak_melihat_apa_pun_kalau_penunggu_belum_dipasang():
    assert _j("htmlPembaruan({terpasang:false, siap:null, berjalan:false, hasil:null}, false)") == ""
    support = _j("htmlPembaruan({terpasang:false, siap:null, berjalan:false, hasil:null}, true)")
    assert "belum dipasang" in support


@butuh_node
def test_dua_bahasa_tanpa_kunci_mentah():
    for bahasa in ("id", "en"):
        for state in ("ok", "rolled_back", "failed", "nothing", "timeout"):
            teks = _j(f"teksHasilPembaruan({{state:'{state}', target:'v1.22.1', installed:'v1.22.0'}})", bahasa)
            assert teks and not teks.startswith("pembaruan"), (bahasa, state)
        html = _j("htmlPembaruan({terpasang:true, siap:'v1.22.1', berjalan:false, hasil:null}, false)", bahasa)
        assert "btnPasangSekarang" not in html and "pembaruanSyarat" not in html, bahasa


@butuh_node
def test_penolakan_menyebut_line_seperti_di_kartunya():
    """User decision 2026-10-02: the backend sends codes, the screen says the card name."""
    peta = "{'line-1':'Line A', 'line-3':'Line C'}"
    assert _j(f"namaLineDari('line-1, line-3', {peta})") == "Line A, Line C"
    # A code the screen has no card for is shown as is, never dropped.
    assert _j(f"namaLineDari('line-1, line-9', {peta})") == "Line A, line-9"
    assert _j("namaLineDari('', {})") == ""


def test_tombol_pasang_lewat_densibuk_dan_tanpa_https():
    awal = HTML.index("async function pasangSekarang(")
    badan = HTML[awal : HTML.index("\n}", awal)]
    assert "denganSibuk(" in badan
    assert "/api/console/update/install" in badan
    assert "namaLineDari(" in badan
    assert "https://" not in HTML


def test_layar_saat_konsol_tidak_menjawab_selama_pasang():
    awal = HTML.index("async function refresh(")
    badan = HTML[awal : HTML.index("\nasync function muatTimbangan", awal)]
    assert "gambarPembaruan(s.pembaruan)" in badan
    assert "pembaruanTerakhir" in badan and "pembaruanTersambungLagi" in badan


def test_pita_dan_wadah_ada_di_markup():
    for penanda in ('id="pita-pembaruan"', 'id="pembaruan-isi"', 'id="pembaruan-support"'):
        assert penanda in HTML, penanda
    # The header badge became a banner (user 2026-10-04): one place says a version is ready.
    assert 'id="badge-pembaruan"' not in HTML


SIAP = "{terpasang:true, siap:'v1.23.0', berjalan:false, hasil:null}"


@butuh_node
def test_pita_bisa_dibuka_dan_ditutup():
    html = _j(f"pitaPembaruan({SIAP}, '')")
    assert "Versi v1.23.0 siap dipasang" in html
    assert "data-buka-pembaruan" in html and "data-tutup-pembaruan" in html


@butuh_node
def test_pita_yang_ditutup_diam_sampai_versi_berikutnya():
    """Closing hides the banner for that version only: a newer one shows it again."""
    assert _j(f"pitaPembaruan({SIAP}, 'v1.23.0')") == ""
    assert "v1.23.0" in _j(f"pitaPembaruan({SIAP}, 'v1.22.1')")


@butuh_node
def test_tanpa_pita_saat_memasang_atau_tanpa_versi():
    assert _j("pitaPembaruan({terpasang:true, siap:'v1.23.0', berjalan:true, hasil:null}, '')") == ""
    assert _j("pitaPembaruan({terpasang:true, siap:null, berjalan:false, hasil:null}, '')") == ""
    assert _j("pitaPembaruan(null, '')") == ""


@butuh_node
def test_pita_dua_bahasa_tanpa_kunci_mentah():
    for bahasa in ("id", "en"):
        html = _j(f"pitaPembaruan({SIAP}, '')", bahasa)
        assert "pembaruanPita" not in html and "toastTutup" not in html, bahasa


@butuh_node
def test_failed_mengajak_coba_lagi_bukan_memanggil_teknisi():
    """`failed` = never tried, and the button comes right back (ruling 2026-10-03)."""
    for bahasa, teknisi in (("id", "teknisi"), ("en", "technician")):
        teks = _j("teksHasilPembaruan({state:'failed', target:'v1.22.1', installed:'v1.22.0'})", bahasa)
        assert teknisi not in teks.lower(), (bahasa, teks)
        assert "v1.22.0" in teks


@butuh_node
def test_versi_lama_kosong_tidak_meninggalkan_lubang():
    for state in ("rolled_back", "failed"):
        teks = _j(f"teksHasilPembaruan({{state:'{state}', target:'v1.22.1', installed:''}})")
        assert " ." not in teks and "ke ." not in teks and "di ." not in teks, teks
        assert "versi sebelumnya" in teks, teks


PETA = "{'line-1':'Line 1', 'line-2':'Line 2', 'line-3':'Line 3'}"
TIGA = (
    "[{line_code:'line-1', assignment:{plate_number:'B 1995 SME'}},"
    " {line_code:'line-2', assignment:{plate_number:'B 1995 SME'}},"
    " {line_code:'line-3', assignment:null}]"
)


@butuh_node
def test_konfirmasi_menyebut_plat_sekali_dengan_semua_line_nya():
    teks = _j(f"teksTrukDilepas({TIGA}, {PETA})")
    assert teks.count("B 1995 SME") == 1
    assert "B 1995 SME di Line 1, Line 2" in teks and "Line 3" not in teks
    assert "dilepas dulu dan rekap gradingnya dikirim ke AutoERP" in teks
    assert teks.endswith("Konsol dan ketiga line restart \u00b12 menit.")


@butuh_node
def test_konfirmasi_dua_plat_dua_kelompok():
    banyak = (
        "[{line_code:'line-1', assignment:{plate_number:'B 1 AA'}},"
        " {line_code:'line-2', assignment:{plate_number:'B 2 BB'}}]"
    )
    teks = _j(f"teksTrukDilepas({banyak}, {PETA})")
    assert "B 1 AA di Line 1" in teks and "B 2 BB di Line 2" in teks


@butuh_node
def test_konfirmasi_tanpa_truk_cuma_kalimat_restart():
    kosong = "[{line_code:'line-1', assignment:null}, {line_code:'line-2', assignment:null}]"
    assert _j(f"teksTrukDilepas({kosong}, {PETA})") == "Konsol dan ketiga line restart \u00b12 menit."
    assert _j(f"teksTrukDilepas([], {PETA})") == "Konsol dan ketiga line restart \u00b12 menit."


@butuh_node
def test_kunci_pasang_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        for kunci in (
            "konfirmasiPasangJudul",
            "konfirmasiPasangTruk",
            "konfirmasiPasangLepas",
            "konfirmasiPasangRestart",
            "tiraiPasang",
            "pembaruanBerhasil",
            "err_pembaruan_lepas_gagal",
        ):
            teks = _j(f"t('{kunci}')", bahasa)
            assert teks and teks != kunci, (bahasa, kunci)
    assert "Lepas semua truk dulu" not in _j("t('pembaruanSyarat')")
    assert "Release every truck first" not in _j("t('pembaruanSyarat')", "en")


def test_tirai_bukan_dialog_dan_menahan_aksi():
    assert 'id="tirai-pembaruan" role="alertdialog" aria-modal="true" aria-busy="true"' in HTML
    assert "<dialog id=\"tirai-pembaruan\"" not in HTML
    for nama in ("tampilkanTirai", "tutupTirai", "cekHasilTirai"):
        assert f"function {nama}(" in HTML, nama
    assert "autograde.pasang" in HTML
