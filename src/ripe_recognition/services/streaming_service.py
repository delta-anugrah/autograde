from __future__ import annotations

import time
from typing import Generator

from ..workers.runtime_state import RuntimeState


class StreamingService:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    def generate_frames(self) -> Generator[bytes, None, None]:
        while True:
            try:
                if not self.state.result_queue.empty():
                    frame_bytes = self.state.result_queue.get()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame_bytes
                        + b"\r\n"
                    )
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"Error in generate_frames: {e}")
                break
