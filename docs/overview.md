# autograde — Detailed Overview

> **The DETAIL doc** (read on-demand). The lean map is `../CLAUDE.md`.
> Even deeper, specialized docs: `architecture.md` (layer boundaries), `backend-overview.md`
> (full endpoint/env tables), `SETUP.md` (from-zero prod setup).

---

## 1. Layered Architecture — per-layer do/don't

`route → controller → service → repository / pipeline / integration`. Each layer has a strict boundary.

| Layer | Folder | May | Must NOT |
|---|---|---|---|
| Routes | `routes/` | path, method, `Depends()`, return type | any logic, file/model/queue access |
| Controllers | `controllers/` | take request, call **one** service, raise `HTTPException` | touch repository, queue, or YOLO |
| Services | `services/` | combine repo + pipeline + integration; run business flow | SQL, vendor SDK detail, direct file I/O |
| Repositories | `repositories/` | read/write JSON & JPEG via `LocalFileStorage` | PASS/FAIL rules, HTTP, inference, voting |
| Pipelines | `pipelines/` | YOLO inference, frame processing, draw boxes | HTTP, file save, business rules, queue |
| Domain | `domain/` | pure functions/dataclasses, zero I/O | import `cv2`/`httpx`/`fastapi`, read/write files |
| Workers | `workers/` | background loop, queue, lock, `RuntimeState` | return HTTP, save to file directly (delegate to repo) |

---

## 2. Worker & Runtime-State Model

`main.py` `lifespan()` starts (all daemon unless noted):

| Worker | Kind | Responsibility |
|---|---|---|
| `FrameCaptureWorker` | thread | grab frame from camera (under `state.lock`) → `state.latest_raw_frame` + `frame_queue`. Auto-reconnects with `device_index`. |
| `FrameProcessingWorker` | thread | YOLO inference from `frame_queue`; sets `state.last_yolo_frame` + `state.last_yolo_results` (paired); janjang menyentuh garis capture → pulse PLC + `event_queue` + serahkan `SaveJob`, lalu **lanjut**. Sejak 2026-09-18 **tidak menulis ke disk maupun outbox sendiri** |
| `CaptureSaveWorker` | thread | penulis bukti: encode WebP bbox+clean+thumb, sidecar JSON, dan satu baris `outbox.add_event()`. Antrean 8 dalam, drop yang terbaru + `logger.error` kalau penuh (`capture_save_dropped`). Ikut diawasi watchdog; antreannya dikuras saat shutdown sebelum kamera dilepas |
| `DisplayWorker` | thread | the **only** writer of `state.latest_frame`: draw boxes → resize → draw ROI → JPEG encode → `frame_condition.notify_all()`. Runs at `STREAM_FPS` (default 12). |
| `OutboxRetryWorker` | thread | kirim isi `outbox.db` ke API **lokal** (`BACKEND_URL`), poll 1 detik — jalur realtime operator, hidup walau internet mati. Batch upload ke cloud jalan terpisah. |
| `PlcWorker` | thread | **hanya kalau `PLC_ENABLED=true`** (default mati → nol thread tambahan di cloud & PC dev). Satu-satunya thread yang menyentuh socket ke PLC (MC Protocol ke CPU Mitsubishi; Modbus ke coupler ODOT kalau `PLC_PROTOCOL=modbus`): kuras antrean keputusan → pulse bit OK/NG, kedipkan heartbeat, baca blok input, tulis bit ERROR. Bangun tiap `PLC_POLL_MS` (default 200ms) **selamanya**. Sinyal telat = buah salah yang tersortir, jadi kebijakannya **buang dan hitung, jangan pernah tunda**. |
| `EventBroadcastWorker` | asyncio task | drain `event_queue` → push to `/ws/results` WebSocket clients |
| `_watchdog` | asyncio task | every **10s**, restart any dead worker thread |

`UploadScheduler` (APScheduler) menjalankan `BatchUploadWorker.run_batch_once` tiap jam (menit `UPLOAD_MINUTE`): scan `artifacts/results/` → manifest SQLite → upload gambar ke R2 → POST teks ke API cloud. `R2_BUCKET` kosong = no-op.

**Queues / sync primitives** (`workers/runtime_state.py`):
- `frame_queue` — raw frames, bounded (drop-old).
- `event_queue` — outgoing events for WebSocket, **drop-old** (`get_nowait()` + `put_nowait()`).
- `frame_condition` (`threading.Condition`) — MJPEG broadcast (multi-viewer; each viewer `wait(timeout=0.5)`).
- `state.lock` — guards physical camera access.
- `current_truck_id`, `current_assignment_id` — set by `POST /internal/assignment`.
- `last_successful_api_push`, `worker_threads`, `websocket_clients`, `main_loop`.

---

## 3. Detection Flow (single-trigger, not voting)

Model `best.pt` detects 4 classes in one pass: `Ripe`, `Unripe`, `JK`
(janjang kosong) and `TP` (tangkai panjang).

The class is NOT the verdict. `Ripe` → ACC; `Unripe` and `JK` → REJ; `TP` is not
a bunch at all and gets no verdict — it rides beside a bunch as `tp_confidence`.
The mapping lives in one place, `domain/grade_class.py`, because two things
downstream stayed binary on purpose: the PLC owns exactly two coils (OK and NG —
a third category would be wiring, not code), and AutoERP books three AI criteria
(`Mentah` / `Tangkai Panjang` / `Matang`) under a frozen contract. So a row
carries both: `ripeness_status` is the verdict that fires pistons and is paid on,
`grade_class` is the detail the console shows.

⚠️ **`JK` is deliberately not sent to AutoERP.** There is no criterion for it
there, and both near-misses misreport: `Sampah` is *weighed*, not seen by a
camera, and folding JK into `Mentah` overstates the unripe share the supplier is
docked for. Its count stays on the edge until a contract change is agreed.

```
each YOLO frame (ByteTrack assigns track_id per object):
  pre-scan: kumpulkan kotak semua TP + semua janjang di frame ini
            (TP butuh track_id sah dan belum dipakai — `kandidat_tp_sah`)

  label in ("Ripe","Unripe","JK") AND center inside ROI AND track not processed
  AND kotaknya MENYENTUH garis capture:
      area = (x2-x1)*(y2-y1)
      if area < MINIMUM_SIZE (460000) OR >1 fruit in ROI this frame → force "rej"
      submit_grading() → pulse PLC          # seketika, tidak boleh ditunda
      tetapkan timestamp                     # sumber event_id uuid5 — WAJIB di sini
      tp = tp_untuk_janjang(...)             # TP TERDEKAT, dan hanya kalau janjang
                                             # ini yang terdekat di antara semua
      push event to event_queue (drop-old) for WebSocket
      capture_saver.submit(SaveJob(...))     # ← encode + disk + outbox pindah ke sini
      mark track processed                   # sesudah DISERAHKAN, bukan sesudah ditulis

  CaptureSaveWorker (thread lain):
      write_pair(): WebP bbox + clean + thumb (quality 65 / 60)
      {ts}_auto_ripeness.json — SATU sidecar per janjang, TP ikut di dalamnya
      outbox.add_event(build_event_payload(...))  # → API lokal via OutboxRetryWorker
      # Pengiriman ke CLOUD terpisah: BatchUploadWorker men-scan file hasil save
      # di atas (lihat §4) dan menghitung ulang uuid5 yang sama dari machine_id +
      # timestamp nama file — dua jalur, satu event_id, jadi tidak pernah dobel.
```

