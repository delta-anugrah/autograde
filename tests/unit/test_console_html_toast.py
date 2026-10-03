"""Toast menutup sendiri paling lama 10 detik (keputusan user 2026-09-29).

Dulu `gagal` dan hasil Danger Zone yang perlu dibaca (`durasi` 0) menunggu
ditutup selamanya, dan toast yang tertinggal menumpuk di pojok layar yang
dibiarkan menyala berhari-hari. Sekarang: sukses/peringatan 5 detik, gagal dan
setiap `0` eksplisit 10 detik, dan kursor di atas toast menahan hitungannya
supaya kalimat panjang yang sedang dibaca tidak ditarik pergi.
"""
from __future__ import annotations

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan, konstanta

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

# Jam palsu: setTimeout/clearTimeout/Date.now dikendalikan test, bukan waktu nyata.
JAM_PALSU = """
let jam = 0;
let urut = 0;
const timer = new Map();
const setTimeout = (fn, ms) => { urut += 1; timer.set(urut, { fn, pada: jam + ms }); return urut; };
const clearTimeout = (id) => { timer.delete(id); };
const Date = { now: () => jam };
const maju = (ms) => {
  jam += ms;
  for (const [id, t] of [...timer]) if (t.pada <= jam) { timer.delete(id); t.fn(); }
};
let ditutup = 0;
const hapus = () => { ditutup += 1; };
"""


def _jalan(ekspresi: str):
    return jalankan(
        ["durasiToast", "hitungMundurToast"], ekspresi,
        tambahan=konstanta("TOAST_PALING_LAMA_MS", "TOAST_UMUR_MAKS_MS", "TOAST_DURASI") + JAM_PALSU,
    )


def _tutup_pada(durasi: str) -> list[bool]:
    """Apakah toast sudah tertutup di detik 4,99 / 5 / 9,99 / 10."""
    return _jalan(
        f"(() => {{ hitungMundurToast(durasiToast({durasi}), hapus); const r = [];"
        " maju(4990); r.push(ditutup > 0); maju(10); r.push(ditutup > 0);"
        " maju(4990); r.push(ditutup > 0); maju(10); r.push(ditutup > 0); return r; })()"
    )


@butuh_node
def test_sukses_dan_peringatan_lima_detik():
    assert _tutup_pada("TOAST_DURASI.sukses") == [False, True, True, True]
    assert _tutup_pada("TOAST_DURASI.peringatan") == [False, True, True, True]


@butuh_node
def test_gagal_menutup_sendiri_sesudah_sepuluh_detik():
    assert _tutup_pada("TOAST_DURASI.gagal") == [False, False, False, True]


@butuh_node
def test_nol_eksplisit_menjadi_sepuluh_detik_bukan_selamanya():
    """Hasil Danger Zone yang perlu dibaca memanggil `toast(..., 0)`."""
    assert _tutup_pada("0") == [False, False, False, True]
    assert _tutup_pada("undefined") == [False, False, False, True]


@butuh_node
def test_tidak_ada_toast_yang_lebih_lama_dari_sepuluh_detik():
    assert _jalan("durasiToast(60000)") == 10000
    assert _jalan("durasiToast(3000)") == 3000


@butuh_node
def test_tumpukan_terbuka_menahan_hitungan():
    """Kursor atau fokus di atas tumpukan (Sonner, 2026-10-03) memanggil `tahan` pada semua
    toast-nya, dan `lanjut` saat pergi: hitungannya jalan lagi dari sisanya."""
    tutup = _jalan(
        "(() => { const h = hitungMundurToast(5000, hapus); const r = [];"
        " maju(2000); h.tahan();"
        " maju(20000); r.push(ditutup);"          # dibaca lama: tetap ada
        " h.lanjut();"
        " maju(2990); r.push(ditutup);"           # sisa 3 detik, belum habis
        " maju(10); r.push(ditutup);"             # habis
        " return r; })()"
    )
    assert tutup == [0, 0, 1]


@butuh_node
def test_kursor_yang_diam_di_pojok_tidak_menahan_toast_selamanya():
    """Kiosk: kursor yang diparkir di pojok toast mendapat `mouseenter` buatan
    browser tiap tata letak berubah. Umur toast tetap dibatasi 30 detik sejak
    muncul, walau kursor tidak pernah pergi."""
    tutup = _jalan(
        "(() => { const h = hitungMundurToast(10000, hapus); const r = [];"
        " maju(100); h.tahan();"
        " maju(29890); r.push(ditutup);"
        " maju(10); r.push(ditutup);"
        " maju(60000); r.push(ditutup, timer.size);"
        " return r; })()"
    )
    assert tutup == [0, 1, 1, 0]


