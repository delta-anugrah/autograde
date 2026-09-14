"""End-to-end: a real clip, decoded by real OpenCV, loops through the capture worker.

Skipped without OpenCV (CI installs none). The unit tests stand cv2 in; this
one proves the seek back to frame 0 works on an actual container.
"""
from __future__ import annotations

import pytest

from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

FRAMES = 6


@pytest.fixture
def clip(tmp_path):
    """Six frames, each a flat grey a different shade, so a frame knows its index."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24, (64, 48))
    for index in range(FRAMES):
        writer.write(np.full((48, 64, 3), 20 + index * 40, dtype=np.uint8))
    writer.release()
    return path


def _shade(frame) -> int:
    return round((float(frame.mean()) - 20) / 40)


def test_a_real_clip_loops_through_the_capture_worker(clip):
    from palmgrade.integrations.camera.opencv_camera import OpenCVCamera

    camera = OpenCVCamera(source=str(clip), fps=0, is_video_file=True, loop=True)
    camera.connect()
    state = RuntimeState()
    worker = FrameCaptureWorker(camera=camera, state=state, target_fps=0)

    shades, rewinds = [], 0
    for _ in range(FRAMES * 3 + 1):
        worker.run_once()
        shades.append(_shade(state.frame_queue.queue[-1]))
        if state.rewind_signal:
            rewinds += 1
            state.rewind_signal = False  # the processing worker clears it too

    assert shades == [i % FRAMES for i in range(FRAMES * 3 + 1)]
    assert rewinds == 3
    assert camera.exhausted is False
    camera.disconnect()


def test_a_real_clip_without_loop_plays_once(clip):
    from palmgrade.integrations.camera.opencv_camera import OpenCVCamera

    camera = OpenCVCamera(source=str(clip), fps=0, is_video_file=True)
    camera.connect()
    frames = [camera.grab_frame() for _ in range(FRAMES + 1)]
    assert all(f is not None for f in frames[:FRAMES])
    assert frames[FRAMES] is None
    assert camera.exhausted is True
