"""Laju frame datang dari SUMBERNYA, dan rekaman memakai laju yang sama.

Dua kegagalan terpisah yang sama-sama membuat video tidak sesuai kejadiannya:

1. **Berkas video dipaksa ke `CAMERA_FPS`.** `connect()` menyetel
   `CAP_PROP_FPS` kalau `CAMERA_FPS` terisi, dan baru membaca laju asli berkas
   kalau env itu kosong. Di PC pabrik `CAMERA_FPS=20`, jadi berkas 30 fps
   diputar 20 fps — melambat sebelum urusan rekaman sama sekali.

2. **Kamera yang tidak bisa melapor menulis `0` ke state.** Hikrobot memang
   tidak melaporkan lajunya (`Camera reports no frame rate` di log Lampung),
   tapi saat itu worker TAHU laju yang dipakainya: `CAMERA_FPS`. Menulis `0`
   membuang keterangan yang ada di tangan, dan encoder jatuh ke angka layar.

Yang dipublikasikan seharusnya **laju yang benar-benar dipakai mengambil
frame**, apa pun sumbernya.
"""
from __future__ import annotations

from palmgrade.integrations.camera.base import CameraSource
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState


class _KameraLapor(CameraSource):
    """Sumber yang bisa menyebutkan lajunya sendiri — berkas video, atau webcam
    yang driver-nya menjawab."""

    def __init__(self, fps: float) -> None:
        super().__init__()
        self._fps = fps

    def connect(self, index: int = 0, serial=None, feature_file=None) -> None:
        self.connected = True

    def grab_frame(self):
        return None

    def disconnect(self) -> None:
        self.connected = False

    def get_fps(self) -> float:
        return self._fps


# ── laju yang dipakai dipublikasikan, apa pun sumbernya ─────────────────────


def test_sumber_yang_melapor_menang():
    """Berkas video 30 fps diputar 30 fps, bukan `CAMERA_FPS`."""
    state = RuntimeState()
    w = FrameCaptureWorker(camera=_KameraLapor(30.0), state=state, target_fps=20)

    w.adopt_camera_frame_rate()

    assert state.camera_fps_terukur == 30.0


def test_sumber_yang_tidak_melapor_memakai_camera_fps():
    """⚠️ Ini kasus Hikrobot di Lampung, dan yang lolos dari test sebelumnya.

    Kamera tidak melapor, tapi worker memacu dirinya pada `CAMERA_FPS=20` —
    jadi 20 ADALAH laju yang sebenarnya dipakai. Menulis `0` di sini membuat
    rekaman jatuh ke angka layar (5) dan videonya melambat 4x.
    """
    state = RuntimeState()
    w = FrameCaptureWorker(camera=_KameraLapor(0.0), state=state, target_fps=20)

    w.adopt_camera_frame_rate()

    assert state.camera_fps_terukur == 20.0


def test_tanpa_laju_sama_sekali_menulis_nol():
    """Kontrol negatif: `CAMERA_FPS=0` berarti memang tidak ada pacing, dan
    `0` tetap cara mengatakan "pakai angka setelan"."""
    state = RuntimeState()
    w = FrameCaptureWorker(camera=_KameraLapor(0.0), state=state, target_fps=0)

    w.adopt_camera_frame_rate()

    assert state.camera_fps_terukur == 0.0


# ── berkas video tidak dipaksa ke CAMERA_FPS ────────────────────────────────


def test_berkas_video_memakai_laju_aslinya(monkeypatch):
    """`connect()` tidak boleh menyetel `CAP_PROP_FPS` untuk sebuah BERKAS.

    Menyetelnya pada berkas tidak mengubah isi berkas — ia cuma membuat
    `get_fps()` membalas angka yang dipaksakan, jadi laju asli hilang tanpa
    jejak dan pemutaran ikut melambat.
    """
    import palmgrade.integrations.camera.opencv_camera as modul

    disetel: list[tuple] = []

    class _CapPalsu:
        def isOpened(self):
            return True

        def set(self, prop, nilai):
            disetel.append((prop, nilai))

        def get(self, prop):
            return 30.0 if prop == modul.cv2.CAP_PROP_FPS else 0.0

    monkeypatch.setattr(modul.cv2, "VideoCapture", lambda *a, **k: _CapPalsu())

    kam = modul.OpenCVCamera(source="uji.avi", fps=20, is_video_file=True)
    kam.connect()

    assert kam.get_fps() == 30.0, "laju asli berkas harus menang"
    assert not any(p == modul.cv2.CAP_PROP_FPS for p, _ in disetel), disetel


def test_webcam_masih_boleh_dipaksa(monkeypatch):
    """Kontrol negatif: untuk perangkat sungguhan, menyetel laju itu perintah
    ke driver dan memang bermakna. Yang berubah cuma perlakuan BERKAS."""
    import palmgrade.integrations.camera.opencv_camera as modul

    disetel: list[tuple] = []

    class _CapPalsu:
        def isOpened(self):
            return True

        def set(self, prop, nilai):
            disetel.append((prop, nilai))

        def get(self, prop):
            return 0.0

    monkeypatch.setattr(modul.cv2, "VideoCapture", lambda *a, **k: _CapPalsu())

    kam = modul.OpenCVCamera(source=0, fps=20, is_video_file=False)
    kam.connect()

    assert any(p == modul.cv2.CAP_PROP_FPS and n == 20 for p, n in disetel), disetel