@butuh_node
def test_tahan_lanjut_berulang_tidak_menggandakan_timer():
    tutup = _jalan(
        "(() => { const h = hitungMundurToast(5000, hapus);"
        " h.lanjut(); h.lanjut(); h.tahan(); h.tahan(); h.lanjut();"
        " maju(5000); return [ditutup, timer.size]; })()"
    )
    assert tutup == [1, 0]


@butuh_node
def test_tutup_manual_membersihkan_kedua_timer():
    """Tombol × dan geser memakai `tutup` dari hitung mundur: kedua timer (sisa dan umur
    maksimal) dibersihkan, dan hapus cuma sekali walau timer lain jatuh tempo."""
    hasil = _jalan(
        "(() => { const { tutup } = hitungMundurToast(5000, hapus);"
        " tutup(); const r = [ditutup, timer.size]; maju(60000); tutup(); r.push(ditutup); return r; })()"
    )
    assert hasil == [1, 0, 1]


def test_toast_memakai_hitung_mundur_bukan_timer_telanjang():
    fn = fungsi("toast")
    assert "hitungMundurToast(durasiToast(durasi), () => lepasToast(el))" in fn
    assert '.addEventListener("click", hitung.tutup)' in fn
    assert "pasangGeserToast(el, hitung.tutup)" in fn
    assert "durasi = TOAST_DURASI[kind]" in fn
    assert "setTimeout(" not in fn
    buka = fungsi("bukaTumpukanToast")
    assert "_hitung.tahan" in buka and "_hitung.lanjut" in buka
    for peristiwa in ('"mouseenter"', '"mouseleave"', '"focusin"', '"focusout"'):
        assert f'$("toasts").addEventListener({peristiwa}' in HTML, peristiwa


def test_komentar_lama_soal_toast_abadi_sudah_dicabut():
    assert "tetap sampai ditutup" not in HTML
    assert "toast-nya tetap sampai ditutup" not in HTML


# ── Sonner-style stack (user 2026-10-03) ─────────────────────────────────


def test_tumpukan_tiga_terlihat_terbaru_di_depan():
    assert konstanta("TOAST_TERLIHAT") == "const TOAST_TERLIHAT = 3;"
    susun = fungsi("susunToast")
    assert ".reverse()" in susun, "newest first: the last appended card is index 0"
    assert 'toggleAttribute("data-belakang", i > 0)' in susun
    assert 'toggleAttribute("data-sembunyi", i >= TOAST_TERLIHAT)' in susun


def test_susun_tidak_membaca_tata_letak():
    """Transform only, no layout thrash: the height is read once when a toast is made."""
    susun = fungsi("susunToast")
    for baca in ("getBoundingClientRect", "offsetHeight", "clientHeight", "getComputedStyle"):
        assert baca not in susun, baca
    assert fungsi("toast").count("getBoundingClientRect()") == 1


def test_ikon_svg_per_jenis_tanpa_font_ikon():
    for jenis in ("sukses:", "peringatan:", "gagal:"):
        assert jenis in HTML.split("const IKON_TOAST = {", 1)[1].split("\n};", 1)[0], jenis
    fn = fungsi("toast")
    assert '<svg class="ikon-toast"' in fn and 'aria-hidden="true"' in fn


def test_css_terlipat_dan_terbuka():
    assert "#toasts:not([data-terbuka]) .toast[data-belakang] { height:var(--tinggi-depan); }" in HTML
    assert "#toasts[data-terbuka] .toast { transform:translateY(calc(-1 * var(--offset, 0px)));" in HTML
    # Only the cards take the pointer; the corner around them stays click-through.
    wadah = HTML.split("  #toasts { position:fixed;", 1)[1].split("}", 1)[0]
    # Above the dropdown panels (20), below the sign-in gate (50).
    assert "pointer-events:none" in wadah and wadah.lstrip().startswith("z-index:40;")
    kartu = HTML.split("  .toast { position:absolute;", 1)[1].split("}", 1)[0]
    assert "pointer-events:auto" in kartu


def test_tanpa_animasi_toast_langsung_dibuang():
    lepas = fungsi("lepasToast")
    assert "if (gerakDikurangi()) el.remove();" in lepas
    assert "prefers-reduced-motion: reduce" in HTML


def test_geser_ke_kanan_memakai_pointer_events():
    geser = fungsi("pasangGeserToast")
    for peristiwa in ('"pointerdown"', '"pointermove"', '"pointerup"', '"pointercancel"'):
        assert peristiwa in geser, peristiwa
    assert "Math.max(0, ev.clientX - awalX)" in geser, "right only"
    assert "dx >= TOAST_GESER_PX" in geser
