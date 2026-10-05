from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Queue
from typing import Any

from ..domain.kesehatan_ai import JEDA_ALIRAN_DETIK
from ..domain.kesehatan_kamera import HitungPutus, JendelaFrameHilang, PenilaiLaju
from .perintah_kamera import AntreanPerintahKamera

#: Lebar jendela hitung `fps_kamera`. Sama dengan log `[FPS] capture` di
#: `FrameCaptureWorker`, supaya dua angka itu bisa dibandingkan langsung.
JENDELA_FPS_DETIK = 5.0


@dataclass
class RuntimeState:
    current_truck_id: str | None = None
    current_assignment_id: str | None = None          # set by /internal/assignment
    current_ffb_source: str | None = None             # "Internal" / "External" / None
    # Capture-folder label and clock, both set by /internal/assignment. The
    # folder is named once per truck, so its time is when the truck was
    # assigned — not when each bunch happened to be graded.
    current_plate: str | None = None
    current_assigned_at: str | None = None            # ISO, mill-local from the console
    last_successful_api_push: str | None = None       # ISO timestamp, set by OutboxRetryWorker

    # Setelan grading yang ditimpa dari konsol (`/internal/setelan`). None =
    # pakai nilai `.env` lewat `Settings`. Ditaruh di sini, BUKAN di `Settings`,
    # karena `Settings` itu `frozen=True` dengan sengaja: env tidak boleh berubah
    # diam-diam di tengah jalan, dan satu-satunya yang boleh bergerak saat line
    # hidup adalah dua angka ini. Dibaca tiap frame, jadi berlaku tanpa restart.
    conf_threshold_override: float | None = None
    minimum_size_override: int | None = None
    # Garis capture dalam ruang STREAM (px dari kiri). 0 = tidak ada garis, dan
    # itu perilaku sebelum fitur ini ada: semua janjang di dalam ROI difoto.
    garis_capture_override: int | None = None
    # Sumbu garis: "tegak" (conveyor mendatar) atau "mendatar" (conveyor
    # menurun). Menentukan koordinat mana yang dibandingkan dengan garis.
    sumbu_garis_override: str | None = None
    # Mode dev: tampilkan angka confidence di kotak janjang. Untuk support
    # yang menyetel ambang; operator tidak butuh dan salah membacanya.
    mode_dev_override: bool | None = None
    # Draw the capture line / the ROI box on the video (2026-10-04). Display only:
    # detection and capture keep using both. None = never set from the console = drawn.
    tampil_garis_override: bool | None = None
    tampil_roi_override: bool | None = None
    # ROI box (x1, y1, x2, y2) in stream space, set from the console. None = `ROI_*` from `.env`.
    roi_override: tuple[int, int, int, int] | None = None
    # Size of the class label on the video, percent (2026-10-05). Display only. None = 100.
    ukuran_label_override: int | None = None

    # Laju yang BENAR-BENAR dikirim kamera, diisi `adopt_camera_frame_rate()`
    # tiap connect. `0` = sumber tidak bisa melapor (berkas video, webcam).
    #
    # Ada di sini karena endpoint `/internal/rekam/mulai` tidak punya akses ke
    # capture worker, sementara rekaman HARUS ditulis pada laju yang sama
    # dengan kejadiannya — kalau tidak, videonya melambat atau mempercepat
    # tanpa ada yang tahu (terjadi di Lampung 2026-09-23: 19 detik jadi 77).
    camera_fps_terukur: float = 0.0

    # Recorder video developer (layar Rekam Video), kalau sedang merekam.
    # `None` selama tidak ada yang merekam — line yang tidak pernah dipakai
    # merekam tidak menyentuh modul rekam sama sekali. Tipenya `Any` supaya
    # modul ini tidak mengimpor `services.video_recorder`, yang menarik cv2.
    video_recorder: Any = None

    # Thread-safe queues
    frame_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=5))
    event_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=10))

    # MJPEG broadcast — hanya DisplayWorker yang boleh nulis ke sini.
    latest_frame: bytes | None = None
    frame_condition: threading.Condition = field(default_factory=threading.Condition)
    # Who is reading the MJPEG stream right now (batch 6.3). `StreamingService` counts each
    # viewer in and out; `DisplayWorker` renders only while this is above zero.
    penonton_stream: int = 0
    kunci_penonton: threading.Lock = field(default_factory=threading.Lock)

    # Shared display state — capture worker set raw_frame, processing worker set last_results.
    # DisplayWorker baca keduanya untuk render MJPEG.
    latest_raw_frame: Any = None          # numpy ndarray, ditulis capture worker
    last_yolo_results: Any = None         # ultralytics Results, ditulis processing worker
    last_yolo_frame: Any = None           # frame yg BENAR-BENAR di-proses YOLO — paired dengan last_yolo_results
    last_yolo_frame_at: float = 0.0       # time.time() saat last_yolo_frame terakhir diupdate
    # TP yang muncul sesudah janjang terdekatnya difoto, jadi tidak ikut ke
    # mana pun. Nol berarti aturan "capture apa adanya" tidak kehilangan
    # tangkai; angka yang naik terus adalah alasan terukur untuk menahan
    # penyimpanan sesaat menunggu TP menyusul.
    tp_telat: int = 0
    # Last Sync (Cloud Photo): `BatchUploadWorker.status_unggah`, dipasang main.py.
    status_unggah: Any = None
    inference_fps: float = 0.0            # YOLO inference FPS — ditulis FrameProcessingWorker, dibaca DisplayWorker overlay

    track_history: dict[int, Any] = field(default_factory=dict)

    # Thread safety untuk akses kamera
    lock: threading.Lock = field(default_factory=threading.Lock)

    # WebSocket clients aktif
    websocket_clients: list[Any] = field(default_factory=list)

    # Event loop utama untuk run_coroutine_threadsafe dari worker thread
    main_loop: asyncio.AbstractEventLoop | None = None

    # Worker threads — populated by main.py lifespan, used by watchdog
    worker_threads: list[tuple[str, threading.Thread, Any]] = field(default_factory=list)

    # Signal dari FrameCaptureWorker ke FrameProcessingWorker saat video loop/rewind
    rewind_signal: bool = False

    # Detik Unix akhir masa tenggang lisensi. 0 = tidak ada lisensi valid.
    # Sengaja int biasa, bukan objek lisensi: worker grading itu thread sinkron
    # sementara LicenseManager async (aiosqlite). Menyeret async ke run_loop
    # harganya jauh lebih mahal daripada satu int yang dibandingkan time.time().
    # Diisi main.py saat lifespan; diabaikan kalau LICENSE_ENABLED=false.
    license_exp: int = 0

    # ── Penjaga AI mati (batch 2.1, `services/penjaga_ai.py`) ──────────────
    # Jam yang dipakai keempat cap di bawah DAN penilainya. `time.monotonic`:
    # jam dinding PC pabrik bisa melompat berjam-jam saat dapat internet, dan
    # lompatan itu tidak boleh terbaca sebagai AI mati. Test menukarnya.
    jam: Callable[[], float] = field(default=time.monotonic)
    ai_dimulai_at: float = 0.0            # loop deteksi mulai jalan (sekali per proses)
    frame_terakhir_at: float = 0.0        # frame terakhir masuk dari kamera
    aliran_frame_sejak: float = 0.0       # awal aliran frame sekarang (sesudah jeda)
    # Frame terakhir yang SELESAI digrading, bukan cuma masuk ke model:
    # `last_yolo_frame_at` di atas dicap sebelum janjangnya diproses, jadi
    # exception sesudah inferensi tetap membuatnya segar tiap detik.
    inferensi_selesai_at: float = 0.0
    # Galat terakhir loop deteksi, untuk `/health/detail` (support), BUKAN
    # untuk layar operator. `ai_galat_at` jam dinding: cuma untuk dibaca.
    ai_galat_terakhir: str | None = None
    ai_galat_at: float = 0.0
    # `PenjagaAi` line ini, dipasang main.py. None di konsol dan sebelum lifespan.
    penjaga_ai: Any = None

    # ── Health jujur (batch 3.6) ───────────────────────────────────────────
    # Hasil sambung kamera terakhir sejak gambar terakhir: `connect()` saat boot
    # (main.py) lalu tiap sambung ulang `FrameCaptureWorker`. None = belum ada
    # sambung sejak gambar terakhir (gambar yang masuk membuktikan kameranya
    # tersambung). Penilai memakainya untuk menutup sela antara `connect()`
    # menyetel `connected` dan hasilnya dicatat di sini
    # (`domain/kesehatan_ai._tersambung`).
    kamera_sambung_ok: bool | None = None
    # Ada sambung yang BERHASIL sejak gambar terakhir masuk: kameranya ada tapi
    # diam. Tetap True walau sambung sesudahnya gagal, supaya sambung ulang yang
    # berselang berhasil dan gagal tidak membuat penilaian berkedip antara frame
    # berhenti dan kamera putus. Dikosongkan tiap gambar masuk.
    kamera_sambung_ok_sejak_frame: bool = False
    # Ada sambung yang GAGAL sejak gambar terakhir masuk.
    kamera_sambung_gagal_sejak_frame: bool = False
    # Sambung BERHASIL yang pertama sejak gambar terakhir, dan sebelumnya sudah
    # ada yang gagal: kamera kembali dari putus sungguhan, tenggang gambar mulai
    # lagi dari sini. Dicap sekali per kejadian. Sambung berhasil tanpa gagal
    # sebelumnya (Hikrobot diam) dan sambung berhasil berikutnya dalam kejadian
    # yang sama tidak mencapnya, kalau tidak tenggangnya diperpanjang selamanya.
    kamera_pulih_at: float = 0.0
    # Laju gambar masuk yang TERUKUR (bukan laju setelan `camera_fps_terukur`),
    # dihitung tiap `JENDELA_FPS_DETIK`. Dibaca bersama `frame_terakhir_at`:
    # angkanya membeku saat gambar berhenti, jadi pembaca yang menentukan 0.
    fps_kamera: float = 0.0
    # Suhu badan kamera (°C) dan jam bacanya (`jam()`), diisi `FrameCaptureWorker`
    # tiap `PANTAU_KAMERA_JEDA_DETIK` selama gambar mengalir. None = belum pernah terbaca:
    # sumber tanpa sensor, atau kamera menolak menjawab. Basi-tidaknya diputuskan
    # `HealthService.ringkasan_kamera`, bukan di sini.
    suhu_kamera_c: float | None = None
    suhu_kamera_at: float = 0.0
    # `CameraSource.suhu_didukung` as last seen by the capture thread: False = the camera
    # has no sensor, and the card says so instead of a dash.
    suhu_kamera_didukung: bool | None = None
    # Camera health without a sensor (`domain/kesehatan_kamera.py`): written only by the
    # capture thread every `PANTAU_KAMERA_JEDA_DETIK`, read by `HealthService`.
    laju_kamera: PenilaiLaju = field(default_factory=PenilaiLaju)
    frame_hilang: JendelaFrameHilang = field(default_factory=JendelaFrameHilang)
    putus_kamera: HitungPutus = field(default_factory=HitungPutus)
    _fps_jendela_mulai: float = 0.0
    _fps_jumlah: int = 0
    # `PemantauDisk` line ini (batch 3.7), dipasang main.py. None di konsol.
    pemantau_disk: Any = None

    # Reconnect camera button (2026-10-04). The route only raises this flag; the capture
    # thread is the one that touches the camera, under `lock` (rule 3: the SDK is not
    # thread safe). An Event so the automatic backoff wait can be cut short by a press.
    sambung_ulang_kamera: threading.Event = field(default_factory=threading.Event)
    sambung_ulang_oleh: str | None = None
    # Camera commands from request threads (camera settings, spec §3.2), run by the capture thread between two
    # grabs under `lock` (rule 3). The route waits on it; it never calls the SDK itself.
    perintah_kamera: AntreanPerintahKamera = field(default_factory=AntreanPerintahKamera)
    # The `.mfs` pushed at the last connect (`integrations/camera/berkas_fitur.py`): the settings screen says
    # whether the camera runs on a saved file or on the baseline. None = no file pushed.
    berkas_fitur_aktif: str | None = None

    def penonton_masuk(self) -> None:
        """One more reader of the MJPEG stream."""
        with self.kunci_penonton:
            self.penonton_stream += 1

    def penonton_keluar(self) -> None:
        """One reader left. Never below zero: a count that went negative would stop the
        display for the viewers that are still there."""
        with self.kunci_penonton:
            self.penonton_stream = max(0, self.penonton_stream - 1)

    def catat_ai_dimulai(self) -> None:
        """Sekali per proses: watchdog yang menyalakan ulang thread deteksi tidak
        boleh memberi tenggang baru, kalau tidak thread yang mati berulang tidak
        pernah terbaca mati."""
        if self.ai_dimulai_at <= 0:
            self.ai_dimulai_at = self.jam()

    def catat_frame_masuk(self) -> None:
        sekarang = self.jam()
        if sekarang - self.frame_terakhir_at > JEDA_ALIRAN_DETIK:
            self.aliran_frame_sejak = sekarang
            self.fps_kamera = 0.0
            self._fps_jendela_mulai, self._fps_jumlah = sekarang, 0
        else:
            self._fps_jumlah += 1
            lama = sekarang - self._fps_jendela_mulai
            if lama >= JENDELA_FPS_DETIK:
                self.fps_kamera = self._fps_jumlah / lama
                self._fps_jendela_mulai, self._fps_jumlah = sekarang, 0
        self.frame_terakhir_at = sekarang
        self.kamera_sambung_ok = None
        self.kamera_sambung_ok_sejak_frame = False
        self.kamera_sambung_gagal_sejak_frame = False

    def catat_sambung_kamera(self, *, berhasil: bool) -> None:
        """Hasil satu sambung kamera: saat boot atau sambung ulang (batch 3.6)."""
        if berhasil:
            if self.kamera_sambung_gagal_sejak_frame and not self.kamera_sambung_ok_sejak_frame:
                self.kamera_pulih_at = self.jam()
            self.kamera_sambung_ok_sejak_frame = True
        else:
            self.kamera_sambung_gagal_sejak_frame = True
        self.kamera_sambung_ok = berhasil

    def minta_sambung_ulang_kamera(self, oleh: str) -> None:
        """Ask the capture thread to reconnect the camera on its next turn. Repeating it
        before then still means one reconnect."""
        self.sambung_ulang_oleh = oleh
        self.sambung_ulang_kamera.set()

    def ambil_permintaan_sambung_ulang(self) -> str | None:
        """Who asked for a reconnect, once; None when nobody did since the last call."""
        if not self.sambung_ulang_kamera.is_set():
            return None
        self.sambung_ulang_kamera.clear()
        return self.sambung_ulang_oleh or "?"

    def catat_suhu_kamera(self, suhu_c: float) -> None:
        self.suhu_kamera_c = suhu_c
        self.suhu_kamera_at = self.jam()

    def catat_inferensi_selesai(self) -> None:
        self.inferensi_selesai_at = self.jam()

    def catat_galat_ai(self, exc: BaseException) -> None:
        self.ai_galat_terakhir = f"{type(exc).__name__}: {exc}"[:300]
        self.ai_galat_at = time.time()
