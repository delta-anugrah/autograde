"""The scan result popup (2026-10-07): what it says, when it goes, and that it is not a dialog.

`teksPopupScan` is pure, so its sentences are read through node with the real KAMUS; the DOM
side is pinned by what the page source must hold (the browser tests pin the behaviour).
"""

from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")

FUNGSI = ["urutkanLineKartu", "teksPopupScan"]
# The cards sit L1, L2, L3 on screen; `kg` and `waktu` are the page's helpers, `namaKartuLine`
# reads the card's name from the DOM.
TAMBAHAN = """
let urutan = ["line-1", "line-2", "line-3"];
const kg = (v) => Number(v).toLocaleString("id-ID");
const waktu = () => "10.00";
const namaKartuLine = (k) => k.replace("line-", "Line ");
const NAMA_LANGKAH = { datang: "scanLangkahDatang", timbang_isi: "scanLangkahIsi", timbang_kosong: "scanLangkahKosong", keluar: "scanLangkahKeluar" };
const PERINGATAN_SCAN = { sudah_tercatat: "datangSudah", belum_terdaftar: "scanBelumAda" };
"""


def _j(ekspresi: str, bahasa: str = "id"):
    return jalankan(FUNGSI, ekspresi, bahasa=bahasa, tambahan=TAMBAHAN)


_ISI = (
    '{hasil:"tersimpan", langkah:"timbang_isi", plate_number:"B 1995 SME", supplier:"PT Sawit Jaya",'
    ' kg:30000, dummy:true, dipasang:['
    '{line_code:"line-1", plate_number:"B 1995 SME", terpasang:true},'
    '{line_code:"line-3", plate_number:"B 1995 SME", terpasang:true},'
    '{line_code:"line-2", plate_number:"B 1995 SME", terpasang:true}]}'
)


@butuh_node
def test_timbang_isi_dummy_menyebut_plat_berat_dan_line_menurut_urutan_kartu():
    h = _j(f"teksPopupScan({_ISI})")
    assert h["jenis"] == "sukses" and h["judul"] == "Timbang isi"
    assert h["baris"] == ["B 1995 SME", "PT Sawit Jaya", "30.000 kg (dummy)", "Dipasang ke Line 1, Line 2, Line 3"]


@butuh_node
def test_urutan_kartu_yang_diacak_operator_diikuti():
    teks = _j(f'(() => {{ urutan = ["line-3", "line-1", "line-2"]; return teksPopupScan({_ISI}); }})()')
    assert teks["baris"][-1] == "Dipasang ke Line 3, Line 1, Line 2"


@butuh_node
def test_berat_dari_timbangan_asli_tanpa_tanda_dummy_dan_tanpa_supplier_jadi_internal():
    h = _j('teksPopupScan({hasil:"tersimpan", langkah:"timbang_isi", plate_number:"B 1 AA", supplier:null,'
           ' kg:14820, dummy:false, dipasang:[]})')
    assert h["baris"] == ["B 1 AA", "Internal", "14.820 kg"]


@butuh_node
def test_datang_dan_keluar_tanpa_berat():
    datang = _j('teksPopupScan({hasil:"tercatat", langkah:"datang", plate_number:"B 1 AA", supplier:"PT X"})')
    assert datang == {"jenis": "sukses", "judul": "Datang", "baris": ["B 1 AA", "PT X"]}
    keluar = _j('teksPopupScan({hasil:"tercatat", langkah:"keluar", plate_number:"B 1 AA", supplier:"PT X"})')
    assert keluar["judul"] == "Keluar"


@butuh_node
def test_timbang_kosong_menyebut_truk_berikutnya_yang_naik():
    h = _j('teksPopupScan({hasil:"tersimpan", langkah:"timbang_kosong", plate_number:"B 1 AA", supplier:"PT X",'
           ' kg:10000, dummy:true, dipasang:[{line_code:"line-1", plate_number:"B 2 BB", terpasang:true}]})')
    assert h["judul"] == "Timbang kosong"
    assert h["baris"][2] == "10.000 kg (dummy)"
    assert h["baris"][3] == "B 2 BB ditugaskan ke Line 1"


@butuh_node
def test_peringatan_jadi_popup_merah_dengan_kalimat_yang_sama():
    h = _j('teksPopupScan({hasil:"belum_terdaftar", plate_number:"B 9 ZZ"})')
    assert h["jenis"] == "gagal" and h["judul"] == ""
    assert h["baris"] == ["Truk belum terdaftar, daftarkan dulu di tab Truk: B 9 ZZ"]


