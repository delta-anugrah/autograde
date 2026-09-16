"""One JSON per truck visit: what the backoffice opens from the ERP ticket."""
from __future__ import annotations

from palmgrade.domain.visit_manifest import build_manifest, detail_url_for, manifest_key

PUBLIC = "https://captures.smagri.id"
MACHINE = "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01"
VISIT = {"id": "v-1", "assignment_id": "a-1", "plate_number": "BE 8821 KL",
         "supplier_name": "KUD Sumber Makmur", "work_date": "2026-09-16"}
GRADING = {"assignment_id": "a-1", "line_code": "line-1", "total": 2, "acc": 1, "rej": 1,
           "tangkai_panjang": 1, "manual_reject": 0,
           "started_at": "2026-09-16T08:00:00+07:00", "ended_at": "2026-09-16T08:20:00+07:00"}


def _bunch(**over):
    return {"event_id": "e-1", "machine_id": MACHINE, "line_code": "line-1",
            "timestamp": "2026-09-16T08:01:00+07:00", "ripeness_status": "ACC",
            "ripeness_confidence": 0.94, "capture_type": "auto", "grade_class": "Ripe",
            "tp_status": None, "tp_confidence": 0.9,
            "image_path": "captures/results/2026-09-16/080000_BE8821KL_a1/bbox/acc/x.webp"} | over


def test_keys_and_url_share_the_visit_id():
    assert manifest_key("v-1") == "visits/v-1.json"
    assert detail_url_for(PUBLIC, "v-1") == "https://captures.smagri.id/viewer.html?visit=v-1"


def test_manifest_carries_the_recap_and_every_bunch_with_both_image_urls():
    m = build_manifest(VISIT, GRADING, [_bunch()], public_url=PUBLIC, generated_at="2026-09-16T09:00:00+07:00")
    assert (m["schema"], m["visit_id"], m["plate_number"], m["line_code"]) == (1, "v-1", "BE 8821 KL", "line-1")
    assert m["counts"] == {"total": 2, "acc": 1, "rej": 1, "tangkai_panjang": 1, "manual_reject": 0}
    [b] = m["bunches"]
    assert b["verdict"] == "ACC" and b["grade_class"] == "Ripe" and b["tangkai_panjang"] is True
    assert b["image"] == f"{PUBLIC}/{MACHINE}/results/2026-09-16/080000_BE8821KL_a1/bbox/acc/x.webp"
    assert b["thumb"] == f"{PUBLIC}/{MACHINE}/results/2026-09-16/080000_BE8821KL_a1/thumb/acc/x.webp"


def test_a_flat_or_missing_image_path_gives_no_urls_rather_than_a_crash():
    m = build_manifest(VISIT, GRADING, [_bunch(image_path=None), _bunch(event_id="e-2", image_path="captures/results/2026-09-16/x.webp")],
                       public_url=PUBLIC, generated_at="t")
    assert [b["image"] for b in m["bunches"]] == [None, f"{PUBLIC}/{MACHINE}/results/2026-09-16/x.webp"]
    assert [b["thumb"] for b in m["bunches"]] == [None, None]


def test_tangkai_panjang_uses_the_same_threshold_as_the_recap():
    """`grading_counts()` counts ACC with tp_confidence > 0.8; a bunch must agree with its own recap."""
    m = build_manifest(VISIT, GRADING, [_bunch(tp_confidence=0.8)], public_url=PUBLIC, generated_at="t")
    assert m["bunches"][0]["tangkai_panjang"] is False


def test_a_missing_tp_confidence_gives_false_rather_than_raising():
    """Manual-reject bunches never go through the model, so `tp_confidence` is
    `None` on that row — this must not be mistaken for a `> TP_THRESHOLD` check."""
    m = build_manifest(VISIT, GRADING, [_bunch(tp_confidence=None)], public_url=PUBLIC, generated_at="t")
    assert m["bunches"][0]["tangkai_panjang"] is False