- `ResultRepository.list_today_results()` merges `_ripeness.json` + `_tp.json` per base_name.
- Manual reject (`CaptureService.capture_manual_reject`): full-frame capture marked `rej`,
  saved as `{ts}_manual_ripeness.json` (suffix `_ripeness` is required so it isn't read as legacy),
  lalu ikut ter-scan `BatchUploadWorker` seperti hasil auto (truck may be `null`).
  `bounding_box` = full frame `{0,0,width,height}`.

**ROI box:** `ROI_X1/Y1/X2/Y2` in **stream space** (`STREAM_WIDTH×STREAM_HEIGHT`, default 1280×720),
NOT sensor space — operators calibrate from what they see in the browser. Center `(cx,cy)` must be
inside the box. `0,0,0,0` = full frame (X2=0→stream width, Y2=0→stream height); require `X2>X1` & `Y2>Y1`.
TP is exempt from the ROI check. `draw_roi()` runs in `DisplayWorker` **after** resize.

**Garis capture (biru, bertanda `CAPTURE`)** — sejak 2026-09-18 menggantikan aturan lama "titik
tengah masuk kotak ROI" sebagai penentu KAPAN janjang difoto. Dua hal yang sengaja dipisah:

| | Menjawab | Aturan |
|---|---|---|
| ROI | di mana | titik tengah janjang di dalam kotak = wilayah conveyor |
| Garis capture | kapan | kotak janjang **menyentuh** garis (`domain/garis_capture`) |

Aturan lama memfoto janjang saat **separuhnya** sudah lewat, dan dengan `ROI_*` bawaan `0,0,0,0`
(= seluruh layar) itu berarti begitu terdeteksi di mana pun — termasuk di pinggir frame saat
janjangnya belum utuh. Itu keluhan "capture terlalu cepat" dari PC Lampung.

Disetel dari **layar support konsol**, satu angka untuk semua line, berlaku tanpa restart lewat
`/internal/setelan` — jalur yang sama persis dengan `CONF_THRESHOLD` dan `MINIMUM_SIZE`
(`domain/setelan_grading`, `RuntimeState.garis_capture_override`). `GARIS_CAPTURE` di `.env` cuma
nilai awal. **`0` = tidak ada garis**, dan itu perilaku sebelum fitur ini ada — satu-satunya cara
PKS yang belum menyetel tidak kehilangan janjang, jadi batas bawahnya inklusif (`BAWAH_INKLUSIF`),
beda dari dua setelan lain yang `0`-nya justru mematikan grading diam-diam.

⚠️ Angkanya ruang **stream**, diskalakan ke ruang sensor saat menyaring (`skala_garis_ke_frame`).
Melewatkan penskalaan itu bug yang sudah pernah terjadi di ROI (`bdcb300`).
⚠️ Pemicunya **perpotongan**, bukan sentuhan persis: garis dievaluasi sekali per frame, dan pada
8-20 fps janjang bisa melompati garis di antara dua frame — menuntut sentuhan persis membuat
janjang cepat tidak pernah difoto, hilang tanpa satu pun pesan.
`TP` dikecualikan dari garis, sama seperti dari ROI.

**Pasangan TP ↔ janjang** (2026-09-18). Janjang difoto **apa adanya** begitu menyentuh garis,
ada TP atau tidak — tanpa penundaan. TP yang dipakai adalah yang pusatnya **paling dekat** dan
masih dalam `_JANGKAUAN_TP` × setengah diagonal janjang (`domain/garis_capture`), dikumpulkan
di pra-pindai supaya urutan kotak dalam satu frame tidak menentukan hasil.

| Urutan | Alur LAMA (`_last_tp`) | Sekarang |
|---|---|---|
| TP terlihat, lalu janjangnya menyentuh garis | ikut, kebetulan urutannya cocok | ikut, karena jaraknya dekat |
| TP milik janjang A, janjang B lewat garis dulu | **salah**: TP menempel ke B | tidak ikut ke B |
| Janjang difoto, TP-nya baru terlihat | **salah**: menempel ke janjang berikutnya | tidak ikut, dihitung `tp_telat` |

Ambangnya relatif, bukan piksel tetap: janjang di dekat kamera jauh lebih besar daripada yang di
ujung frame, jadi satu angka piksel akan benar cuma di satu jarak kamera. Setengah diagonal
dipakai supaya janjang tegak dan janjang rebah menjangkau sama jauhnya.
⚠️ Yang dipakai **jarak**, bukan irisan kotak: TP bisa terpisah dari kotak janjangnya (jawaban
operator 2026-09-18), jadi menuntut irisan akan membuang tangkai yang sah.
⚠️ Yang menang **yang terdekat**, bukan yang paling yakin: confidence mengukur seberapa yakin
model itu TP, bukan seberapa mungkin TP itu milik janjang ini.
⚠️ **Terdekat di antara SEMUA janjang di frame**, bukan sekadar dalam ambangnya sendiri
(`janjang_lain`). Dua janjang berdempetan — 450x450 px berjarak 500 px pada sensor 2448x2048 —
sama-sama berjangkauan 477 px, jadi satu tangkai di antara keduanya masuk jangkauan dua-duanya
dan pemenangnya tinggal urutan pemrosesan, yang tidak dijamin. Janjang yang sudah difoto ikut
jadi saingan, supaya tangkai milik janjang yang baru selesai tidak pindah ke tetangganya.
⚠️ TP tepat di **tengah sela** dua janjang memang ambigu secara geometri; aturan apa pun cuma
menebak di situ, dan itu sengaja tidak diuji seolah punya jawaban benar.
`tp_telat` dihitung dari `_janjang_difoto` (catatan sendiri, umur 300 detik), **bukan**
`track_history` — tabel itu dibuang 10 frame sesudah janjangnya hilang dari pandangan, jadi TP
yang muncul sesudahnya tidak pernah terhitung dan angkanya diam-diam terlalu kecil.

**Arah conveyor** (`sumbu_garis`, disetel di layar yang sama sejak 2026-09-18):

| Sumbu | Conveyor | Garis | Angkanya |
|---|---|---|---|
| `tegak` (bawaan) | mendatar, buah lewat kiri↔kanan | vertikal | px dari **kiri** |
| `mendatar` | menurun, buah lewat atas↔bawah | horizontal | px dari **atas** |

Arah gerak DI DALAM satu sumbu tidak perlu disetel: pemicunya perpotongan, berlaku dari sisi
mana pun, jadi conveyor yang membalik arah tetap jalan tanpa satu pun perubahan.
⚠️ Sumbu mendatar diskalakan dengan **tinggi** frame, bukan lebar (`skala_garis`) — frame
2448x2048 tidak persegi, jadi memakai lebar membuat garis meleset ~19% tanpa satu pun error.
⚠️ Sumbu yang tidak dikenal **tidak melempar** di jalur deteksi (jatuh ke `tegak`): nilainya
bisa datang dari konsol versi lain, dan satu string asing tidak boleh menghentikan grading.
Yang menolak nilai aneh adalah jalur SIMPAN, di gerbang, sebelum sampai ke tiga line.

**Label janjang tanpa angka confidence** (2026-09-18, permintaan operator). Angkanya keyakinan
model, bukan mutu buah, dan dari beberapa meter "54%" terbaca seperti "54% matang"; ambangnya
sudah diputuskan `CONF_THRESHOLD`, jadi apa pun yang tergambar sudah lolos ambang itu.
`viewer.html` membuangnya lebih dulu (`abd8f17`). Nilainya **tetap** disimpan di sidecar dan
dikirim ke API — yang dibuang tampilannya, bukan datanya.

**DisplayWorker draw order:** `draw_boxes()` (on `last_yolo_frame`) → `cv2.resize()` → `draw_roi()`
(yang juga menggambar **garis capture** biru bertanda `CAPTURE`, sesudah resize, di ruang stream).
Render boxes over `last_yolo_frame` (paired with results), **never** over `latest_raw_frame` — on CPU,
inference can take 0.5–2s and the conveyor moves, so boxes would land in the wrong place. Fallback to
`latest_raw_frame` only before the first YOLO run.

---

## 4. Batch Upload Delivery (hourly, at-least-once)

> Jalur ke **cloud**, berdampingan dengan outbox (spec batch-upload-r2, 2026-07-10).
> Antriannya **file di disk**, bukan `outbox.db`: `_scan()` menemukan `results/{date}/*.json`
> dan menyimpan state per-item di `UploadManifest`. Outbox mengurus jalur **lokal** (§3) dan
> tidak dibaca di sini; `event_id` keduanya identik sehingga sebuah event yang lewat dua-duanya
> dibalas `already_processed` di API kedua.

```
FrameProcessingWorker / CaptureService
  → simpan WebP + {ts}_*_ripeness.json ke artifacts/results/{date}/    # ini antriannya
      ↓  (UploadScheduler: APScheduler cron, tiap jam pada menit UPLOAD_MINUTE)
BatchUploadWorker.run_batch_once()
  1. _scan()      glob results/**/*_ripeness.json → UploadManifest.upsert_item() (idempotent)
  2. claim        SELECT WHERE status IN ('pending','image_uploaded') AND next_retry_at <= now
                  ORDER BY discovered_at ASC   LIMIT UPLOAD_MAX_ITEMS_PER_TICK (2000)
  3. PUT gambar   → Cloudflare R2 (boto3)          → mark_image_uploaded()
  4. POST teks    → {upload_events_url}             → mark_done()
                    header x-webhook-secret: UPLOAD_API_SECRET
  5. _retention() hapus WebP+JSON yg `done` & lewat UPLOAD_RETENTION_DAYS (default 7)
```

- **Target POST = API CLOUD**, bukan API lokal: `upload_events_url` =
  `{UPLOAD_API_URL}{backend_api_ver}/internal/vision/events`, secret-nya `UPLOAD_API_SECRET`.
  `canonical_events_url` (`BACKEND_URL`, webhook realtime ke API lokal) **tidak dipakai worker ini**.
- **`R2_BUCKET` kosong = worker no-op** (saklar off). Bukan error — cuma `logger.warning` **sekali**
  (`_warned_noop`), jadi gampang terlewat di log yang sudah jalan lama. Kalau event tidak pernah
  sampai cloud, cek variabel ini duluan.
- Sukses kalau API balas `200/201` **atau** body memuat `already_processed`.
- Error handling per item (yang bikin satu item busuk tidak menyandera batch):
  | Kondisi | Exception | Efek |
  |---|---|---|
  | HTTP 400/422, meta cacat, file gambar hilang | `_PoisonError` | `mark_poisoned` + **continue**. File **tidak** dihapus — ditinggal untuk diperiksa manual |
  | HTTP 404 (truck belum ada di DB cloud) | `_RequeueError(batch_fatal=False)` | requeue + **continue** — antrian `ORDER BY discovered_at ASC`, jadi tanpa ini satu item lama bisa head-of-line starve seluruh batch |
  | HTTP 401/403/5xx, jaringan mati | `_RequeueError` (default `batch_fatal=True`) | requeue + **break batch** — percuma lanjut kalau endpoint/kredensialnya yang bermasalah |
- Backoff: base **5s**, eksponensial sampai cap **600s** (`upload_manifest.py`). **TANPA retry cap
  dan TANPA TTL** — beda kontrak dari outbox lama yang punya dead-letter setelah 50 retry. Item
  menunggu di disk selamanya sampai terkirim (syarat "tahan outage berapa lama pun").
- Tahan restart karena **file-nya ada di disk**; manifest hanya menyimpan progres.
  SQLite durability eksplisit: **`PRAGMA journal_mode=WAL` + `synchronous=FULL`** — commit di-fsync,
  progres yang tercatat selamat dari mati listrik (write rate rendah, biaya fsync ringan).
- `event_id`: uuid5 deterministik dari `machine_id:timestamp` untuk **auto maupun manual**
  (formula tunggal di `domain/vision_event.py`, dipakai jalur outbox juga) → item yang di-upload
  ulang, atau event yang sudah lewat jalur realtime, dibalas `already_processed` → tidak dobel.
- `state/upload_manifest.db` sengaja **sibling** `artifacts/`, di luar mount statis `/captures`
  (`Settings.state_dir`) supaya DB operasional tidak ikut ter-serve sebagai file publik.
- ⚠️ Progres batch **tidak ter-expose** di endpoint mana pun. `outbox_pending`/`outbox_failed` di
  `/health/detail` mengukur jalur realtime ke API lokal, **bukan** backlog upload cloud.
  Untuk backlog sungguhan: query `state/upload_manifest.db` atau baca log worker.

**Event payload (field names exact):**
```json
{
  "event_id": "uuid (auto: uuid5 deterministik, manual: uuid4)",
  "machine_id": "uuid",
  "assignment_id": "uuid-or-null",
  "truck_id": "uuid-or-null",
  "timestamp": "ISO-8601 UTC-aware (+00:00)",
  "image_path": "captures/results/{date}/{HHMMSS}_{plat}_{assign8}/bbox/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp",
  "prediction": "Acc | Rej",
  "ripeness_status": "ACC | REJ",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS | null",
  "tp_confidence": 0.88,
  "capture_type": "auto | manual",
  "bounding_box": { "x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100 }
}
```
Contracts: `ripeness_status` UPPERCASE; `prediction` required; `tp_status` `"PASS"` or `null`
(never `"TP"`); `event_id` is the api idempotency key; `assignment_id` from `state.current_assignment_id`.

---

## 5. Integration Contract (cross-checked vs palmgrade-api code)

**vision → api**
- `POST {BACKEND_URL}{BACKEND_API_VER}/internal/vision/events`, header `x-webhook-secret`
  (`webhook.middleware.ts` checks equality with `process.env.WEBHOOK_SECRET`).
- api validates `VisionEventRequest` DTO (`@IsIn` on prediction/ripeness/tp/capture_type, `@IsUUID`
  on machine_id). `truck_id`/`bounding_box` optional on the api side.

**api → vision** (`gradingConsole.service.impl.ts`), header `x-internal-secret`:
- `POST {vision_base_url}/internal/assignment` `{machine_id, assignment_id, truck_id, assigned_at}`
  → `AssignmentSyncRequest` → sets `state.current_truck_id` + `state.current_assignment_id`.
- `POST {vision_base_url}/internal/manual-reject` `{machine_id, assignment_id, requested_by, requested_at}`
  → `ManualRejectCommandRequest` → `capture_manual_reject()` via executor.
- `GET {vision_base_url}/health` for the line health check.

**Shared:** one `WEBHOOK_SECRET` both directions untuk jalur **API lokal** (`BACKEND_URL`). Jalur
**batch ke cloud** pakai pasangan sendiri: `UPLOAD_API_URL` + `UPLOAD_API_SECRET` (= `WEBHOOK_SECRET`
API cloud) — jangan tertukar. `LINE_1/2/3_MACHINE_ID` = the three `machines.id`
UUIDs (docker-compose falls back to seed UUIDs if unset). api maps `machine_id → machines.line_code`
to serve images at `/api/v1/captures/<line_code>/...`. api SSE events after ingest:
`inspection_saved`, `new_quality_control`, `assignment_changed`.

> Day-boundary note: **event** `timestamp` sekarang UTC-aware (`datetime.now(timezone.utc)`) — api
> parse dengan benar tanpa asumsi TZ. File JSON di disk masih pakai naive local time (nama folder
> tanggal + `results_today` mengikuti jam lokal container).

---

## 6. Invariants — full rationale (don't change without discussion)

0. **Disk before API.** Never POST events directly from a detection worker. `CaptureService` dan
   `FrameProcessingWorker` menulis file (WebP + `_ripeness.json`) ke `results/{date}/` lalu satu
   baris ke `outbox.db` — **tidak pernah** memanggil HTTP sendiri. Yang bicara ke jaringan cuma
   `OutboxRetryWorker` (API lokal, §3) dan `BatchUploadWorker` (R2 + cloud, §4). Deteksi **tanpa
   truck aktif tetap dikirim** (`truck_id: null`) di kedua jalur: `_scan()` tidak memfilter truck,
   dan outbox juga tidak — API punya `TruckResolver.resolveOrStub`.
1. **`_processed_objects`.** After saving a track_id, add it so the next iteration `continue`s
   (single-trigger). Never `discard()` an active track. `run_once` trims only IDs that are gone from
   `track_history` **and** stale >300s (`_processed_times`) — pure memory control, can't re-trigger
   (the fruit left the frame long ago).
   **Ordering:** `processed` di-set **SETELAH janjang diserahkan ke `CaptureSaveWorker`** — sejak
   2026-09-18 itu titik yang tidak boleh diulang, menggantikan "setelah file tersimpan" yang berlaku
   selama penulisan masih sinkron. Yang dijaga tidak berubah: nama file (dan `event_id` uuid5
   `machine_id:timestamp` yang dihitung `BatchUploadWorker` dari nama itu) ditetapkan **di jalur
   deteksi**, sebelum serah-terima, jadi idempotensi dipegang oleh nama, bukan oleh urutan tulis.
   Track tanpa truck aktif tetap ditandai processed supaya tidak re-trigger.
   ⚠️ Konsekuensi yang dibeli sadar: kalau proses mati di antara serah-terima dan penulisan, janjang
   itu hilang (tidak ada retry — track sudah `processed`). Lifespan karena itu **menguras antrean
   dulu** saat shutdown. Jendelanya ratusan milidetik, dan harganya adalah hilangnya lag ~590 ms per
   janjang yang sebelumnya membuang ~12 frame kamera dan memutus jejak ByteTrack.
2. **`state.lock`** around all physical camera access (`FrameCaptureWorker.run_once` +
   `capture_manual_reject`) — concurrent Hikrobot SDK access can crash.
3. **MJPEG via `threading.Condition`**, not `result_queue` — the old queue pattern served only one
   viewer. `event_queue` stays drop-old.
4. **DI** (`core/dependencies.py`): `@lru_cache` singletons; `get_outbox_store()` may cache (SQLite +
   `threading.Lock`, fresh connection per op). **NOT** cached: `get_capture_service()` /
   `get_health_service()` — they call `get_camera()` which raises before startup; caching would freeze
   `_camera = None`.
5. **`repo_root = parents[3]`** — `src/palmgrade/core/config.py` → 3 levels up = `/app` in Docker.
6. **`lifespan`** (not deprecated `@app.on_event`); scheduler + camera disconnect are lifespan locals.
7. **MJPEG written only by `DisplayWorker`** — two writers to `state.latest_frame` cause flicker.
   It renders `last_yolo_frame` (paired with `last_yolo_results`), runs at `STREAM_FPS` (default 12),
   decoupled from `CAMERA_FPS` (default 15).
8. **Manual capture JSON** uses suffix `_ripeness` so `list_today_results()` reads it correctly.
9. **Every worker `run_loop` wraps `run_once` in `try/except`** + `logger.exception` — without it the
   thread dies silently and the watchdog restarts without a stack trace.
10. **`FrameCaptureWorker` needs `device_index`** — reconnect calls `camera.connect(index=...)`; a bare
    `connect()` (default 0) makes line-2/3 reconnect to the wrong camera.
11. **`cv2.imwrite` failure raises `OSError`** in `LocalFileStorage.write_image` — a silent warning
    would leave orphaned JSON pointing at a missing image — dan karena JSON itulah yang di-scan
    `BatchUploadWorker`, item-nya berakhir `poisoned` saat upload. Auto path: caught by
    `run_loop` (skip 1 frame). Manual path: propagates → 500 to operator.

---

## 7. Camera Abstraction

`CAMERA_TYPE` (default `hikrobot`) selects the implementation in `lifespan()` — no code edit to switch:

| `CAMERA_TYPE` | Class | When |
|---|---|---|
| `hikrobot` | `HikrobotCamera` | production (needs MVS SDK + GigE hardware) |
| `opencv` | `OpenCVCamera` | dev — webcam (`CAMERA_DEVICE_INDEX`) or video file (`CAMERA_VIDEO_PATH`) |
| `photo` | `PhotoCamera` | testing — single image looped (`CAMERA_PHOTO_PATH`) |

`CameraSource` ABC: `connect(index)`, `grab_frame() -> np.ndarray | None`, `disconnect()`.

**Graceful startup:** `main.py` wraps `camera.connect()` in try/except for hikrobot. If absent, the app
still runs (`health.detail.camera_connected=false`), `FrameCaptureWorker` retries ~every 30s, and
`grab_frame()` returns `None` (no crash). Plug the camera in (MVS closed) → `connected=true`, no restart.

---

## 8. Docker / SDK / GPU Internals

**Docker-only** (no host venv). Volumes: `.:/app` (hot-reload), anonymous `/app/.venv` (shadow host),
`./artifacts/line-N:/app/artifacts`, `./models:/app/models:ro`. `entrypoint.sh` lives at `/entrypoint.sh`
(outside `/app`, so the `.:/app` mount can't shadow it). `load_dotenv(override=False)` in `main.py`;
docker-compose `environment:` always wins over host `.env`.

**Shared image:** only `ripe-line-1` has `build:` + `image: palmgrade-vision:latest`; line-2/3 reuse the
image (build once, ~20GB saved). Don't re-add `build:` to line-2/3.

**`network_mode: host`** — required for GigE Vision: `MV_CC_EnumDevices()` uses UDP broadcast that the
Docker bridge blocks. Consequence: `ports:`/`extra_hosts:` are ignored — each container binds its own
`APP_PORT` (8001/8002/8003).

**GPU passthrough** (`deploy.resources.reservations.devices: nvidia/all/[gpu]`) — needs NVIDIA Container
Toolkit on host (add the NVIDIA apt repo first; `apt install nvidia-container-toolkit` alone isn't enough
— see `SETUP.md`). Without it YOLO runs on CPU (~10× slower).

**TensorRT engine:** `make build-engine` (one-shot container, `scripts/build_engine.py`) export
`.pt` → engine FP16 di `engines/<model>.sm<cc>.engine` — **hardware-locked** per compute capability
(`Settings.engine_path_for_gpu`), tidak di-commit, **tidak di-bake ke image**, auto-skip kalau sudah ada.
Runtime (`pipelines/model_registry.py`) auto-pakai engine dan **fallback ke `.pt`** kalau tidak ada atau
tidak cocok — jadi build engine yang gagal bukan outage, cuma balik ke kecepatan lama.
Butuh ~5–15 mnt sekali per GPU, **tidak butuh kamera**.

⚠️ Di PC yang menjalankan **image dari GHCR** (bukan build lokal), `make build-engine` TIDAK bisa dipakai
apa adanya: target itu memakai `docker-compose.yml` polos yang `image: palmgrade-vision:latest` + punya
`build:`, jadi Docker akan mem-build ulang dari source alih-alih memakai image yang sudah di-pull.
Di sana jalankan `docker compose run` dengan file override yang sama seperti stack-nya, sehingga
`${PALMGRADE_VISION_IMAGE}` dan mount `./engines:/app/engines` ikut terpakai — tanpa mount itu engine
ditulis ke dalam container sekali pakai dan hilang begitu container keluar.

PENTING: TensorRT wajib di-install dari index NVIDIA (`https://pypi.nvidia.com`, wheel binary) —
PyPI publik cuma punya source stub yang bikin pip hang di "Preparing metadata".

**SDK flow in `make up`:** `mkdir -p sdk/lib64` → `cp -r /opt/MVS/lib/64/. sdk/lib64/` +
`cp -r /opt/MVS/Samples/64/Python/MvImport sdk/MvImport` → Dockerfile `COPY sdk/ /tmp/sdk/` → copy into
`/opt/MVS/lib/64` + site-packages → `ENV MVCAM_COMMON_RUNENV=/opt/MVS/lib`. The **whole** `lib64` is
needed (not just `libMvCameraControl.so`): `MV_CC_EnumDevices()` dynamically loads the transport layer
(`MvProducerGEV.cti`, `libMVGigEVisionSDK.so`); missing them → `MV_E_LOAD_LIBRARY (0x8000000C)`.

**Production deployment checklist (new PC — order matters):**
1. Install NVIDIA Container Toolkit → verify `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi`.
2. Install Hikrobot MVS SDK at `/opt/MVS/` (`SETUP.md § 3`).
3. `mkdir -p models/release` + copy `best.pt`.
4. `.env`: `LINE_1/2/3_MACHINE_ID` (real UUIDs), `BACKEND_URL`, `WEBHOOK_SECRET`, `CAMERA_TYPE=hikrobot`, `CAMERA_FPS=15` (samakan dengan Acquisition Frame Rate kamera — `SETUP.md § 6.3`, alasan bandwidth 3 kamera).
5. `make up`.
6. Verify `curl :8001/health/detail | grep -E "gpu_available|camera_connected"`.

**`requirements.txt`:** never replace with `pip freeze` from elsewhere. Only what the source imports:
`fastapi`, `uvicorn[standard]`, `python-multipart`, `python-dotenv`, `ultralytics`, `numpy`,
`opencv-python`, `httpx`, `pydantic`, `apscheduler`, `aiosqlite`, `cryptography`, `psutil`
(torch/torchvision are installed separately in the Dockerfile per `TORCH_VARIANT`).

---

## 9. Artifact Layout

```
artifacts/line-N/   (host) ↔ /app/artifacts (container)
  results/{YYYY-MM-DD}/                        # tanggal = UTC
    {ts}_auto_ripeness.json                        # sidecar — DATAR di sini, wajib
    {ts}_manual_ripeness.json                        # manual reject
    {HHMMSS}_{plat}_{assign8}/                       # satu folder per kunjungan truk
      bbox/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp      # bergambar kotak → image_path, naik R2
      clean/{acc|rej}/{ts}_auto.webp                 # polos → latih model, TIDAK diupload
    _belum-assign/                                   # ter-grading sebelum truk dipasang
  outbox.db                 # SQLite — antrean realtime ke API lokal (OutboxRetryWorker)

state/line-N/   (host) ↔ /app/state (container)   # SIBLING artifacts/, DI LUAR mount /captures
  upload_manifest.db        # progres BatchUploadWorker (WAL + synchronous=FULL)
```
⚠️ `results/` **bukan arsip permanen**: `_retention()` menghapus WebP + JSON yang `done` dan lewat
`UPLOAD_RETENTION_DAYS` (default 7) — setelah itu satu-satunya salinan gambar ada di R2. Item
`poisoned` sengaja tidak dihapus.
Gambar disimpan **WebP quality 65** (`JPEG_QUALITY_SAVE` di `core/constants.py` — nama konstanta
legacy, berlaku untuk WebP juga; `LocalFileStorage.write_image` pilih codec dari ekstensi file).
⚠️ **Sidecar JSON tidak pernah ikut pindah ke subfolder.** `_scan()` mencarinya dengan
`glob("*/*_ripeness.json")` — kedalaman dipatok dua, jadi sidecar yang lebih dalam tidak akan
pernah ketemu dan upload cloud berhenti **tanpa error apa pun**. Yang masuk subfolder cuma
gambar; letaknya dibaca dari `image_path` di dalam JSON.
⚠️ **Jam folder truk pakai `FACTORY_TZ`, nama berkas tetap UTC** — nama berkas menurunkan
`event_id` (uuid5) jadi tidak boleh bergeser, sementara nama folder satu-satunya yang dibaca
manusia. Dua zona dalam satu pohon disengaja: folder buat manusia, berkas buat mesin.
Aturan penamaan: `domain/capture_layout.py`. Penulis (satu-satunya, dipakai jalur auto maupun
manual): `services/capture_writer.py`.
⚠️ **Salinan `clean/` bikin pemakaian disk dua kali lipat** dan tidak punya baris manifest
sendiri — `_delete_item_files` menghapusnya lewat `clean_twin_of()`. Menambah gambar ketiga
tanpa ikut mendaftarkannya di situ = file yang tidak pernah dihapus siapa pun.
Served by FastAPI `StaticFiles` mount `/captures` → `artifacts/`, so `image_url`
`captures/results/{date}/{truk}/{bbox|clean}/{acc|rej}/{file}` resolves on the vision side. (The api re-serves per line under
`/api/v1/captures/<line_code>/...`.)

---

## 10. License Guard (optional, default off)

`LICENSE_ENABLED=true` adds `LicenseGuardMiddleware` (Ed25519 JWS verify of `LICENSE_TOKEN`) plus a
grading gate in `FrameProcessingWorker` — the HTTP middleware alone would leave the cameras running.
Added before CORS so a 403 still gets CORS headers. `LicenseManager` / `LicenseLocalRepo` /
`gate.py` live in `license/`. No network: the token comes from env, installed with
`palmgrade license <token>`.

**Effective-status state machine** (`LicenseManager._evaluate`, urutan cek):
`nbf` belum tiba → clock rollback (jam < lantai `max(max_seen_server_time, server_time)` − 300 s) → status `CANCEL`/`EXPIRED` →
`now > exp` (grace habis) → semua di atas ⇒ **EXPIRED**. Kalau `license_expires_at < now ≤ exp` ⇒
**GRACE** (`should_slow_response=True`, warning `LICENSE_EXPIRED_GRACE`). Online ⇒ pakai status token
apa adanya (`online-valid`); offline ⇒ valid hanya jika `now ≤ max_offline_until` **dan** status
`ACTIVE`/`TRIAL` (`offline-valid`), selain itu `offline-expired`. `max_offline_until = min(exp, iat +
max_offline_days·86400)`. Middleware hanya mem-block status **EXPIRED** (403); GRACE tetap lolos tapi
di-slow + header `x-license-warning-*`.

**Tests** (`tests/unit/test_license_manager.py`, `test_license_local_repo.py`, murni-logic, no network):
`_verify_jws` diuji dengan signature Ed25519 **asli** (tamper payload / kid-mismatch / foreign-key
harus ditolak), seluruh cabang `_evaluate` di atas, `_warning_for`, plus hash-chain + monotonic
`max_seen_server_time` di `LicenseLocalRepo`. Guard middleware sendiri tidak di-unit-test (butuh
FastAPI/Starlette — di luar filosofi CI murni-logic); logic-nya tipis dan seluruhnya bersandar pada
`get_effective_license()` yang sudah tercakup.

---

## 11. Konsol Operator Offline (`APP_MODE=console`, Fase 2)

Layar operator pindah dari `palmgrade-frontend` ke sini. Instance **ke-4 dari image yang sama**,
port **8000**, halaman di `http://localhost:8000/console`. Rencana & keputusan yang mengunci
bentuknya: runbook `2026-09-09-rencana-palmos-autograde.md` di repo `sawit` (§4, §6.1, §6.2,
§3.5b). Nama "PalmOS" di judulnya sudah pensiun — kotak ERP sekarang **AutoERP**.

**Kenapa modul ASGI-nya terpisah.** `main.py` menarik `core/dependencies.py` → pipelines →
ultralytics → torch, dan `core/constants.py` → cv2. Konsol tidak butuh satupun, jadi
`entrypoint.sh` memilih `src.palmgrade.console_main:app` saat `APP_MODE=console`. Efeknya bukan
sekadar hemat memori: satu line kamera yang mati (SDK hang, GPU hilang) tidak ikut menjatuhkan
layar operator, dan konsol boot dalam hitungan detik.

**Kenapa konsol tidak "membaca disknya sendiri".** docker-compose memberi tiap line
`artifacts/line-N` + `state/line-N` sendiri-sendiri, jadi instance ke-4 melihat pohon kosong.
Yang dipakai justru **kontrak event beku §5**: konsol membuka
`POST {BACKEND_API_VER}/internal/vision/events` dengan header `x-webhook-secret` — bentuk yang
persis sama dengan palmgrade-api — lalu tiap line cukup di-set `BACKEND_URL=http://localhost:8000`.
`OutboxRetryWorker` yang sudah ada menanggung retry, backoff, dan dedupe uuid5 saat konsol
restart. Nol perubahan di kode line, dan `palmgrade_api` lokal tidak perlu hidup lagi di PC
pabrik (7 → 4 container).

Gambar tetap milik line-nya: tiga `artifacts/line-N` di-mount **read-only** ke konsol dan
di-serve statis di `/captures/{line_code}/...` — bentuk URL yang sama dengan
`resolveCaptureUrl()` di palmgrade-api, supaya pindah antara konsol dan cloud tidak mengubah
apa yang dilihat operator.

**Batas hari kerja (§6.1).** Pabrik jalan ~20 jam/hari dan **lewat tengah malam**, jadi batas
hari UTC memotong satu shift jadi dua tanggal. `work_date` dihitung **saat ingest** dari
timestamp event itu sendiri (`domain/working_day.py`, zona `FACTORY_TZ`) lalu **disimpan
sebagai kolom** — bukan diturunkan ulang saat query, dan tidak pernah dari `now()`, `creation`,
atau nama folder. Event yang datang telat (outbox menyusul setelah listrik mati) tetap mendarat
di harinya sendiri. Timestamp cacat → 400 → outbox line menandainya `outbox_failed`, sengaja
terlihat gagal. Batasnya **kalender**, tanpa cutoff shift; karena kolomnya disimpan, mengubah
aturan itu nanti cuma menyentuh satu fungsi. `python:3.11-slim` butuh `tzdata` (sudah
ditambahkan) — tanpa itu `ZoneInfo` gagal dan tanggal diam-diam kembali ke UTC.

**Index, bukan pindai (§6.2).** Semua yang dibaca layar datang dari `state/console.db`
(`repositories/console_repository.py`) — konvensinya sama dengan `OutboxStore`: WAL,
`synchronous=FULL`, satu `threading.Lock`, `INSERT OR IGNORE` dengan kunci `event_id`. Layar
polling tiap 2 detik lewat `GET /api/console/state`; tidak ada `listdir` di jalur manapun.
Tabelnya: `inspections` (+ index `(work_date, line_code)` dan `(work_date, timestamp)`),
`trucks`, `suppliers`, `assignments`, `sync_state`.

**Master data & Sumber TBS (§3.5b).** `MasterDataWorker` menarik dari **AutoERP**, bukan lagi
dari cloud api: `GET {ERP_URL}/api/resource/Supplier` lalu `.../Truck`, REST bawaan Frappe
dengan `Authorization: token <key>:<secret>`, `filters=[["modified",">",kursor]]`,
`order_by=modified asc`, 500 baris per halaman. **Nol kode di sisi ERP.** `ERP_URL` kosong =
worker mati diam-diam dan konsol jalan dari salinan terakhir.

Tiap DocType punya **kursornya sendiri** (`erp_cursor_supplier`, `erp_cursor_truck`): supplier
dan truk berubah dengan laju yang jauh berbeda, dan satu kursor bersama akan terus menyeret
yang sepi melewati baris yang sudah dilihat. Jendela tumpang tindih 5 detik dipertahankan —
jam edge dan ERP tidak pernah sama persis. Kursor hanya maju kalau **semua** baris mendarat;
melewati satu baris yang gagal berarti pabrik terjebak di matriks setengah basi, termasuk
pencabutan truk yang sudah dilakukan ERP.

Identitas mengikuti "masing-masing menyimpan id lawannya": id truk lokal tetap uuid5 plat
ternormalisasi, dan **AutoERP menormalkan plat dengan aturan yang sama**, jadi truk hasil tarik
mendarat di baris yang sudah diketik operator, bukan baris kembar. `erp_name` (unik, boleh
NULL) menyimpan docname ERP dan **tidak pernah dihapus** oleh kiriman yang tidak membawanya
(`COALESCE`), supaya operator yang mengetik ulang plat tidak memutus tautannya.
Supplier `disabled` di ERP → `status='inactive'`, barisnya tetap ada untuk riwayat. `Truck` di
AutoERP **tidak punya** field `disabled`, jadi truk hasil tarik selalu `active`.

**Field yang diminta harus persis milik DocType.** Frappe membalas **417 `DataError: Field not
permitted in query`** untuk satu field yang tidak ada, dan seluruh request gagal. Daftarnya
disalin dari kontrak (`autoerp/docs/autograde-integration.md` §4.A), dan ERP palsu di
`test_erp_master_data.py` menolak field asing dengan cara yang sama.

**Sumber TBS mengikuti AutoERP, bukan ditebak edge.** AutoERP menurunkannya dari supplier saja
(`sumber_for_supplier`: punya supplier = External, tidak punya = Internal). `domain/ffb_source.py`
mencerminkan aturan itu: truk ber-supplier → External; truk yang **sudah ada di ERP** tanpa
supplier → Internal; truk tanpa supplier yang belum dilihat ERP → `—`. Kelima query store
memakai satu definisi (`_SOURCE_FACTS`), jadi truk yang sama tidak pernah berlabel beda di tab
lain. Grup supplier tetap disimpan **mentah** di `suppliers.source_group` — beda Plasma vs agen hidup
di situ. **Tidak ada boolean `is_internal` di manapun.**

**Per janjang tidak dikirim ke ERP.** Kontrak AutoERP §2 tegas: *"Not synced: per-bunch rows,
images"*. Janjang dan gambarnya tetap di edge sebagai bukti; AutoERP menerima **satu pesan per
kunjungan truk** (`upsert_visit`: timbang masuk → grading selesai → timbang keluar). Karena itu
`ErpPushWorker` (POST per janjang ke `palmos.interfaces.api.terima_event`, endpoint yang tidak
ada di autoerp) dihapus. Kolom `inspections.erp_state` dibiarkan tanpa dipakai supaya database
pabrik tidak perlu dibangun ulang; indeksnya dilepas lewat `_MIGRATE_SQL`.

`prediction`, `tp_status`, dan `tp_confidence` tetap disimpan **apa adanya** dari line: rekap
per kunjungan butuh `tp_confidence` untuk menghitung tangkai panjang (ACC dengan
`tp_confidence > 0.8`).

**Antrean kirim ke AutoERP (§5).** Yang dikirim ke ERP tidak pernah langsung dari jalur
permintaan: `POST /api/console/trucks` menaruh satu baris di `state/erp_outbox.db`, dan
`ErpOutboxWorker` yang mengirimkannya tiap 30 detik. Antreannya di **edge**, bukan cloud,
karena di situ mati lampu dan internet putusnya.

Kuncinya `(kind, key)` dengan `key` = kunci alami yang dicocokkan AutoERP (plat ternormalisasi
untuk truk), jadi satu truk yang diketik dua kali tetap **satu pesan berisi keadaan terbaru** —
bukan dua. Pesan yang diganti **saat masih di jalan** sengaja tidak ditandai terkirim
(`mark_sent` mencocokkan payload-nya), supaya keadaan yang lebih baru tidak hilang.

`integrations/erp/client.py` membedakan dua hal, dan pemanggilnya bertindak beda:

| Balasan | Artinya | Yang dilakukan worker |
|---|---|---|
| 2xx | mendarat | handler mencatat jawabannya (mis. `erp_name` truk), baris selesai |
| **4xx** (`ErpRejected`) | AutoERP **menolak isinya** — diulang pun sama | disimpan **dengan alasan dari Frappe**, batch lanjut ke pesan berikutnya |
| **jaringan / 5xx** (`ErpUnavailable`) | AutoERP **tidak terjangkau** | batch **berhenti** — sisanya cuma akan membakar backoff-nya sendiri |

Backoff 30 detik → 1 jam (kontrak §5). Handler yang gagal mencatat di sisi kita juga menahan
pesannya: AutoERP sudah menerima, tapi kirim ulang aman (semua handler upsert) sedangkan
kehilangan jawabannya tidak.

**Kunjungan truk (§4.C).** Satu pesan per kunjungan, dikirim tiga kali saat kejadian yang
memang terjadi: **timbang masuk**, **truk dilepas dari line**, dan **timbang keluar**. Plus
kirim ulang kunjungan kemarin sekali sehari (`VisitResendWorker`, penanda harinya di
`sync_state`) sebagai jaring pengaman.

`services/erp_queue.py` satu-satunya yang merakit pesan — pemicu langsung dan kirim ulang
memakai jalan yang sama, jadi keduanya tidak bisa berbeda isi. Payloadnya **dibangun ulang dari
store tiap kali**, tidak ditambal, sehingga kiriman yang antre di belakang tidak pernah membawa
keadaan lebih lama daripada barisnya.

| Hal | Aturannya |
|---|---|
| `visit_id` | id baris timbangan (uuid5 dari `ref`, atau plat + `waktu_masuk`) |
| `stage` | **diturunkan** dari keadaan: ada tara → `departed`, ada grading → `grading`, sisanya `gate` |
| bagian kosong | **tidak dikirim** — tiap kiriman mengganti bagian yang dibawanya, jadi bagian kosong menghapus isi ERP |
| grading | lewat `weighings.assignment_id`, ditulis **saat truk dilepas**; tanpa itu tiket kedua hari itu mewarisi janjang tiket pertama |
| kriteria | mentah = REJ, tangkai panjang = ACC dengan `tp_confidence > 0.8`, matang diturunkan AutoERP |
| `erp_ticket` | nomor Weighbridge Ticket jawaban AutoERP, disimpan balik ke baris timbangan |

⚠️ AutoERP **mengadopsi tiket terbuka milik truk yang sama** dalam jendela ±2 jam. Dua
kunjungan truk itu di jam yang sama karena itu mendarat di satu tiket — perilaku ERP, bukan bug
konsol. Dan tiket yang sudah punya berat bersih lalu menerima grading akan **difinalisasi**;
untuk buah Inti itu butuh Gudang Penerimaan TBS + Akun Pendapatan Transfer di Pengaturan PKS,
yang di situs demo belum diisi (AutoERP membalas 417 dan antrean menahannya dengan alasannya).

**Truk baru naik (§4.B).** Truk yang diketik operator dikirim ke
`erpnext.palm_mill.api.upsert_truck` dengan `plate_number` + `autograde_id`; AutoERP membuatnya
**tanpa pemilik** dan backoffice yang melengkapi. Jawabannya (`name`, dan `supplier` kalau ERP
sudah mengenal platnya) disimpan lewat `link_truck`, lalu tarikan berikutnya mengadopsinya jadi
truk ERP biasa. Supplier dan kelas **tidak** ikut dikirim — itu milik AutoERP.

`ERP_URL` kosong = worker pulang saat start dan menulis satu baris log. Itu default: jalur ini
tidak boleh jadi syarat hidupnya layar operator.

**Perintah ke line.** Konsol meneruskan ke endpoint line yang **sudah ada**
(`POST /internal/assignment`, `POST /internal/manual-reject`, header `x-internal-secret`).
HTTP-nya duduk di `integrations/notifications/line_client.py` — satu-satunya bagian konsol yang
tahu soal httpx — dan `ConsoleService` menerimanya lewat konstruktor bersama `ConsoleStore`
(composition root: `get_console_service()` di `routes/console.py`). Line yang tidak menjawab
melempar `LineUnavailable` → route balas **502**, bukan diam. Registry line-nya nilai bertipe
(`Settings.console_lines` → `LineEndpoint`), dan `LINE_N_MACHINE_ID` dibaca **di Settings**,
bukan di service. `assign_truck` menunggu line menerima **sebelum** menyimpan: layar yang menampilkan truk
terpasang padahal line tidak tahu apa-apa membuat operator mengira sudah beres, dan tandan
berikutnya terhitung tanpa truk. Penugasan disimpan di SQLite, bukan memori (§6.4), jadi
selamat dari restart konsol di tengah shift.

**UI.** Satu file `src/palmgrade/static/console.html` — vanilla JS, tanpa build step, **tanpa
CDN** (harus tetap terbuka saat internet mati). Stream kamera pakai `<img>` MJPEG langsung ke
line di port 8001-8003, jadi tiga koneksi video ditanggung browser, bukan proses konsol. ~2200
baris React di frontend lama **diekspresikan ulang, bukan di-port**.

**Login (Fase 4, §6.5).** Layar tertutup gerbang **email + sandi** sampai ada yang masuk, dan
**semua** `/api/console/*` menjawab 401 `belum_masuk` tanpa cookie `konsol_sesi` — kecuali
`/console` sendiri, daftar akun untuk mengisi kolom email, dan `login`. Akun datang dari dua
tempat: DocType **`AutoGrade Operator`** di AutoERP (ditarik §4.A) dan akun **lokal** di PC itu
(bawaan + support, supaya pabrik tanpa internet tetap bisa dibuka). Keduanya diverifikasi di
pabrik — yang ditarik `password_hash`-nya, bukan sandinya, dan itulah sebabnya field-nya `Data`
biasa: fieldtype `Password` hidup di `__Auth` yang Frappe sengaja tidak pernah layani lewat REST,
jadi tidak akan ada yang bisa ditarik. Dua skema berdampingan: `pbkdf2_sha256` milik AutoERP
(dibaca `hashlib` saja) dan `scrypt` untuk akun lokal. Sesi 12 jam (`sesi`), lockout berlipat dua
sesudah lima kali salah, dan `requested_by` Reject Manual sekarang nama operator yang masuk —
bukan lagi string `"operator"`. Akun lokal dibuat dari PC dengan `make operator`; tidak ada lane
web untuk itu. Rincian aturannya di `CLAUDE.md` invarian 19.

**Belum termasuk Fase 2** (sengaja): timbangan brondolan lewat PLC (§6.6b, Fase 3), nomor dokumen
berprefiks lokal (§6.3), toggle tampil/sembunyi per line, dan halaman riwayat/laporan lintas hari
(itu urusan cloud — live/hari ini lokal, riwayat cloud).

**Tests** (`tests/unit/test_working_day.py`, `test_console_store.py`, murni-logic; satu-satunya yang
memakai FastAPI adalah penjaga sesi konsol, lawan app rakitan sendiri): batas hari lewat tengah
malam WIB vs UTC, timestamp cacat melempar, dedupe event
kirim-ulang, pemisahan ACC/REJ per line, penugasan yang selamat restart, urutan
line-dulu-baru-catat, bentuk URL gambar (relatif vs R2 absolut), Sumber TBS yang sama di kelima
tampilan, dan `LINE_N_MACHINE_ID` yang benar-benar sampai lewat Settings.
`test_erp_master_data.py` + `test_ffb_source.py` mengunci tarikan AutoERP: field persis milik
DocType (ERP palsunya membalas 417 seperti Frappe), adopsi baris manual, `erp_name` yang tidak
terhapus, kursor per-DocType yang tidak maju saat ada baris gagal, bentuk header `token k:s`, dan
aturan `sumber_for_supplier`. Seam-nya kolaborator:
test menukar `LineClient` dengan yang palsu dan jaringan dengan `httpx.MockTransport`,
bukan menambal method privat service. `test_console_html.py` menjaga dua invarian UI yang tidak
punya test runner sendiri (tanpa build step, jadi tanpa Vitest): tidak ada handler `on*` inline
— tombol dipasang lewat delegasi + `data-line` — dan `esc()` tetap meloloskan `'` dan `` ` ``,
karena nilainya masuk ke atribut HTML.
