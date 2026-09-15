"""Cetak QR truk: gambar yang ditempel di kaca truk atau dikirim ke HP supir.

Dibuat di server, **bukan** pustaka JavaScript dari CDN: `console.html` nol referensi
`https://` dengan sengaja — layar operator harus tetap terbuka saat internet mati, dan
QR yang gagal dimuat berarti gerbang timbangan berhenti.

Yang dijaga di sini:

- QR yang dicetak harus **terbaca kembali** oleh lane scan. Kalau dua sisi memakai
  aturan normalisasi berbeda, kita mencetak QR yang tidak bisa kita baca sendiri —
  dan itu baru ketahuan di gerbang pabrik, dengan setumpuk kartu yang sudah tercetak.
- isinya **cuma plat**, tidak boleh bocor data lain
- tingkat koreksi kesalahan harus cukup: kartunya kena hujan, debu sawit, dan gesekan
"""

from __future__ import annotations

import segno

from palmgrade.domain.qr import baca_qr, isi_qr_untuk
from palmgrade.services.qr_cetak import KOREKSI, png_qr


def _matriks(teks: str) -> list[list[int]]:
    """Pola QR untuk satu isi, sebagai pembanding."""
    return [list(baris) for baris in segno.make(teks, error=KOREKSI).matrix]


def test_qr_yang_dicetak_berisi_plat_ternormalisasi():
    """Pembuktiannya lewat pola QR-nya sendiri, bukan lewat pustaka pembaca: pola untuk
    satu isi bersifat tetap, jadi cocok dengan pola `BE4412OFL` berarti isinya memang
    itu. Tidak perlu menyeret decoder (dan cv2) ke CI."""
    diharapkan = _matriks("BE4412OFL")

    for tulisan in ("BE 4412 OFL", "be-4412-ofl", "BE4412OFL"):
        assert _matriks(isi_qr_untuk(tulisan)) == diharapkan


def test_qr_yang_dicetak_terbaca_kembali_oleh_lane_scan():
    """Lingkaran penuh. Kalau ini pecah, kita mencetak kartu yang tidak bisa dibaca
    sendiri — dan ketahuannya di gerbang, sesudah semuanya tercetak."""
    for tulisan in ("BE 4412 OFL", "be-4412-ofl", "  BE 4412 OFL  "):
        assert baca_qr(isi_qr_untuk(tulisan)) == "BE4412OFL"


def test_dua_plat_berbeda_tidak_pernah_menghasilkan_qr_sama():
    assert _matriks(isi_qr_untuk("BE 4412 OFL")) != _matriks(isi_qr_untuk("BE 9999 XYZ"))


def test_keluarannya_png_yang_sah():
    """Layar memuatnya lewat `<img>`, jadi header PNG-nya harus benar."""
    data = png_qr("BE 4412 OFL")

    assert data.startswith(b"\x89PNG\r\n\x1a\n"), "bukan PNG"
    assert len(data) > 50


def test_koreksi_kesalahan_cukup_untuk_kartu_yang_kotor():
    """Kartunya hidup di kaca truk: hujan, debu sawit, gesekan. Level 'L' (7%) terlalu
    tipis untuk itu; 'M' (15%) masih terbaca walau sebagian rusak."""
    assert KOREKSI in ("m", "q", "h"), f"koreksi {KOREKSI!r} terlalu rendah untuk kartu truk"


def test_plat_kosong_ditolak_bukan_mencetak_qr_kosong():
    """QR kosong yang tercetak dan tertempel adalah kartu yang tidak pernah bisa
    di-scan, dan tidak ada yang tahu sampai truknya sampai di gerbang."""
    import pytest

    from palmgrade.domain.operator_error import OperatorError

    for teks in ("", "   "):
        with pytest.raises(OperatorError):
            png_qr(teks)


def test_yang_bukan_plat_ditolak():
    """Isi QR datang dari baris truk di database, dan baris itu bisa berisi apa saja
    kalau pernah diisi salah. Yang bukan plat jangan sampai tercetak jadi kartu."""
    import pytest

    from palmgrade.domain.operator_error import OperatorError

    with pytest.raises(OperatorError):
        png_qr("https://contoh.id/promo")
