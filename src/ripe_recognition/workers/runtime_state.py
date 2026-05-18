from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Any


@dataclass
class RuntimeState:
    current_truck_id: str | None = None

    # Thread-safe queues — identik dengan predict.py:84-87
    frame_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=5))
    result_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=5))
    event_queue: Queue[Any] = field(default_factory=lambda: Queue(maxsize=10))

    # Voting state per track_id — identik dengan predict.py:89-90
    track_history: dict[int, Any] = field(default_factory=dict)
    classified_labels: dict[int, tuple[str, float]] = field(default_factory=dict)

    # Thread safety untuk akses kamera — identik dengan predict.py:83
    lock: threading.Lock = field(default_factory=threading.Lock)

    # WebSocket clients aktif — identik dengan predict.py:83
    websocket_clients: list[Any] = field(default_factory=list)

    # Event loop utama untuk run_coroutine_threadsafe dari worker thread
    main_loop: asyncio.AbstractEventLoop | None = None
