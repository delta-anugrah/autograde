"""A video file that loops until the line is stopped.

For performance runs on the mill PC: one line plays a clip over and over while
the others keep their real cameras. Guarded here: looping is opt-in and off by
default (a video still plays once), each new pass is flagged so the tracker
restarts, a file that cannot start over stops instead of spinning, and a real
camera never reports a rewind.

cv2 is swapped for a stand-in: CI installs no OpenCV. The real decoder is
exercised in `tests/e2e/test_video_loop_opencv.py`.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.camera.base import CameraSource
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState

POS_FRAMES = 1
MODULE = "palmgrade.integrations.camera.opencv_camera"


class FakeCapture:
    def __init__(self, frames: list, *, seekable: bool = True) -> None:
        self.frames, self.seekable, self.pos, self.opened = frames, seekable, 0, True

    def isOpened(self) -> bool:  # noqa: N802 - cv2's own naming
        return self.opened

    def read(self):
        if self.pos < len(self.frames):
            self.pos += 1
            return True, self.frames[self.pos - 1]
        return False, None

    def set(self, prop, value) -> bool:
        if prop != POS_FRAMES:
            return True
        if self.seekable:
            self.pos = int(value)
        return self.seekable

    def get(self, _prop) -> float:
        return 24.0

    def release(self) -> None:
        self.opened = False


@pytest.fixture
def video(monkeypatch):
    """Build an OpenCVCamera over a fake clip: `video(frames, loop=..., seekable=...)`."""

    def build(frames: list, *, loop: bool = False, seekable: bool = True):
        capture = FakeCapture(frames, seekable=seekable)
        fake_cv2 = SimpleNamespace(
            VideoCapture=lambda _source: capture,
            CAP_PROP_POS_FRAMES=POS_FRAMES, CAP_PROP_FPS=5,
            CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4,
        )
        monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
        monkeypatch.delitem(sys.modules, MODULE, raising=False)
        module = importlib.import_module(MODULE)
        camera = module.OpenCVCamera(source="clip.mov", is_video_file=True, loop=loop)
        camera.connect()
        return camera

    yield build
    # The module imported here is bound to the fake cv2: drop it, or a later test
    # that imports the real camera gets this one.
    sys.modules.pop(MODULE, None)


def _grab(camera, n: int) -> list:
    return [camera.grab_frame() for _ in range(n)]


def test_a_looping_video_starts_over_instead_of_stopping(video):
    camera = video(["a", "b"], loop=True)
    assert _grab(camera, 5) == ["a", "b", "a", "b", "a"]
    assert camera.exhausted is False


def test_the_first_frame_of_each_new_pass_is_flagged_once(video):
    camera = video(["a", "b"], loop=True)
    flags = []
    for _ in range(5):
        camera.grab_frame()
        flags.append(camera.rewound)
    assert flags == [False, False, True, False, True]


def test_without_loop_a_video_still_plays_once_and_stops(video):
    camera = video(["a", "b"])
    assert _grab(camera, 3) == ["a", "b", None]
    assert camera.exhausted is True


def test_an_empty_video_stops_instead_of_spinning(video):
    camera = video([], loop=True)
    assert camera.grab_frame() is None
    assert camera.exhausted is True


def test_a_video_that_cannot_start_over_stops_instead_of_spinning(video):
    camera = video(["a", "b"], loop=True, seekable=False)
    assert _grab(camera, 3) == ["a", "b", None]
    assert camera.exhausted is True


class LiveCamera(CameraSource):
    """A real camera as the worker sees it: frames, and no idea what a rewind is."""

    def connect(self, index: int = 0, serial=None, feature_file=None) -> None:
        self.connected = True

    def grab_frame(self):
        return "frame"

    def disconnect(self) -> None:
        self.connected = False


class RewindingCamera(LiveCamera):
    @property
    def rewound(self) -> bool:
        return True


def _run_once(camera: CameraSource) -> RuntimeState:
    state = RuntimeState()
    state.frame_queue.put_nowait("stale")
    FrameCaptureWorker(camera=camera, state=state, target_fps=0).run_once()
    return state


def test_a_live_camera_never_signals_a_rewind():
    state = _run_once(LiveCamera())
    assert state.rewind_signal is False
    assert list(state.frame_queue.queue) == ["stale", "frame"]


def test_a_rewind_drops_stale_frames_and_restarts_the_tracker():
    state = _run_once(RewindingCamera())
    assert state.rewind_signal is True
    assert list(state.frame_queue.queue) == ["frame"]


def test_looping_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("CAMERA_VIDEO_LOOP", raising=False)
    assert Settings().camera_video_loop is False
    monkeypatch.setenv("CAMERA_VIDEO_LOOP", "true")
    assert Settings().camera_video_loop is True


def test_the_loop_setting_reaches_every_line_and_the_camera():
    repo = Path(__file__).resolve().parents[2]
    compose = re.findall(
        r"CAMERA_VIDEO_LOOP=\$\{CAMERA_VIDEO_LOOP:-(\w+)\}", (repo / "docker-compose.yml").read_text()
    )
    assert compose == ["false"] * 3, "every line must carry the setting, off by default"
    assert "\nCAMERA_VIDEO_LOOP=false\n" in (repo / ".env.example").read_text()
    # main.py imports torch, so it cannot be run here; the wiring is read instead.
    assert "loop=settings.camera_video_loop" in (repo / "src/palmgrade/main.py").read_text()
