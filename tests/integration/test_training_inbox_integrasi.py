"""Real photo on disk -> console ingest -> outbox -> worker -> bucket, the way the factory runs it.

The line's own repository writes the bbox/clean pair under its artifacts folder, which the
console sees as `<console artifacts>/<line_code>` (the read-only mount). The console's
ingest queues the package, the worker uploads.

Two buckets: an in-memory fake (checks the package itself), and a local S3 endpoint on
127.0.0.1 reached through the real wiring (`_build_training`: `R2Uploader`, boto3,
`KIRIM_CONFIG`), so the keys, the order and the content types are what R2 would receive.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import pytest

# cv2 and numpy before any palmgrade import: LocalFileStorage imports cv2 at module top.
np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.erp.outbox_store import GAGAL_KUNCI_DITOLAK, GAGAL_TAK_TERJANGKAU  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.integrations.upload.training_outbox_store import TrainingOutboxStore  # noqa: E402
from palmgrade.repositories.capture_repository import CaptureRepository  # noqa: E402
from palmgrade.repositories.console_repository import ConsoleStore  # noqa: E402
from palmgrade.routes import console_deps  # noqa: E402
from palmgrade.services.console_service import ConsoleService  # noqa: E402
from palmgrade.services.training_inbox import TrainingInbox  # noqa: E402
from palmgrade.workers.training_upload_worker import TrainingUploadWorker  # noqa: E402

ASSIGNMENT = "a3f9c201-dead-beef"


class Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.order: list[str] = []

    def put_bytes(self, body, r2_key, *, content_type):
        self.objects[r2_key] = body
        self.order.append(r2_key)


class FakeLineClient:
    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


def _manual_reject_on_disk(tmp_path, monkeypatch, console_settings):
    """The line process writes a manual reject; returns (line, what the repository returned)."""
    line = console_settings.console_lines[0]
    # The line process: its ARTIFACTS_DIR is what the console mounts as artifacts/<line_code>.
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts" / line.line_code))
    line_settings = replace(Settings(), repo_root=tmp_path, machine_id=line.machine_id, factory_tz="Asia/Jakarta")
    frame = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    saved = CaptureRepository(line_settings, LocalFileStorage()).save_manual_reject(
        frame=frame, truck_id="truck-1", assignment_id=ASSIGNMENT, plate="BE 1234 XY",
        assigned_at="2026-10-05T10:12:44+07:00",
    )
    monkeypatch.delenv("ARTIFACTS_DIR")
    return line, saved


def _event(line, saved, event_id: str) -> dict:
    return {"event_id": event_id, "machine_id": line.machine_id, "timestamp": saved["timestamp"],
            "ripeness_status": "REJ", "prediction": "Rej", "capture_type": "manual",
            "ripeness_confidence": 1.0, "image_path": saved["image_url"], "assignment_id": ASSIGNMENT}


def _clean_on_disk(tmp_path, line, saved):
    rel = saved["image_url"].removeprefix("captures/").replace("/bbox/", "/clean/")
    return tmp_path / "artifacts" / line.line_code / rel


def test_a_manual_reject_lands_in_the_bucket(tmp_path, monkeypatch):
    console_settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    line, saved = _manual_reject_on_disk(tmp_path, monkeypatch, console_settings)

    outbox = TrainingOutboxStore(tmp_path / "training_outbox.db")
    inbox = TrainingInbox(outbox, artifacts_dir=console_settings.artifacts_dir, company="PT Contoh",
                          autograde_version="test", send_mode="all", low_confidence=0.6)
    svc = ConsoleService(console_settings, ConsoleStore(tmp_path / "console.db"), FakeLineClient(),
                         training_inbox=inbox)
    svc.ingest(_event(line, saved, "e-1"))

    bucket = Bucket()
    assert asyncio.run(TrainingUploadWorker(outbox, bucket).drain()) == 1
    photo_key, manifest_key = bucket.order
    assert photo_key.endswith("/e-1.webp")
    assert manifest_key.endswith("/e-1.json")
    manifest = json.loads(bucket.objects[manifest_key])
    assert manifest["image"]["sha256"] == hashlib.sha256(bucket.objects[photo_key]).hexdigest()
    assert manifest["prediction"] is None
    assert manifest["priority"]["reasons"] == ["MANUAL_REJECT"]
    assert manifest["folder"]["truck"].endswith("_BE1234XY_a3f9c201")
    # The clean copy went, never the annotated one: same bytes as the clean file on disk.
    assert bucket.objects[photo_key] == _clean_on_disk(tmp_path, line, saved).read_bytes()

    # The line redelivers the same event (outbox retry, console restart): nothing new is sent.
    svc.ingest(_event(line, saved, "e-1"))
    assert asyncio.run(TrainingUploadWorker(outbox, bucket).drain()) == 0
    assert len(bucket.order) == 2


class _LocalS3(BaseHTTPRequestHandler):
    """Answers PutObject like S3 does and records what arrived; nothing else."""

    protocol_version = "HTTP/1.1"
    received: list[tuple[str, str, bytes]] = []
    status = 200

    def do_PUT(self) -> None:  # noqa: N802 : http.server dispatches on this name
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(self.status)
        if self.status == 200:
            self.received.append((unquote(urlsplit(self.path).path), self.headers.get("Content-Type", ""), body))
            self.send_header("ETag", f'"{hashlib.md5(body).hexdigest()}"')  # S3's ETag is the body's MD5
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args) -> None:
        """Quiet: pytest output is not the place for an access log."""


@pytest.fixture
def local_s3():
    _LocalS3.received = []
    _LocalS3.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalS3)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _LocalS3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _closed_port_endpoint() -> str:
    """An address nothing listens on: what a dead uplink looks like to boto3."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


