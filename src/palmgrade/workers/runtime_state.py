from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Any


@dataclass
class RuntimeState:
    current_truck_id: str | None = None

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

    track_history: dict[int, Any] = field(default_factory=dict)

    # Thread safety untuk akses kamera
    lock: threading.Lock = field(default_factory=threading.Lock)

    # WebSocket clients aktif
    websocket_clients: list[Any] = field(default_factory=list)

    # Event loop utama untuk run_coroutine_threadsafe dari worker thread
    main_loop: asyncio.AbstractEventLoop | None = None

    # Worker threads — populated by main.py lifespan, used by watchdog
    worker_threads: list[tuple[str, threading.Thread, Any]] = field(default_factory=list)