@butuh_node
def test_inggris():
    h = _j(f"teksPopupScan({_ISI})", bahasa="en")
    assert h["judul"] == "Weigh-in" and h["baris"][-1] == "Assigned to Line 1, Line 2, Line 3"


def test_popup_bukan_dialog_dan_ada_penjelasannya():
    tag = re.search(r'<(\w+) id="scan-popup"[^>]*>', HTML)
    assert tag and tag.group(1) == "div", "popup scan harus <div>, bukan <dialog>"
    assert 'role="status"' in tag.group(0) and 'aria-live="polite"' in tag.group(0)
    sebelum = HTML[: tag.start()]
    assert "BUKAN <dialog>" in sebelum[sebelum.rindex("<!--") :]


def test_durasi_dan_tirai_di_atas_popup():
    assert "const DURASI_POPUP_SUKSES_MS = 4000;" in HTML
    assert "const DURASI_POPUP_GAGAL_MS = 8000;" in HTML
    assert "const DURASI_POPUP_BERAT_DIAM_MS = 60000;" in HTML
    z = lambda sel: int(re.search(re.escape(sel) + r" \{[^}]*?z-index:(\d+)", HTML).group(1))  # noqa: E731
    assert z("#scan-popup") < z("#tirai-pembaruan")


def test_popup_berat_menyimpan_lewat_pembentuk_muatan_yang_sama_dengan_kotak_tangan():
    assert "muatanBruto(plate_number, gross_kg)" in HTML
    assert "muatanTara(w, teks)" in HTML
    simpan = HTML[HTML.index("async function simpanBeratPopup") :]
    simpan = simpan[: simpan.index("\n}\n")]
    assert "muatanBruto(p.plat, teks)" in simpan and "muatanTara(p.weighing, teks)" in simpan
    assert "MINIMUM_BERAT_KG" in simpan


