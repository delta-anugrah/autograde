from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from ..domain.kesehatan_kamera import (
    AMAN,
    JENDELA_FRAME_HILANG_DETIK,
    LAJU_TURUN_TAHAN_DETIK,
    tingkat_frame_hilang,
)
from ..domain.transisi import PelacakTransisi, teks_lama
from ..integrations.camera.base import CameraSource
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)
T = TypeVar("T")

_MAX_CONSECUTIVE_FAILURES = 5
#: Pace for a source with no rate of its own that never waits in `grab_frame` (photo, video
#: file without a rate) while `CAMERA_FPS` is 0 or empty. Same number as the `CAMERA_FPS`
#: default (`tests/unit/test_camera_frame_rate.py`).
LAJU_TANPA_SUMBER_FPS = 20
_RECONNECT_BACKOFF_BASE = 1.0
_RECONNECT_BACKOFF_MAX = 30.0
# The automatic backoff sleeps in slices this long, so a press of the reconnect button
# (or a stop) waits at most one slice instead of up to `_RECONNECT_BACKOFF_MAX`.
_IRIS_JEDA_DETIK = 0.25
# Suhu kamera dan hitungan aliran berubah dalam hitungan menit; 10 detik sudah lebih rapat
# dari yang dibaca orang di kartu Diagnostik (disegarkan tiap 5 detik).
PANTAU_KAMERA_JEDA_DETIK = 10.0


