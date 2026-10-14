"""The line tells the console which model graded a bunch and where its TP box was.

Both feed the training manifest (nexio spec §4). Optional so a line on an older
image, and a manual reject, still send a valid event.
"""
from __future__ import annotations

from palmgrade.domain.vision_event import build_event_payload

BASE = dict(
    machine_id="M1", file_ts="2026-10-05_031244_123456", timestamp="2026-10-05T03:12:44.123456+00:00",
    ripeness_status="acc", ripeness_confidence=0.93, capture_type="auto",
    image_path="captures/results/2026-10-05/101244_BE1234XY_a3f9c201/bbox/Ripe/TP/x_auto.webp",
    truck_id="t-1", assignment_id="a3f9c201-0000-0000-0000-000000000000",
)


def test_fields_travel_when_given():
    box = {"x_min": 1102, "y_min": 1290, "x_max": 1380, "y_max": 1488}
    p = build_event_payload(**BASE, tp_status="PASS", tp_confidence=0.71, tp_bounding_box=box, model_file="ripe_v7.pt")
    assert p["tp_bounding_box"] == box
    assert p["model_file"] == "ripe_v7.pt"


def test_fields_are_none_when_unknown():
    p = build_event_payload(**BASE)
    assert p["tp_bounding_box"] is None
    assert p["model_file"] is None


def test_blank_model_file_reads_as_unknown():
    assert build_event_payload(**BASE, model_file="  ")["model_file"] is None
