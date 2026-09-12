"""Guards on the camera feature file, which is the real frame-rate setting.

`config/camera/hikrobot.mfs` is pushed to every camera on connect, so it — not
`CAMERA_FPS` — decides the runtime frame rate. Two things silently broke this
before and both are pinned here:

1. The `.mfs` drifting away from the rate the docs and bandwidth budget assume.
2. `docker-compose.yml` substituting the `.mfs` default via `:-`, which applies
   to an *empty* value too. Commenting `LINE_<n>_FEATURE_FILE` out therefore
   enables the default instead of disabling it — a manual MVS change gets
   overwritten seconds after the container connects.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MFS = REPO / "config" / "camera" / "hikrobot.mfs"
COMPOSE = REPO / "docker-compose.yml"

EXPECTED_FPS = 15
"""Kept in sync with docs/camera-spec.md § 2.2 and the § 3 bandwidth budget."""


def _mfs_value(key: str) -> str:
    for line in MFS.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] == key:
            return parts[1]
    pytest.fail(f"{key} not found in {MFS.name}")


def test_feature_file_pins_expected_frame_rate():
    assert float(_mfs_value("AcquisitionFrameRate")) == EXPECTED_FPS
    assert _mfs_value("AcquisitionFrameRateEnable") == "1", "limiter must stay on"


def test_exposure_fits_inside_the_frame_period():
    # Exposure longer than 1/fps would starve the limiter.
    exposure_s = float(_mfs_value("ExposureTime")) / 1_000_000
    assert exposure_s < 1 / EXPECTED_FPS


def test_every_line_falls_back_to_the_repo_feature_file():
    # Regression: a line left without a default would silently keep whatever
    # rate the camera firmware holds.
    defaults = re.findall(
        r"CAMERA_FEATURE_FILE=\$\{LINE_\d+_FEATURE_FILE:-([^}]+)\}",
        COMPOSE.read_text(),
    )
    assert len(defaults) == 3
    assert set(defaults) == {"config/camera/hikrobot.mfs"}
