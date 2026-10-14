"""A bunch's first arrival at the console queues its training package, once, and never breaks ingest."""
from __future__ import annotations

from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.training_outbox_store import TrainingOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.training_inbox import TrainingInbox

IMAGE = "captures/results/2026-09-16/101244_BE1234XY_a3f9c201/bbox/Ripe/2026-09-16_030000_000001_auto.webp"


class FakeLineClient:
    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


def _inbox(tmp_path, send_mode="all"):
    return TrainingInbox(
        TrainingOutboxStore(tmp_path / "training_outbox.db"), artifacts_dir=tmp_path / "artifacts",
        company="PT Contoh", autograde_version="v1.23.0", send_mode=send_mode, low_confidence=0.60,
    )


@pytest.fixture()
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLineClient(),
                          training_inbox=_inbox(tmp_path))


def _event(svc, event_id="e-1", **extra):
    payload = {
        "event_id": event_id, "machine_id": svc.lines[0].machine_id, "timestamp": "2026-09-16T03:00:00+00:00",
        "ripeness_status": "ACC", "prediction": "Acc", "capture_type": "auto", "assignment_id": "a-1",
        "grade_class": "Ripe", "ripeness_confidence": 0.9, "image_path": IMAGE,
        "bounding_box": {"x_min": 1, "y_min": 1, "x_max": 9, "y_max": 9},
    }
    payload.update(extra)
    return svc.ingest(payload)


def test_first_arrival_queues_one_package(service, tmp_path):
    _event(service)
    _event(service)  # redelivered by the line outbox
    rows = service.training_inbox.outbox.due(10)
    assert len(rows) == 1
    row = rows[0]
    assert row.line_code == service.lines[0].line_code
    assert row.photo_path.endswith("101244_BE1234XY_a3f9c201/clean/Ripe/2026-09-16_030000_000001_auto.webp")
    assert row.manifest["source"]["line_code"] == service.lines[0].line_code
    assert row.manifest["folder"] == {"day": "2026-09-16", "truck": "101244_BE1234XY_a3f9c201"}


def test_priority_mode_skips_normal_photos(tmp_path):
    inbox = _inbox(tmp_path, send_mode="priority")
    payload = {"event_id": "e-1", "machine_id": "M1", "timestamp": "2026-09-16T03:00:00+00:00",
               "capture_type": "auto", "grade_class": "Ripe", "ripeness_confidence": 0.95, "image_path": IMAGE}
    assert inbox.offer(payload, line_code="line-1", plate=None) is False
    assert inbox.offer({**payload, "event_id": "e-2", "ripeness_confidence": 0.3}, line_code="line-1", plate=None) is True


def test_flat_old_path_is_not_queued(tmp_path):
    inbox = _inbox(tmp_path)
    payload = {"event_id": "e-1", "machine_id": "M1", "timestamp": "2026-09-16T03:00:00+00:00",
               "capture_type": "auto", "image_path": "captures/results/2026-09-16/x.webp"}
    assert inbox.offer(payload, line_code="line-1", plate=None) is False


def test_offer_failure_never_breaks_ingest(service, caplog, monkeypatch):
    def boom(*_a, **_kw):
        raise OSError("disk full")
    monkeypatch.setattr(service.training_inbox.outbox, "enqueue", boom)
    assert _event(service) == "2026-09-16"
    assert service.store.inspections("2026-09-16", limit=50, offset=0)
    assert "e-1" in caplog.text


def test_malformed_timestamp_is_logged_not_raised(tmp_path, caplog):
    inbox = _inbox(tmp_path)
    payload = {"event_id": "e-bad", "machine_id": "M1", "timestamp": "not-a-time",
               "capture_type": "auto", "image_path": IMAGE}
    assert inbox.offer(payload, line_code="line-1", plate=None) is False
    assert "e-bad" in caplog.text
    assert inbox.outbox.due(10) == []


def test_plate_lookup_failure_still_queues_without_plate(service, monkeypatch):
    def boom(_truck_id):
        raise OSError("db locked")
    monkeypatch.setattr(service, "_plate", boom)
    assert _event(service, truck_id="T-1") == "2026-09-16"
    row = service.training_inbox.outbox.due(10)[0]
    assert row.manifest["visit"]["plate"] is None


def test_unknown_machine_is_not_queued(service, caplog):
    caplog.set_level("INFO")
    assert _event(service, machine_id="UNKNOWN-9") == "2026-09-16"
    assert service.training_inbox.outbox.due(10) == []
    assert "e-1" in caplog.text


def test_service_without_inbox_ingests_as_before(tmp_path):
    svc = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), ConsoleStore(tmp_path / "c.db"), FakeLineClient())
    assert svc.training_inbox is None
    assert _event(svc) == "2026-09-16"