class FrameCaptureWorker:
    def __init__(self, camera: CameraSource, state: RuntimeState, target_fps: int = 20, device_index: int = 0, serial: str | None = None, feature_file: str | None = None, **_) -> None:
        self.camera = camera
        self.state = state
        self._device_index = device_index
        self._serial = serial
        self._feature_file = feature_file
        self._target_fps = target_fps
        self._frame_interval = 1.0 / max(1, target_fps) if target_fps > 0 else 0.0
        self._last_frame_time: float = 0.0
        self._consecutive_failures: int = 0
        self._reconnect_backoff: float = _RECONNECT_BACKOFF_BASE
        self._fps_counter: int = 0
        self._fps_timer: float = 0.0
        self._exhausted_logged: bool = False
        # Dipasang langkah tutup line (batch 2.2): loop berhenti dan kamera tidak
        # disambung ulang, supaya kamera yang baru dilepas tidak dibuka lagi.
        self._berhenti = threading.Event()
        # Batch 3.3: satu WARNING saat kamera berhenti mengirim gambar, satu saat
        # kembali. Di antaranya grab gagal tiap 100 ms dan sambung ulang tiap <=30 dtk
        # cuma DEBUG.
        self._putus = PelacakTransisi()
        self._pantau_at: float | None = None
        self._galat_pantau_dilapor: set[str] = set()
        # One WARNING when frames start getting lost, one when the window is clean again.
        self._frame_hilang = PelacakTransisi(jam=state.jam)
        self._percobaan_sambung = 0
        self._sambung_gagal = 0

    def berhenti(self) -> None:
        """Akhiri `run_loop` sesudah putaran yang sedang jalan; jangan sambung ulang kamera."""
        self._berhenti.set()

    @property
    def frame_interval(self) -> float:
        """Seconds between grabs. 0 = grab as fast as the camera hands frames over."""
        return self._frame_interval

    def adopt_camera_frame_rate(self) -> None:
        """Let the camera decide the pace, so the rate lives in ONE place.

        On a Hikrobot line that place is the `.mfs` pushed to the camera on
        every connect (`CAMERA_FEATURE_FILE`), and reading the rate back from
        the camera is what keeps `CAMERA_FPS` from quietly becoming a second
        setting: pacing slower than the camera used to throttle it, while
        pacing faster did nothing at all.

        `CAMERA_FPS` stays the fallback for sources that cannot report a rate —
        a webcam or a video file.
        """
        detected = self.camera.get_fps()
        # Yang dipublikasikan adalah laju yang BENAR-BENAR dipakai mengambil
        # frame, bukan cuma laju yang dilaporkan kamera. Dipakai layar Rekam
        # Video supaya durasi video sama dengan durasi kejadian.
        #
        # ⚠️ Kamera Hikrobot TIDAK melaporkan lajunya (`Camera reports no frame
        # rate` di log Lampung) — tapi saat itu worker memacu dirinya pada
        # `CAMERA_FPS`, jadi angka itulah lajunya. Menulis `0` di sini membuang
        # keterangan yang ada di tangan, dan rekaman jatuh ke angka layar:
        # 19 detik kejadian jadi berkas 77 detik.
        #
        # `0` disisakan untuk kasus yang benar-benar tidak punya laju
        # (`CAMERA_FPS=0`), dan di situ angka layar memang yang dipakai.
        #
        # A source that never waits (photo, video file with no rate in its header) is
        # paced at the fallback even then: unpaced, the loop spun at 5,600 grabs a second
        # on a Mac photo line and starved detection (2026-10-04).
        cadangan = self._target_fps if self._target_fps > 0 else (
            0 if self.camera.menunggu_frame else LAJU_TANPA_SUMBER_FPS
        )
        self.state.camera_fps_terukur = float(detected) if detected > 0 else float(cadangan)
        # INFO hanya saat lajunya BERUBAH: kamera yang diam disambung ulang tiap ~2 detik
        # selama FRAME_BERHENTI, dan baris yang sama tiap siklus cuma derau.
        if detected > 0:
            self._frame_interval = 1.0 / detected
            self._catat_laju("Capture paced by the camera: %.2f fps", detected)
            return
        self._frame_interval = 1.0 / cadangan if cadangan > 0 else 0.0
        if cadangan and self._target_fps <= 0:
            self._catat_laju("Source has no frame rate and never waits; pacing at %s fps", cadangan)
            return
        self._catat_laju("Camera reports no frame rate; pacing from CAMERA_FPS=%s", self._target_fps)

    def _catat_laju(self, pesan: str, nilai: float) -> None:
        kunci = (pesan, nilai)
        level = logging.DEBUG if kunci == getattr(self, "_laju_tercatat", None) else logging.INFO
        self._laju_tercatat = kunci
        logger.log(level, pesan, nilai)

    def _try_reconnect(self) -> None:
        """Automatic reconnect after `_MAX_CONSECUTIVE_FAILURES` failed grabs, with backoff.

        A press of the reconnect button during the backoff wait cuts it short: the
        connect below then counts as that press, so it is not followed by a second one.
        """
        if self._berhenti.is_set():
            return
        logger.debug("Camera: %d consecutive failures, attempting reconnect", self._consecutive_failures)
        self._percobaan_sambung += 1
        self._lepas_kamera()
        ditekan = self._tunggu_jeda(self._reconnect_backoff)
        self._reconnect_backoff = min(self._reconnect_backoff * 2, _RECONNECT_BACKOFF_MAX)
        if self._berhenti.is_set():
            return
        oleh = self.state.ambil_permintaan_sambung_ulang() if ditekan else None
        try:
            self._sambung_kamera()
        except Exception as exc:
            if oleh is not None:
                self._catat_hasil_manual(oleh, exc)
                return
            self._sambung_gagal += 1
            if self._sambung_gagal == 1:
                logger.error(
                    "Kamera gagal disambung ulang: %s. Dicoba lagi dengan jeda sampai %d detik;"
                    " kegagalan berikutnya tidak ditulis lagi sampai kamera mengirim gambar",
                    exc, int(_RECONNECT_BACKOFF_MAX),
                )
            else:
                logger.debug("Camera reconnect failed: %s", exc)
            return
        if oleh is not None:
            self._catat_hasil_manual(oleh, None)

    def _sambung_ulang_manual(self, oleh: str) -> None:
        """The reconnect button: one disconnect and connect now, no backoff wait.

        The route already refused a source that cannot reconnect (409); this check only
        keeps a video file or a photo from being reopened if a request slips through.
        """
        if not self.camera.supports_reconnect:
            logger.info("Manual camera reconnect requested by %s ignored: this source is not a camera", oleh)
            return
        self._lepas_kamera()
        try:
            self._sambung_kamera()
        except Exception as exc:
            self._catat_hasil_manual(oleh, exc)
        else:
            self._catat_hasil_manual(oleh, None)
        self.state.catat_sambung_kamera(berhasil=self.camera.connected)

    def _catat_hasil_manual(self, oleh: str, galat: Exception | None) -> None:
        """One line per press. A failure is a WARNING, not the automatic path's ERROR: the
        operator is watching the card, and Discord carries only ERROR (rule 34)."""
        if galat is None:
            logger.info("Manual camera reconnect requested by %s: camera connected", oleh)
        else:
            logger.warning("Manual camera reconnect requested by %s failed: %s", oleh, galat)

    def _lepas_kamera(self) -> None:
        with self.state.lock:
            try:
                self.camera.disconnect()
            except Exception as exc:
                # A camera that is already gone may refuse to close; the connect below decides.
                logger.debug("Camera disconnect before reconnect raised %s: %s", type(exc).__name__, exc)

    def _sambung_kamera(self) -> None:
        """Connect under `state.lock` (rule 3). Raises what `connect()` raises."""
        with self.state.lock:
            self.camera.connect(index=self._device_index, serial=self._serial, feature_file=self._feature_file)
            self._consecutive_failures = 0
            self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
            self.adopt_camera_frame_rate()
        logger.debug("Camera reconnected")

    def _tunggu_jeda(self, detik: float) -> bool:
        """Sleep `detik` in slices; True as soon as the reconnect button was pressed.

        Slices of `time.sleep`, not `Event.wait`: the worker tests replace `time.sleep`
        to skip the backoff, and a stop request is noticed within one slice too.
        """
        for _ in range(max(1, math.ceil(detik / _IRIS_JEDA_DETIK))):
            if self.state.sambung_ulang_kamera.is_set():
                return True
            if self._berhenti.is_set():
                return False
            time.sleep(min(_IRIS_JEDA_DETIK, detik))
        return self.state.sambung_ulang_kamera.is_set()

    def _catat_kamera_putus(self) -> None:
        """Kejadian dimulai saat grab gagal `_MAX_CONSECUTIVE_FAILURES` kali berturut:
        satu-dua frame terpotong di GigE itu biasa dan tidak pantas satu baris pun."""
        if not self._putus.gagal():
            return
        self.state.putus_kamera.catat(self.state.jam())
        alasan = getattr(self.camera, "galat_terakhir", None) or "kamera tidak menyebut alasannya"
        logger.warning(
            "Kamera tidak mengirim gambar: %d kali gagal berturut (terakhir: %s)%s",
            self._consecutive_failures, alasan,
            ", menyambung ulang" if self.camera.supports_reconnect else "",
        )

    def _catat_kamera_kembali(self) -> None:
        lama = self._putus.pulih()
        if lama is None:
            return
        logger.warning(
            "Kamera mengirim gambar lagi sesudah %s (%d kali sambung ulang)",
            teks_lama(lama), self._percobaan_sambung,
        )
        self._percobaan_sambung = 0
        self._sambung_gagal = 0

    def _pantau_kamera_kalau_waktunya(self) -> None:
        """One round of camera questions per `PANTAU_KAMERA_JEDA_DETIK`, under the same camera
        lock as `grab_frame()` (rule 3). A failed question means "not known", never a reason
        to stop taking frames."""
        sekarang = self.state.jam()
        if self._pantau_at is not None and sekarang - self._pantau_at < PANTAU_KAMERA_JEDA_DETIK:
            return
        self._pantau_at = sekarang
        with self.state.lock:
            suhu = None if self.camera.suhu_didukung is False else self._tanya("temperature", self.camera.get_temperature)
            statistik = self._tanya("stream counters", self.camera.get_statistik_aliran)
        self.state.suhu_kamera_didukung = self.camera.suhu_didukung
        if suhu is not None:
            self.state.catat_suhu_kamera(suhu)
        if statistik is not None:
            self.state.frame_hilang.tambah(statistik, sekarang)
        self._nilai_laju(sekarang)
        self._nilai_frame_hilang(sekarang)

    def _tanya(self, apa: str, fungsi: Callable[[], T]) -> T | None:
        try:
            return fungsi()
        except Exception as exc:
            level = logging.DEBUG if apa in self._galat_pantau_dilapor else logging.WARNING
            self._galat_pantau_dilapor.add(apa)
            logger.log(level, "Reading the camera %s raised %s: %s", apa, type(exc).__name__, exc)
            return None

    def _nilai_laju(self, sekarang: float) -> None:
        target = self.state.camera_fps_terukur
        berubah = self.state.laju_kamera.nilai(self.state.fps_kamera, target, sekarang)
        if berubah is True:
            logger.warning(
                "Laju kamera turun: %.1f fps dari target %.1f, sudah lebih dari %d menit",
                self.state.fps_kamera, target, int(LAJU_TURUN_TAHAN_DETIK // 60),
            )
        elif berubah is False:
            logger.warning("Laju kamera normal lagi: %.1f fps dari target %.1f", self.state.fps_kamera, target)

    def _nilai_frame_hilang(self, sekarang: float) -> None:
        ringkas = self.state.frame_hilang.ringkas(sekarang)
        if ringkas is None:
            return
        hilang, total = ringkas
        menit = int(JENDELA_FRAME_HILANG_DETIK // 60)
        if tingkat_frame_hilang(hilang, total) == AMAN:
            if self._frame_hilang.pulih() is not None:
                logger.warning("Kamera tidak kehilangan gambar lagi dalam %d menit terakhir", menit)
        elif self._frame_hilang.gagal():
            logger.warning(
                "Kamera kehilangan gambar: %d dari %d dalam %d menit terakhir (%.1f%%)",
                hilang, total, menit, hilang * 100.0 / total,
            )

    def run_once(self) -> None:
        oleh = self.state.ambil_permintaan_sambung_ulang()
        if oleh is not None:
            self._sambung_ulang_manual(oleh)
            return

        now = time.time()
        wait = self._frame_interval - (now - self._last_frame_time)
        if wait > 0:
            time.sleep(wait)
        self._last_frame_time = time.time()

        with self.state.lock:
            frame = self.camera.grab_frame()

        if frame is None:
            if self.camera.exhausted:
                if not self._exhausted_logged:
                    logger.info("Camera source exhausted, capture paused without reconnect")
                    self._exhausted_logged = True
                self._consecutive_failures = 0
                time.sleep(max(self._frame_interval, 0.25))
                return

            self._exhausted_logged = False
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                self._catat_kamera_putus()
            # Syarat yang sama sengaja diulang: log putus untuk semua kamera, sambung ulang cuma yang mendukungnya.
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES and self.camera.supports_reconnect:
                self._try_reconnect()
                self.state.catat_sambung_kamera(berhasil=self.camera.connected)
            else:
                time.sleep(0.1)
            return

        self._exhausted_logged = False
        self._consecutive_failures = 0
        self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
        self._catat_kamera_kembali()
        self.state.latest_raw_frame = frame
        # Penjaga AI mati (batch 2.1): gambar MASUK. Tanpa cap ini penilai tidak
        # bisa membedakan "AI mati" dari "kamera tidak mengirim apa pun".
        self.state.catat_frame_masuk()
        self._pantau_kamera_kalau_waktunya()

        # Rekaman developer, kalau menyala. Frame di sini masih CLEAN — bbox
        # digambar jauh di hilir — jadi rekamannya otomatis polos tanpa kerja
        # tambahan.
        #
        # Dibungkus try: recorder rusak tidak boleh menjatuhkan capture worker,
        # karena itu berarti mematikan line demi fitur yang cuma dipakai saat
        # menelusuri masalah. `tulis()` sendiri tidak pernah blocking — antrean
        # penuh membuang frame, bukan menahan deteksi (lihat video_recorder).
        recorder = self.state.video_recorder
        if recorder is not None:
            try:
                recorder.tulis(frame)
            except Exception:
                logger.exception("Recorder video menolak frame, rekaman diabaikan")

        self._fps_counter += 1
        if self._fps_timer == 0.0:
            self._fps_timer = time.time()
        else:
            fps_now = time.time()
            if fps_now - self._fps_timer >= 5.0:
                logger.info("[FPS] capture=%.1f", self._fps_counter / (fps_now - self._fps_timer))
                self._fps_counter = 0
                self._fps_timer = fps_now

        # Saat video rewind (loop): flush stale frames + signal ke processing worker
        # untuk reset ByteTrack agar detection berjalan normal dari awal loop.
        if self.camera.rewound:
            while not self.state.frame_queue.empty():
                try:
                    self.state.frame_queue.get_nowait()
                except queue.Empty:
                    break
            self.state.rewind_signal = True

        # Drop-oldest policy: hapus frame paling lama dulu baru masukkan frame terbaru.
        # Ini memastikan processing worker selalu dapat frame terbaru, bukan frame stale.
        try:
            self.state.frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.state.frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.state.frame_queue.put_nowait(frame)
            except queue.Full:
                pass

    def run_loop(self) -> None:
        self.adopt_camera_frame_rate()
        while not self._berhenti.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in FrameCaptureWorker.run_once")
                time.sleep(1)
