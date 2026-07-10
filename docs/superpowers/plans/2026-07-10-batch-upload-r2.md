# Batch Upload R2 + DB Cloud — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-07-10-batch-upload-r2-design.md` (baca dulu — semua keputusan arsitektur locked di sana).

**Goal:** Tiap jam, PC pabrik meng-upload gambar hasil deteksi ke Cloudflare R2 + POST teksnya ke API cloud, tahan outage berapa pun tanpa data hilang / duplikat.

**Architecture:** Manifest SQLite (WAL + synchronous=FULL) melacak state per item (`pending → image_uploaded → done`, + `poisoned`). Worker batch (APScheduler hourly) scan `artifacts/results/`, upload gambar dulu (boto3 → R2, key deterministik), lalu POST payload yang direkonstruksi dari JSON disk ke `/internal/vision/events` API cloud (`event_id` uuid5 deterministik → idempoten). Outbox realtime lama di-comment (disimpan utuh); kanal webhook realtime lokal tidak disentuh.

**Tech Stack:** Python 3.11, SQLite (stdlib `sqlite3`), boto3, httpx, APScheduler 3.10.4, pytest + unittest.mock. API: TypeScript/Express, vitest.

## Global Constraints

- **Backup dulu:** branch `backup/staging-pre-batch-upload` dari `origin/staging` di KETIGA repo sebelum kode apa pun (Task 0).
- **Commit TANPA co-author Claude.** Gaya conventional commits (`feat(upload):`, `test(upload):`, `chore:`).
- **Kredensial R2/cloud = placeholder** — nilai asli tidak pernah masuk git. `.env` sudah gitignored; `.env.example` hanya placeholder kosong.
- **Outbox lama di-comment, TIDAK dihapus.** Penanda persis: `# [DISABLED: batch-upload-r2 — lihat spec 2026-07-10]`. Modul `integrations/outbox/` tidak disentuh.
- **Durability:** TANPA retry cap, TANPA TTL. Backoff eksponensial base 5 dtk, cap 600 dtk (sama dgn outbox). File lokal tidak pernah dihapus sebelum `done` + lewat retensi; `poisoned` tidak pernah dihapus.
- **Defaults:** `UPLOAD_MAX_ITEMS_PER_TICK=2000`, `UPLOAD_RETENTION_DAYS=7`, `UPLOAD_MINUTE=0` (hourly, `CronTrigger(minute=...)`, `max_instances=1`, `coalesce=True`). `R2_BUCKET` kosong = worker no-op (saklar off).
- **Test tanpa jaringan & tanpa kredensial** — boto3 client & httpx client di-inject lalu di-fake; SQLite pakai `tmp_path` asli; TANPA moto.
- **CI vision:** Python 3.11, deps ringan saja (tidak ada torch/cv2) — `workers/frame_processing_worker.py` TIDAK bisa di-import di CI (narik ultralytics), jadi kontrak JSON-nya di-test lewat fixture di test batch worker, bukan import langsung.
- **PR ke `staging`** (konvensi proyek), vision & api terpisah.
- Semua path vision relatif ke `/home/nexio/Desktop/Projects/sawit/palmgrade-vision`, path api relatif ke `/home/nexio/Desktop/Projects/sawit/palmgrade-api`.

## File Structure

**palmgrade-vision (baru):**
- `src/palmgrade/integrations/upload/__init__.py` — kosong (marker paket)
- `src/palmgrade/integrations/upload/upload_manifest.py` — state store SQLite; satu tanggung jawab: transisi state item yang crash-safe
- `src/palmgrade/integrations/upload/r2_uploader.py` — klien R2 bodoh: `put()` + `build_r2_key()`; tanpa state/retry
- `src/palmgrade/workers/batch_upload_worker.py` — orkestrasi per tick: scan → proses per item → retensi
- `tests/unit/test_upload_manifest.py`, `tests/unit/test_r2_uploader.py`, `tests/unit/test_batch_upload_worker.py`, `tests/unit/test_batch_upload_outage.py`, `tests/unit/test_batch_upload_crash.py`

**palmgrade-vision (modif):**
- `src/palmgrade/core/config.py` — env baru R2_*/UPLOAD_*, hapus `upload_hour`/`destination_upload`, warning prod
- `src/palmgrade/workers/frame_processing_worker.py` — +`assignment_id` di meta JSON; comment blok enqueue outbox
- `src/palmgrade/services/capture_service.py` + `src/palmgrade/repositories/capture_repository.py` — +`assignment_id` di JSON manual; comment enqueue outbox
- `src/palmgrade/integrations/scheduler/upload_scheduler.py` — GANTI TOTAL (archiver copytree/rmtree lama dibuang)
- `src/palmgrade/main.py` — comment startup OutboxRetryWorker; wiring worker batch baru
- `.env.example`, `.env`, `.env.production`, `docker-compose.yml`, `requirements.txt`, `.github/workflows/ci.yml`
- `docs/overview.md`, `docs/backend-overview.md`, `README.md` — sync deskripsi outbox/scheduler

**palmgrade-api (modif):**
- `src/utils/captureUrl.ts` + `tests/unit/utils/captureUrl.test.ts`

---

### Task 0: Backup branch 3 repo + feature branch

**Files:** tidak ada (git saja).

**Interfaces:**
- Consumes: `origin/staging` di ketiga repo.
- Produces: branch `backup/staging-pre-batch-upload` (pushed) di 3 repo; branch kerja `feat/batch-upload-r2` (vision, berbasis `docs/spec-batch-upload-r2` supaya spec ikut dalam PR) dan `feat/r2-capture-url` (api, dari `staging`).

- [ ] **Step 1: Backup ketiga repo**

```bash
cd /home/nexio/Desktop/Projects/sawit/palmgrade-vision && git fetch origin && git branch backup/staging-pre-batch-upload origin/staging && git push origin backup/staging-pre-batch-upload
cd /home/nexio/Desktop/Projects/sawit/palmgrade-api && git fetch origin && git branch backup/staging-pre-batch-upload origin/staging && git push origin backup/staging-pre-batch-upload
cd /home/nexio/Desktop/Projects/sawit/palmgrade-frontend && git fetch origin && git branch backup/staging-pre-batch-upload origin/staging && git push origin backup/staging-pre-batch-upload
```

Expected: 3 branch baru terlihat di remote (`git ls-remote --heads origin backup/staging-pre-batch-upload` → 1 baris per repo).

- [ ] **Step 2: Feature branch**

```bash
cd /home/nexio/Desktop/Projects/sawit/palmgrade-vision && git checkout -b feat/batch-upload-r2 docs/spec-batch-upload-r2
cd /home/nexio/Desktop/Projects/sawit/palmgrade-api && git checkout -b feat/r2-capture-url origin/staging
```

**FE tidak punya feature branch** — tidak ada perubahan kode FE.

---

### Task 1: Config env — tambah R2_*/UPLOAD_*, hapus UPLOAD_HOUR & DESTINATION_UPLOAD, rapikan .env

**Files:**
- Modify: `src/palmgrade/core/config.py` (baris 95-98 blok "Scheduler upload"; method `validate_for_runtime` baris 102-121)
- Modify: `.env.example`, `.env`, `.env.production`, `docker-compose.yml` (3 service)
- Test: `tests/unit/test_config_validation.py` (file sudah ada — tambah test)

**Interfaces:**
- Produces (dipakai semua task berikutnya): field `Settings` baru — `r2_account_id: str`, `r2_access_key_id: str`, `r2_secret_access_key: str`, `r2_bucket: str`, `r2_public_url: str` (di-rstrip `/`), `upload_api_url: str` (di-rstrip `/`), `upload_api_secret: str`, `upload_max_items_per_tick: int` (default 2000), `upload_retention_days: int` (default 7); property `upload_events_url: str`. Field `upload_hour` dan `destination_upload` HILANG.

- [ ] **Step 1: Write failing tests** — tambahkan di akhir `tests/unit/test_config_validation.py`:

```python
def test_batch_upload_defaults(monkeypatch):
    for var in ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_PUBLIC_URL", "UPLOAD_API_URL",
                "UPLOAD_MAX_ITEMS_PER_TICK", "UPLOAD_RETENTION_DAYS"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.r2_bucket == ""
    assert s.upload_max_items_per_tick == 2000
    assert s.upload_retention_days == 7
    # var scheduler lama sudah dihapus dari Settings
    assert not hasattr(s, "upload_hour")
    assert not hasattr(s, "destination_upload")


def test_upload_events_url_built_from_upload_api_url(monkeypatch):
    monkeypatch.setenv("UPLOAD_API_URL", "https://api.palmgrade.ai/")
    s = Settings()
    assert s.upload_api_url == "https://api.palmgrade.ai"  # trailing slash dibuang
    assert s.upload_events_url == "https://api.palmgrade.ai/api/v1/internal/vision/events"


def test_production_empty_r2_bucket_warns_not_crash(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEBHOOK_SECRET", "bukan-default-123")
    monkeypatch.delenv("R2_BUCKET", raising=False)
    s = Settings()
    with caplog.at_level("WARNING"):
        s.validate_for_runtime()  # TIDAK raise
    assert any("R2_BUCKET" in r.message for r in caplog.records)
```

