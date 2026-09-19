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

from palmgrade.domain.garis_capture import (
    kandidat_tp_sah,
    menyentuh_garis,
    menyentuh_kotak,
    skala_garis_ke_frame,
    tp_untuk_janjang,
)


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


# ------------------------------------------------------- sumbu garis (arah conveyor)


class TestSumbuGaris:
    """Conveyor bisa dipasang mendatar atau menurun, dan garisnya ikut.

    Diminta operator 2026-09-18: "kalau nanti arah conveyor berubah kiri kanan
    atau atas bawah". Yang berubah cuma SUMBU-nya — aturan sentuhnya sendiri
    sudah netral arah (perpotongan berlaku dari sisi mana pun), jadi conveyor
    yang membalik arah pada sumbu yang sama tidak butuh setelan apa-apa.
    """

    def test_sumbu_tegak_memakai_koordinat_x(self):
        """Conveyor mendatar: janjang menyeberang garis tegak."""
        assert menyentuh_kotak(
            x1=700, y1=100, x2=900, y2=400, garis=800, sumbu="tegak"
        ) is True
        assert menyentuh_kotak(
            x1=100, y1=100, x2=300, y2=400, garis=800, sumbu="tegak"
        ) is False

    def test_sumbu_mendatar_memakai_koordinat_y(self):
        """Conveyor menurun: janjang menyeberang garis mendatar.

        Kalau sumbunya diabaikan dan `x` tetap dipakai, janjang akan difoto di
        tempat yang sama sekali berbeda — dan tidak ada error di mana pun.
        """
        assert menyentuh_kotak(
            x1=100, y1=700, x2=400, y2=900, garis=800, sumbu="mendatar"
        ) is True
        assert menyentuh_kotak(
            x1=100, y1=100, x2=400, y2=300, garis=800, sumbu="mendatar"
        ) is False

    def test_sumbu_tidak_dikenal_jatuh_ke_tegak(self):
        """Nilai asing tidak boleh mematikan grading satu line.

        Sumbu itu data yang bisa berasal dari konsol versi lain; menolaknya
        dengan melempar akan menghentikan deteksi gara-gara satu string.
        """
        assert menyentuh_kotak(
            x1=700, y1=100, x2=900, y2=400, garis=800, sumbu="miring"
        ) is True

    def test_garis_mati_meloloskan_semua_di_kedua_sumbu(self):
        for sumbu in ("tegak", "mendatar"):
            assert menyentuh_kotak(
                x1=100, y1=100, x2=200, y2=200, garis=0, sumbu=sumbu
            ) is True

    def test_penskalaan_mendatar_memakai_TINGGI_frame(self):
        """Sumbu mendatar diskalakan dengan tinggi, bukan lebar.

        Memakai lebar di sini adalah versi lain dari bug ROI `bdcb300`: frame
        2448x2048 tidak persegi, jadi garis mendatar akan mendarat ~19% meleset
        dan tidak ada yang memberi tahu.
        """
        from palmgrade.domain.garis_capture import skala_garis

        assert skala_garis(
            360, sumbu="mendatar", stream_width=1280, stream_height=720,
            frame_width=2448, frame_height=2048,
        ) == 1024
        assert skala_garis(
            640, sumbu="tegak", stream_width=1280, stream_height=720,
            frame_width=2448, frame_height=2048,
        ) == 1224


class TestValidasiSumbu:
    def test_sumbu_masuk_setelan_dan_bawaannya_tegak(self):
        from palmgrade.domain.setelan_grading import bersihkan_setelan

        bersih = bersihkan_setelan({"conf_threshold": 0.5, "minimum_size": 3000})
        assert bersih["sumbu_garis"] == "tegak"

    def test_sumbu_mendatar_diterima(self):
        from palmgrade.domain.setelan_grading import bersihkan_setelan

        bersih = bersihkan_setelan({
            "conf_threshold": 0.5, "minimum_size": 3000,
            "garis_capture": 360, "sumbu_garis": "mendatar",
        })
        assert bersih["sumbu_garis"] == "mendatar"

    def test_sumbu_asing_ditolak_di_gerbang(self):
        """Di sini boleh melempar: ini jalur SIMPAN, bukan jalur deteksi.

        Menolak di gerbang membuat nilai cacat tidak pernah sampai ke tiga line;
        `menyentuh_kotak` tetap memaafkan supaya line yang sudah terlanjur
        memegang nilai aneh tidak berhenti menggrading.
        """
        from palmgrade.domain.setelan_grading import SetelanTidakSah, bersihkan_setelan

        with pytest.raises(SetelanTidakSah):
            bersihkan_setelan({
                "conf_threshold": 0.5, "minimum_size": 3000,
                "garis_capture": 360, "sumbu_garis": "miring",
            })


