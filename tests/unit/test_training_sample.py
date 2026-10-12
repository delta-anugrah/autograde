"""Training manifest rules (nexio spec §4-§5). Pure, so every edge is cheap to pin."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from palmgrade.domain import training_sample as ts

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "autograde-training-sample" / "v1"
IMAGE_PATH = "captures/results/2026-10-05/101244_BE1234XY_a3f9c201/bbox/Ripe/TP/2026-10-05_031244_123456_auto.webp"


def _auto_payload(**over):
    p = {
        "event_id": "5b0e0c1e-6f0a-5d6e-9a43-2c8f2f2d7a10", "machine_id": "M1",
        "timestamp": "2026-10-05T03:12:44.123456+00:00", "capture_type": "auto",
        "grade_class": "Ripe", "ripeness_confidence": 0.55,
        "bounding_box": {"x_min": 812, "y_min": 404, "x_max": 1630, "y_max": 1488},
        "tp_status": "PASS", "tp_confidence": 0.71,
        "tp_bounding_box": {"x_min": 1102, "y_min": 1290, "x_max": 1380, "y_max": 1488},
        "model_file": "ripe_v7.pt", "image_path": IMAGE_PATH,
        "truck_id": "t-1", "assignment_id": "a3f9c201-0000-0000-0000-000000000000",
    }
    p.update(over)
    return p


def _build(payload, **over):
    kw = dict(line_code="line-2", plate="BE 1234 XY", company="PT Contoh", autograde_version="v1.23.0", low_confidence=0.60)
    kw.update(over)
    return ts.build_manifest(payload, **kw)


def test_auto_manifest_matches_the_shared_fixture():
    fixture = json.loads((FIXTURES / "auto_ripe_tp_low_confidence.json").read_text())
    built = ts.with_image(_build(_auto_payload()), sha256="0" * 64, size=182311)
    assert built == fixture


def test_manual_reject_matches_the_shared_fixture():
    fixture = json.loads((FIXTURES / "manual_reject.json").read_text())
    payload = _auto_payload(
        event_id="8d4b2f8e-0c3a-5f2e-8b1a-6e2d9c4f7a11", timestamp="2026-10-05T04:00:01.000001+00:00",
        capture_type="manual", grade_class=None, ripeness_confidence=1.0, tp_status=None, tp_confidence=0,
        tp_bounding_box=None, model_file=None,
        image_path="captures/results/2026-10-05/101244_BE1234XY_a3f9c201/bbox/unknown/2026-10-05_040001_000001_manual.webp",
        bounding_box={"x_min": 0, "y_min": 0, "x_max": 2448, "y_max": 2048},
    )
    built = ts.with_image(_build(payload), sha256="1" * 64, size=150000)
    assert built == fixture


@pytest.mark.parametrize(
    ("capture_type", "grade_class", "confidence", "tp", "expected"),
    [
        ("auto", "Ripe", 0.90, False, []),
        ("auto", "Ripe", 0.59, False, ["LOW_CONFIDENCE"]),
        ("auto", "Ripe", 0.60, False, []),
        ("auto", "JK", 0.95, False, ["RARE_CLASS"]),
        ("auto", "Ripe", 0.95, True, ["RARE_CLASS"]),
        ("auto", "JK", 0.40, True, ["LOW_CONFIDENCE", "RARE_CLASS"]),
        ("manual", None, 1.0, False, ["MANUAL_REJECT"]),
        ("auto", None, None, False, []),
    ],
)
def test_priority_reasons(capture_type, grade_class, confidence, tp, expected):
    got = ts.priority_reasons(capture_type=capture_type, grade_class=grade_class, confidence=confidence,
                              tp_present=tp, low_confidence=0.60)
    assert got == expected


@pytest.mark.parametrize(
    ("image_path", "expected"),
    [
        (IMAGE_PATH, {"day": "2026-10-05", "truck": "101244_BE1234XY_a3f9c201"}),
        ("captures/results/2026-10-05/_belum-assign/bbox/Unripe/x.webp", {"day": "2026-10-05", "truck": "_belum-assign"}),
        ("captures/results/2026-10-05/x.webp", {"day": "2026-10-05", "truck": None}),
        ("/captures/results/2026-10-05/T/bbox/JK/x.webp", {"day": "2026-10-05", "truck": "T"}),
        (None, {"day": None, "truck": None}),
        ("https://captures.smagri.id/x.webp", {"day": None, "truck": None}),
    ],
)
def test_folders_of(image_path, expected):
    assert ts.folders_of(image_path) == expected


def test_object_keys_use_the_utc_day_of_the_capture():
    photo, manifest = ts.object_keys("M1", "2026-10-05T23:30:00+07:00", "e-1")
    assert photo == "v1/M1/2026-10-05/e-1.webp"
    assert manifest == "v1/M1/2026-10-05/e-1.json"
    photo, _ = ts.object_keys("M1", "2026-10-06T02:00:00+07:00", "e-2")
    assert photo == "v1/M1/2026-10-05/e-2.webp"


def test_object_keys_never_leave_their_prefix():
    photo, _ = ts.object_keys("../M 1", "2026-10-05T03:00:00+00:00", "e/1")
    assert photo == "v1/.._M_1/2026-10-05/e_1.webp"


@pytest.mark.parametrize("bad", ["..", ".", "", "..."])
def test_dots_only_or_empty_segment_becomes_an_underscore(bad):
    photo, manifest = ts.object_keys(bad, "2026-10-05T03:00:00+00:00", bad)
    assert photo == "v1/_/2026-10-05/_.webp"
    assert manifest == "v1/_/2026-10-05/_.json"


def test_box_with_corners_out_of_order_is_dropped():
    m = _build(_auto_payload(bounding_box={"x_min": 10, "y_min": 10, "x_max": 5, "y_max": 20}))
    assert m["prediction"]["bunch_box"] is None


def test_empty_box_is_dropped():
    m = _build(_auto_payload(bounding_box={}))
    assert m["prediction"]["bunch_box"] is None


def test_tp_without_box_from_an_older_line():
    m = _build(_auto_payload(tp_bounding_box=None))
    assert m["prediction"]["tp"] == {"present": True, "confidence": 0.71, "box": None}


def test_no_tp():
    m = _build(_auto_payload(tp_status=None, tp_confidence=0, tp_bounding_box=None))
    assert m["prediction"]["tp"] is None


def test_unknown_company_and_version_read_as_null():
    m = _build(_auto_payload(), company="", autograde_version="")
    assert m["source"]["company"] is None
    assert m["source"]["autograde_version"] is None


def test_photo_path_is_the_clean_twin_under_the_line_mount(tmp_path):
    got = ts.photo_path(tmp_path, "line-2", IMAGE_PATH)
    assert got == tmp_path / "line-2" / "results/2026-10-05/101244_BE1234XY_a3f9c201/clean/Ripe/TP/2026-10-05_031244_123456_auto.webp"


def test_photo_path_none_for_a_flat_old_capture_or_no_path(tmp_path):
    assert ts.photo_path(tmp_path, "line-2", "captures/results/2026-10-05/x.webp") is None
    assert ts.photo_path(tmp_path, "line-2", None) is None
