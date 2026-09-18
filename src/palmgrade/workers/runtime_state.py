from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Any


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

    # Thread-safe queues
    frame_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=5))
    event_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=10))

    # MJPEG broadcast — hanya DisplayWorker yang boleh nulis ke sini.
    latest_frame: bytes | None = None
    frame_condition: threading.Condition = field(default_factory=threading.Condition)

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