def test_kamus_popup_ada_di_dua_bahasa():
    for bahasa in ("id", "en"):
        for kunci in ("scanLangkahKeluar", "scanInternal", "scanDipasang", "scanKetikBeratPopup",
                      "scanBeratMinimum", "scanBeratLabel"):
            blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", HTML.split("const KAMUS = {", 1)[1], re.S | re.M).group(1)
            assert f"{kunci}:" in blok, f"KAMUS.{bahasa} belum punya {kunci}"


def test_mintaberat_tidak_lagi_menyentuh_kotak_bruto_dan_bar_tara():
    blok = HTML[HTML.index("async function mintaBerat") : HTML.index("function galatPopupScan")]
    for terlarang in ("tanyaTara(", 'pilihNilai($("plat-timbang")', '$("bruto")'):
        assert terlarang not in blok


# --- The weight box's key handling, run through node with a fake clock --------------------

_DASAR_KUNCI = """
let sekarang = 1000000; Date.now = () => sekarang;
let jam = []; let nomorJam = 0;
const setTimeout = (f, ms) => { const id = ++nomorJam; jam.push({ id, f, pada: sekarang + ms }); return id; };
const clearTimeout = (id) => { jam = jam.filter((x) => x.id !== id); };
const maju = (ms) => { sekarang += ms; for (const x of jam.filter((j) => j.pada <= sekarang)) { jam = jam.filter((j) => j !== x); x.f(); } };
let timerPopupScan = null;
const kolom = { value: "", blur() {} };
let popupBerat = { plat: "B 1995 SME", langkah: "timbang_isi", ketik: "", pada: 0, awal: "", cepat: false, rusak: false, rusakPada: 0, menyimpan: false };
const $ = () => kolom;
const galat = [], disimpan = [], terkirim = [], ditutup = [];
const galatPopupScan = (m) => galat.push(m);
const simpanBeratPopup = () => disimpan.push(kolom.value);
const kirimScanOtomatis = (q) => terkirim.push(q);
const tutupPopupScan = () => { ditutup.push(sekarang); popupBerat = null; };
const samaPlat = (a, b) => String(a).replace(/\\s+/g, "").toUpperCase() === String(b).replace(/\\s+/g, "").toUpperCase();
const tekan = (key) => {
  const ev = { key, ctrlKey: false, altKey: false, metaKey: false, preventDefault() { this.dicegah = true; } };
  tombolPopupBerat(ev);
  // What the browser does when the key was not stopped: a digit lands in the box.
  if (!ev.dicegah && key.length === 1) kolom.value += key;
  return ev;
};
const ketik = (teks, jeda) => { for (const c of teks) { tekan(c); sekarang += jeda; } };
"""


def _kunci(aksi: str, ekspresi: str):
    return jalankan(
        ["tombolPopupBerat"], ekspresi, tambahan=konstanta_kunci() + _DASAR_KUNCI + aksi,
    )


def konstanta_kunci() -> str:
    from konsol_js import konstanta

    return konstanta("JEDA_KETIK_SCANNER_MS", "JEDA_ENTER_SCANNER_MS", "JEDA_RUSAK_MS", "DURASI_POPUP_BERAT_DIAM_MS")


_KELUAR = "({ nilai: kolom.value, galat, disimpan, terkirim })"


@butuh_node
def test_scan_yang_macet_lalu_sambung_tidak_jadi_berat():
    # "B 19", a 600 ms stall, "95 SME" + Enter: the digits 19 and 95 never become a weight.
    h = _kunci('ketik("B 19", 10); sekarang += 600; ketik("95 SME", 10); tekan("Enter");', _KELUAR)
    assert h == {"nilai": "", "galat": ["Scan tidak terbaca, ulangi scan"], "disimpan": [], "terkirim": []}


@butuh_node
def test_scan_macet_dengan_sisa_angka_saja_tidak_jadi_berat():
    h = _kunci('ketik("BE 12", 10); sekarang += 600; ketik("34", 10); tekan("Enter");', _KELUAR)
    assert h == {"nilai": "", "galat": ["Scan tidak terbaca, ulangi scan"], "disimpan": [], "terkirim": []}


@butuh_node
def test_scan_macet_tidak_menyentuh_berat_yang_sudah_diketik_orang():
    # A person typed 30000 slowly, then a broken scan: the box goes back to 30000 exactly.
    h = _kunci('ketik("30000", 200); sekarang += 600; ketik("BE 12", 10); sekarang += 600;'
               ' ketik("34", 10); tekan("Enter");', _KELUAR)
    assert h["nilai"] == "30000" and h["disimpan"] == [] and h["galat"] == ["Scan tidak terbaca, ulangi scan"]


@butuh_node
def test_angka_ketikan_cepat_di_keypad_tidak_pernah_dibatalkan_sendiri():
    # "300" at 90 ms gaps is as fast as a scanner, but digits only: a pause, then "00" + Enter saves.
    h = _kunci('ketik("300", 90); sekarang += 700; ketik("00", 90); tekan("Enter");', _KELUAR)
    assert h == {"nilai": "30000", "galat": [], "disimpan": ["30000"], "terkirim": []}


@butuh_node
def test_tombol_saat_rusak_tidak_memperpanjang_rusak():
    # Rolled back at the "3"; a key 1.1 s later is accepted although "3" and "4" were typed in between.
    h = _kunci('ketik("BE 12", 10); sekarang += 600; tekan("3"); sekarang += 500; tekan("4");'
               ' sekarang += 600; tekan("5"); tekan("0"); tekan("Enter");', _KELUAR)
    assert h["disimpan"] == ["50"] and h["galat"] == []


@butuh_node
def test_ketikan_lambat_tetap_jadi_berat():
    h = _kunci('ketik("30000", 200); tekan("Enter");', _KELUAR)
    assert h == {"nilai": "30000", "galat": [], "disimpan": ["30000"], "terkirim": []}


@butuh_node
def test_plat_lain_utuh_dikirim_dan_plat_sama_menyimpan():
    h = _kunci('ketik("30000", 200); sekarang += 600; ketik("BE 77 ZZ", 10); tekan("Enter");', _KELUAR)
    assert h["terkirim"] == ["BE 77 ZZ"] and h["nilai"] == "30000"
    h = _kunci('ketik("30000", 200); sekarang += 600; ketik("B 1995 SME", 10); tekan("Enter");', _KELUAR)
    assert h["disimpan"] == ["30000"] and h["terkirim"] == [] and h["nilai"] == "30000"


@butuh_node
def test_popup_berat_menutup_sendiri_60_detik_sesudah_tombol_terakhir():
    skrip = 'tekan("3"); maju(59_000); const sebelum = ditutup.length; tekan("0"); maju(59_000);' \
            ' const tengah = ditutup.length; maju(1_001); '
    h = _kunci(skrip, "[sebelum, tengah, ditutup.length]")
    assert h == [0, 0, 1], "every key restarts the 60 s; closes only after 60 s without one"


def test_simpan_hanya_menyentuh_popup_yang_sama_dan_kosong_ada_kalimat():
    simpan = HTML[HTML.index("async function simpanBeratPopup") :]
    simpan = simpan[: simpan.index("\n}\n")]
    assert simpan.count("popupBerat === p") == 2
    assert 'galatPopupScan(t("scanBeratKosong"))' in simpan
