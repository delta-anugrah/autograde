"""Button icons and one button size (Lampung 2026-10-08, v1.26.0).

The owner asked for an icon on every action button and one size for all of them. Icons are CSS
masks written by `scripts/ikon_tombol.py`; a button names its icon with `data-ikon`.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from konsol_js import HTML

_SKRIP = Path(__file__).resolve().parents[2] / "scripts/ikon_tombol.py"
_spec = importlib.util.spec_from_file_location("ikon_tombol", _SKRIP)
ikon_tombol = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ikon_tombol)


def test_halaman_sama_dengan_skrip_ikon():
    assert ikon_tombol.tanam(HTML) == HTML, "jalankan .venv/bin/python scripts/ikon_tombol.py"


def test_setiap_ikon_yang_dipakai_punya_gambar():
    dipakai = set(re.findall(r'data-ikon="([a-z-]+)"', HTML))
    # The account buttons get their icon as the 4th argument of `tombol(...)` in `aksiAkun`.
    akun = HTML.split("function aksiAkun(a) {", 1)[1].split("\n}\n", 1)[0]
    dari_akun = {n for n in re.findall(r'"([a-z-]+)"', akun) if n in {"kunci", "peran", "akun-hidup", "akun-mati"}}
    assert dari_akun == {"kunci", "peran", "akun-hidup", "akun-mati"}
    dipakai |= dari_akun
    assert dipakai <= set(ikon_tombol.IKON), dipakai - set(ikon_tombol.IKON)
    # And no icon is drawn that no button uses.
    assert set(ikon_tombol.IKON) <= dipakai, set(ikon_tombol.IKON) - dipakai


def test_tombol_lihat_sandi_tanpa_ikon_dan_tanpa_lebar_minimum():
    # Review 2026-10-08: the minimum width pushed the in-field Lihat button over the typed text.
    for tag in re.findall(r'<button\b[^>]*class="sandi-lihat"[^>]*>', HTML):
        assert "data-ikon" not in tag, tag
    assert ":where(td, .antrean-aksi, .truk-grup) button { min-width:0; }" in HTML


def test_ikon_tidak_membawa_url_polos():
    # F1: zero https:// in the page; the SVG namespace inside the data URI is encoded.
    assert "https://" not in HTML and "xmlns='http" not in HTML


def test_tombol_aksi_utama_berikon():
    for id_ in ("riwayat-tampilkan", "riwayat-csv", "riwayat-impor", "datang", "masuk", "daftar", "cetak-qr",
                "set-simpan", "akun-tambah-buka", "konfirmasi-ya", "konfirmasi-tidak", "gerbang-masuk"):
        tag = re.search(rf'<button\b[^>]*\bid="{id_}"[^>]*>', HTML).group(0)
        assert "data-ikon=" in tag, id_
    for aksi in ("tolak", "tugaskan", "lepas", "piston", "keluar", "pergi", "batal-datang", "pasang", "lewati"):
        assert re.search(rf'data-aksi="{aksi}"[^>]*data-ikon="', HTML), aksi


def test_ikon_ikut_warna_teks_dan_mengalah_pada_spinner_sibuk():
    assert re.search(r"button\[data-ikon\]::before \{[^}]*background:currentColor;[^}]*mask:var\(--ikon\)", HTML)
    assert re.search(r"button\.sibuk\[data-ikon\]::before \{[^}]*mask:none;", HTML)
    # `display:inline-flex` on the button must not beat the hidden attribute.
    assert "button[data-ikon][hidden] { display:none; }" in HTML


def test_satu_ukuran_tombol():
    assert "--tinggi-tombol:44px;" in HTML and "--lebar-tombol:" in HTML
    dasar = re.search(r"  button, input \{([^}]*)\}", HTML).group(1)
    assert "min-height:var(--tinggi-tombol)" in dasar
    # No button rule may set its own smaller height any more (2.4rem, 2.6rem, 2.8rem were mixed).
    for aturan in re.findall(r"\n  ([^\n{]*button[^\n{]*)\{([^}]*)\}", HTML):
        pemilih, isi = aturan
        if "sub-tab" in pemilih or "uji-coil" in pemilih:
            continue  # tabs and the PLC coil tiles are not action buttons
        assert not re.search(r"min-height:2\.[468]rem", isi), pemilih


def test_kepala_satu_tinggi():
    assert "--tinggi-kepala:48px;" in HTML
    assert re.search(r"\.pil \{[^}]*min-height:var\(--tinggi-kepala\)", HTML)
    assert re.search(r"\.jam\.pil \{[^}]*height:var\(--tinggi-kepala\)", HTML)
    assert re.search(r"#topbar \.aksi button \{[^}]*height:var\(--tinggi-kepala\)", HTML)


def test_rekap_dua_baris_dan_tombol_di_kanan():
    saring = HTML.split('<div class="riwayat-saring">', 1)[1].split('<div id="riwayat-ringkasan"', 1)[0]
    assert saring.count('class="riwayat-baris') == 2
    periode, isian = saring.split('<div class="riwayat-baris">', 1)
    assert 'id="riwayat-dari"' in periode and 'class="riwayat-cepat"' in periode
    assert 'id="riwayat-line"' in isian and 'class="riwayat-aksi"' in isian
    assert re.search(r"\.riwayat-aksi \{[^}]*margin-left:auto", HTML)
