"""End-to-end: the built image can track with no network at all.

Skipped unless E2E_IMAGE names a built vision image (e.g. palmgrade-vision:latest).
The container runs with `--network none`, so Ultralytics' runtime pip install —
which hid the missing `lap` on one Lampung line and not the other two — cannot
paper over a missing dependency.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

IMAGE = os.getenv("E2E_IMAGE", "")
pytestmark = pytest.mark.skipif(
    not IMAGE or shutil.which("docker") is None, reason="E2E_IMAGE not set or no docker"
)

# The exact import ByteTrack's matcher does, plus one real assignment solve.
PROBE = (
    "import numpy as np, lap; "
    "from ultralytics.trackers.utils import matching; "
    "cost, x, y = lap.lapjv(np.array([[1.0, 9.0], [9.0, 1.0]]), extend_cost=True); "
    "print('lap', lap.__version__, list(x))"
)


def test_the_image_tracks_offline():
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python", IMAGE, "-c", PROBE],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "lap 0.5.12 [0, 1]" in result.stdout