def _wired(tmp_path, monkeypatch, endpoint: str):
    """The console as console_deps assembles it at the factory, pointed at `endpoint`."""
    console_settings = replace(
        Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", app_version="v1.28.0",
        erp_company="PT Contoh", training_inbox_bucket="nexio-inbox", training_inbox_endpoint=endpoint,
        training_inbox_access_key_id="inbox-key", training_inbox_secret_access_key="inbox-secret",
        training_inbox_send="all", training_inbox_low_confidence=0.6,
    )
    line, saved = _manual_reject_on_disk(tmp_path, monkeypatch, console_settings)
    inbox, worker = console_deps._build_training(console_settings)
    assert inbox is not None and worker is not None
    assert console_settings.training_outbox_db_path.is_file()
    svc = ConsoleService(console_settings, ConsoleStore(tmp_path / "console.db"), FakeLineClient(),
                         training_inbox=inbox, training_worker=worker)
    return svc, worker, line, saved


def test_the_factory_wiring_puts_photo_then_manifest_into_the_inbox_bucket(tmp_path, monkeypatch, local_s3):
    endpoint, s3 = local_s3
    svc, worker, line, saved = _wired(tmp_path, monkeypatch, endpoint)
    svc.ingest(_event(line, saved, "e-2"))

    assert asyncio.run(worker.drain()) == 1
    (photo_path, photo_type, photo), (manifest_path, manifest_type, manifest_body) = s3.received
    day = saved["timestamp"][:10]  # UTC timestamp from the line, so its date is the UTC day
    assert photo_path == f"/nexio-inbox/v1/{line.machine_id}/{day}/e-2.webp"
    assert manifest_path == f"/nexio-inbox/v1/{line.machine_id}/{day}/e-2.json"
    assert (photo_type, manifest_type) == ("image/webp", "application/json")
    assert photo == _clean_on_disk(tmp_path, line, saved).read_bytes()
    manifest = json.loads(manifest_body)
    assert manifest["schema"] == "autograde-training-sample/v1"
    assert manifest["source"]["company"] == "PT Contoh"
    assert manifest["source"]["autograde_version"] == "v1.28.0"
    assert manifest["image"] == {
        "key": photo_path.removeprefix("/nexio-inbox/"), "sha256": hashlib.sha256(photo).hexdigest(),
        "bytes": len(photo), "content_type": "image/webp",
    }
    assert worker.outbox.pending_count() == 0
    assert worker.outbox.failed_count() == 0
    assert worker.outbox.last_sent_at() is not None


@pytest.mark.parametrize("failure, kind", [("key refused", GAGAL_KUNCI_DITOLAK), ("uplink down", GAGAL_TAK_TERJANGKAU)])
def test_a_failed_upload_holds_the_photo_and_says_why(tmp_path, monkeypatch, local_s3, failure, kind):
    """What the Status sub-tab reads when the inbox cannot be reached: the row waits, worded by kind."""
    endpoint, s3 = local_s3
    if failure == "key refused":
        s3.status = 403
    else:
        endpoint = _closed_port_endpoint()
    svc, worker, line, saved = _wired(tmp_path, monkeypatch, endpoint)
    svc.ingest(_event(line, saved, "e-3"))

    assert asyncio.run(worker.drain()) == 0
    assert s3.received == []  # nothing half-sent: the manifest never goes without its photo
    (row,) = worker.outbox.failed_rows()
    assert (row["kind"], row["key"], row["error_kind"]) == (line.line_code, "e-3", kind)
    assert worker.outbox.failed_count() == 1
    assert worker.outbox.last_sent_at() is None
