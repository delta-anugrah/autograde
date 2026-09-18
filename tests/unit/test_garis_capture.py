"""Janjang difoto saat MENYENTUH garis, bukan saat titik tengahnya masuk kotak.

Permintaan operator 2026-09-18, sesudah melihat garis pemicu yang pertama:
zonanya bukan kotak, tapi satu garis lurus, dan yang memicu adalah tepi janjang
yang menyentuh garis itu.

Bedanya dengan aturan lama bukan kosmetik — itu yang bikin capture terasa cepat:

| | Lama | Sekarang |
|---|---|---|
| bentuk | kotak ROI 4 sisi | satu garis vertikal |
| pemicu | titik TENGAH masuk kotak | tepi KIRI janjang menyentuh garis |

Buah bergerak kanan → kiri, jadi tepi kiri adalah ujung depan janjang. Memakai
titik tengah berarti foto diambil saat setengah janjang sudah lewat; memakai
tepi kanan berarti fotonya diambil saat janjang hampir keluar dari garis.

Aturan ini murni aritmetika — tanpa cv2, tanpa numpy (CLAUDE.md § Tests).
"""
from __future__ import annotations

import pytest

from palmgrade.domain.garis_capture import menyentuh_garis, skala_garis_ke_frame


class TestMenyentuhGaris:
    """Kotak janjang (x1..x2) lawan satu garis vertikal di `garis_x`."""

    def test_janjang_yang_belum_sampai_garis_tidak_difoto(self):
        """Masih di kanan garis, seluruhnya. Ini keadaan paling umum."""
        assert menyentuh_garis(x1=900, x2=1100, garis_x=800) is False

    def test_tepi_kiri_menyentuh_garis_memicu_capture(self):
        """Ujung depan janjang tepat di garis — inilah momen yang diminta."""
        assert menyentuh_garis(x1=800, x2=1000, garis_x=800) is True

    def test_janjang_yang_melewati_garis_tetap_dihitung(self):
        """Garis dievaluasi per frame, dan pada 8-20 fps janjang bisa melompati
        garis di antara dua frame. Menuntut sentuhan persis akan membuat janjang
        cepat TIDAK PERNAH difoto — hilang tanpa satu pun pesan."""
        assert menyentuh_garis(x1=600, x2=850, garis_x=800) is True

    def test_janjang_yang_sudah_lewat_seluruhnya_tidak_difoto_lagi(self):
        """Sudah di kiri garis sepenuhnya. Single-trigger tetap dijaga
        `_processed_objects`, tapi aturan ini harus jujur sendiri."""
        assert menyentuh_garis(x1=400, x2=700, garis_x=800) is False

    def test_tepi_kanan_menempel_garis_dari_kiri_masih_terhitung(self):
        """Batas seberang: janjang yang baru saja lewat garis persis."""
        assert menyentuh_garis(x1=500, x2=800, garis_x=800) is True

    def test_garis_nol_berarti_mati_dan_semua_janjang_lolos(self):
        """`0` = tidak ada garis. Dipakai supaya PKS yang belum menyetel tidak
        kehilangan satu janjang pun — perilakunya persis seperti sebelum fitur
        ini ada."""
        assert menyentuh_garis(x1=900, x2=1100, garis_x=0) is True
        assert menyentuh_garis(x1=100, x2=200, garis_x=0) is True


class TestSkalaGarisKeFrame:
    """Garis disetel operator di ruang STREAM; deteksi jalan di ruang SENSOR.

    Ini jebakan yang sudah pernah memakan korban di ROI (commit bdcb300): satu
    angka dipakai di dua ruang koordinat, kotaknya terlihat benar di layar
    sementara yang menyaring cuma sebagian kecil frame — dan janjang di luar itu
    dilewati tanpa pesan apa pun.
    """

    def test_garis_diskalakan_dari_ruang_stream_ke_sensor(self):
        """900 dari 1280 di layar = 1721 dari 2448 di sensor."""
        assert skala_garis_ke_frame(900, stream_width=1280, frame_width=2448) == 1721

    def test_tanpa_penskalaan_kalau_ukurannya_sama(self):
        assert skala_garis_ke_frame(900, stream_width=1280, frame_width=1280) == 900

    def test_garis_mati_tetap_mati_setelah_diskalakan(self):
        """0 harus tetap 0, bukan jadi angka kecil yang memicu di tepi kiri."""
        assert skala_garis_ke_frame(0, stream_width=1280, frame_width=2448) == 0

    def test_lebar_stream_nol_tidak_membagi_nol(self):
        """`STREAM_WIDTH` kosong itu salah setel, bukan alasan mematikan line."""
        assert skala_garis_ke_frame(900, stream_width=0, frame_width=2448) == 900


class TestValidasiSetelan:
    """Garisnya ikut jalur setelan yang sudah ada, jadi ikut batas kewarasannya."""

    def test_garis_masuk_daftar_field_yang_boleh_diatur(self):
        from palmgrade.domain.setelan_grading import BATAS

        assert "garis_capture" in BATAS

    def test_garis_disimpan_sebagai_bilangan_bulat_piksel(self):
        from palmgrade.domain.setelan_grading import bersihkan_setelan

        bersih = bersihkan_setelan(
            {"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": "900,0"}
        )
        assert bersih["garis_capture"] == 900
        assert isinstance(bersih["garis_capture"], int)

    def test_nol_diterima_karena_artinya_mematikan_garis(self):
        """Beda dari dua setelan lain: batas bawahnya inklusif.

        `conf_threshold` 0 mematikan grading diam-diam, jadi ditolak. `0` di sini
        justru perilaku lama yang sah — tanpa itu, PKS yang belum menyetel tidak
        punya cara mengembalikan keadaan semula.
        """
        from palmgrade.domain.setelan_grading import bersihkan_setelan

        bersih = bersihkan_setelan(
            {"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": 0}
        )
        assert bersih["garis_capture"] == 0

    def test_garis_negatif_ditolak(self):
        from palmgrade.domain.setelan_grading import SetelanTidakSah, bersihkan_setelan

        with pytest.raises(SetelanTidakSah):
            bersihkan_setelan(
                {"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": -5}
            )

    def test_garis_di_luar_lebar_layar_ditolak(self):
        """Garis di x=99999 tidak akan pernah disentuh janjang mana pun: line
        terlihat jalan sambil tidak pernah memfoto apa-apa."""
        from palmgrade.domain.setelan_grading import SetelanTidakSah, bersihkan_setelan

        with pytest.raises(SetelanTidakSah):
            bersihkan_setelan(
                {"conf_threshold": 0.5, "minimum_size": 3000, "garis_capture": 99999}
            )

    def test_setelan_lama_tanpa_garis_masih_diterima(self):
        """Konsol versi lama (dan `.env` yang belum tahu field ini) tidak boleh
        ditolak 400 — line-nya akan berhenti menerima setelan sama sekali."""
        from palmgrade.domain.setelan_grading import bersihkan_setelan

        bersih = bersihkan_setelan({"conf_threshold": 0.5, "minimum_size": 3000})
        assert bersih["garis_capture"] == 0, "tanpa garis = perilaku lama"
