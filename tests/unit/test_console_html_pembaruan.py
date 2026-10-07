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
    assert "teksGagalPasang(" in badan
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


def _tirai(ekspresi: str):
    stub = (
        "const KUNCI_PASANG = 'autograde.pasang'; const BATAS_PENANDA_MS = 25*60*1000; let penandaMemori = null;"
        " const sessionStorage = {getItem(){ throw new Error('x'); }, setItem(){ throw new Error('x'); },"
        " removeItem(){ throw new Error('x'); }};"
    )
    nama = ["penandaPasang", "penandaBasi", "bacaPenandaPasang", "tulisPenandaPasang", "hapusPenandaPasang", "putusanTirai"]
    return jalankan(nama, ekspresi, tambahan=stub)


PENANDA = "{target:'v1.22.1', pada: Date.now()}"


def _putusan(versi: str, hasil: str, versi_halaman: str = "v1.22.1") -> str:
    return _tirai(f"putusanTirai({PENANDA}, {{versi:'{versi}', pembaruan:{{hasil:{hasil}}}}}, '{versi_halaman}')")


@butuh_node
def test_putusan_versi_cocok_tanpa_vonis_masih_menunggu():
    """The new image answers for up to 90 s before a rollback: the version alone is not success."""
    assert _putusan("v1.22.1", "null") == "tunggu"
    assert _putusan("v1.22.1", "{state:'ok', target:'v1.22.0'}") == "tunggu"


@butuh_node
def test_putusan_ok_berhasil_hanya_di_halaman_versi_baru():
    ok = "{state:'ok', target:'v1.22.1'}"
    assert _putusan("v1.22.1", ok) == "berhasil"
    assert _putusan("v1.22.1", ok, versi_halaman="v1.22.0") == "tunggu"
    assert _putusan("v1.22.0", ok) == "tunggu"


@butuh_node
def test_putusan_gagal_untuk_vonis_gagal():
    for state in ("rolled_back", "failed", "timeout", "nothing"):
        assert _putusan("v1.22.0", f"{{state:'{state}', target:'v1.22.1'}}") == "gagal", state


@butuh_node
def test_penanda_bertahan_di_memori_saat_storage_error():
    assert _tirai("(tulisPenandaPasang('v1.22.1'), bacaPenandaPasang().target)") == "v1.22.1"
    assert _tirai("(tulisPenandaPasang('v1.22.1'), hapusPenandaPasang(), bacaPenandaPasang())") is None


@butuh_node
def test_penanda_pada_bukan_angka_dianggap_basi():
    assert _tirai("(penandaMemori = {target:'v1', pada:'abc'}, bacaPenandaPasang())") is None
    assert _tirai("(penandaMemori = {target:'v1', pada: Date.now() - 26*60*1000}, bacaPenandaPasang())") is None
    assert _tirai("(penandaMemori = {target:'v1', pada: Date.now()}, bacaPenandaPasang().target)") == "v1"


GAGAL = ["kodeDikenal", "saranUmum", "alasan", "gagalKarena", "namaLineDari", "teksGagalPasang"]


def _gagal(e: str, bahasa: str = "id"):
    return jalankan(GAGAL, f"teksGagalPasang({e}, {{'line-1':'Line A','line-2':'Line B','line-3':'Line C'}})",
                    bahasa=bahasa)


@butuh_node
def test_lepas_gagal_menyebut_line_yang_sudah_dilepas():
    teks = _gagal("{kode:'pembaruan_lepas_gagal', params:{line:'line-2', dilepas:'line-1, line-3'}}")
    assert "Line B tidak menjawab" in teks
    assert teks.endswith("Truk di Line A, Line C sudah dilepas: tugaskan lagi kalau belum selesai bongkar.")
    en = _gagal("{kode:'pembaruan_lepas_gagal', params:{line:'line-2', dilepas:'line-1'}}", "en")
    assert "Line B is not answering" in en and "Line A" in en.split("again.")[-1]


@butuh_node
def test_lepas_gagal_tanpa_yang_dilepas_tidak_menambah_kalimat():
    teks = _gagal("{kode:'pembaruan_lepas_gagal', params:{line:'line-2, line-3'}}")
    assert "Line B, Line C tidak menjawab" in teks
    assert "sudah dilepas" not in teks
    ada_truk = _gagal("{kode:'pembaruan_ada_truk', params:{line:'line-1'}}")
    assert "Lepas dulu truk di Line A" in ada_truk


@butuh_node
def test_batas_tirai_tanpa_penanda_menyebut_versi_yang_ditampilkan():
    """Marker gone (storage cleared) while the curtain is up: the timeout toast still names the
    version the curtain showed, never an empty one."""
    stub = (
        "const KUNCI_PASANG = 'autograde.pasang'; const BATAS_PENANDA_MS = 25*60*1000; let penandaMemori = null;"
        " const sessionStorage = {getItem(){ return null; }, setItem(){}, removeItem(){}};"
        " let tiraiTarget = ''; const akhir = [];"
        " const akhiriTirai = (p, putusan) => akhir.push([p.target, putusan]);"
        " const el = {'tirai-pembaruan': {hidden: true}, 'tirai-teks': {textContent: ''}};"
        " const $ = (id) => el[id]; const document = {activeElement: null};"
    )
    nama = ["penandaPasang", "penandaBasi", "bacaPenandaPasang", "tampilkanTirai", "periksaBatasTirai"]
    hasil = jalankan(nama, "(tampilkanTirai('v1.22.1'), periksaBatasTirai(), akhir)", tambahan=stub)
    assert hasil == [["v1.22.1", "gagal"]]
