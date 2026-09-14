"""The image must carry what the tracker imports, not fetch it at runtime.

`RealtimeInspectionPipeline` grades with `model.track(tracker="bytetrack.yaml")`,
and Ultralytics' ByteTrack matcher imports `lap`. Ultralytics does not depend on
it: when it is missing, it tries to `pip install` it inside the running
container. On 2026-09-14 in Lampung that worked on one line and not on the other
two — they captured at 15 fps and graded nothing, every frame failing with
`No module named 'lap'`. A mill PC may also be offline, where it never works.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Ultralytics 8.3.x asks for this floor in ultralytics/trackers/utils/matching.py.
LAP_FLOOR = (0, 5, 12)


def _pin(package: str) -> tuple[int, ...] | None:
    text = (REPO / "requirements.txt").read_text()
    found = re.search(rf"^{package}==([\d.]+)\s*$", text, re.M)
    return tuple(int(part) for part in found.group(1).split(".")) if found else None


def test_the_pipeline_still_tracks_with_bytetrack():
    # If this ever changes, the lap pin below may no longer be the right one.
    source = (REPO / "src/palmgrade/pipelines/realtime_inspection_pipeline.py").read_text()
    assert 'tracker="bytetrack.yaml"' in source


def test_lap_is_pinned_in_the_image_at_the_version_ultralytics_asks_for():
    pinned = _pin("lap")
    assert pinned is not None, "lap must be pinned (==) in requirements.txt"
    assert pinned >= LAP_FLOOR
