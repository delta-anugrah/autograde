"""Cap waktu penjaga AI di dua worker ASLI (batch 2.1), tanpa torch.

Yang dijaga: frame masuk dicap oleh capture; frame SELESAI dicap oleh deteksi
hanya kalau seluruh putaran selesai (exception di mana pun = tidak dicap), dan
galatnya disimpan untuk support. `run_loop` sendiri tidak pernah berhenti,
jadi yang diuji `putaran()`, isi satu putarannya.
"""
from __future__ import annotations

from ai_palsu import LinePalsu


def test_frame_masuk_dicap_capture():
    line = LinePalsu()
    line.capture.run_once()
    assert line.state.frame_terakhir_at == 1_000.0


def test_frame_yang_tidak_datang_tidak_dicap():
    line = LinePalsu()
    line.kamera.mengirim = False
    line.capture.run_once()
    assert line.state.frame_terakhir_at == 0.0


def test_putaran_sukses_mencap_inferensi_selesai():
    line = LinePalsu()
    line.jalan(1)
    assert line.state.inferensi_selesai_at == 1_000.0
    assert line.pipeline.dipanggil == 1


def test_putaran_yang_melempar_tidak_mencap_dan_menyimpan_galat():
    line = LinePalsu()
    line.pipeline.galat = RuntimeError("CUDA error: an illegal memory access was encountered")
    line.jalan(3)
    assert line.state.inferensi_selesai_at == 0.0
    assert line.state.ai_galat_terakhir == "RuntimeError: CUDA error: an illegal memory access was encountered"


def test_exception_sesudah_inferensi_juga_tidak_mencap():
    """`last_yolo_frame_at` dicap SEBELUM janjang diproses. Kalau cap penjaga
    ikut di sana, bug di loop janjang membuat line terlihat memproses."""
    line = LinePalsu()

    class HasilRusak:
        names: dict = {}

        @property
        def boxes(self):
            raise ValueError("kotak rusak")

    line.pipeline.track_ripeness = lambda frame, conf=None: HasilRusak()
    line.jalan(1)
    assert line.state.last_yolo_frame_at > 0
    assert line.state.inferensi_selesai_at == 0.0
    assert "ValueError: kotak rusak" in line.state.ai_galat_terakhir


def test_frame_lompatan_skip_tidak_mencap_tapi_frame_yolo_mencap():
    line = LinePalsu(yolo_skip_frames=3)
    line.jalan(2)
    pertama = line.state.inferensi_selesai_at
    line.jalan(3)
    assert pertama == 1_000.0                          # frame 1: belum ada hasil, selalu YOLO
    assert line.state.inferensi_selesai_at == 1_002.0  # frame 3 (3 % 3 == 0); frame 4-5 dilompati


def test_putaran_gagal_menjeda_lewat_tidur_yang_disuntik():
    jeda = []
    line = LinePalsu()
    line.deteksi._tidur = jeda.append
    line.pipeline.galat = RuntimeError("x")
    line.capture.run_once()
    line.deteksi.putaran()
    assert jeda == [1.0]
    assert isinstance(jeda[0], float)


class _Berhenti(BaseException):
    """Keluar dari `run_loop` yang berputar selamanya, sesudah putaran pertama."""


def test_run_loop_memulai_tenggang_ai_sebelum_putaran_pertama():
    """Parkiran Task 5: `run_loop` yang mencap `ai_dimulai_at` dulu tidak teruji,
    `LinePalsu` menyalin baris itu sendiri. Sekarang lewat `mulai()` yang sama."""
    line = LinePalsu()
    urutan = []

    def putaran() -> None:
        urutan.append(("putaran", line.state.ai_dimulai_at))
        raise _Berhenti

    line.deteksi.putaran = putaran
    try:
        line.deteksi.run_loop()
    except _Berhenti:
        pass

    assert urutan == [("putaran", 1_000.0)]


def test_line_palsu_memakai_mulai_milik_worker():
    line = LinePalsu()
    dipanggil = []
    line.deteksi.mulai = lambda: dipanggil.append(1)
    line.mulai()
    assert dipanggil == [1]


def test_lisensi_habis_tidak_mencap_inferensi():
    line = LinePalsu(lic_enabled=True)
    line.state.license_exp = 0
    line.jalan(2)
    assert line.state.inferensi_selesai_at == 0.0