# ------------------------------------------- pasangan TP ↔ janjang (jarak)


class TestPasanganTp:
    """TP menempel ke janjang TERDEKAT, bukan ke janjang yang kebetulan lewat
    garis sesudahnya.

    Aturan lama menyimpan satu slot "TP terakhir terlihat" dan memberikannya ke
    janjang berikutnya yang menyentuh garis, tanpa pernah melihat posisi. Dua
    akibatnya sama-sama salah bayar dan sama-sama senyap:

    * TP milik janjang A menempel ke janjang B yang lewat garis lebih dulu;
    * TP yang terlihat sesudah janjangnya difoto menempel ke janjang berikutnya.

    Jarak diukur antar PUSAT kotak, dengan ambang yang ikut ukuran janjang —
    bukan angka piksel tetap, karena janjang di dekat kamera jauh lebih besar
    daripada yang di ujung frame, dan satu ambang tetap akan benar cuma di satu
    jarak kamera.
    """

    def _janjang(self, x1, y1, x2, y2):
        return (x1, y1, x2, y2)

    def test_tp_di_dalam_kotak_janjang_dipasangkan(self):
        """Kasus yang terlihat di layar pabrik: kotak TP di dalam kotak janjang."""
        assert tp_untuk_janjang(
            janjang=(500, 300, 900, 900),
            kandidat=[{"bbox": (700, 800, 820, 920), "tp_confidence": 0.8}],
        ) is not None

    def test_tp_yang_terpisah_tapi_dekat_tetap_dipasangkan(self):
        """TP bisa terpisah dari kotak janjangnya (jawaban operator 2026-09-18),
        jadi irisan kotak saja tidak cukup — yang dipakai jarak."""
        pasangan = tp_untuk_janjang(
            janjang=(500, 300, 900, 900),
            kandidat=[{"bbox": (920, 850, 1000, 950), "tp_confidence": 0.8}],
        )
        assert pasangan is not None

    def test_tp_di_seberang_frame_tidak_dipasangkan(self):
        """Ini inti perbaikannya: TP milik janjang lain tidak boleh ikut."""
        assert tp_untuk_janjang(
            janjang=(100, 100, 300, 400),
            kandidat=[{"bbox": (2000, 1800, 2100, 1900), "tp_confidence": 0.8}],
        ) is None

    def test_yang_terdekat_yang_menang(self):
        """Dua TP di frame yang sama: yang menang yang pusatnya lebih dekat."""
        dekat = {"bbox": (900, 850, 980, 930), "tp_confidence": 0.5}
        jauh = {"bbox": (1200, 1100, 1280, 1180), "tp_confidence": 0.9}
        pasangan = tp_untuk_janjang(
            janjang=(500, 300, 900, 900), kandidat=[jauh, dekat]
        )
        assert pasangan is dekat, "confidence tidak boleh mengalahkan jarak"

    def test_ambang_ikut_ukuran_janjang(self):
        """Janjang besar (dekat kamera) memaafkan jarak lebih jauh daripada
        janjang kecil di ujung frame. Ambang piksel tetap akan benar cuma di
        satu jarak kamera."""
        # TP yang sama, dua janjang berpusat SAMA supaya jaraknya identik —
        # yang berbeda cuma ukuran janjangnya, dan itu yang sedang diuji.
        tp = {"bbox": (640, 640, 700, 700), "tp_confidence": 0.8}
        besar = tp_untuk_janjang(janjang=(150, 150, 650, 650), kandidat=[tp])
        kecil = tp_untuk_janjang(janjang=(370, 370, 430, 430), kandidat=[tp])
        assert besar is not None, "janjang besar harus menjangkau TP ini"
        assert kecil is None, "janjang kecil tidak boleh menjangkau sejauh itu"

    def test_tanpa_kandidat_mengembalikan_none(self):
        assert tp_untuk_janjang(janjang=(100, 100, 300, 300), kandidat=[]) is None


