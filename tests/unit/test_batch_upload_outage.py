"""Simulasi outage & recovery (spec §7.2) — jantungnya requirement
"tahan internet mati berapa lama pun, nol data hilang, nol duplikat"."""
from __future__ import annotations

import json

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker


class FakeUploader:
    def __init__(self):
        self.puts: list[str] = []
        self.fail = False

    def put(self, local_path, r2_key):
        if self.fail:
            raise ConnectionError("R2 unreachable")
        self.puts.append(r2_key)


class FakeResponse:
    def __init__(self, status_code=201, text="created"):
        self.status_code = status_code
        self.text = text


class FakeHttp:
    def __init__(self):
        self.posts: list[dict] = []
        self.response = FakeResponse()
        self.exc: Exception | None = None

    def post(self, url, json=None, headers=None):
        if self.exc:
            raise self.exc
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self.response


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", "palmgrade")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://img.palmgrade.ai")
    monkeypatch.setenv("UPLOAD_API_URL", "https://api.palmgrade.ai")
    monkeypatch.setenv("UPLOAD_API_SECRET", "cloud-secret")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    uploader, http = FakeUploader(), FakeHttp()
    worker = BatchUploadWorker(settings=settings, manifest=manifest,
                               uploader=uploader, http_client=http)
    return settings, manifest, worker, uploader, http


def _write_items(settings, n, date="2026-07-10"):
    d = settings.results_dir / date
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        ts = f"{date}_0830{i:02d}_000000"
        (d / f"{ts}_auto.webp").write_bytes(b"w")
        (d / f"{ts}_auto_ripeness.json").write_text(json.dumps({
            "timestamp": f"{date}T08:30:{i:02d}", "image_path": f"captures/results/{date}/{ts}_auto.webp",
            "ripeness_status": "acc", "ripeness_confidence": 0.9, "tp_status": None,
            "tp_confidence": 0, "capture_type": "auto", "truck_id": None,
            "bounding_box": {}, "assignment_id": None,
        }))


def test_happy_path_image_then_text(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    worker.run_batch_once()
    assert len(uploader.puts) == 1
    assert len(http.posts) == 1
    assert http.posts[0]["url"] == settings.upload_events_url
    assert http.posts[0]["headers"]["x-webhook-secret"] == "cloud-secret"
    assert manifest.counts()["done"] == 1


def test_network_error_requeues_without_deadletter(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    uploader.fail = True
    worker.run_batch_once()
    assert manifest.counts()["pending"] == 1  # bukan poisoned/failed
    assert http.posts == []                    # teks TIDAK dikirim sebelum gambar


def test_no_retry_cap_100_ticks(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    uploader.fail = True
    for _ in range(100):
        # reset backoff supaya item selalu eligible (unit test, bukan wall-clock)
        worker.manifest._db.execute("UPDATE upload_items SET next_retry_at=0")
        worker.run_batch_once()
    assert manifest.counts()["pending"] == 1   # inilah "tahan durasi apa pun"


def test_batch_break_not_abort(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 5)
    calls = {"n": 0}
    orig_put = uploader.put

    def flaky_put(local_path, r2_key):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ConnectionError("drop di item ke-3")
        orig_put(local_path, r2_key)

    uploader.put = flaky_put
    worker.run_batch_once()
    c = manifest.counts()
    assert c["done"] == 2                      # item 1-2 selamat
    assert c["pending"] == 3                   # item 3 requeued + 4-5 belum disentuh


def test_recovery_uploads_all_unique(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 50)
    uploader.fail = True
    worker.run_batch_once()                    # outage
    uploader.fail = False
    worker.manifest._db.execute("UPDATE upload_items SET next_retry_at=0")
    worker.run_batch_once()                    # pulih
    assert manifest.counts()["done"] == 50
    assert len(set(uploader.puts)) == 50       # 50 key R2 unik, nol duplikat


def test_already_processed_counts_as_done(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    http.response = FakeResponse(200, '{"status":"already_processed"}')
    worker.run_batch_once()
    assert manifest.counts()["done"] == 1


def test_http_422_poisons_and_continues(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 2)
    http.response = FakeResponse(422, "validation error")
    worker.run_batch_once()
    c = manifest.counts()
    assert c["poisoned"] == 2                  # CONTINUE, bukan break
    # file TIDAK dihapus
    assert len(list((settings.results_dir / "2026-07-10").glob("*_ripeness.json"))) == 2


def test_http_401_requeues_with_break(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 3)
    http.response = FakeResponse(401, "unauthorized")
    worker.run_batch_once()
    c = manifest.counts()
    # item pertama: gambar sudah ke R2 (tak diulang), teks requeued (resume dari
    # image_uploaded); item 2-3 belum disentuh (break) → tetap pending.
    assert c["image_uploaded"] == 1 and c["pending"] == 2
    assert c["done"] == 0 and c["poisoned"] == 0   # requeue + break di item pertama
    assert len(http.posts) == 1


def test_http_404_truck_missing_requeues(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    http.response = FakeResponse(404, "Truck not found")
    worker.run_batch_once()
    c = manifest.counts()
    # gambar sudah ke R2 (tak diulang), teks requeued — resume dari image_uploaded.
    assert c["image_uploaded"] == 1
    assert c["done"] == 0 and c["poisoned"] == 0   # nunggu truck disinkron, bukan poisoned


def test_missing_image_file_poisons_json_kept(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    next(iter((settings.results_dir / "2026-07-10").glob("*.webp"))).unlink()
    worker.run_batch_once()
    assert manifest.counts()["poisoned"] == 1
    assert len(list((settings.results_dir / "2026-07-10").glob("*_ripeness.json"))) == 1


def test_empty_bucket_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", "")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    uploader, http = FakeUploader(), FakeHttp()
    worker = BatchUploadWorker(settings=settings, manifest=manifest,
                               uploader=uploader, http_client=http)
    _write_items(settings, 2)
    worker.run_batch_once()
    assert uploader.puts == [] and http.posts == []
    assert manifest.counts()["pending"] == 0   # bahkan tidak scan


def test_retention_deletes_done_after_cutoff(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    worker.run_batch_once()
    assert manifest.counts()["done"] == 1
    # mundurkan uploaded_at 8 hari (> UPLOAD_RETENTION_DAYS=7)
    with worker.manifest._db:
        worker.manifest._db.execute("UPDATE upload_items SET uploaded_at = uploaded_at - 8*86400")
    worker.run_batch_once()
    assert manifest.counts()["done"] == 0
    assert list((settings.results_dir / "2026-07-10").iterdir()) == []  # gambar+json terhapus
