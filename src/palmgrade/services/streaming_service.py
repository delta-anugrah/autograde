from __future__ import annotations

import logging
from typing import Generator

from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class StreamingService:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def generate_frames(self) -> Generator[bytes, None, None]:
        last_frame: bytes | None = None
        while True:
            try:
                with self.state.frame_condition:
                    # Releases lock and blocks until notify_all() or timeout.
                    # All connected clients wake simultaneously — true broadcast.
                    self.state.frame_condition.wait(timeout=0.5)
                    frame = self.state.latest_frame
                if frame is not None and frame is not last_frame:
                    last_frame = frame
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
            except Exception as e:
                logger.error("Error in generate_frames: %s", e)
                break