(`Settings` sudah di-import di file itu.)

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_config_validation.py -v`
Expected: 3 test baru FAIL (`AttributeError: ... r2_bucket` / `hasattr` True).

- [ ] **Step 3: Implement di `config.py`** — ganti blok baris 95-98:

```python
    # Scheduler upload
    upload_hour: int = field(default_factory=lambda: int(os.getenv("UPLOAD_HOUR", "0")))
    upload_minute: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MINUTE", "0")))
    destination_upload: str = field(default_factory=lambda: os.getenv("DESTINATION_UPLOAD", ""))
```

menjadi:

```python
    # Batch upload cloud (R2 + API cloud) — semua kredensial placeholder sampai
    # bucket/domain dibuat. R2_BUCKET kosong = batch worker no-op (saklar off).
    upload_minute: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MINUTE", "0")))
    r2_account_id: str = field(default_factory=lambda: os.getenv("R2_ACCOUNT_ID", ""))
    r2_access_key_id: str = field(default_factory=lambda: os.getenv("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = field(default_factory=lambda: os.getenv("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket: str = field(default_factory=lambda: os.getenv("R2_BUCKET", ""))
    r2_public_url: str = field(default_factory=lambda: os.getenv("R2_PUBLIC_URL", "").rstrip("/"))
    # Target POST teks = API CLOUD. BACKEND_URL tetap menunjuk API LOKAL (webhook realtime).
    upload_api_url: str = field(default_factory=lambda: os.getenv("UPLOAD_API_URL", "").rstrip("/"))
    upload_api_secret: str = field(default_factory=lambda: os.getenv("UPLOAD_API_SECRET", ""))
    upload_max_items_per_tick: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MAX_ITEMS_PER_TICK", "2000")))
    upload_retention_days: int = field(default_factory=lambda: int(os.getenv("UPLOAD_RETENTION_DAYS", "7")))
```

Tambah property (setelah `canonical_events_url`, baris 177-179):

```python
    @property
    def upload_events_url(self) -> str:
        return f"{self.upload_api_url}{self.backend_api_ver}/internal/vision/events"
```

Di `validate_for_runtime`, tambah SEBELUM blok `if self.webhook_secret != _DEFAULT_WEBHOOK_SECRET:` (blok itu ber-`return` dini):

```python
        if self.environment == "production" and not self.r2_bucket:
            logger.warning(
                "R2_BUCKET kosong — batch upload ke cloud nonaktif (no-op). "
                "Isi R2_*/UPLOAD_API_* di .env untuk mengaktifkan."
            )
```

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_config_validation.py -v` → semua PASS.

- [ ] **Step 5: Update `.env.example`** — ganti blok "Auto Upload Schedule" (baris 93-99) dengan:

```bash
# ========================
# Batch Upload Cloud (R2 + API cloud) — jalan tiap jam pada menit UPLOAD_MINUTE
# Semua kredensial PLACEHOLDER — isi saat bucket R2 & domain dibuat.
# R2_BUCKET kosong = batch upload nonaktif (aman untuk dev/lokal).
# UPLOAD_API_SECRET = WEBHOOK_SECRET milik API CLOUD (bukan API lokal).
# ========================
UPLOAD_MINUTE=0
UPLOAD_MAX_ITEMS_PER_TICK=2000
UPLOAD_RETENTION_DAYS=7
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=
R2_PUBLIC_URL=
UPLOAD_API_URL=
UPLOAD_API_SECRET=
```

Sekalian **audit kelengkapan** (permintaan user): tambahkan var yang sudah dipakai `.env`/compose tapi hilang dari `.env.example` — sisipkan di section Camera / Inference yang sesuai:

```bash
# Serial kamera per line (Hikrobot, pilih by-serial — cegah rebutan antar line)
LINE_1_CAMERA_SERIAL=
LINE_2_CAMERA_SERIAL=
LINE_3_CAMERA_SERIAL=
# File .mfs (MVS Feature Save) per line — kosong = default config/camera/hikrobot.mfs
LINE_1_FEATURE_FILE=
LINE_2_FEATURE_FILE=
LINE_3_FEATURE_FILE=
# Jalankan YOLO tiap N frame (1 = production)
YOLO_SKIP_FRAMES=1
# Log verbose output model (1/true = aktif)
DEBUG_MODEL_OUTPUT=
```

- [ ] **Step 6: Update `.env` dan `.env.production`** — di keduanya: hapus baris `UPLOAD_HOUR=...` dan `DESTINATION_UPLOAD=...`, tambah blok var baru yang sama seperti `.env.example` (semua kosong; `.env.production` pakai placeholder gaya file itu, mis. `R2_SECRET_ACCESS_KEY=GANTI_R2_SECRET`). **Dua file ini gitignored — jangan pernah di-add.**

- [ ] **Step 7: Update `docker-compose.yml`** — di KETIGA service (`ripe-line-1/2/3`), ganti 3 baris:

```yaml
      - UPLOAD_HOUR=${UPLOAD_HOUR:-0}
      - UPLOAD_MINUTE=${UPLOAD_MINUTE:-0}
      - DESTINATION_UPLOAD=${DESTINATION_UPLOAD:-}
```

dengan:

```yaml
      - UPLOAD_MINUTE=${UPLOAD_MINUTE:-0}
      - UPLOAD_MAX_ITEMS_PER_TICK=${UPLOAD_MAX_ITEMS_PER_TICK:-2000}
      - UPLOAD_RETENTION_DAYS=${UPLOAD_RETENTION_DAYS:-7}
      - R2_ACCOUNT_ID=${R2_ACCOUNT_ID:-}
      - R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID:-}
      - R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY:-}
      - R2_BUCKET=${R2_BUCKET:-}
      - R2_PUBLIC_URL=${R2_PUBLIC_URL:-}
      - UPLOAD_API_URL=${UPLOAD_API_URL:-}
      - UPLOAD_API_SECRET=${UPLOAD_API_SECRET:-}
```

- [ ] **Step 8: Full unit run + commit**

```bash
pytest tests/unit/ -q   # semua pass
git add src/palmgrade/core/config.py .env.example docker-compose.yml tests/unit/test_config_validation.py
git commit -m "feat(config): env batch upload R2 + hapus UPLOAD_HOUR/DESTINATION_UPLOAD"
```

---

### Task 2: JSON meta +assignment_id; comment enqueue outbox (auto & manual)

**Files:**
- Modify: `src/palmgrade/workers/frame_processing_worker.py` (`_save_ripeness` baris 82-92, `_save_tp` baris 110-120, blok outbox baris 307-334)
- Modify: `src/palmgrade/services/capture_service.py` (call `save_manual_reject` baris 47-50, blok outbox baris 73-92)
- Modify: `src/palmgrade/repositories/capture_repository.py` (`save_manual_reject` baris 23-56)

**Interfaces:**
- Produces (kontrak JSON disk, dikonsumsi Task 5): setiap `*_ripeness.json` dan `*_tp.json` baru punya key tambahan `"assignment_id"` (string UUID atau `null`). JSON lama TANPA key ini tetap sah (builder pakai `.get()`).
- Catatan test: modul-modul ini menarik ultralytics/numpy → TIDAK di-import di CI-light. Kontrak JSON di-verifikasi oleh test payload-builder Task 5 (fixture dgn & tanpa `assignment_id`). Tidak ada test baru di task ini — verifikasi = review diff + `pytest tests/unit/ -q` tetap hijau.

- [ ] **Step 1: `frame_processing_worker.py` — meta `assignment_id`**

Di dict `meta` dalam `_save_ripeness` (setelah `"bounding_box": bounding_box,`) tambah:

```python
            "assignment_id": self.state.current_assignment_id,
```

Tambahkan baris yang sama di dict `meta` dalam `_save_tp`.

- [ ] **Step 2: `frame_processing_worker.py` — comment blok outbox**

Blok baris 307-334 (`truck_id = self.state.current_truck_id` s/d `logger.error("Failed to write event ...`) di-comment utuh, diawali satu baris penanda:

```python
                    # [DISABLED: batch-upload-r2 — lihat spec 2026-07-10]
                    # truck_id = self.state.current_truck_id
                    # if truck_id:
                    #     ...(seluruh blok asli, indentasi dipertahankan)...
```

JANGAN sentuh push `event_queue` (baris 300-305) — kanal realtime lokal tetap hidup. Import `uuid`/`OutboxStore` dibiarkan (rollback = uncomment; file ini di luar scope ruff CI).

- [ ] **Step 3: `capture_repository.py` — param `assignment_id`**

Ubah signature:

```python
    def save_manual_reject(
        self,
        frame: np.ndarray,
        truck_id: str | None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
```

dan di dict `payload` (setelah `"bounding_box": bounding_box,`) tambah:

```python
            "assignment_id": assignment_id,
```

- [ ] **Step 4: `capture_service.py` — pass assignment + comment outbox**

Ubah call jadi:

```python
        result = self.capture_repository.save_manual_reject(
            frame=frame,
            truck_id=truck_id,
            assignment_id=self.state.current_assignment_id,
        )
```

Comment blok outbox baris 73-92 (`event_id = str(uuid.uuid4())` s/d `logger.error(...)`) dengan penanda yang sama `# [DISABLED: batch-upload-r2 — lihat spec 2026-07-10]`. (Ini di luar teks spec §4 — spec cuma sebut frame worker & main.py — tapi wajib: tanpa ini manual capture terus menulis ke outbox.db yang tidak punya pengirim lagi. Sudah di-flag ke user.)

- [ ] **Step 5: Verify + commit**

```bash
pytest tests/unit/ -q                              # tetap hijau
grep -n "DISABLED: batch-upload-r2" src/palmgrade/workers/frame_processing_worker.py src/palmgrade/services/capture_service.py   # 2 penanda
git add src/palmgrade/workers/frame_processing_worker.py src/palmgrade/services/capture_service.py src/palmgrade/repositories/capture_repository.py
git commit -m "feat(upload): assignment_id di meta JSON + nonaktifkan enqueue outbox (comment)"
```

---

### Task 3: `upload_manifest.py` — state store SQLite

**Files:**
- Create: `src/palmgrade/integrations/upload/__init__.py` (kosong)
- Create: `src/palmgrade/integrations/upload/upload_manifest.py`
- Test: `tests/unit/test_upload_manifest.py`

**Interfaces:**
- Produces (dikonsumsi Task 5/6):
  - `UploadManifest(db_path: Path)`
  - `has_item(item_key: str) -> bool`
  - `upsert_item(item_key: str, event_id: str, image_path: str | None, r2_key: str | None) -> None` — INSERT OR IGNORE
  - `get_uploadable(limit: int) -> list[dict]` — status IN (pending, image_uploaded) AND next_retry_at <= now, ORDER BY discovered_at ASC; tiap dict berkey `id, item_key, event_id, image_path, r2_key, status, retry_count`
  - `mark_image_uploaded(item_id: int)`, `mark_done(item_id: int)`, `mark_poisoned(item_id: int, error: str)`
  - `requeue(item_id: int, error: str)` — retry_count++, `next_retry_at = now + min(5 * 2**(retry-1), 600)`, status TIDAK berubah, TANPA batas retry
  - `get_expired_done(cutoff: float) -> list[dict]` (uploaded_at < cutoff), `delete_item(item_id: int)`
  - `counts() -> dict[str, int]` — `{"pending": n, "image_uploaded": n, "done": n, "poisoned": n}`
- Konstanta modul: `_BACKOFF_BASE = 5`, `_BACKOFF_MAX = 600` (sama dgn `outbox_store.py`; TANPA `_MAX_RETRIES`).

- [ ] **Step 1: Write failing tests** — `tests/unit/test_upload_manifest.py`:

```python
"""Unit tests manifest batch-upload (spec 2026-07-10 §3.1, §7.1-7.3).

Manifest = jaminan durability alur batch: pending → image_uploaded → done
(+ poisoned). Beda kontrak dgn outbox lama: TANPA retry cap, TANPA TTL.
SQLite asli di tmp_path (bukan mock) — durability-nya justru yang di-test.
"""
from __future__ import annotations

import time

import pytest

from palmgrade.integrations.upload.upload_manifest import (
    _BACKOFF_BASE,
    _BACKOFF_MAX,
    UploadManifest,
)


@pytest.fixture
def m(tmp_path):
    return UploadManifest(db_path=tmp_path / "upload_manifest.db")


def _add(m, key="results/2026-07-10/a_auto_ripeness.json", **over):
    kw = dict(event_id="e1", image_path="captures/results/2026-07-10/a_auto.webp",
              r2_key="M1/results/2026-07-10/a_auto.webp")
    kw.update(over)
    m.upsert_item(key, **kw)


def test_scan_idempotent(m):
    _add(m); _add(m)  # scan 2x → tetap 1 row
    assert m.counts()["pending"] == 1
    assert m.has_item("results/2026-07-10/a_auto_ripeness.json")


def test_state_transitions(m):
    _add(m)
    item = m.get_uploadable(limit=10)[0]
    m.mark_image_uploaded(item["id"])
    assert m.get_uploadable(limit=10)[0]["status"] == "image_uploaded"
    m.mark_done(item["id"])
    assert m.get_uploadable(limit=10) == []
    assert m.counts()["done"] == 1


def test_done_never_reprocessed(m):
    _add(m)
    m.mark_done(m.get_uploadable(limit=10)[0]["id"])
    _add(m)  # re-scan file yang sama
    assert m.counts() == {"pending": 0, "image_uploaded": 0, "done": 1, "poisoned": 0}


def test_requeue_backoff_no_cap(m):
    # "tahan durasi outage apa pun": gagal 100x → TETAP eligible nanti, tak ada dead-letter
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    before = time.time()
    for _ in range(100):
        m.requeue(item_id, "ConnectionError")
    row = m._db.execute("SELECT status, retry_count, next_retry_at FROM upload_items WHERE id=?",
                        (item_id,)).fetchone()
    assert row["status"] == "pending"           # bukan 'failed'
    assert row["retry_count"] == 100
    assert row["next_retry_at"] - before <= _BACKOFF_MAX + 1


def test_requeue_first_backoff_is_base(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    before = time.time()
    m.requeue(item_id, "timeout")
    row = m._db.execute("SELECT next_retry_at FROM upload_items WHERE id=?", (item_id,)).fetchone()
    assert _BACKOFF_BASE - 1 <= row["next_retry_at"] - before <= _BACKOFF_BASE + 2
    assert m.get_uploadable(limit=10) == []     # backed off → tidak eligible sekarang


def test_requeue_preserves_state(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.mark_image_uploaded(item_id)
    m.requeue(item_id, "HTTP 503")
    row = m._db.execute("SELECT status FROM upload_items WHERE id=?", (item_id,)).fetchone()
    assert row["status"] == "image_uploaded"    # resume dari teks, gambar tak diulang


def test_poisoned_excluded(m):
    _add(m)
    _add(m, key="results/2026-07-10/b_auto_ripeness.json", event_id="e2")
    items = m.get_uploadable(limit=10)
    m.mark_poisoned(items[0]["id"], "json korup")
    left = m.get_uploadable(limit=10)
    assert len(left) == 1 and left[0]["id"] == items[1]["id"]


def test_oldest_first_and_limit(m):
    for i in range(5):
        _add(m, key=f"results/d/{i}_auto_ripeness.json", event_id=f"e{i}")
        time.sleep(0.01)
    got = m.get_uploadable(limit=3)
    assert [g["item_key"] for g in got] == [f"results/d/{i}_auto_ripeness.json" for i in range(3)]


def test_retention_query(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.mark_done(item_id)
    assert m.get_expired_done(cutoff=time.time() + 10)[0]["id"] == item_id
    assert m.get_expired_done(cutoff=time.time() - 10) == []
    m.delete_item(item_id)
    assert m.counts()["done"] == 0


def test_wal_survives_reopen(tmp_path):
    db = tmp_path / "upload_manifest.db"
    m1 = UploadManifest(db_path=db)
    m1.upsert_item("k1", event_id="e1", image_path=None, r2_key=None)
    m1.mark_image_uploaded(m1.get_uploadable(limit=1)[0]["id"])
    m2 = UploadManifest(db_path=db)  # "restart"
    assert m2.get_uploadable(limit=1)[0]["status"] == "image_uploaded"
    assert m2._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/unit/test_upload_manifest.py -v`
Expected: FAIL `ModuleNotFoundError: palmgrade.integrations.upload`.

- [ ] **Step 3: Implement** — `src/palmgrade/integrations/upload/upload_manifest.py`:

```python
"""Manifest SQLite untuk batch upload R2 + API cloud (spec 2026-07-10 §3.1).

State machine per item:
    pending ──PUT R2 ok──▶ image_uploaded ──POST API ok──▶ done ──retensi──▶ dihapus
       │ (item tanpa gambar: langsung POST → done)
       └─ input cacat ──▶ poisoned (di-skip, file TIDAK pernah dihapus)

Beda kontrak dgn outbox lama: TANPA retry cap & TANPA TTL — item nunggu di
disk selamanya sampai terkirim (syarat "tahan outage berapa pun").
Durability: WAL + synchronous=FULL, sama persis dgn outbox_store.py.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS upload_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key      TEXT NOT NULL UNIQUE,
    event_id      TEXT,
    image_path    TEXT,
    r2_key        TEXT,
    status        TEXT DEFAULT 'pending',
    retry_count   INTEGER DEFAULT 0,
    next_retry_at REAL DEFAULT 0,
    last_error    TEXT,
    discovered_at REAL,
    uploaded_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_upload_status ON upload_items (status, next_retry_at);
"""

_BACKOFF_BASE = 5
_BACKOFF_MAX = 600


class UploadManifest:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)

    def has_item(self, item_key: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM upload_items WHERE item_key = ?", (item_key,)
            ).fetchone()
        return row is not None

    def upsert_item(
        self, item_key: str, event_id: str, image_path: str | None, r2_key: str | None
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO upload_items "
                "(item_key, event_id, image_path, r2_key, discovered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (item_key, event_id, image_path, r2_key, time.time()),
            )

    def get_uploadable(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT id, item_key, event_id, image_path, r2_key, status, retry_count
                   FROM upload_items
                   WHERE status IN ('pending', 'image_uploaded') AND next_retry_at <= ?
                   ORDER BY discovered_at ASC LIMIT ?""",
                (time.time(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_image_uploaded(self, item_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE upload_items SET status='image_uploaded', last_error=NULL WHERE id=?",
                (item_id,),
            )

    def mark_done(self, item_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE upload_items SET status='done', uploaded_at=?, last_error=NULL WHERE id=?",
                (time.time(), item_id),
            )

    def mark_poisoned(self, item_id: int, error: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE upload_items SET status='poisoned', last_error=? WHERE id=?",
                (error[:500], item_id),
            )

    def requeue(self, item_id: int, error: str) -> None:
        # TANPA batas retry — status tidak berubah, hanya backoff yang maju.
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT retry_count FROM upload_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                return
            retry = row["retry_count"] + 1
            backoff = min(_BACKOFF_BASE * (2 ** (retry - 1)), _BACKOFF_MAX)
            self._db.execute(
                "UPDATE upload_items SET retry_count=?, next_retry_at=?, last_error=? WHERE id=?",
                (retry, time.time() + backoff, error[:500], item_id),
            )

    def get_expired_done(self, cutoff: float) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, item_key, image_path FROM upload_items "
                "WHERE status='done' AND uploaded_at < ?",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_item(self, item_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM upload_items WHERE id=?", (item_id,))

    def counts(self) -> dict[str, int]:
        base = {"pending": 0, "image_uploaded": 0, "done": 0, "poisoned": 0}
        with self._lock:
            rows = self._db.execute(
                "SELECT status, COUNT(*) AS n FROM upload_items GROUP BY status"
            ).fetchall()
        base.update({r["status"]: r["n"] for r in rows})
        return base
```

Buat juga `src/palmgrade/integrations/upload/__init__.py` kosong.

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/unit/test_upload_manifest.py -v` → 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/integrations/upload/ tests/unit/test_upload_manifest.py
git commit -m "feat(upload): manifest SQLite durable (WAL+FULL, tanpa retry cap)"
```

---

### Task 4: `r2_uploader.py` + dependensi boto3

**Files:**
- Create: `src/palmgrade/integrations/upload/r2_uploader.py`
- Modify: `requirements.txt`, `.github/workflows/ci.yml`
- Test: `tests/unit/test_r2_uploader.py`

**Interfaces:**
- Produces (dikonsumsi Task 5/6 & main.py):
  - `build_r2_key(machine_id: str, image_path: str) -> str` — fungsi modul, deterministik: strip prefix `captures/` lalu prefix `{machine_id}/` → `"M1/results/2026-07-10/x.webp"`
  - `R2Uploader(account_id: str, access_key_id: str, secret_access_key: str, bucket: str, client=None)` — `client` injectable untuk test; kalau None dibuat lazy saat `put()` pertama
  - `put(local_path: Path, r2_key: str) -> None` — PUT object `ContentType="image/webp"`; exception dibiarkan naik (retry urusan manifest)

- [ ] **Step 1: Install & pin boto3**

```bash
pip install boto3
python -c "import boto3; print(boto3.__version__)"
```

Tambahkan ke `requirements.txt` di bawah section `# ── HTTP Client ──` dengan versi persis hasil perintah di atas:

```
boto3==<versi hasil print di atas>
```

- [ ] **Step 2: Write failing tests** — `tests/unit/test_r2_uploader.py`:

```python
"""Unit tests klien R2 (spec §3.2, §7.4). boto3 client di-inject & di-fake —
tanpa jaringan, tanpa kredensial, tanpa moto."""
from __future__ import annotations

from unittest.mock import Mock

from palmgrade.integrations.upload.r2_uploader import R2Uploader, build_r2_key


def test_r2_key_deterministic():
    # path sama = key sama → re-upload menimpa dirinya sendiri (anti-duplikat lapis 2)
    a = build_r2_key("M1", "captures/results/2026-07-10/x_auto.webp")
    b = build_r2_key("M1", "captures/results/2026-07-10/x_auto.webp")
    assert a == b == "M1/results/2026-07-10/x_auto.webp"


def test_r2_key_machine_prefix_isolates_lines():
    p = "captures/results/2026-07-10/x_auto.webp"
    assert build_r2_key("M1", p) != build_r2_key("M2", p)


def test_put_calls_put_object(tmp_path):
    f = tmp_path / "x.webp"
    f.write_bytes(b"webp-bytes")
    fake = Mock()
    up = R2Uploader(account_id="acc", access_key_id="k", secret_access_key="s",
                    bucket="palmgrade", client=fake)
    up.put(f, "M1/results/2026-07-10/x.webp")
    kwargs = fake.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "palmgrade"
    assert kwargs["Key"] == "M1/results/2026-07-10/x.webp"
    assert kwargs["ContentType"] == "image/webp"
    assert kwargs["Body"] == b"webp-bytes"


def test_put_propagates_client_error(tmp_path):
    f = tmp_path / "x.webp"
    f.write_bytes(b"d")
    fake = Mock()
    fake.put_object.side_effect = ConnectionError("R2 down")
    up = R2Uploader(account_id="a", access_key_id="k", secret_access_key="s",
                    bucket="b", client=fake)
    try:
        up.put(f, "k")
        raise AssertionError("harus raise")
    except ConnectionError:
        pass  # retry = urusan manifest, bukan uploader
```

- [ ] **Step 3: Run, verify FAIL**

Run: `pytest tests/unit/test_r2_uploader.py -v` → FAIL `ModuleNotFoundError`/`ImportError`.

- [ ] **Step 4: Implement** — `src/palmgrade/integrations/upload/r2_uploader.py`:

```python
"""Klien Cloudflare R2 — bodoh & stateless (spec 2026-07-10 §3.2).

Satu tugas: PUT file lokal ke bucket. Tanpa retry sendiri, tanpa state —
kegagalan dibiarkan naik ke pemanggil (manifest yang mengatur requeue).
r2_key deterministik dari path → re-upload selalu menimpa objek yang sama
(S3 PUT overwrite) → tidak pernah ada duplikat di R2.
"""
from __future__ import annotations

from pathlib import Path

import boto3


def build_r2_key(machine_id: str, image_path: str) -> str:
    relative = image_path.lstrip("/").removeprefix("captures/")
    return f"{machine_id}/{relative}"


class R2Uploader:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        client=None,
    ) -> None:
        self._account_id = account_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self.bucket = bucket
        self._client = client  # injectable untuk test; lazy untuk runtime

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{self._account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
            )
        return self._client

    def put(self, local_path: Path, r2_key: str) -> None:
        self._get_client().put_object(
            Bucket=self.bucket,
            Key=r2_key,
            Body=local_path.read_bytes(),
            ContentType="image/webp",
        )
```

- [ ] **Step 5: Run, verify PASS**

Run: `pytest tests/unit/test_r2_uploader.py -v` → 4 PASS.

- [ ] **Step 6: Update CI (boto3 saja)** — `.github/workflows/ci.yml`:

Baris install: `pip install ruff pytest cryptography aiosqlite psutil httpx` → tambah ` boto3` di akhir. (boto3/botocore pure-python wheel — tetap ringan, komentar "deps ringan" di atasnya masih benar.)

Baris ruff JANGAN diubah dulu — `workers/batch_upload_worker.py` baru ada di Task 5; ruff terhadap path yang belum ada akan error. Perubahan ruff line dilakukan di Task 5 Step 5.

- [ ] **Step 7: Commit**

```bash
git add src/palmgrade/integrations/upload/r2_uploader.py tests/unit/test_r2_uploader.py requirements.txt .github/workflows/ci.yml
git commit -m "feat(upload): klien R2 stateless (boto3) + key deterministik"
```

---

### Task 5: Batch worker — discovery, pairing tp, rekonstruksi payload

**Files:**
- Create: `src/palmgrade/workers/batch_upload_worker.py` (bagian discovery + payload; orkestrasi `run_batch_once` menyusul Task 6 di file yang sama)
- Modify: `.github/workflows/ci.yml` (ruff line — lihat Task 4 Step 6)
- Test: `tests/unit/test_batch_upload_worker.py`

**Interfaces:**
- Consumes: `UploadManifest` (Task 3), `build_r2_key` (Task 4), `Settings` field Task 1, kontrak JSON Task 2.
- Produces (dipakai Task 6 & test):
  - `file_timestamp(json_name: str) -> str` — `"2026-07-10_083000_123456_auto_ripeness.json"` → `"2026-07-10_083000_123456"`; suffix dikenali: `_auto_ripeness.json`, `_manual_ripeness.json`, `_auto_tp.json`; selain itu `ValueError`
  - `event_id_for(machine_id: str, file_ts: str) -> str` — `str(uuid.uuid5(uuid.NAMESPACE_URL, f"{machine_id}:{file_ts}"))` — RUMUS PERSIS outbox lama (`frame_processing_worker.py:313-315`) → idempoten lintas alur
  - `class _PoisonError(Exception)` — input cacat; `class _RequeueError(Exception)` — kondisi eksternal rusak
  - `BatchUploadWorker(settings, manifest, uploader, http_client=None)`
  - `worker._scan() -> None` — isi manifest dari disk (INSERT OR IGNORE)
  - `worker._build_payload(item: dict) -> dict` — payload POST lengkap; raise `_PoisonError` kalau JSON korup / field wajib hilang

**Aturan discovery (dari kode existing, bukan asumsi):**
- File ripeness: `results/<date>/{ts}_auto_ripeness.json` (auto, `frame_processing_worker._save_ripeness`) dan `{ts}_manual_ripeness.json` (manual, `capture_repository.save_manual_reject`). Key gambar di JSON: auto pakai `image_path`, manual pakai `image_url` → builder baca `meta.get("image_path") or meta.get("image_url")`.
- File tp: `{ts}_auto_tp.json` — SELALU ditulis setelah ripeness ber-ts sama (lihat `run_once`), jadi tp yatim praktis mustahil; tetap ditangani (item sendiri).
- `item_key` = path JSON relatif terhadap `settings.artifacts_dir`, mis. `"results/2026-07-10/{ts}_auto_ripeness.json"`.
- Pairing tp TIDAK disimpan di manifest — di-derive: sibling path = `item_key` dengan `"_ripeness.json"` → `"_tp.json"`. Merge terjadi saat build payload (otomatis mencakup tp yang datang setelah item dibuat tapi belum done).
- tp yatim (`_tp.json` tanpa sibling ripeness di disk saat scan) → item sendiri `image_path=NULL`; saat build, kalau sibling ripeness muncul belakangan → merge penuh → POST dibalas `already_processed` (item ripeness-nya sudah/akan kirim payload sama) → done; kalau tetap tak ada → `_PoisonError` (field wajib `ripeness_status`/`prediction` tidak bisa direkonstruksi).

- [ ] **Step 1: Write failing tests** — `tests/unit/test_batch_upload_worker.py`:

```python
"""Unit tests discovery + rekonstruksi payload batch worker (spec §3.3, §7.1, §7.4)."""
from __future__ import annotations

import json
import uuid

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
    meta = json.loads(p.read_text()); meta.pop("assignment_id"); p.write_text(json.dumps(meta))
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
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/unit/test_batch_upload_worker.py -v` → FAIL `ModuleNotFoundError: ... batch_upload_worker`.

- [ ] **Step 3: Implement** — `src/palmgrade/workers/batch_upload_worker.py`:

```python
"""Batch upload worker — kirim hasil deteksi (gambar + teks) ke cloud tiap jam.

Alur per tick (spec 2026-07-10 §3.3): scan → proses per item (gambar dulu ke
R2, lalu POST teks ke API cloud) → retensi. State per item hidup di
UploadManifest; worker ini stateless antar tick.

Klasifikasi kegagalan (spec §5):
- _RequeueError  → kondisi eksternal rusak (jaringan/5xx/429/401/403/404):
  requeue item + BREAK batch (percuma lanjut; sisa antrean nunggu tick berikut).
- _PoisonError   → input cacat (JSON korup/field hilang/gambar hilang):
  poisoned + CONTINUE (satu item busuk tidak menyandera batch). File TIDAK dihapus.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..core.config import Settings
from ..integrations.upload.r2_uploader import R2Uploader, build_r2_key
from ..integrations.upload.upload_manifest import UploadManifest

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # payload teks kecil; 30s aman utk link pabrik lambat

_RIPENESS_SUFFIXES = ("_auto_ripeness.json", "_manual_ripeness.json")
_TP_SUFFIX = "_auto_tp.json"


class _PoisonError(Exception):
    """Input cacat — retry tidak akan menolong; item di-skip permanen."""


class _RequeueError(Exception):
    """Kondisi eksternal rusak — item diantre ulang, batch berhenti dulu."""


def file_timestamp(json_name: str) -> str:
    for suffix in (*_RIPENESS_SUFFIXES, _TP_SUFFIX):
        if json_name.endswith(suffix):
            return json_name.removesuffix(suffix)
    raise ValueError(f"Bukan nama file hasil deteksi: {json_name}")


def event_id_for(machine_id: str, file_ts: str) -> str:
    # Rumus PERSIS sama dgn outbox lama (frame_processing_worker) → POST ulang
    # event yang pernah terkirim dibalas already_processed, bukan row baru.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{machine_id}:{file_ts}"))


class BatchUploadWorker:
    def __init__(
        self,
        settings: Settings,
        manifest: UploadManifest,
        uploader: R2Uploader | None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.manifest = manifest
        self.uploader = uploader
        self._client = http_client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        self._warned_noop = False

    # ---------------------------------------------------------------- discovery

    def _read_meta(self, json_path: Path) -> dict[str, Any]:
        try:
            return json.loads(json_path.read_text())
        except FileNotFoundError as exc:
            raise _PoisonError(f"JSON hilang: {json_path}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _PoisonError(f"JSON korup: {json_path}: {exc}") from exc

    def _image_ref(self, meta: dict[str, Any]) -> str | None:
        # auto pakai "image_path", manual pakai "image_url" (capture_repository)
        return meta.get("image_path") or meta.get("image_url")

    def _scan(self) -> None:
        artifacts = self.settings.artifacts_dir
        results = self.settings.results_dir
        if not results.exists():
            return
        for json_path in sorted(results.glob("*/*_ripeness.json")):
            item_key = str(json_path.relative_to(artifacts))
            if self.manifest.has_item(item_key):
                continue
            ts = file_timestamp(json_path.name)
            image_path = None
            r2_key = None
            try:
                image_path = self._image_ref(self._read_meta(json_path))
            except _PoisonError:
                pass  # item tetap dibuat; poison ketahuan saat build payload
            if image_path:
                r2_key = build_r2_key(self.settings.machine_id, image_path)
            self.manifest.upsert_item(
                item_key,
                event_id=event_id_for(self.settings.machine_id, ts),
                image_path=image_path,
                r2_key=r2_key,
            )
        for tp_path in sorted(results.glob(f"*/*{_TP_SUFFIX}")):
            sibling = tp_path.with_name(
                tp_path.name.replace(_TP_SUFFIX, "_auto_ripeness.json")
            )
            if sibling.exists():
                continue  # digabung ke item ripeness-nya (merge saat build)
            item_key = str(tp_path.relative_to(artifacts))
            if self.manifest.has_item(item_key):
                continue
            ts = file_timestamp(tp_path.name)
            self.manifest.upsert_item(
                item_key,
                event_id=event_id_for(self.settings.machine_id, ts),
                image_path=None,
                r2_key=None,
            )

    # ---------------------------------------------------------------- payload

    def _build_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        artifacts = self.settings.artifacts_dir
        json_path = artifacts / item["item_key"]

        if json_path.name.endswith(_TP_SUFFIX):
            # Item tp yatim: coba pasangan ripeness yang muncul belakangan.
            sibling = json_path.with_name(
                json_path.name.replace(_TP_SUFFIX, "_auto_ripeness.json")
            )
            if not sibling.exists():
                raise _PoisonError(
                    f"tp tanpa pasangan ripeness — payload tak bisa direkonstruksi: {json_path}"
                )
            json_path = sibling  # merge penuh; event_id sama → already_processed

        meta = self._read_meta(json_path)
        ripeness_status = meta.get("ripeness_status")
        if not ripeness_status:
            raise _PoisonError(f"ripeness_status hilang: {json_path}")

        image_ref = self._image_ref(meta)
        if not image_ref:
            raise _PoisonError(f"image_path hilang: {json_path}")
        r2_key = item["r2_key"] or build_r2_key(self.settings.machine_id, image_ref)

        tp_status = meta.get("tp_status")
        tp_confidence = meta.get("tp_confidence", 0)
        tp_path = json_path.with_name(
            json_path.name.replace("_auto_ripeness.json", _TP_SUFFIX)
        )
        if tp_path != json_path and tp_path.exists():
            tp_meta = self._read_meta(tp_path)
            tp_status = tp_meta.get("tp_status") or tp_status
            tp_confidence = tp_meta.get("tp_confidence", tp_confidence)

        payload: dict[str, Any] = {
            "event_id": item["event_id"],
            "machine_id": self.settings.machine_id,
            "timestamp": meta.get("timestamp"),
            "prediction": "Acc" if str(ripeness_status).lower() == "acc" else "Rej",
            "ripeness_status": str(ripeness_status).upper(),
            "ripeness_confidence": meta.get("ripeness_confidence", 0),
            "tp_status": tp_status,
            "tp_confidence": tp_confidence,
            "capture_type": meta.get("capture_type", "auto"),
            "truck_id": meta.get("truck_id"),
            "image_path": f"{self.settings.r2_public_url}/{r2_key}",
            "bounding_box": meta.get("bounding_box") or {},
        }
        if meta.get("assignment_id"):
            payload["assignment_id"] = meta["assignment_id"]
        if not payload["timestamp"]:
            raise _PoisonError(f"timestamp hilang: {json_path}")
        return payload
```

(`run_batch_once`, `_process_item`, `_retention` ditambahkan Task 6 di file yang sama.)

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/unit/test_batch_upload_worker.py -v` → 9 PASS.

- [ ] **Step 5: Update ruff line CI** (yang ditunda dari Task 4) lalu jalankan lokal:

Di `.github/workflows/ci.yml`, ganti baris ruff menjadi:

```yaml
        run: ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ src/palmgrade/license/ src/palmgrade/workers/batch_upload_worker.py
```

lalu:

```bash
ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ src/palmgrade/license/ src/palmgrade/workers/batch_upload_worker.py
```

Expected: clean (perbaiki kalau ada temuan).

- [ ] **Step 6: Commit**

```bash
git add src/palmgrade/workers/batch_upload_worker.py tests/unit/test_batch_upload_worker.py .github/workflows/ci.yml
git commit -m "feat(upload): discovery + pairing tp + rekonstruksi payload"
```

---

### Task 6: Batch worker — orkestrasi run_batch_once, klasifikasi error, retensi

**Files:**
- Modify: `src/palmgrade/workers/batch_upload_worker.py` (lanjutan Task 5)
- Test: `tests/unit/test_batch_upload_outage.py`, `tests/unit/test_batch_upload_crash.py`

**Interfaces:**
- Consumes: semua dari Task 3-5.
- Produces: `worker.run_batch_once() -> None` (dipanggil scheduler Task 7 & test).
- Klasifikasi respons POST (dari kontrak `visionIngest.controller.ts` + spec §5):
  - `httpx` exception (koneksi/timeout) → `_RequeueError`
  - HTTP 200/201 ATAU body mengandung `already_processed` → sukses
  - HTTP 400/422 → `_PoisonError` (payload cacat)
  - HTTP 401/403 → `_RequeueError` + log ERROR (secret salah — benerin .env, antrean jalan sendiri)
  - HTTP 404 → `_RequeueError` + log ERROR (**tambahan dari kode nyata, di luar tabel spec §5**: controller balas 404 "Truck not found" kalau truck belum ada di DB cloud; setelah truck disinkron, antrean jalan lagi — data tidak boleh hilang karena poisoned)
  - HTTP lain (429/5xx/apa pun) → `_RequeueError`
- PUT R2: `FileNotFoundError` → `_PoisonError` (gambar hilang, file JSON TIDAK dihapus); exception lain → `_RequeueError`.

- [ ] **Step 1: Write failing tests** — `tests/unit/test_batch_upload_outage.py`:

```python
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
    assert manifest.counts()["pending"] == 3   # requeue + break di item pertama
    assert len(http.posts) == 1


def test_http_404_truck_missing_requeues(env):
    settings, manifest, worker, uploader, http = env
    _write_items(settings, 1)
    http.response = FakeResponse(404, "Truck not found")
    worker.run_batch_once()
    assert manifest.counts()["pending"] == 1   # nunggu truck disinkron, bukan poisoned


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
```

dan `tests/unit/test_batch_upload_crash.py`:

```python
"""Simulasi mati listrik (spec §7.3): os._exit di tengah transisi state →
manifest tetap konsisten saat dibuka ulang (WAL + synchronous=FULL)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

_CRASH_SCRIPT = """
import os, sys
from pathlib import Path
from palmgrade.integrations.upload.upload_manifest import UploadManifest

db = Path(sys.argv[1])
m = UploadManifest(db_path=db)
for i in range(3):
    m.upsert_item(f"results/d/{i}_auto_ripeness.json", event_id=f"e{i}",
                  image_path=f"captures/results/d/{i}.webp", r2_key=f"M/d/{i}.webp")
m.mark_image_uploaded(m.get_uploadable(limit=1)[0]["id"])
os._exit(1)  # mati listrik: tanpa cleanup, tanpa flush python
"""


def test_crash_mid_batch_no_partial_write(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "PYTHONPATH": str(_REPO / "src")}
    proc = subprocess.run([sys.executable, "-c", _CRASH_SCRIPT, str(db)],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 1, proc.stderr

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT item_key, status FROM upload_items ORDER BY item_key").fetchall()
    # Semua transaksi yang commit sebelum crash selamat; tidak ada row setengah jadi.
    assert [r["status"] for r in rows] == ["image_uploaded", "pending", "pending"]
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/unit/test_batch_upload_outage.py tests/unit/test_batch_upload_crash.py -v`
Expected: FAIL `AttributeError: ... run_batch_once`.

- [ ] **Step 3: Implement** — tambahkan di `BatchUploadWorker` (file Task 5):

```python
    # ---------------------------------------------------------------- orchestration

    def run_batch_once(self) -> None:
        if not self.settings.r2_bucket:
            if not self._warned_noop:
                logger.warning("R2_BUCKET kosong — batch upload no-op (saklar off)")
                self._warned_noop = True
            return

        self._scan()
        items = self.manifest.get_uploadable(limit=self.settings.upload_max_items_per_tick)
        logger.info("Batch tick: %d item eligible (%s)", len(items), self.manifest.counts())

        for item in items:
            try:
                self._process_item(item)
            except _PoisonError as exc:
                logger.error("Item poisoned %s: %s", item["item_key"], exc)
                self.manifest.mark_poisoned(item["id"], str(exc))
                continue  # satu item busuk tidak menyandera batch
            except _RequeueError as exc:
                logger.warning("Item requeued %s: %s — batch break", item["item_key"], exc)
                self.manifest.requeue(item["id"], str(exc))
                break  # kondisi eksternal rusak — sisa antrean nunggu tick berikut

        self._retention()

    def _process_item(self, item: dict[str, Any]) -> None:
        if item["status"] == "pending" and item["image_path"]:
            local = self.settings.artifacts_dir / item["image_path"].lstrip("/").removeprefix("captures/")
            try:
                self.uploader.put(local, item["r2_key"])
            except FileNotFoundError as exc:
                raise _PoisonError(f"file gambar hilang: {local}") from exc
            except Exception as exc:
                raise _RequeueError(f"PUT R2 gagal: {exc}") from exc
            self.manifest.mark_image_uploaded(item["id"])
            item["status"] = "image_uploaded"

        payload = self._build_payload(item)  # bisa raise _PoisonError
        headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": self.settings.upload_api_secret,
        }
        try:
            res = self._client.post(self.settings.upload_events_url, json=payload, headers=headers)
        except Exception as exc:
            raise _RequeueError(f"POST gagal: {exc}") from exc

        if res.status_code in (200, 201) or "already_processed" in res.text:
            self.manifest.mark_done(item["id"])
            return
        if res.status_code in (400, 422):
            raise _PoisonError(f"HTTP {res.status_code}: {res.text[:200]}")
        if res.status_code in (401, 403):
            logger.error("Auth ke API cloud ditolak (HTTP %s) — cek UPLOAD_API_SECRET", res.status_code)
        if res.status_code == 404:
            logger.error("Truck belum ada di DB cloud (HTTP 404) — item nunggu sinkronisasi truck")
        raise _RequeueError(f"HTTP {res.status_code}: {res.text[:200]}")

    # ---------------------------------------------------------------- retention

    def _retention(self) -> None:
        cutoff = time.time() - self.settings.upload_retention_days * 86400
        for item in self.manifest.get_expired_done(cutoff):
            json_path = self.settings.artifacts_dir / item["item_key"]
            targets = [json_path]
            if json_path.name.endswith("_auto_ripeness.json"):
                targets.append(json_path.with_name(json_path.name.replace("_auto_ripeness.json", _TP_SUFFIX)))
            if item["image_path"]:
                targets.append(
                    self.settings.artifacts_dir / item["image_path"].lstrip("/").removeprefix("captures/")
                )
            for t in targets:
                t.unlink(missing_ok=True)
            self.manifest.delete_item(item["id"])
```

**Catatan `FileNotFoundError` di PUT:** `R2Uploader.put` membaca `local_path.read_bytes()` — file hilang → `FileNotFoundError` naik sebelum kena jaringan → poison. FakeUploader di test tidak membaca file, jadi kasus itu dites via `_build_payload`? TIDAK — `test_missing_image_file_poisons_json_kept` menghapus `.webp` dan FakeUploader tidak raise... **Karena itu `_process_item` HARUS cek eksistensi file dulu:** tambahkan sebelum `self.uploader.put(...)`:

```python
            if not local.exists():
                raise _PoisonError(f"file gambar hilang: {local}")
```

(baris `except FileNotFoundError` tetap dipertahankan sebagai lapis kedua untuk race file-dihapus-di-tengah).

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/unit/ -q` → semua PASS (termasuk 12 outage + 1 crash).

- [ ] **Step 5: Commit**

```bash
git add src/palmgrade/workers/batch_upload_worker.py tests/unit/test_batch_upload_outage.py tests/unit/test_batch_upload_crash.py
git commit -m "feat(upload): orkestrasi batch + klasifikasi error + retensi 7 hari"
```

---

### Task 7: Scheduler hourly + wiring main.py + nonaktifkan OutboxRetryWorker

**Files:**
- Modify: `src/palmgrade/integrations/scheduler/upload_scheduler.py` (GANTI TOTAL — archiver copytree/rmtree lama dibuang; berbahaya & tak terpakai)
- Modify: `src/palmgrade/main.py` (blok OutboxRetryWorker baris 139-147; konstruksi `UploadScheduler` baris 160-161)

**Interfaces:**
- Consumes: `BatchUploadWorker.run_batch_once` (Task 6), `Settings.upload_minute`.
- Produces: `UploadScheduler(settings: Settings, run_batch: Callable[[], None])` dengan `.start()` / `.stop()` — dipakai `main.py`.
- Tidak ada unit test timing APScheduler (keputusan spec §7) — perilaku tick sudah di-test lewat `run_batch_once` langsung.

- [ ] **Step 1: Tulis ulang `upload_scheduler.py`** (isi penuh file):

```python
"""Scheduler batch upload cloud — tiap jam pada menit UPLOAD_MINUTE.

Pengganti archiver lokal lama (copytree+rmtree ke DESTINATION_UPLOAD) yang
sudah tidak dipakai. Sekarang satu-satunya job: BatchUploadWorker.run_batch_once
(spec 2026-07-10 §3.4). max_instances=1 + coalesce=True → tick yang telat/numpuk
di-skip, tidak pernah jalan paralel.
"""
from __future__ import annotations

import atexit
import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from ...core.config import Settings

logger = logging.getLogger(__name__)


class UploadScheduler:
    def __init__(self, settings: Settings, run_batch: Callable[[], None]) -> None:
        self.settings = settings
        self._run_batch = run_batch
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._run_batch,
            CronTrigger(minute=self.settings.upload_minute),
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        atexit.register(self.stop)
        logger.info(
            "Batch upload terjadwal tiap jam pada menit %02d (R2_BUCKET=%s)",
            self.settings.upload_minute,
            self.settings.r2_bucket or "<kosong — no-op>",
        )

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown()
            logger.info("Batch upload scheduler stopped")
```

- [ ] **Step 2: `main.py` — comment OutboxRetryWorker, wiring baru**

Ganti blok baris 139-147 dengan versi ter-comment (penanda sama):

```python
        # [DISABLED: batch-upload-r2 — lihat spec 2026-07-10]
        # OutboxRetryWorker — delivers pending events to canonical API endpoint
        # outbox_store = get_outbox_store()
        # outbox_worker = OutboxRetryWorker(
        #     outbox=outbox_store,
        #     settings=settings,
        #     state=state,
        # )
        # outbox_thread = _start_worker("outbox_retry", outbox_worker.run_loop)
        # state.worker_threads.append(("outbox_retry", outbox_thread, outbox_worker))
```

Ganti baris 160-161 (`upload_scheduler = UploadScheduler(settings=settings)` + `.start()`) dengan:

```python
        # Batch upload cloud: gambar → R2, teks → API cloud, tiap jam.
        upload_manifest = UploadManifest(db_path=settings.artifacts_dir / "upload_manifest.db")
        r2_uploader = R2Uploader(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
        batch_worker = BatchUploadWorker(
            settings=settings, manifest=upload_manifest, uploader=r2_uploader
        )
        upload_scheduler = UploadScheduler(settings=settings, run_batch=batch_worker.run_batch_once)
        upload_scheduler.start()
```

Tambah import (dekat import scheduler yang sudah ada, baris 34):

```python
from .integrations.upload.r2_uploader import R2Uploader
from .integrations.upload.upload_manifest import UploadManifest
from .workers.batch_upload_worker import BatchUploadWorker
```

Import `OutboxRetryWorker` (baris 24) DIBIARKAN — rollback = uncomment blok; file ini di luar scope ruff CI. `upload_scheduler.stop()` di shutdown (baris 171) tidak berubah.

- [ ] **Step 3: Verify syntax & tests**

```bash
pytest tests/unit/ -q    # tetap hijau
python -c "import ast; ast.parse(open('src/palmgrade/main.py').read()); ast.parse(open('src/palmgrade/integrations/scheduler/upload_scheduler.py').read()); print('syntax ok')"
```

(Full import `main.py` butuh torch — cukup cek syntax di sini; startup nyata diverifikasi smoke test Task 9.)

- [ ] **Step 4: Commit**

```bash
git add src/palmgrade/integrations/scheduler/upload_scheduler.py src/palmgrade/main.py
git commit -m "feat(upload): scheduler hourly batch + nonaktifkan OutboxRetryWorker (comment)"
```

---

### Task 8: Sync docs vision

**Files:**
- Modify: `docs/overview.md` (baris 34, 38, 92), `docs/backend-overview.md` (blok outbox baris ±305-344, tabel env baris ±379-381), `README.md` (baris 31)

**Interfaces:** tidak ada — dokumentasi mengikuti kode.

- [ ] **Step 1: Update `docs/overview.md`**

- Baris 34 (row tabel `OutboxRetryWorker`): tandai nonaktif —
  `| ~~OutboxRetryWorker~~ | thread | **DINONAKTIFKAN (di-comment)** sejak batch-upload-r2 (spec 2026-07-10) — digantikan batch upload hourly ke R2 + API cloud |`
- Baris 38: ganti `` `UploadScheduler` (APScheduler) runs the daily artifact upload cron. `` dengan:
  `` `UploadScheduler` (APScheduler) menjalankan `BatchUploadWorker.run_batch_once` tiap jam (menit `UPLOAD_MINUTE`): scan `artifacts/results/` → manifest SQLite → upload gambar ke R2 → POST teks ke API cloud. `R2_BUCKET` kosong = no-op. ``
- Baris 92 (diagram): ganti baris `→ OutboxRetryWorker (thread, poll 1s)` dengan `→ [DISABLED] OutboxRetryWorker — diganti BatchUploadWorker (hourly, R2 + API cloud)`

- [ ] **Step 2: Update `docs/backend-overview.md`**

- Blok baris ±305-344 (deskripsi outbox flow): tambahkan kalimat pembuka `**Status: DINONAKTIFKAN (di-comment) sejak batch-upload-r2 — lihat docs/superpowers/specs/2026-07-10-batch-upload-r2-design.md.** Event historis kini dikirim batch worker tiap jam; webhook realtime lokal tidak berubah.` — isi lama biarkan (masih akurat sebagai dokumentasi kode yang di-comment).
- Tabel env baris ±379-381: hapus row `UPLOAD_HOUR` dan `DESTINATION_UPLOAD`; tambah row `UPLOAD_MINUTE` (menit tiap jam batch jalan), `UPLOAD_MAX_ITEMS_PER_TICK` (2000), `UPLOAD_RETENTION_DAYS` (7), `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` / `R2_PUBLIC_URL` (placeholder — kosong = no-op), `UPLOAD_API_URL` (base URL API cloud), `UPLOAD_API_SECRET` (WEBHOOK_SECRET API cloud).
- Tambah catatan operasional di bawah blok outbox: `outbox.db lama bisa berisi row pending sisa — inert (tidak ada pengirim); backfill batch meng-cover file yang sama via manifest, dan event_id idempoten mencegah dobel kalau outbox di-uncomment lagi.`

- [ ] **Step 3: Update `README.md` baris 31**

`→ OutboxRetryWorker (daemon thread)` → `→ BatchUploadWorker (hourly — R2 + API cloud; OutboxRetryWorker di-comment)`

- [ ] **Step 4: Commit**

```bash
git add docs/overview.md docs/backend-overview.md README.md
git commit -m "docs: sync arsitektur batch upload R2 (outbox dinonaktifkan)"
```

---

### Task 9: Verifikasi penuh vision + push + PR

**Files:** tidak ada file baru — verifikasi + git.

- [ ] **Step 1: Full test + lint**

```bash
pytest tests/unit/ -q
ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ src/palmgrade/license/ src/palmgrade/workers/batch_upload_worker.py
```

Expected: semua pass, ruff clean.

- [ ] **Step 2: Smoke test startup (opsional — butuh venv dgn torch; skip kalau tak tersedia)**

```bash
CAMERA_TYPE=photo CAMERA_PHOTO_PATH=<path foto apa pun> timeout 20 uvicorn palmgrade.main:app --app-dir src --port 8010; echo "exit=$?"
```

Expected: log berisi `Batch upload terjadwal tiap jam pada menit 00 (R2_BUCKET=<kosong — no-op>)`, dan TIDAK ada `OutboxRetryWorker started`. (exit 124 dari timeout = normal.)

- [ ] **Step 3: Push + PR ke staging**

```bash
git push -u origin feat/batch-upload-r2
gh pr create --base staging --title "feat: batch upload hourly teks+gambar ke R2 + DB cloud" --body "Implementasi spec docs/superpowers/specs/2026-07-10-batch-upload-r2-design.md.

- Manifest SQLite durable (WAL+FULL, tanpa retry cap/TTL) — tahan outage berapa pun
- Upload gambar → R2 (key deterministik) lalu POST teks → API cloud (uuid5 idempoten)
- Outbox realtime lama di-comment (penanda [DISABLED: batch-upload-r2]), rollback = uncomment
- Kanal webhook realtime lokal TIDAK disentuh
- Env baru R2_*/UPLOAD_* (placeholder), UPLOAD_HOUR & DESTINATION_UPLOAD dihapus
- Test: manifest/outage/crash/anti-duplikat — tanpa jaringan & kredensial"
```

Expected: PR terbuka, CI hijau.

---

### Task 10 (palmgrade-api): passthrough URL absolut di `resolveCaptureUrl`

**Files:**
- Modify: `src/utils/captureUrl.ts`
- Test: `tests/unit/utils/captureUrl.test.ts`

**Interfaces:**
- Produces: `resolveCaptureUrl` mengembalikan `imagePath` apa adanya kalau sudah URL absolut (`/^https?:\/\//i`) — BAHKAN saat `lineCode` null (row R2 tidak butuh line untuk resolve). Path relatif legacy: perilaku persis seperti sekarang.
- Checkpoint spec §4.5 (SUDAH diverifikasi dari kode `visionEventRequest.interface.ts:49-50`): `image_path` hanya `@IsString() @IsNotEmpty()` → URL absolut lolos validasi. **Tidak ada perubahan endpoint yang dibutuhkan.**

- [ ] **Step 1: Write failing tests** — tambahkan di dalam `describe` di `tests/unit/utils/captureUrl.test.ts`:

```ts
  it("passes through an absolute https URL unchanged (R2 rows)", () => {
    const url = "https://img.palmgrade.ai/M1/results/2026-07-10/a.webp";
    expect(resolveCaptureUrl(url, "line-1", "/api/v1")).toBe(url);
  });

  it("passes through absolute URLs even without a lineCode", () => {
    const url = "http://img.palmgrade.ai/M1/results/2026-07-10/a.webp";
    expect(resolveCaptureUrl(url, null, "/api/v1")).toBe(url);
  });
```

- [ ] **Step 2: Run, verify FAIL**

Run: `npx vitest run tests/unit/utils/captureUrl.test.ts`
Expected: 2 test baru FAIL (dapat `/api/v1/captures/...` atau `null`).

- [ ] **Step 3: Implement** — di `src/utils/captureUrl.ts`, sisipkan SEBELUM `if (!imagePath || !lineCode) return null;`:

```ts
  // Row baru (batch upload): image_path sudah URL R2 absolut — serve apa adanya.
  // Row lama (path relatif): tetap dirakit ke {apiPrefix}/captures/{lineCode}/...
  if (imagePath && /^https?:\/\//i.test(imagePath)) return imagePath;
```

Update juga docstring fungsi (tambah 1 kalimat): `Absolute URLs (R2 public bucket) are returned unchanged.`

- [ ] **Step 4: Run, verify PASS**

```bash
npx vitest run tests/unit/utils/captureUrl.test.ts   # 7 pass
npx tsc --noEmit
```

- [ ] **Step 5: Commit + push + PR**

```bash
git add src/utils/captureUrl.ts tests/unit/utils/captureUrl.test.ts
git commit -m "feat(captures): passthrough image_path URL absolut (R2) di resolveCaptureUrl"
git push -u origin feat/r2-capture-url
gh pr create --base staging --title "feat: passthrough URL R2 absolut di resolveCaptureUrl" --body "Pendamping PR batch-upload-r2 di palmgrade-vision (spec 2026-07-10).

- image_path berupa URL absolut (R2 public bucket) dikembalikan apa adanya
- Path relatif legacy tetap dirakit seperti sebelumnya (backward-compatible)
- Verifikasi §4.5: VisionEventRequest.image_path = @IsString @IsNotEmpty → URL absolut lolos, endpoint tidak perlu diubah"
```

Expected: PR terbuka, CI hijau.

---

## Acceptance Criteria Mapping (spec §10)

| Kriteria spec | Dibuktikan oleh |
|---|---|
| Outage → semua done, key unik, nol duplikat | `test_recovery_uploads_all_unique`, `test_already_processed_counts_as_done` |
| Kill mid-batch → resume tanpa dobel | `test_crash_mid_batch_no_partial_write`, `test_wal_survives_reopen`, `test_requeue_preserves_state` |
| JSON korup → poisoned, file utuh, item lain jalan | `test_scan_survives_corrupt_json`, `test_http_422_poisons_and_continues`, `test_missing_image_file_poisons_json_kept` |
| Backlog > limit terkuras bertahap, tertua dulu | `test_oldest_first_and_limit` |
| Kanal realtime lokal utuh | Task 2 tidak menyentuh `event_queue` (diff review) + smoke test Task 9 |
| File tak terhapus sebelum done+retensi; poisoned tak pernah dihapus | `test_retention_deletes_done_after_cutoff` + retensi hanya query status `done` (`get_expired_done`) |
| `resolveCaptureUrl` 2 kasus | Task 10 Step 1 tests |
| CI hijau tanpa jaringan/kredensial | Semua client di-inject & di-fake; Task 9 Step 1 |
