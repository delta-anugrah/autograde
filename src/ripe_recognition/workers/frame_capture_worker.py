from __future__ import annotations

import time

from ..integrations.camera.base import CameraSource
from .runtime_state import RuntimeState


class FrameCaptureWorker:
    def __init__(self, camera: CameraSource, state: RuntimeState) -> None:
        self.camera = camera
        self.state = state

    def run_once(self) -> None:
        with self.state.lock:
            frame = self.camera.grab_frame()
        if frame is None:
            return
        if not self.state.frame_queue.full():
            self.state.frame_queue.put(frame)

    def run_loop(self) -> None:
        while True:
            self.run_once()
            time.sleep(0.001)
