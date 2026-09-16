"""Unit tests discovery + rekonstruksi payload batch worker (spec §3.3, §7.1, §7.4)."""
from __future__ import annotations

import json
import uuid
from unittest.mock import Mock

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import (
    BatchUploadWorker,
    _PoisonError,
    event_id_for,
    file_timestamp,
)

TS = "2026-07-10_083000_123456"
DATE = "2026-07-10"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", "palmgrade")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://img.palmgrade.ai")
    monkeypatch.setenv("UPLOAD_API_URL", "https://api.palmgrade.ai")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    worker = BatchUploadWorker(settings=settings, manifest=manifest, uploader=None)
    return settings, manifest, worker


def _write_ripeness(settings, ts=TS, date=DATE, kind="auto", **over):
    d = settings.results_dir / date
    d.mkdir(parents=True, exist_ok=True)
    img = f"{ts}_{kind}.webp"
    (d / img).write_bytes(b"webp")
    meta = {
        "timestamp": "2026-07-10T08:30:00.123456",
        "image_path": f"captures/results/{date}/{img}",
        "ripeness_status": "acc", "ripeness_confidence": 0.91,
        "tp_status": None, "tp_confidence": 0,
        "capture_type": kind, "truck_id": "t-1",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        "assignment_id": "a-1",
    }
    meta.update(over)
    p = d / f"{ts}_{kind}_ripeness.json"
    p.write_text(json.dumps(meta))
    return p


def _write_tp(settings, ts=TS, date=DATE):
    d = settings.results_dir / date
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{ts}_auto_tp.json"
    p.write_text(json.dumps({
        "timestamp": "2026-07-10T08:30:00.123456", "image_path": None,
        "ripeness_status": None, "ripeness_confidence": 0,
        "tp_status": "PASS", "tp_confidence": 0.88,
        "capture_type": "auto", "truck_id": "t-1",
        "bounding_box": {"x_min": 5, "y_min": 6, "x_max": 7, "y_max": 8},
        "assignment_id": "a-1",
    }))
    return p


def test_file_timestamp_and_event_id():
    assert file_timestamp(f"{TS}_auto_ripeness.json") == TS
    assert file_timestamp(f"{TS}_manual_ripeness.json") == TS
    assert file_timestamp(f"{TS}_auto_tp.json") == TS
    with pytest.raises(ValueError):
        file_timestamp("random.json")
    # rumus PERSIS sama dgn outbox lama → idempoten lintas alur
    assert event_id_for("M1", TS) == str(uuid.uuid5(uuid.NAMESPACE_URL, f"M1:{TS}"))


def test_scan_creates_one_item_for_ripeness_plus_tp(env):
    settings, manifest, worker = env
    _write_ripeness(settings)
    _write_tp(settings)
    worker._scan()
    worker._scan()  # idempoten
    c = manifest.counts()
    assert c["pending"] == 1  # pasangan digabung: 1 item, bukan 2


def test_scan_orphan_tp_is_own_item(env):
    settings, manifest, worker = env
    _write_tp(settings)  # tanpa ripeness sibling
    worker._scan()
    items = manifest.get_uploadable(limit=10)
    assert len(items) == 1
    assert items[0]["image_path"] is None


def test_build_payload_merges_tp(env):
    settings, manifest, worker = env
    _write_ripeness(settings)
    _write_tp(settings)
    worker._scan()
    item = manifest.get_uploadable(limit=1)[0]
    p = worker._build_payload(item)
    assert p["event_id"] == event_id_for(settings.machine_id, TS)
    assert p["machine_id"] == settings.machine_id
    assert p["prediction"] == "Acc"
    assert p["ripeness_status"] == "ACC"
    assert p["tp_status"] == "PASS"           # dari file tp sibling
    assert p["tp_confidence"] == 0.88
    assert p["assignment_id"] == "a-1"
    assert p["truck_id"] == "t-1"
    assert p["image_path"] == f"https://img.palmgrade.ai/{settings.machine_id}/results/{DATE}/{TS}_auto.webp"


def test_build_payload_legacy_json_without_assignment(env):
    settings, manifest, worker = env
    _write_ripeness(settings)
    # JSON lama (pra-Task-2): tanpa key assignment_id
    p = settings.results_dir / DATE / f"{TS}_auto_ripeness.json"
    meta = json.loads(p.read_text())
    meta.pop("assignment_id")
    p.write_text(json.dumps(meta))
    worker._scan()
    payload = worker._build_payload(manifest.get_uploadable(limit=1)[0])
    assert "assignment_id" not in payload      # @IsOptional di API → omit, bukan null


def test_build_payload_manual_uses_image_url_key(env):
    settings, manifest, worker = env
    meta_p = _write_ripeness(settings, kind="manual", ripeness_status="rej")
    meta = json.loads(meta_p.read_text())
    meta["image_url"] = meta.pop("image_path")  # manual JSON pakai key image_url
    meta_p.write_text(json.dumps(meta))
    worker._scan()
    payload = worker._build_payload(manifest.get_uploadable(limit=1)[0])
    assert payload["prediction"] == "Rej"
    assert payload["capture_type"] == "manual"
    assert payload["image_path"].endswith(f"{TS}_manual.webp")


def test_build_payload_corrupt_json_raises_poison(env):
    settings, manifest, worker = env
    p = _write_ripeness(settings)
    worker._scan()
    p.write_text("{bukan json")
    item = manifest.get_uploadable(limit=1)[0]
    with pytest.raises(_PoisonError):
        worker._build_payload(item)


def test_scan_survives_corrupt_json(env):
    # JSON korup SAAT scan → item tetap dibuat (image_path NULL); poison saat build
    settings, manifest, worker = env
    p = _write_ripeness(settings)
    p.write_text("{bukan json")
    worker._scan()
    items = manifest.get_uploadable(limit=10)
    assert len(items) == 1 and items[0]["image_path"] is None
    with pytest.raises(_PoisonError):
        worker._build_payload(items[0])


def test_build_payload_orphan_tp_without_pair_raises_poison(env):
    settings, manifest, worker = env
    _write_tp(settings)
    worker._scan()
    with pytest.raises(_PoisonError):
        worker._build_payload(manifest.get_uploadable(limit=1)[0])


def test_without_a_text_receiver_the_item_is_done_once_the_image_is_up(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "M1")
    monkeypatch.setenv("R2_BUCKET", "palmgrade")
    monkeypatch.delenv("UPLOAD_API_URL", raising=False)
    # Penjaga disk dimatikan: dia menghapus item `done` tertua begitu sisa disk
    # di bawah lantainya, dan runner CI sering di bawah 20 GB — itu membuang
    # justru item yang tes ini periksa. Pola yang sama dipakai
    # `test_batch_upload_thumb.py` dan `test_batch_upload_clean_retention.py`.
    monkeypatch.setenv("UPLOAD_DISK_MIN_FREE_GB", "0")
    settings = Settings(repo_root=tmp_path)
    assert settings.upload_events_url == ""
    _write_ripeness(settings)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    uploader, http = Mock(), Mock()
    BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader, http_client=http).run_batch_once()
    assert manifest.counts()["done"] == 1
    http.post.assert_not_called()
