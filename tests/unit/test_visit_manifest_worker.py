"""The manifest reaches R2 through a queue, like everything else that leaves the mill."""
from __future__ import annotations

import asyncio
import json

from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

PUBLIC = "https://captures.smagri.id"


class FakeUploader:
    def __init__(self, fail: bool = False) -> None:
        self.puts: list[tuple[str, str, bytes]] = []
        self.fail = fail

    def put_bytes(self, body, r2_key, *, content_type):
        if self.fail:
            raise ConnectionError("R2 down")
        self.puts.append((r2_key, content_type, body))


def _inspection_row(**over) -> dict:
    """Shaped exactly like `add_inspection`'s INSERT requires — same helper
    pattern as `test_console_store.py`'s `_inspection_row`. `grade_class` is
    the only key the store defaults on its own."""
    row = {
        "event_id": "e-1",
        "machine_id": "M1",
        "line_code": "line-1",
        "work_date": "2026-09-16",
        "timestamp": "2026-09-16T08:01:00+07:00",
        "ripeness_status": "ACC",
        "ripeness_confidence": 0.9,
        "capture_type": "auto",
        "image_path": "captures/results/2026-09-16/T/bbox/acc/x.webp",
        "truck_id": None,
        "assignment_id": "a-1",
        "prediction": "Acc",
        "tp_status": None,
        "tp_confidence": None,
    }
    row.update(over)
    return row


def _store(tmp_path) -> tuple[ConsoleStore, str]:
    """`ConsoleStore` has no `record_weighing` — that lives on `ConsoleService`
    and needs `Settings`/`ErpQueue`/a line client this worker never touches.
    The worker only depends on `ConsoleStore`, so the weighing row is built
    straight through `upsert_weighing`, the same way `test_console_store.py`'s
    `test_visit_carries_supplier_name` builds one."""
    store = ConsoleStore(tmp_path / "c.db")
    weighing_id = "w-1"
    store.upsert_weighing(
        {
            "id": weighing_id,
            "ref": "SCL-1",
            "plate_number": "BE 8821 KL",
            "plate_norm": "BE8821KL",
            "truck_id": None,
            "work_date": "2026-09-16",
            "gross_kg": 14560.0,
            "tare_kg": None,
            "net_kg": None,
            "entered_at": "2026-09-16T07:41:00+07:00",
            "exited_at": None,
        }
    )
    store.add_inspection(_inspection_row())
    store.link_weighing_to_assignment(weighing_id, "a-1")
    return store, weighing_id


def _worker(tmp_path, store, uploader):
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html>viewer</html>")
    return VisitManifestWorker(
        store,
        ErpOutboxStore(tmp_path / "m.db"),
        uploader,
        public_url=PUBLIC,
        viewer_html=viewer,
        clock=lambda: "2026-09-16T09:00:00+07:00",
    )


def test_a_queued_visit_is_uploaded_as_one_json_under_its_visit_id(tmp_path):
    store, wid = _store(tmp_path)
    uploader = FakeUploader()
    worker = _worker(tmp_path, store, uploader)
    worker.enqueue(wid, "a-1")
    assert asyncio.run(worker.drain_once()) == 1
    keys = [k for k, _, _ in uploader.puts]
    assert f"visits/{wid}.json" in keys
    body = json.loads(next(b for k, _, b in uploader.puts if k == f"visits/{wid}.json"))
    assert body["visit_id"] == wid and body["bunches"][0]["thumb"].endswith("/thumb/acc/x.webp")


def test_the_viewer_page_is_uploaded_once_per_process(tmp_path):
    store, wid = _store(tmp_path)
    uploader = FakeUploader()
    worker = _worker(tmp_path, store, uploader)
    worker.enqueue(wid, "a-1")
    asyncio.run(worker.drain_once())
    asyncio.run(worker.drain_once())
    assert [k for k, ct, _ in uploader.puts if k == "viewer.html" and ct == "text/html; charset=utf-8"] == [
        "viewer.html"
    ]


def test_r2_down_keeps_the_row_and_backs_off(tmp_path):
    store, wid = _store(tmp_path)
    worker = _worker(tmp_path, store, FakeUploader(fail=True))
    worker.enqueue(wid, "a-1")
    assert asyncio.run(worker.drain_once()) == 0
    assert worker.outbox.failed_count() == 1


def test_an_assignment_that_graded_nothing_is_dropped_not_retried(tmp_path):
    store, wid = _store(tmp_path)
    uploader = FakeUploader()
    worker = _worker(tmp_path, store, uploader)
    worker.enqueue(wid, "kosong")
    asyncio.run(worker.drain_once())
    assert worker.outbox.failed_count() == 0 and not [k for k, _, _ in uploader.puts if k.startswith("visits/")]
