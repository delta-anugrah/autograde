from __future__ import annotations

import logging
from typing import Generator

from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)

# MJPEG keep-alive: sebuah boundary kosong yang di-ignore oleh viewer, tapi cukup
# untuk memaksa generator yield saat idle. Tanpa ini, kalau kamera down dan tidak
# ada frame baru, generator sync ini blok selamanya tanpa pernah yield → thread
# anyio yang menyervis /api/video_feed tidak pernah balik ke pool (disconnect
# client baru terdeteksi saat yield berikutnya). Retry stream dari frontend saat
# kamera down = thread bocor satu per satu → threadpool habis → SEMUA endpoint
# (termasuk /health) ikut hang. Keep-alive menutup lubang ini.
_KEEPALIVE = b"--frame\r\n\r\n"

# Berapa tick idle (tanpa frame baru) sebelum memancarkan satu keep-alive.
# Pada _WAIT_TIMEOUT=0.5s, 4 tick ≈ 2 detik — cukup sering untuk mendeteksi
# disconnect, cukup jarang untuk tidak membebani viewer yang sehat.
_IDLE_YIELD_AFTER = 4
_WAIT_TIMEOUT = 0.5


class StreamingService:
    def __init__(
        self,
        state: RuntimeState,
        idle_yield_after: int = _IDLE_YIELD_AFTER,
        wait_timeout: float = _WAIT_TIMEOUT,
    ) -> None:
        self.state = state
        self._idle_yield_after = idle_yield_after
        self._wait_timeout = wait_timeout

    def generate_frames(self) -> Generator[bytes, None, None]:
        last_frame: bytes | None = None
        idle_ticks = 0
        while True:
            try:
                with self.state.frame_condition:
                    # Releases lock and blocks until notify_all() or timeout.
                    # All connected clients wake simultaneously — true broadcast.
                    self.state.frame_condition.wait(timeout=self._wait_timeout)
                    frame = self.state.latest_frame

                if frame is not None and frame is not last_frame:
                    last_frame = frame
                    idle_ticks = 0
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                else:
                    # Tidak ada frame baru (kamera down / stream stale). Pancarkan
                    # keep-alive secara berkala supaya disconnect client terdeteksi
                    # dan thread dilepas balik ke pool.
                    idle_ticks += 1
                    if idle_ticks >= self._idle_yield_after:
                        idle_ticks = 0
                        yield _KEEPALIVE
            except Exception as e:
                logger.error("Error in generate_frames: %s", e)
                break
