"""Who decides the capture rate.

There used to be two places: the `.mfs` pushed to the camera on every connect,
and `CAMERA_FPS`, which paces `FrameCaptureWorker`. The lower of the two won, so
lowering the `.mfs` worked while raising it silently did nothing — the symptom
that was read for months as "CAMERA_FPS does nothing".

One place now: a camera that can report its own rate decides. `CAMERA_FPS` is
the fallback for sources that cannot (a webcam, a video file).
"""
from __future__ import annotations

import pytest

from palmgrade.integrations.camera.base import CameraSource
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState

MFS_RATE = 15.0
ENV_RATE = 24


class FakeCamera(CameraSource):
    """A line that answers, but never hands over a frame.

    Frames are irrelevant here: what is under test is the rate the worker paces
    itself at, which is decided before any frame arrives.
    """

    def __init__(self, fps: float = 0.0, fps_after_connect: float | None = None) -> None:
        super().__init__()
        self._fps = fps
        self._fps_after_connect = fps_after_connect
        self.connects = 0

    def connect(self, index: int = 0, serial=None, feature_file=None) -> None:
        self.connects += 1
        # The real camera only knows its rate once the .mfs has been pushed,
        # which happens inside connect().
        if self._fps_after_connect is not None:
            self._fps = self._fps_after_connect
        self.connected = True

    def grab_frame(self):
        return None

    def disconnect(self) -> None:
        self.connected = False

    def get_fps(self) -> float:
        return self._fps


def _worker(camera: FakeCamera) -> FrameCaptureWorker:
    return FrameCaptureWorker(camera=camera, state=RuntimeState(), target_fps=ENV_RATE)


def test_the_camera_rate_wins_over_camera_fps():
    worker = _worker(FakeCamera(fps=MFS_RATE))

    worker.adopt_camera_frame_rate()

    assert worker.frame_interval == pytest.approx(1 / MFS_RATE)


def test_camera_fps_is_the_fallback_when_the_camera_cannot_report_one():
    # A webcam or a video file: CAMERA_FPS is all there is.
    worker = _worker(FakeCamera(fps=0.0))

    worker.adopt_camera_frame_rate()

    assert worker.frame_interval == pytest.approx(1 / ENV_RATE)


def test_the_rate_is_read_again_after_a_reconnect(monkeypatch):
    """A camera that comes back has just been sent the `.mfs` again, and it may
    now hold a different rate — the worker must not keep pacing at the old one."""
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    camera = FakeCamera(fps=0.0, fps_after_connect=MFS_RATE)
    worker = _worker(camera)
    worker.adopt_camera_frame_rate()
    assert worker.frame_interval == pytest.approx(1 / ENV_RATE)

    for _ in range(5):  # _MAX_CONSECUTIVE_FAILURES, then the worker reconnects
        worker.run_once()

    assert camera.connects == 1
    assert worker.frame_interval == pytest.approx(1 / MFS_RATE)


def test_a_camera_reporting_nothing_and_no_camera_fps_does_not_divide_by_zero():
    worker = FrameCaptureWorker(camera=FakeCamera(fps=0.0), state=RuntimeState(), target_fps=0)

    worker.adopt_camera_frame_rate()

    assert worker.frame_interval == 0.0