class TestKandidatTpDiPraPindai:
    """TP yang boleh jadi kandidat harus lewat gerbang yang sama dengan dulu.

    Kode lama mencatat TP hanya sesudah dua gerbang: `track_id != -1` dan track
    itu belum diproses. Pra-pindai yang melewatkannya adalah perubahan perilaku
    yang tidak disengaja — dan yang pertama berbahaya: kotak tanpa track id
    adalah deteksi yang ByteTrack sendiri belum yakini, jadi menempelkannya ke
    janjang berarti menambah tangkai panjang yang mungkin tidak ada.
    """

    def test_tp_tanpa_track_id_bukan_kandidat(self):
        assert kandidat_tp_sah(track_id=-1, sudah_diproses=False) is False

    def test_tp_yang_sudah_dipakai_bukan_kandidat_lagi(self):
        """Satu tangkai menempel ke SATU janjang. Tanpa ini, tangkai yang sama
        ikut ke setiap janjang yang lewat selama dia masih terlihat."""
        assert kandidat_tp_sah(track_id=7, sudah_diproses=True) is False

    def test_tp_bertrack_dan_belum_dipakai_adalah_kandidat(self):
        assert kandidat_tp_sah(track_id=7, sudah_diproses=False) is True


class TestTpTidakDirebutTetangga:
    """TP milik janjang yang PALING dekat di antara semua janjang di frame.

    Ambang jarak saja tidak cukup begitu dua janjang berdempetan di conveyor:
    keduanya bisa sama-sama berada dalam jangkauan TP yang sama, dan yang
    menang tinggal siapa yang kebetulan diproses lebih dulu — urutan kotak
    dalam satu frame tidak dijamin. Akibatnya janjang B dikreditkan tangkai
    milik A, dan tangkai A yang asli tidak tercatat. `tp_confidence > 0.8` itu
    kriteria Tangkai Panjang yang dibukukan AutoERP, jadi ini menggeser
    potongan yang dibayar ke supplier.
    """

    # Angka skala sensor 2448x2048: dua janjang 450x450 berjarak 500 px.
    #
    # TP-nya sengaja ditaruh di posisi yang BENAR-BENAR diperebutkan: jaraknya
    # 253 px dari A dan 457 px dari B, sementara ambang keduanya 477 px. Jadi
    # dua-duanya "dalam jangkauan" dan aturan ambang saja akan menyerahkannya ke
    # siapa pun yang diproses lebih dulu. A yang lebih dekat, jadi A pemiliknya.
    #
    # TP tepat di tengah sela sengaja TIDAK diuji: di situ geometrinya memang
    # ambigu, dan aturan apa pun cuma menebak.
    A = (775, 675, 1225, 1125)
    B = (1275, 675, 1725, 1125)
    TP_MILIK_A = (1075, 1100, 1135, 1160)

    def test_tanpa_saingan_janjang_terdekat_mendapatkannya(self):
        assert tp_untuk_janjang(
            janjang=self.A, kandidat=[{"bbox": self.TP_MILIK_A}], janjang_lain=[]
        ) is not None

    def test_tetangga_yang_lebih_jauh_tidak_boleh_merebut(self):
        """B masih dalam ambangnya sendiri, tapi A lebih dekat — jadi bukan milik B."""
        assert tp_untuk_janjang(
            janjang=self.B, kandidat=[{"bbox": self.TP_MILIK_A}], janjang_lain=[self.A]
        ) is None

    def test_pemilik_sah_tetap_mendapatkannya_walau_ada_tetangga(self):
        assert tp_untuk_janjang(
            janjang=self.A, kandidat=[{"bbox": self.TP_MILIK_A}], janjang_lain=[self.B]
        ) is not None

    def test_urutan_pemrosesan_tidak_lagi_menentukan(self):
        """Inti perbaikannya: hasilnya sama, diproses A dulu atau B dulu."""
        tp = {"bbox": self.TP_MILIK_A}
        a_dulu = (
            tp_untuk_janjang(janjang=self.A, kandidat=[tp], janjang_lain=[self.B]),
            tp_untuk_janjang(janjang=self.B, kandidat=[tp], janjang_lain=[self.A]),
        )
        b_dulu = (
            tp_untuk_janjang(janjang=self.B, kandidat=[tp], janjang_lain=[self.A]),
            tp_untuk_janjang(janjang=self.A, kandidat=[tp], janjang_lain=[self.B]),
        )
        assert a_dulu == (tp, None)
        assert b_dulu == (None, tp)

    def test_janjang_lain_yang_di_luar_jangkauan_tidak_menghalangi(self):
        """Tetangga di seberang frame bukan saingan; dia tidak boleh membatalkan
        pasangan yang sah hanya karena dia ada."""
        assert tp_untuk_janjang(
            janjang=self.A,
            kandidat=[{"bbox": self.TP_MILIK_A}],
            janjang_lain=[(2000, 1700, 2400, 2000)],
        ) is not None
