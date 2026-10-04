# autograde: Detailed Overview

> **The DETAIL doc** (read on-demand). The lean map is `../CLAUDE.md`.
> Layer boundaries: §1 below. Full endpoint and env tables: `backend-overview.md`. Host and
> camera setup: `SETUP.md`. Factory PC install and operation: `MANUAL.md`.

---

## 1. Layered Architecture: per-layer do/don't

`route → controller → service → repository / pipeline / integration`. The console app skips the
controller on purpose (`route → service → repository`, see `routes/console.py`). Each layer has a
strict boundary; the coding rules that go with it are in `docs/coding-standard.md`.

| Layer | Folder | May | Must NOT |
|---|---|---|---|
| Routes | `routes/` | path, method, `Depends()`, return type | any logic, file/model/queue access |
| Controllers | `controllers/` | take request, call **one** service, raise `HTTPException` | touch repository, queue, or YOLO |
| Services | `services/` | combine repo + pipeline + integration; run business flow | SQL, vendor SDK detail, direct file I/O |
| Repositories | `repositories/` | read/write SQLite (`console.db` for visits, accounts and history; the event log in its own file) and JSON or images via `LocalFileStorage` | PASS/FAIL rules, HTTP, inference, voting |
| Pipelines | `pipelines/` | YOLO inference, frame processing, draw boxes | HTTP, file save, business rules, queue |
| Domain | `domain/` | pure functions/dataclasses, zero I/O | import `cv2`/`httpx`/`fastapi`, read/write files |
| Workers | `workers/` | background loop, queue, lock, `RuntimeState` | return HTTP, save to file directly (delegate to repo) |
| Schemas | `schemas/` | Pydantic models that validate input at the boundary and shape responses | logic, I/O |
| Integrations | `integrations/` | the outside world: AutoERP client and outbox store, camera sources, file storage, R2 upload, notifications, scheduler | business rules, deciding a verdict |
| PLC | `plc/` | MC Protocol and Modbus clients, pulse and hold, the PLC worker | deciding a verdict (that is `domain/`) |
| Core | `core/` | `Settings` from env vars, DI factories, logging, constants | business rules; no other module reads env vars |

---

## 2. Worker & Runtime-State Model

`main.py` `lifespan()` starts (all daemon unless noted):

| Worker | Kind | Responsibility |
|---|---|---|
| `FrameCaptureWorker` | thread | grab frame from camera (under `state.lock`) → `state.latest_raw_frame` + `frame_queue`. Auto-reconnects with `device_index`. |
| `FrameProcessingWorker` | thread | YOLO inference from `frame_queue`; sets `state.last_yolo_frame` + `state.last_yolo_results` (paired); janjang menyentuh garis capture → pulse PLC + `event_queue` + serahkan `SaveJob`, lalu **lanjut**. Sejak 2026-09-18 **tidak menulis ke disk maupun outbox sendiri** |
| `CaptureSaveWorker` | thread | penulis bukti: encode WebP bbox+clean+thumb, sidecar JSON, dan satu baris `outbox.add_event()`. Antrean 8 dalam, drop yang terbaru + `logger.error` kalau penuh (`capture_save_dropped`). Ikut diawasi watchdog; dikuras oleh urutan tutup line (SIGTERM dan perintah restart/hapus dari konsol) bersamaan dengan coil PLC dimatikan |
| `DisplayWorker` | thread | the **only** writer of `state.latest_frame`: resize → draw boxes (scaled) → draw ROI → JPEG encode → `frame_condition.notify_all()`. Runs at `STREAM_FPS` (default 12), and renders nothing while no MJPEG viewer is counted in (`state.penonton_stream`, batch 6.3). |
| `OutboxRetryWorker` | thread | kirim isi `outbox.db` ke **konsol lokal** (`BACKEND_URL`), poll 1 detik: jalur realtime operator, hidup walau internet mati. Batch upload foto ke R2 jalan terpisah. |
| `PlcWorker` | thread | **hanya kalau `PLC_ENABLED=true`** (default mati → nol thread tambahan di PC dev). Satu-satunya thread yang menyentuh socket ke PLC (MC Protocol ke CPU Mitsubishi; Modbus ke coupler ODOT kalau `PLC_PROTOCOL=modbus`): kuras antrean keputusan → pulse bit OK/NG, kedipkan heartbeat, baca blok input, tulis bit ERROR. Bangun tiap `PLC_POLL_MS` (default 200ms) **selamanya**. Sinyal telat = buah salah yang tersortir, jadi kebijakannya **buang dan hitung, jangan pernah tunda**. |
| `EventBroadcastWorker` | asyncio task | drain `event_queue` → push to `/ws/results` WebSocket clients |
| `_watchdog` | asyncio task | every **10s**, restart any dead worker thread |

`UploadScheduler` (APScheduler) menjalankan `BatchUploadWorker.run_batch_once` tiap jam (menit `UPLOAD_MINUTE`): scan `artifacts/results/` → manifest SQLite → upload gambar ke R2 → POST teks ke `UPLOAD_API_URL` **kalau diisi** (kosong di pabrik: penerimanya, palmgrade-api, sudah pensiun). `R2_BUCKET` kosong = no-op.

**Queues / sync primitives** (`workers/runtime_state.py`):
- `frame_queue`: raw frames, bounded (drop-old).
- `event_queue`: outgoing events for WebSocket, **drop-old** (`get_nowait()` + `put_nowait()`).
- `frame_condition` (`threading.Condition`): MJPEG broadcast (multi-viewer; each viewer `wait(timeout=0.5)`).
- `state.lock`: guards physical camera access.
- `current_truck_id`, `current_assignment_id`: set by `POST /internal/assignment`.
- `last_successful_api_push`, `worker_threads`, `websocket_clients`, `main_loop`.

**AI mati (batch 2.1).** Empat stempel `time.monotonic()` di `RuntimeState` (`ai_dimulai_at`,
`frame_terakhir_at`, `aliran_frame_sejak`, `inferensi_selesai_at`) ditulis worker, dan
`services/penjaga_ai.py` (`PenjagaAi`) membacanya untuk menjawab satu pertanyaan: kamera
mengirim gambar, tapi ada frame yang selesai digrading dalam `AI_MATI_DETIK` detik terakhir?
Kalau tidak, AI dinyatakan mati, dan coil ERROR PLC, `/health` (503), serta kartu line konsol
sama-sama membaca penilaian yang sama dari objek ini, bukan menghitung sendiri-sendiri. Detail
aturan dan lima keadaan yang sengaja tidak dialarm: `domain/kesehatan_ai.py`, `docs/rules.md` aturan 32.
Sejak batch 3.6 objek yang sama juga menilai **frame berhenti** (kamera tersambung tapi tidak
mengirim gambar): coil ERROR dan `/health` 503 seperti AI mati, `ai.mati` tetap AI saja (aturan 35).

**Log line (batch 3.2).** WARNING/ERROR line dulu berhenti di stdout + `PenulisLogLine` (antrean
memori tiap ~0,2 detik, thread deteksi tidak pernah menunggu disk, aturan 1b), sekarang juga
ditulis ke `log_line.db` di folder DB line (maks 2.000 baris). Konsol menariknya ke tab Log
(`TarikLogLineWorker`, tiap 10 detik), jadi galat line tetap terbaca sesudah container di-recreate.
Aturan lengkapnya `docs/rules.md` aturan 34.

---

## 3. Detection Flow (single-trigger, not voting)

Model `best.pt` detects 4 classes in one pass: `Ripe`, `Unripe`, `JK`
(janjang kosong) and `TP` (tangkai panjang).

The class is NOT the verdict. `Ripe` → ACC; `Unripe` and `JK` → REJ; `TP` is not
a bunch at all and gets no verdict, it rides beside a bunch as `tp_confidence`.
The mapping lives in one place, `domain/grade_class.py`, because two things
downstream stayed binary on purpose: the PLC owns exactly two coils (OK and NG,
a third category would be wiring, not code), and AutoERP books three AI criteria
(`Mentah` / `Tangkai Panjang` / `Matang`) under a frozen contract. So a row
carries both: `ripeness_status` is the verdict that fires pistons and is paid on,
`grade_class` is the detail the console shows.

⚠️ **The JK count itself is not sent to AutoERP, but JK bunches are inside `Mentah`.**
The visit message books `Mentah` from the REJ count, and JK is REJ (so are Ripe bunches
forced to REJ for being stacked or too small). The 2026-09-16 design wanted JK kept on
the edge (`Sampah` is weighed, not seen by a camera, and JK in `Mentah` overstates the
share the supplier is docked for). Which one is intended is undecided (found
2026-09-28); see `docs/rules.md` rule 0.

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
      outbox.add_event(build_event_payload(...))  # → konsol lokal via OutboxRetryWorker
      # Upload ke R2 terpisah: BatchUploadWorker men-scan file hasil save
      # di atas (lihat §4) dan menghitung ulang uuid5 yang sama dari machine_id +
      # timestamp nama file — dua jalur, satu event_id, jadi tidak pernah dobel.
```

- `ResultRepository.list_today_results()` merges `_ripeness.json` + `_tp.json` per base_name.
- Manual reject (`CaptureService.capture_manual_reject`): full-frame capture marked `rej`,
  saved as `{ts}_manual_ripeness.json` (suffix `_ripeness` is required so it isn't read as legacy),
  lalu ikut ter-scan `BatchUploadWorker` seperti hasil auto (truck may be `null`).
  `bounding_box` = full frame `{0,0,width,height}`.

**ROI box:** `ROI_X1/Y1/X2/Y2` in **stream space** (`STREAM_WIDTH×STREAM_HEIGHT`, default 1280×720),
NOT sensor space: operators calibrate from what they see in the browser. Center `(cx,cy)` must be
inside the box. `0,0,0,0` = full frame (X2=0→stream width, Y2=0→stream height); require `X2>X1` & `Y2>Y1`.
TP is exempt from the ROI check. `draw_roi()` runs in `DisplayWorker` **after** resize.
Since 2026-10-04 the console can set the box (`RuntimeState.roi_override`, grading settings path): it wins over
`ROI_*`, `null` = not set there, so `.env` decides; a box covering none of the stream picture is refused at
save and ignored by a line. Two display switches (`tampil_garis`, `tampil_roi`) only skip the drawing.

**Garis capture (biru, bertanda `CAPTURE`)**: sejak 2026-09-18 menggantikan aturan lama "titik
tengah masuk kotak ROI" sebagai penentu KAPAN janjang difoto. Dua hal yang sengaja dipisah:

| | Menjawab | Aturan |
|---|---|---|
| ROI | di mana | titik tengah janjang di dalam kotak = wilayah conveyor |
| Garis capture | kapan | kotak janjang **menyentuh** garis (`domain/garis_capture`) |

Aturan lama memfoto janjang saat **separuhnya** sudah lewat, dan dengan `ROI_*` bawaan `0,0,0,0`
(= seluruh layar) itu berarti begitu terdeteksi di mana pun, termasuk di pinggir frame saat
janjangnya belum utuh. Itu keluhan "capture terlalu cepat" dari PC Lampung.

Disetel dari **layar support konsol**, satu angka untuk semua line, berlaku tanpa restart lewat
`/internal/setelan`: jalur yang sama persis dengan `CONF_THRESHOLD` dan `MINIMUM_SIZE`
(`domain/setelan_grading`, `RuntimeState.garis_capture_override`). `GARIS_CAPTURE` di `.env` cuma
nilai awal. **`0` = tidak ada garis**, dan itu perilaku sebelum fitur ini ada, satu-satunya cara
PKS yang belum menyetel tidak kehilangan janjang, jadi batas bawahnya inklusif (`BAWAH_INKLUSIF`),
beda dari dua setelan lain yang `0`-nya justru mematikan grading diam-diam.

⚠️ Angkanya ruang **stream**, diskalakan ke ruang sensor saat menyaring (`skala_garis_ke_frame`).
Melewatkan penskalaan itu bug yang sudah pernah terjadi di ROI (`bdcb300`).
⚠️ Pemicunya **perpotongan**, bukan sentuhan persis: garis dievaluasi sekali per frame, dan pada
8-20 fps janjang bisa melompati garis di antara dua frame, menuntut sentuhan persis membuat
janjang cepat tidak pernah difoto, hilang tanpa satu pun pesan.
`TP` dikecualikan dari garis, sama seperti dari ROI.

**Pasangan TP ↔ janjang** (2026-09-18). Janjang difoto **apa adanya** begitu menyentuh garis,
ada TP atau tidak: tanpa penundaan. TP yang dipakai adalah yang pusatnya **paling dekat** dan
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
(`janjang_lain`). Dua janjang berdempetan: 450x450 px berjarak 500 px pada sensor 2448x2048,
sama-sama berjangkauan 477 px, jadi satu tangkai di antara keduanya masuk jangkauan dua-duanya
dan pemenangnya tinggal urutan pemrosesan, yang tidak dijamin. Janjang yang sudah difoto ikut
jadi saingan, supaya tangkai milik janjang yang baru selesai tidak pindah ke tetangganya.
⚠️ TP tepat di **tengah sela** dua janjang memang ambigu secara geometri; aturan apa pun cuma
menebak di situ, dan itu sengaja tidak diuji seolah punya jawaban benar.
`tp_telat` dihitung dari `_janjang_difoto` (catatan sendiri, umur 300 detik), **bukan**
`track_history`: tabel itu dibuang 10 frame sesudah janjangnya hilang dari pandangan, jadi TP
yang muncul sesudahnya tidak pernah terhitung dan angkanya diam-diam terlalu kecil.

**Arah conveyor** (`sumbu_garis`, disetel di layar yang sama sejak 2026-09-18):

| Sumbu | Conveyor | Garis | Angkanya |
|---|---|---|---|
| `tegak` (bawaan) | mendatar, buah lewat kiri↔kanan | vertikal | px dari **kiri** |
| `mendatar` | menurun, buah lewat atas↔bawah | horizontal | px dari **atas** |

Arah gerak DI DALAM satu sumbu tidak perlu disetel: pemicunya perpotongan, berlaku dari sisi
mana pun, jadi conveyor yang membalik arah tetap jalan tanpa satu pun perubahan.
⚠️ Sumbu mendatar diskalakan dengan **tinggi** frame, bukan lebar (`skala_garis`): frame
2448x2048 tidak persegi, jadi memakai lebar membuat garis meleset ~19% tanpa satu pun error.
⚠️ Sumbu yang tidak dikenal **tidak melempar** di jalur deteksi (jatuh ke `tegak`): nilainya
bisa datang dari konsol versi lain, dan satu string asing tidak boleh menghentikan grading.
Yang menolak nilai aneh adalah jalur SIMPAN, di gerbang, sebelum sampai ke tiga line.

**Label janjang tanpa angka confidence** (2026-09-18, permintaan operator). Angkanya keyakinan
model, bukan mutu buah, dan dari beberapa meter "54%" terbaca seperti "54% matang"; ambangnya
sudah diputuskan `CONF_THRESHOLD`, jadi apa pun yang tergambar sudah lolos ambang itu.
`viewer.html` membuangnya lebih dulu (`abd8f17`). Nilainya **tetap** disimpan di sidecar dan
dikirim ke konsol: yang dibuang tampilannya, bukan datanya. `MODE_DEV=true` (tab Setelan)
menggambarnya lagi, untuk support yang sedang menyetel ambang.

**DisplayWorker draw order (since batch 6.3):** `cv2.resize()` of `last_yolo_frame` to stream size → `draw_boxes(skala=...)` on the small frame (box and style scaled by `domain/skala_tampilan.py`) → `draw_roi()`
(yang juga menggambar **garis capture** biru bertanda `CAPTURE`, sesudah resize, di ruang stream).
Render boxes over `last_yolo_frame` (paired with results), **never** over `latest_raw_frame`, on CPU,
inference can take 0.5–2s and the conveyor moves, so boxes would land in the wrong place. Fallback to
`latest_raw_frame` only before the first YOLO run.

---

## 4. Batch Upload Delivery (hourly, at-least-once)

> Jalur ke **cloud**, berdampingan dengan outbox. Antriannya **file di disk**, bukan
> `outbox.db`: `_scan()` menemukan `results/{date}/*.json` dan menyimpan state per-item di
> `UploadManifest`. Outbox mengurus jalur **lokal** ke konsol (§3) dan tidak dibaca di sini.
>
> **Di pabrik sekarang yang naik cuma gambar.** `UPLOAD_API_URL` kosong (penerima teks per
> janjang, palmgrade-api, pensiun 2026-09-20), jadi item `done` begitu PUT ke R2 berhasil dan
> langkah 4 dilewati. AutoERP tidak menerima per janjang; konsol mengirim satu pesan per
> kunjungan truk (§11).

```
CaptureSaveWorker (auto) / CaptureService (manual)
  → simpan WebP + {ts}_*_ripeness.json ke artifacts/results/{date}/    # ini antriannya
      ↓  (UploadScheduler: APScheduler cron, tiap jam pada menit UPLOAD_MINUTE)
BatchUploadWorker.run_batch_once()
  1. _scan()      glob results/**/*_ripeness.json → UploadManifest.upsert_item() (idempotent)
  2. claim        SELECT WHERE status IN ('pending','image_uploaded') AND next_retry_at <= now
                  ORDER BY discovered_at ASC   LIMIT UPLOAD_MAX_ITEMS_PER_TICK (2000)
  3. PUT gambar   → Cloudflare R2 (boto3)          → mark_image_uploaded()
                    (+ thumbnail 400 px; gagal thumb cuma warning)
  4. POST teks    → {upload_events_url}             → mark_done()
                    header x-webhook-secret: UPLOAD_API_SECRET
                    UPLOAD_API_URL kosong → langsung mark_done() sesudah langkah 3
  5. _retention() hapus WebP+JSON yg `done` & lewat UPLOAD_RETENTION_DAYS (default 7),
                  lebih awal kalau sisa disk < UPLOAD_DISK_MIN_FREE_GB
```

- **Target POST = API cloud**, bukan konsol: `upload_events_url` =
  `{UPLOAD_API_URL}{backend_api_ver}/internal/vision/events`, secret-nya `UPLOAD_API_SECRET`.
  `canonical_events_url` (`BACKEND_URL`, jalur realtime ke konsol) **tidak dipakai worker ini**.
- **`R2_BUCKET` kosong = worker no-op** (saklar off). Bukan error: cuma `logger.warning` **sekali**
  (`_warned_noop`), jadi gampang terlewat di log yang sudah jalan lama. Kalau event tidak pernah
  sampai cloud, cek variabel ini duluan.
- Sukses kalau API balas `200/201` **atau** body memuat `already_processed`.
- Error handling per item (yang bikin satu item busuk tidak menyandera batch):
  | Kondisi | Exception | Efek |
  |---|---|---|
  | HTTP 400/422, meta cacat, file gambar hilang, foto/sidecar 0 byte atau sisa `.tmp` | `_PoisonError` | `mark_poisoned` + **continue**. File **tidak** dihapus: ditinggal untuk diperiksa manual |
  | HTTP 404 (truck belum ada di DB cloud) | `_RequeueError(batch_fatal=False)` | requeue + **continue**: antrian `ORDER BY discovered_at ASC`, jadi tanpa ini satu item lama bisa head-of-line starve seluruh batch |
  | HTTP 401/403/5xx, jaringan mati | `_RequeueError` (default `batch_fatal=True`) | requeue + **break batch**: percuma lanjut kalau endpoint/kredensialnya yang bermasalah |
- Backoff: base **5s**, eksponensial sampai cap **600s** (`upload_manifest.py`). **TANPA retry cap
  dan TANPA TTL**: kontrak yang sama dengan outbox line sejak batch 2.4 (tanpa batas nyerah). Item
  menunggu di disk selamanya sampai terkirim (syarat "tahan outage berapa lama pun").
- Tahan restart karena **file-nya ada di disk**; manifest hanya menyimpan progres.
  SQLite durability eksplisit: **`PRAGMA journal_mode=WAL` + `synchronous=FULL`**: commit di-fsync,
  progres yang tercatat selamat dari mati listrik (write rate rendah, biaya fsync ringan).
- `event_id`: uuid5 deterministik dari `machine_id:timestamp` untuk **auto maupun manual**
  (formula tunggal di `domain/vision_event.py`, dipakai jalur outbox juga) → item yang di-upload
  ulang, atau event yang sudah lewat jalur realtime, dibalas `already_processed` → tidak dobel.
- `state/upload_manifest.db` sengaja **sibling** `artifacts/`, di luar mount statis `/captures`
  (`Settings.state_dir`) supaya DB operasional tidak ikut ter-serve sebagai file publik.
- Progres batch **tidak** ada di `/health/detail`: `outbox_pending`/`outbox_failed` di sana
  mengukur jalur realtime ke konsol (`outbox_pending` = semua yang belum sampai, `outbox_failed`
  selalu 0 sejak batch 2.4). Ringkasannya naik lewat blok `unggah` di `GET
  /internal/status` (dihitung sekali per batch) dan tampil di konsol sebagai **Last Sync →
  Cloud Photo**. Rincian per item: query `state/upload_manifest.db` atau baca log worker.

**Event payload** (field names, contract, and how the batch variant differs): `backend-overview.md`
§Payload event. Realtime: `domain/vision_event.build_event_payload`; batch:
`BatchUploadWorker._build_payload`, same fields.

---

## 5. Integration Contract (line ↔ konsol)

Kontraknya beku sejak palmgrade-api: konsol meniru URL dan header yang sama, jadi
`OutboxRetryWorker` di line tidak berubah sama sekali.

**line → konsol** (`BACKEND_URL` = konsol di mesin yang sama, `http://localhost:8100` di PC pabrik),
header `x-webhook-secret`:
- `POST {BACKEND_URL}{BACKEND_API_VER}/internal/vision/events`: event per janjang. Secret salah →
  401; payload cacat → 400, dan outbox line menahannya dan terus mencoba (tab Status → Antrean
  line, sengaja terlihat gagal).
- `GET .../internal/setelan` dan `GET .../internal/penugasan?machine_id=`: dibaca line saat start,
  supaya setelan grading dan truk terpasang selamat dari container yang dibuat ulang.

**konsol → line** (`CONSOLE_LINE_HOST` + port 8001-8003), header `x-internal-secret`:
- `POST /internal/assignment` `{machine_id, assignment_id, truck_id, assigned_at, ffb_source?, plate?}`
  → sets `state.current_truck_id` + `state.current_assignment_id`.
- `POST /internal/manual-reject` `{machine_id, assignment_id, requested_by, requested_at}`
  → `capture_manual_reject()` via executor.
- `POST /internal/piston` `{open, requested_by, requested_at}`: dipanggil lewat
  `POST /api/console/lines/{line}/piston`, yang sejak batch 1 keamanan (2026-09-28) butuh sesi
  operator seperti lane operator lain (dulu tanpa sesi).
- `GET /internal/status` tiap detik, `POST /internal/setelan`, `POST /internal/restart`, dan
  lane support lainnya: daftar lengkap di `backend-overview.md`.

**Shared, tapi dua secret sejak batch 1**: `WEBHOOK_SECRET` tetap satu untuk line ↔ konsol
(`x-webhook-secret`, dua arah §5) dan program timbangan pihak ketiga. `INTERNAL_SECRET`
memisahkan header `x-internal-secret` (konsol → line) dari kunci itu: kosong atau sama dengan
`WEBHOOK_SECRET` = perintah konsol masih memakai kunci lama (`.env` yang dipasang sebelum batch 1
tetap jalan), diisi beda = terpisah. Perbandingan constant-time dan fail closed di kedua secret
(`domain/rahasia.py`, `routes/penjaga_rahasia.py`): nilai kosong yang dikonfigurasi tidak pernah
membuka lane. Line dan konsol sama-sama menolak boot di `APP_ENV=production` kalau `WEBHOOK_SECRET`
masih bawaan atau kosong (`Settings.validate_secrets()`); `INTERNAL_SECRET` kosong/tidak diisi cuma
warning (jatuh ke `WEBHOOK_SECRET`, itu yang membuat rilis backward compatible), tapi kalau diisi
ikut aturan menolak-boot yang sama. Jalur **batch ke cloud** pakai
pasangan sendiri, `UPLOAD_API_URL` + `UPLOAD_API_SECRET`, yang di pabrik sekarang kosong.
`LINE_1/2/3_MACHINE_ID` = identitas tiga line (compose membawa bawaan UUID); konsol memetakan
`machine_id → line_code` dan menyajikan gambar di `/captures/<line_code>/...` (butuh sesi
operator sejak batch 1; `/captures` line sendiri tetap terbuka, tanpa konsep sesi).

> Day-boundary note: **event** `timestamp` UTC-aware (`datetime.now(timezone.utc)`). File JSON di
> disk masih pakai naive local time (nama folder tanggal + `results_today` mengikuti jam lokal
> container). Konsol menurunkan tanggal kerja sendiri dari timestamp event (§11).

---

## 6. Invariants: full rationale (don't change without discussion)

0. **Disk before network.** Never POST events directly from a detection worker. `CaptureSaveWorker`
   (jalur auto) dan `CaptureService` (manual) menulis file (WebP + `_ripeness.json`) ke
   `results/{date}/` lalu satu baris ke `outbox.db`: **tidak pernah** memanggil HTTP sendiri. Yang
   bicara ke jaringan cuma `OutboxRetryWorker` (konsol, §3) dan `BatchUploadWorker` (R2, §4).
   Deteksi **tanpa truck aktif tetap dikirim** (`truck_id: null`) di kedua jalur: `_scan()` tidak
   memfilter truck, dan outbox juga tidak.
1. **`_processed_objects`.** After saving a track_id, add it so the next iteration `continue`s
   (single-trigger). Never `discard()` an active track. `run_once` trims only IDs that are gone from
   `track_history` **and** stale >300s (`_processed_times`): pure memory control, can't re-trigger
   (the fruit left the frame long ago).
   **Ordering:** `processed` di-set **SETELAH janjang diserahkan ke `CaptureSaveWorker`**, sejak
   2026-09-18 itu titik yang tidak boleh diulang, menggantikan "setelah file tersimpan" yang berlaku
   selama penulisan masih sinkron. Yang dijaga tidak berubah: nama file (dan `event_id` uuid5
   `machine_id:timestamp` yang dihitung `BatchUploadWorker` dari nama itu) ditetapkan **di jalur
   deteksi**, sebelum serah-terima, jadi idempotensi dipegang oleh nama, bukan oleh urutan tulis.
   Track tanpa truck aktif tetap ditandai processed supaya tidak re-trigger.
   ⚠️ Konsekuensi yang dibeli sadar: kalau proses mati di antara serah-terima dan penulisan, janjang
   itu hilang (tidak ada retry: track sudah `processed`). Urutan tutup line (`langkah_tutup_line`)
   karena itu **menguras antrean dulu** saat shutdown, sama untuk SIGTERM maupun restart/hapus dari
   konsol. Jendelanya ratusan milidetik, dan harganya adalah hilangnya lag ~590 ms per
   janjang yang sebelumnya membuang ~12 frame kamera dan memutus jejak ByteTrack.
2. **`state.lock`** around all physical camera access (`FrameCaptureWorker.run_once` +
   `capture_manual_reject`): concurrent Hikrobot SDK access can crash.
3. **MJPEG via `threading.Condition`**, not `result_queue`, the old queue pattern served only one
   viewer. `event_queue` stays drop-old.
4. **DI** (`core/dependencies.py`): `@lru_cache` singletons; `get_outbox_store()` may cache (SQLite +
   `threading.Lock`, fresh connection per op). **NOT** cached: `get_capture_service()` /
   `get_health_service()`: they call `get_camera()` which raises before startup; caching would freeze
   `_camera = None`.
5. **`repo_root = parents[3]`**: `src/palmgrade/core/config.py` → 3 levels up = `/app` in Docker.
6. **`lifespan`** (not deprecated `@app.on_event`); scheduler + camera disconnect are lifespan locals, registered with `PenutupLine` before `yield`.
7. **MJPEG written only by `DisplayWorker`**: two writers to `state.latest_frame` cause flicker.
   It renders `last_yolo_frame` (paired with `last_yolo_results`), runs at `STREAM_FPS` (default 12),
   decoupled from `CAMERA_FPS` (default 15).
8. **Manual capture JSON** uses suffix `_ripeness` so `list_today_results()` reads it correctly.
9. **Every worker `run_loop` wraps `run_once` in `try/except`** + `logger.exception`, without it the
   thread dies silently and the watchdog restarts without a stack trace.
10. **`FrameCaptureWorker` needs `device_index`**: reconnect calls `camera.connect(index=...)`; a bare
    `connect()` (default 0) makes line-2/3 reconnect to the wrong camera.
11. **Encode or write failure raises `OSError`** (including `cv2.error`) in
    `LocalFileStorage.write_image`, a silent warning
    would leave orphaned JSON pointing at a missing image, dan karena JSON itulah yang di-scan
    `BatchUploadWorker`, item-nya berakhir `poisoned` saat upload. Auto path: caught by
    `CaptureSaveWorker.run_loop` (that bunch has no image and no sidecar, logged; the writer
    keeps running). Manual path: propagates → 500 to operator.
    Since batch 2.6, photos and sidecars are written whole-or-nothing: `cv2.imencode` in memory,
    then `tulis_atomik` (temp `.<name>.<random>.tmp` + fsync + `os.replace` + folder fsync). A
    power cut leaves a hidden leftover temp file, never a 0-byte file under the final name.

---

## 7. Camera Abstraction

`CAMERA_TYPE` (default `hikrobot`) selects the implementation in `lifespan()`, no code edit to switch.
Per line it comes from `media.env` (`LINE_N_CAMERA_TYPE` + `LINE_N_MEDIA_FILE`), written by the console
tab **Line → Sumber Kamera** and read by the line itself at boot (`Settings.__post_init__`):

| `CAMERA_TYPE` | Class | When |
|---|---|---|
| `hikrobot` | `HikrobotCamera` | production (needs MVS SDK + GigE hardware) |
| `opencv` | `OpenCVCamera` | dev: webcam (`CAMERA_DEVICE_INDEX`) or video file (`MEDIA_FILE`; `CAMERA_VIDEO_PATH` on the native `make line` path) |
| `photo` | `PhotoCamera` | testing: single image looped (`MEDIA_FILE`; `CAMERA_PHOTO_PATH` on `make line`) |

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

**Shared image:** `ripe-line-1` and `console` have `build:` + `image: palmgrade-vision:latest`; line-2/3
reuse the image (build once, ~20GB saved). Don't re-add `build:` to line-2/3. The factory PC builds
nothing: it pulls `ghcr.io/delta-anugrah/autograde:vX.Y.Z`.

**`network_mode: host`**: required for GigE Vision: `MV_CC_EnumDevices()` uses UDP broadcast that the
Docker bridge blocks. Consequence: `ports:`/`extra_hosts:` are ignored: each container binds its own
`APP_PORT` (lines 8001/8002/8003; console 8000 in the dev compose, 8100 in `docker-compose.prod.yml`
because 8000 is the Frappe bench port).

**GPU passthrough** (`deploy.resources.reservations.devices: nvidia/all/[gpu]`): needs NVIDIA Container
Toolkit on host (add the NVIDIA apt repo first; `apt install nvidia-container-toolkit` alone isn't enough,
see `SETUP.md`). Without it YOLO runs on CPU (~10× slower).

**TensorRT engine:** `make build-engine` (one-shot container, `scripts/build_engine.py`) export
`.pt` → engine FP16 di `engines/<model>.sm<cc>.engine`, **hardware-locked** per compute capability
(`Settings.engine_path_for_gpu`), tidak di-commit, **tidak di-bake ke image**, auto-skip kalau sudah ada.
Runtime (`pipelines/model_registry.py`) auto-pakai engine dan **fallback ke `.pt`** kalau tidak ada atau
tidak cocok: jadi build engine yang gagal bukan outage, cuma balik ke kecepatan lama.
Butuh ~5–15 mnt sekali per GPU, **tidak butuh kamera**.

⚠️ Di PC yang menjalankan **image dari GHCR** (bukan build lokal), `make build-engine` TIDAK bisa dipakai
apa adanya: target itu memakai `docker-compose.yml` polos yang `image: palmgrade-vision:latest` + punya
`build:`, jadi Docker akan mem-build ulang dari source alih-alih memakai image yang sudah di-pull.
Di sana jalankan `docker compose run` dengan file override yang sama seperti stack-nya, sehingga
`${PALMGRADE_AUTOGRADE_IMAGE}` dan mount `./engines:/app/engines` ikut terpakai, tanpa mount itu engine
ditulis ke dalam container sekali pakai dan hilang begitu container keluar. Perintah lengkapnya:
`docs/runbooks/2026-09-24-model-deteksi-per-line.md` §Engine TensorRT per model.

PENTING: TensorRT wajib di-install dari index NVIDIA (`https://pypi.nvidia.com`, wheel binary),
PyPI publik cuma punya source stub yang bikin pip hang di "Preparing metadata".

**SDK flow in `make up`:** `mkdir -p sdk/lib64` → `cp -r /opt/MVS/lib/64/. sdk/lib64/` +
`cp -r /opt/MVS/Samples/64/Python/MvImport sdk/MvImport` → Dockerfile `COPY sdk/ /tmp/sdk/` → copy into
`/opt/MVS/lib/64` + site-packages → `ENV MVCAM_COMMON_RUNENV=/opt/MVS/lib`. The **whole** `lib64` is
needed (not just `libMvCameraControl.so`): `MV_CC_EnumDevices()` dynamically loads the transport layer
(`MvProducerGEV.cti`, `libMVGigEVisionSDK.so`); missing them → `MV_E_LOAD_LIBRARY (0x8000000C)`.

**New factory PC:** host and camera prep in `SETUP.md` §1-6, the install order (image, `.env`,
launcher, AutoERP, PLC) in `MANUAL.md` §5. The factory PC does not run `make up`: it pulls the
GHCR image through the host launcher (`autograde pull` / `autograde use vX.Y.Z`). Frame rate lives in
`config/camera/hikrobot.mfs` (15 fps), not `CAMERA_FPS`.

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
      thumb/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp     # bbox 400 px → naik R2 (grid backoffice)
      clean/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp     # polos → latih model, TIDAK diupload
    _belum-assign/                                   # ter-grading sebelum truk dipasang

state/line-N/   (host) ↔ /app/state (container)   # SIBLING artifacts/, DI LUAR mount /captures
  upload_manifest.db        # progres BatchUploadWorker (WAL + synchronous=FULL)
  outbox.db                 # SQLite: antrean realtime ke konsol (OutboxRetryWorker)
  license.db                # penjaga jam lisensi (satu penanda jam tertinggi), kalau LICENSE_ENABLED
```

⚠️ **`outbox.db` dan `license.db` pindah ke `state/` sejak batch 1 keamanan (2026-09-28)**,
sebelumnya keduanya duduk di `artifacts/` dan ikut tersaji apa adanya lewat mount `/captures`.
`folder_db_line()` (`services/pindah_db_line.py`) memilih `state_dir` kecuali `/app/state` bukan
mount dari host (PC yang belum ditambah `./state/line-N:/app/state` di compose host): dalam
keadaan itu keduanya tetap di `artifacts/`, tetap tidak tersaji (lihat aturan berkas DB di bawah),
dan `logger.error` mencatat kenapa. Isi berkas lama **diserap** ke lokasi baru saat boot pertama
(`pindahkan_db_lama()`), bukan dipindah mentah: `os.replace` gagal lintas bind mount Docker
(EXDEV), dan penyerapan berdasarkan kunci alami membuat boot yang terputus di tengah aman diulang.
⚠️ **Serapan yang gagal** (berkas lama rusak, disk `state/` penuh, `MemoryError`) meninggalkan
`artifacts/outbox.db` yang barisnya tidak terhitung `pending_count()`. Supaya tidak terbaca
"antrean kosong": `/health/detail` melapor `outbox_lama_tertinggal: true` dan `outbox_pending:
null` (tidak diketahui, bukan 0), Danger Zone menahan hapus data dengan hambatan `outbox_lama`
(menyebut line-nya dan menyuruh restart line itu, lalu tab Log + teknisi kalau masih muncul),
dan hapus-data saat boot (`hapus_kalau_diminta(..., folder_db=...)`) **tidak** menghapus
`artifacts/outbox.db*` selama folder DB line bukan `artifacts/`. Boot berikutnya mencoba
menyerapnya lagi. `autograde reset-data` di host hanya mengenali angka di `outbox_pending`, jadi
`null` terbaca "tidak diketahui" dan ikut menolak.
⚠️ `results/` **bukan arsip permanen**: `_retention()` menghapus WebP + JSON yang `done` dan lewat
`UPLOAD_RETENTION_DAYS` (default 7): setelah itu satu-satunya salinan gambar ada di R2. Item
`poisoned` sengaja tidak dihapus.
Gambar disimpan **WebP quality 65** (`JPEG_QUALITY_SAVE` di `core/constants.py`: nama konstanta
legacy, berlaku untuk WebP juga; `LocalFileStorage.write_image` pilih codec dari ekstensi file).
⚠️ **Sidecar JSON tidak pernah ikut pindah ke subfolder.** `_scan()` mencarinya dengan
`glob("*/*_ripeness.json")`: kedalaman dipatok dua, jadi sidecar yang lebih dalam tidak akan
pernah ketemu dan upload cloud berhenti **tanpa error apa pun**. Yang masuk subfolder cuma
gambar; letaknya dibaca dari `image_path` di dalam JSON.
⚠️ **Jam folder truk pakai `FACTORY_TZ`, nama berkas tetap UTC**, nama berkas menurunkan
`event_id` (uuid5) jadi tidak boleh bergeser, sementara nama folder satu-satunya yang dibaca
manusia. Dua zona dalam satu pohon disengaja: folder buat manusia, berkas buat mesin.
Aturan penamaan: `domain/capture_layout.py`. Penulis (satu-satunya, dipakai jalur auto maupun
manual): `services/capture_writer.py`.
⚠️ **Salinan `clean/` dan `thumb/` tidak punya baris manifest sendiri**: retensi menghapusnya
lewat `twins_of()` (`domain/capture_layout.py`). Menambah varian gambar baru tanpa ikut
mendaftarkannya di situ = file yang tidak pernah dihapus siapa pun.
Served by FastAPI `StaticFiles` mount `/captures` → `artifacts/`, so `image_url`
`captures/results/{date}/{truk}/bbox/{Ripe|Unripe|JK}[/TP]/{file}` resolves on the line side.
`.db`/`.sqlite`/hidden files are always 404 (`domain/berkas_captures.py`, `StaticTanpaDb`), on
the line as on the console. The console re-serves each line read-only under
`/captures/<line_code>/...`, and since batch 1 keamanan (2026-09-28) that mount also requires an
operator session (`CapturesBersesi`): no `konsol_sesi` cookie → 401 `belum_masuk`. The line's own
`/captures` stays open (it has no session concept and other LAN consumers rely on it).

---

## 10. License Guard (optional, default off)

`LICENSE_ENABLED=true` adds `LicenseGuardMiddleware` (Ed25519 JWS verify of `LICENSE_TOKEN`) plus a
grading gate in `FrameProcessingWorker`: the HTTP middleware alone would leave the cameras running.
Added before CORS so a 403 still gets CORS headers. `LicenseManager` / `LicenseLocalRepo` /
`gate.py` live in `license/`. No network: the token comes from env. It is issued in AutoERP
(DocType `AutoGrade Licence`) and installed on the factory PC with `autograde licence <token>`.

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
FastAPI/Starlette: di luar filosofi CI murni-logic); logic-nya tipis dan seluruhnya bersandar pada
`get_effective_license()` yang sudah tercakup.

---

## 11. Konsol Operator Offline (`APP_MODE=console`, Fase 2)

Layar operator pindah dari `palmgrade-frontend` ke sini. Instance **ke-4 dari image yang sama**,
port **8100** di PC pabrik (`docker-compose.prod.yml`) dan di `make console`; compose dev tanpa
override memakai 8000. Halaman di `/console`. Rencana & keputusan yang mengunci bentuknya: runbook
`2026-09-09-rencana-palmos-autograde.md` di repo `sawit` (§4, §6.1, §6.2, §3.5b). Nama "PalmOS" di
judulnya sudah pensiun, kotak ERP sekarang **AutoERP**.

**Kenapa modul ASGI-nya terpisah.** `main.py` menarik `core/dependencies.py` → pipelines →
ultralytics → torch, dan `core/constants.py` → cv2. Konsol tidak butuh satupun, jadi
`entrypoint.sh` memilih `src.palmgrade.console_main:app` saat `APP_MODE=console`. Efeknya bukan
sekadar hemat memori: satu line kamera yang mati (SDK hang, GPU hilang) tidak ikut menjatuhkan
layar operator, dan konsol boot dalam hitungan detik.

**Kenapa konsol tidak "membaca disknya sendiri".** docker-compose memberi tiap line
`artifacts/line-N` + `state/line-N` sendiri-sendiri, jadi instance ke-4 melihat pohon kosong.
Yang dipakai justru **kontrak event beku §5**: konsol membuka
`POST {BACKEND_API_VER}/internal/vision/events` dengan header `x-webhook-secret`, bentuk yang
persis sama dengan palmgrade-api dulu, lalu tiap line cukup menunjuk `BACKEND_URL` ke konsol
(`http://localhost:8100` di PC pabrik). `OutboxRetryWorker` yang sudah ada menanggung retry,
backoff, dan dedupe uuid5 saat konsol restart. Nol perubahan di kode line.

Gambar tetap milik line-nya: tiga `artifacts/line-N` di-mount **read-only** ke konsol dan
di-serve statis di `/captures/{line_code}/...`, di belakang sesi operator sejak batch 1 keamanan
(2026-09-28, `CapturesBersesi`): browser tanpa cookie `konsol_sesi` dijawab 401.

**Batas hari kerja (§6.1).** Pabrik jalan ~20 jam/hari dan **lewat tengah malam**, jadi batas
hari UTC memotong satu shift jadi dua tanggal. `work_date` dihitung **saat ingest** dari
timestamp event itu sendiri (`domain/working_day.py`, zona `FACTORY_TZ`) lalu **disimpan
sebagai kolom**: bukan diturunkan ulang saat query, dan tidak pernah dari `now()`, `creation`,
atau nama folder. Event yang datang telat (outbox menyusul setelah listrik mati) tetap mendarat
di harinya sendiri. Timestamp cacat → 400 → outbox line menahannya dan terus mencoba (tab Status
→ Antrean line), sengaja terlihat gagal. Batasnya **kalender**, tanpa cutoff shift; karena kolomnya disimpan, mengubah
aturan itu nanti cuma menyentuh satu fungsi. `python:3.11-slim` butuh `tzdata` (sudah
ditambahkan): tanpa itu `ZoneInfo` gagal dan tanggal diam-diam kembali ke UTC.

**Index, bukan pindai (§6.2).** Semua yang dibaca layar datang dari `state/console.db`, dibagi
empat berkas: `repositories/console_repository.py` (query), skema dan migrasinya di
`repositories/console_skema.py`, akun di mixin `repositories/console_akun_repository.py` (batch 2),
dan jam gerbang di mixin `repositories/console_gerbang_repository.py` (aturan 37).
Konvensinya sama dengan `OutboxStore`: WAL, `synchronous=FULL`, satu `threading.Lock`,
`INSERT OR IGNORE` dengan kunci `event_id`. Layar polling tiap 2 detik lewat
`GET /api/console/state`; tidak ada `listdir` di jalur manapun.
Tabelnya: `inspections` (+ index `(work_date, line_code)` dan `(work_date, timestamp)`),
`trucks`, `suppliers`, `assignments`, `weighings`, `arrivals`, `sync_state`. Tiga index tambahan (batch 2.5):
`idx_inspections_assignment` (`inspections(assignment_id, timestamp)`, dipakai query per
penugasan), `idx_weighings_assignment` (`weighings(assignment_id)`), dan
`idx_auto_releases_waktu` (`auto_releases(released_at)`, dipakai pencarian pelepasan
terbaru). Dibangun sekali di boot pertama konsol sesudah upgrade, lewat
`CREATE INDEX IF NOT EXISTS`: sekitar 0,65 detik per bulan data (terukur di `inspections`
558 ribu baris, cache hangat, MacBook), sekitar 2,3 detik untuk tiga bulan. Boot berikutnya
cuma sekitar 0,001 detik karena index-nya sudah ada. Query panas yang sebelumnya `SCAN
inspections` turun dari sekitar 61 ms jadi sekitar 0,2 ms.

**Master data & Sumber TBS (§3.5b).** `MasterDataWorker` menarik dari **AutoERP**, bukan lagi
dari cloud api: `GET {ERP_URL}/api/resource/Supplier` lalu `.../Truck`, REST bawaan Frappe
dengan `Authorization: token <key>:<secret>`, `filters=[["modified",">",kursor]]`,
`order_by=modified asc`, 500 baris per halaman. **Nol kode di sisi ERP.** `ERP_URL` kosong =
worker mati diam-diam dan konsol jalan dari salinan terakhir.

Tiap DocType punya **kursornya sendiri** (`erp_cursor_supplier`, `erp_cursor_truck`): supplier
dan truk berubah dengan laju yang jauh berbeda, dan satu kursor bersama akan terus menyeret
yang sepi melewati baris yang sudah dilihat. Jendela tumpang tindih 5 detik dipertahankan,
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
lain. Grup supplier tetap disimpan **mentah** di `suppliers.source_group`, beda Plasma vs agen hidup
di situ. **Tidak ada boolean `is_internal` di manapun.**

**Per janjang tidak dikirim ke ERP.** Kontrak AutoERP §2 tegas: *"Not synced: per-bunch rows,
images"*. Janjang dan gambarnya tetap di edge sebagai bukti; AutoERP menerima **satu pesan per
kunjungan truk** (`upsert_visit`: timbang isi → grading selesai → timbang kosong). Karena itu
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
untuk truk), jadi satu truk yang diketik dua kali tetap **satu pesan berisi keadaan terbaru**,
bukan dua. Pesan yang diganti **saat masih di jalan** sengaja tidak ditandai terkirim
(`mark_sent` dan `mark_error` mencocokkan kolom `version`, yang naik di setiap antre),
supaya keadaan yang lebih baru tidak hilang. Yang dicocokkan generasinya, bukan isinya:
antrean ulang halaman R2 isinya selalu sama (`{"assignment_id": X}`) tapi tetap berarti
"bangun lagi". Kolom itu ditambahkan di tempat saat konsol pertama jalan; baris lama mulai
dari 0 dan tetap terkirim.

`integrations/erp/client.py` membedakan empat hal (batch 2.7), dan pemanggilnya bertindak beda:

| Balasan | Artinya | Yang dilakukan worker |
|---|---|---|
| 2xx (objek JSON Frappe) | mendarat | handler mencatat jawabannya (mis. `erp_name` truk), baris selesai |
| **4xx** (`ErpRejected`) | AutoERP **menolak isinya**: diulang pun sama | dicatat **dengan alasan dari Frappe**, backoff sendiri, batch lanjut ke pesan berikutnya |
| **5xx beramplop Frappe** (`ErpServerError`) | AutoERP **hidup**, tapi handler request ini yang crash | dicatat **dengan alasan dari Frappe**, backoff sendiri, batch lanjut, sama seperti penolakan |
| **jaringan / gateway / 5xx bukan-Frappe / 2xx bukan objek JSON** (`ErpUnavailable`) | AutoERP **tidak terjangkau**: tidak ada jawaban yang bisa dipakai | dicatat di baris kepala dengan backoff, batch **tertahan**, Last Sync membaca `terputus` |
| galat lain per pesan (exception tak terduga) | satu pesan bermasalah, bukan seluruh batch | dicatat + backoff, batch lanjut; `drain_once` sendiri tidak pernah melempar |

Backoff 30 detik → 1 jam (kontrak §5). Handler yang gagal mencatat di sisi kita juga menahan
pesannya: AutoERP sudah menerima, tapi kirim ulang aman (semua handler upsert) sedangkan
kehilangan jawabannya tidak.

**Kunjungan truk (§4.C).** Satu pesan per kunjungan, dikirim tiga kali saat kejadian yang
memang terjadi: **timbang isi**, **truk dilepas dari line**, dan **timbang kosong**. Plus
kirim ulang kunjungan kemarin sekali sehari (`VisitResendWorker`, penanda harinya di
`sync_state`) sebagai jaring pengaman.

`services/erp_queue.py` satu-satunya yang merakit pesan, pemicu langsung dan kirim ulang
memakai jalan yang sama, jadi keduanya tidak bisa berbeda isi. Payloadnya **dibangun ulang dari
store tiap kali**, tidak ditambal, sehingga kiriman yang antre di belakang tidak pernah membawa
keadaan lebih lama daripada barisnya.

| Hal | Aturannya |
|---|---|
| `visit_id` | id baris timbangan (uuid5 dari `ref`, atau plat + `waktu_masuk`) |
| `stage` | **diturunkan** dari keadaan: ada tara → `departed`, ada grading → `grading`, sisanya `gate` |
| bagian kosong | **tidak dikirim**: tiap kiriman mengganti bagian yang dibawanya, jadi bagian kosong menghapus isi ERP |
| grading | semua penugasan line yang tertaut ke tiketnya, dijumlah (`visit_assignments`, ditulis **saat truk dilepas**); tanpa tautan itu tiket kedua hari itu mewarisi janjang tiket pertama |
| kriteria | mentah = REJ, tangkai panjang = ACC dengan `tp_confidence > 0.8`, matang diturunkan AutoERP |
| `erp_ticket` | nomor Weighbridge Ticket jawaban AutoERP, disimpan balik ke baris timbangan |

⚠️ AutoERP **mengadopsi tiket terbuka milik truk yang sama** dalam jendela ±2 jam. Dua
kunjungan truk itu di jam yang sama karena itu mendarat di satu tiket, perilaku ERP, bukan bug
konsol. Dan tiket yang sudah punya berat bersih lalu menerima grading akan **difinalisasi**;
untuk buah Inti itu butuh Gudang Penerimaan TBS + Akun Pendapatan Transfer di Pengaturan PKS,
yang di situs demo belum diisi (AutoERP membalas 417 dan antrean menahannya dengan alasannya).

**Janjang susulan (batch 2.3).** Kamera line boleh mengirim janjang yang tiba **sesudah**
truknya dilepas: line offline sebentar, atau truk sudah timbang kosong sementara janjang
terakhir masih diproses. `ConsoleService.ingest` mendeteksinya lewat `add_inspection`: cuma
kalau baris itu **insert sungguhan** (bukan kiriman ulang `event_id` yang sudah ada), ia mencari
tiket timbangan milik penugasan itu (`weighing_for_assignment`) dan memanggil `ErpQueue.visit`
lagi, membangun ulang pesan kunjungan dari store seperti biasa. Kalau truknya **sedang ditimbang
kosong** (timbang kosong melepas semua lininya satu per satu), janjang susulan dan Lepas manual
**ditahan**: janjangnya dan tautannya tersimpan, tapi kunjungannya tidak diantre sampai line
terakhir lepas, supaya AutoERP tidak menerima tara dengan sebagian line. Timbang kosong lalu
mengantre sekali, dari store, termasuk semua yang tertahan.

Yang membedakan hasilnya cuma **kapan** AutoERP menerimanya, dan itu ditentukan §4.C step 4
di AutoERP sendiri (`upsert_visit`), bukan konsol:

- **Sebelum baris antrean lama berangkat**: `enqueue` mengganti baris `(kind, key)` yang sama
  (kunci alami = id kunjungan), jadi AutoERP menerima **satu kiriman** berisi seluruh janjang,
  tanpa ada yang ditandai. Ini kasus umum: sampai 8 janjang bisa menumpuk di antrean simpan
  line saat truk timbang kosong.
- **Sesudah tiket difinalisasi**: AutoERP menjawab `revised: true` + catatan, dan **tidak
  menulis ulang** bruto/neto/grading yang sudah dibukukan (`_after_finalisation`). Konsol
  menandainya untuk operator dan support: tab **Timbangan** menampilkan tag **Cek AutoERP** di
  baris truk itu (dibaca dari `erp_perlu_dicek` pada `GET /api/console/weighings`), dan tab
  **Log** mencatat satu WARNING `[TIKET_FINAL_BERBEDA]` (tiket yang sudah dibatalkan →
  `[TIKET_DIBATALKAN]`) menyebut apa yang berbeda dalam bahasa Indonesia dan rekap pabrik
  sekarang (`domain/jawaban_kunjungan.py`).

Tag Timbangan hidup selama **hari kerja itu saja** (dihitung ulang tiap query, tidak pernah
dibersihkan tindakan backoffice di AutoERP); jejak yang tahan lama adalah WARNING di tab Log
(retensi 180 hari, sama dengan `event_log` lain). WARNING dicatat **sekali per catatan AutoERP
yang berbeda**, bukan sekali per kirim ulang harian: kirim ulang harian yang menjawab catatan
sama persis lagi cuma mencatat INFO (`visit unchanged`). Harga yang disadari: janjang susulan
kedua yang sungguhan pada tiket yang sudah ditandai tidak menambah WARNING baru, tapi tag
Timbangan-nya tetap ada.

**Truk baru naik (§4.B).** Truk yang diketik operator dikirim ke
`erpnext.palm_mill.api.upsert_truck` dengan `plate_number` + `autograde_id`; AutoERP membuatnya
**tanpa pemilik** dan backoffice yang melengkapi. Jawabannya (`name`, dan `supplier` kalau ERP
sudah mengenal platnya) disimpan lewat `link_truck`, lalu tarikan berikutnya mengadopsinya jadi
truk ERP biasa. Supplier dan kelas **tidak** ikut dikirim, itu milik AutoERP.

`ERP_URL` kosong = worker pulang saat start dan menulis satu baris log. Itu default: jalur ini
tidak boleh jadi syarat hidupnya layar operator.

**Perintah ke line.** Konsol meneruskan ke endpoint line yang **sudah ada**
(`POST /internal/assignment`, `POST /internal/manual-reject`, `POST /internal/piston`, header
`x-internal-secret`: `INTERNAL_SECRET`, kosong = `WEBHOOK_SECRET`, lihat §5).
HTTP-nya duduk di `integrations/notifications/line_client.py`: satu-satunya bagian konsol yang
tahu soal httpx: dan `ConsoleService` menerimanya lewat konstruktor bersama `ConsoleStore`
(composition root: `get_console_service()` di `routes/console.py`). Line yang tidak menjawab
melempar `LineUnavailable` → route balas **502**, bukan diam. Registry line-nya nilai bertipe
(`Settings.console_lines` → `LineEndpoint`), dan `LINE_N_MACHINE_ID` dibaca **di Settings**,
bukan di service. `assign_truck` menunggu line menerima **sebelum** menyimpan: layar yang menampilkan truk
terpasang padahal line tidak tahu apa-apa membuat operator mengira sudah beres, dan tandan
berikutnya terhitung tanpa truk. Penugasan disimpan di SQLite, bukan memori (§6.4), jadi
selamat dari restart konsol di tengah shift.

**UI.** Satu file `src/palmgrade/static/console.html`: vanilla JS, tanpa build step, **tanpa
CDN** (harus tetap terbuka saat internet mati). Stream kamera pakai `<img>` MJPEG langsung ke
line di port 8001-8003, jadi tiga koneksi video ditanggung browser, bukan proses konsol. ~2200
baris React di frontend lama **diekspresikan ulang, bukan di-port**.

**Last Sync (2026-09-27).** Satu bagian di strip "Hari ini" dengan dua baris, **AutoERP** dan
**Cloud Photo**: jam = kapan data terakhir benar-benar tersinkron, warna = apakah sambungannya
hidup sekarang. Tidak ada endpoint baru: ringkasannya menumpang `/api/console/state` (field
`sinkron`), dan blok `unggah` tiap line menumpang `/internal/status` yang sudah di-poll tiap
detik. Semua worker yang bicara ke luar mencatat hasilnya ke satu `StatusSinkron`, dan
`CekSinkronWorker` mengecek AutoERP (`ping`) dan R2 (`head_object`) tiap 60 detik supaya warnanya
tetap segar saat tidak ada data yang lewat. Aturan lengkapnya `docs/rules.md` aturan 27.

**Login (Fase 4, §6.5).** Layar tertutup gerbang **email + sandi** sampai ada yang masuk, dan
**semua** `/api/console/*` menjawab 401 `belum_masuk` tanpa cookie `konsol_sesi`, kecuali
`/console` sendiri, daftar akun untuk mengisi kolom email, dan `login`. Akun datang dari dua
tempat: DocType **`AutoGrade Operator`** di AutoERP (ditarik §4.A) dan akun **lokal** di PC itu
(bawaan + support, supaya pabrik tanpa internet tetap bisa dibuka). Keduanya diverifikasi di
pabrik: yang ditarik `password_hash`-nya, bukan sandinya, dan itulah sebabnya field-nya `Data`
biasa: fieldtype `Password` hidup di `__Auth` yang Frappe sengaja tidak pernah layani lewat REST,
jadi tidak akan ada yang bisa ditarik. Dua skema berdampingan: `pbkdf2_sha256` milik AutoERP
(dibaca `hashlib` saja) dan `scrypt` untuk akun lokal. Sesi 12 jam (`sesi`), lockout berlipat dua
sesudah lima kali salah, dan `requested_by` Reject Manual sekarang nama operator yang masuk,
bukan lagi string `"operator"`. Akun lokal dibuat dari PC dengan `make operator`, dan sejak
2026-09-26 juga dari tab Akun (support) dengan aturan yang sama. Rincian aturannya di `docs/rules.md`
aturan 19.

**Impor grading dari CSV (2026-09-27, support).** Kebalikan Unduh CSV di tab Rekap: CSV Per janjang
dari konsol ini atau PC lain dibaca ulang jadi janjang (misalnya memindahkan riwayat ke PC baru, atau
memulihkan hari-hari yang terhapus Danger Zone). Periksa dulu, lalu impor berkas yang sama; janjang
hari ini tidak diimpor, yang sudah ada dilewati, dan satu impor bisa dibatalkan utuh. Janjang impor
tidak punya penugasan, jadi tidak pernah ikut pesan kunjungan ke AutoERP. Aturannya `docs/rules.md`
aturan 26.

**Belum termasuk Fase 2** (sengaja): timbangan brondolan lewat PLC (§6.6b, Fase 3), nomor dokumen
berprefiks lokal (§6.3), dan toggle tampil/sembunyi per line. Riwayat lintas hari dulu juga di
daftar ini ("urusan cloud"); sekarang ada di tab **Rekap** konsol (maks 31 hari per tampilan,
`docs/rules.md` aturan 26; tab Riwayat digabung ke Rekap 2026-09-28), karena cloud lama sudah mati
dan AutoERP cuma menerima rekap per truk.

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
punya test runner sendiri (tanpa build step, jadi tanpa Vitest): tidak ada handler `on*` inline,
tombol dipasang lewat delegasi + `data-line`, dan `esc()` tetap meloloskan `'` dan `` ` ``,
karena nilainya masuk ke atribut HTML.


## 12. System role, tech stack and project structure (moved from CLAUDE.md 2026-09-30)

## System Role

`autograde` is the **Python AI camera service plus the operator console**, one image run four
times: **3 line containers** (one per camera, real-time YOLO ripeness detection, ports
8001/8002/8003) and a **4th console container** (`APP_MODE=console`, `console_main.py`, no
torch/cv2 so a dead camera line never takes the operator screen down). The lines deliver
detection events to the **local console** (`BACKEND_URL`); the console sends one message per truck
visit to **AutoERP**. palmgrade-api and palmgrade-frontend are **retired** (stopped 2026-09-20).

Console port: **8100** in `docker-compose.prod.yml` (factory image; 8000 there belongs to the
Frappe bench) and for `make console` on a laptop; **8000** when started from source with
`docker-compose.yml` alone (`make up`). Screen at `http://localhost:<port>/console`.

| Repo | Role | Tech | Port |
|---|---|---|---|
| **autograde** | **AI camera per line + operator console** | **Python 3.11 / FastAPI** | **8001-8003, console 8100** |
| autoerp | ERP (ERPNext fork, module `palm_mill`): per-visit books, licences | Frappe | server |
| palmgrade-api / palmgrade-frontend | retired 2026-09-20 | Node / Next.js | stopped |

Full system map: `../ARCHITECTURE.md`.

⚠️ **Repo ini dulu bernama `palmgrade-vision`** (diganti 2026-09-14, bareng `autoerp` pindah
ke org `delta-anugrah`). Yang **sengaja tidak ikut berubah**, jangan "dirapikan":

- **Nama image GHCR `ghcr.io/delta-anugrah/autograde`**, satu nama, tanpa warisan (keputusan
  2026-09-18: semuanya pindah ke AutoGrade, PC Lampung ikut; `palmgrade-vision` **dicabut**).
  Dipatok di `deploy.yml` dan dijaga `tests/unit/test_deploy_image_name.py`. Di PC Lampung
  image itu dipilih `PALMGRADE_AUTOGRADE_IMAGE` di `/opt/palmgrade/autograde/.env` (folder dan
  variabel diganti dari `vision` 2026-09-18), dan dipasang dengan `autograde pull` atau
  `autograde use vX.Y.Z`, tidak pernah dengan mengedit variabel itu tangan.
- **Tag image lokal** `palmgrade-vision:latest` di `docker-compose.yml` + `Makefile`.
- **Paket Python** `src/palmgrade/` dan **nama container** di compose repo (`ripe_line_*`,
  `palmgrade_console`).

Yang dua terakhir baru berganti kalau memang ada alasan kuat: mengganti nama container membuat
Docker menganggapnya container baru dan bentrok dengan yang lama di PC pabrik.

---

## Tech Stack

- Python 3.11, **FastAPI** + uvicorn
- **Ultralytics YOLO** (YOLOv8 + ByteTrack); torch/torchvision (CPU for dev, CUDA `cu126` for prod)
- OpenCV, NumPy
- **httpx** (cloud upload + realtime push), **APScheduler** (hourly batch upload), **SQLite**
  (`outbox.db` = antrean realtime ke API lokal, di `state/` sejak batch 1 (dulu `artifacts/`, folder
  yang disajikan `/captures`); `UploadManifest` = state per-item batch R2), **boto3** (R2)
- **Hikrobot MVS SDK** (GigE industrial camera: prod only)
- **pymcprotocol** (MC Protocol ke CPU Mitsubishi, PLC integration, jalur hidup) + **pymodbus** (Modbus-TCP, jalur coupler ODOT lama, `PLC_PROTOCOL=modbus`); PC pabrik only, mati default
- **Docker-only** (no host venv). Deps pinned in `requirements.txt` (torch installed separately in Dockerfile).

---

## Project Structure (key dirs)

```
src/palmgrade/
  main.py          # app factory + lifespan: camera init, workers, 10s watchdog, /captures mount, /ws/results
  console_main.py  # app factory KONSOL (APP_MODE=console) — sengaja terpisah: tidak boleh import torch/cv2
  static/          # console.html — satu file, vanilla JS, tanpa build step & tanpa CDN (harus jalan offline)
  core/            # config.py (Settings/env), dependencies.py (DI), logging.py, constants.py
  routes/          # endpoint declarations only → controllers
  controllers/     # request handlers
  services/        # business flow (capture, inspection, streaming, truck, health, result)
  repositories/    # file I/O (WebP/JSON) via LocalFileStorage
  pipelines/       # YOLO inference (realtime_inspection_pipeline, model_registry)
  workers/         # background threads + RuntimeState (capture / display / processing / capture_save / event_broadcast / outbox_retry / batch_upload)
                   # capture_save = penulis bukti (encode WebP + sidecar + outbox) di thread sendiri; deteksi cuma menyerahkan, tidak pernah menunggu disk
                   # konsol pakai asyncio, bukan thread: master_data (tarik supplier + truk) / erp_outbox (kirim ke AutoERP) / visit_resend (kirim ulang kunjungan kemarin) — dirakit di workers/erp_link.py, mati total kalau ERP_URL kosong
  integrations/    # camera/{hikrobot,opencv,photo}, notifications/ (webhook_client → api, line_client → line dari konsol), storage/, scheduler/, upload/ (R2Uploader + UploadManifest), outbox/ (OutboxStore)
  domain/          # pure rules + entities (no I/O) — termasuk working_day.py (§6.1) & ffb_source.py (§3.5b)
  plc/             # PLC integration (MC Protocol ke CPU Mitsubishi; Modbus/ODOT dipertahankan via PLC_PROTOCOL), self-contained — mc_client.py + modbus_client.py isi lubang yang sama, build_plc_client memilih
  schemas/         # Pydantic request/response models
  license/         # Ed25519 license guard (opsional) — `manager` memverifikasi, `gate` menghentikan
                   # grading, `summary` membentuk angka untuk layar. Tokennya DITERBITKAN di AutoERP.
docs/              # MANUAL.md (+pdf), overview.md (DETAIL), backend-overview.md, SETUP.md, runbooks/
tests/unit/        # unit test murni-logic (pytest, no torch/cv2)
models/release/    # best.pt (required, NOT committed)
artifacts/line-N/  # runtime output per line (NOT committed)
```

Tooling: `pyproject.toml` (pytest + ruff config, TIDAK untuk build), `.github/workflows/ci.yml` (lint + test,
plus dipanggil `deploy.yml` sebelum image rilis mana pun dibangun).

Layer rule (strict): `route → controller → service → repository / pipeline / integration`.
Per-layer do/don't: `docs/overview.md`.
**Pengecualian sadar:** konsol jalan `route → service → repository / integration`, tanpa
controller: controller di repo ini isinya cuma meneruskan argumen, dan konsol tidak punya
logika yang butuh tempat menganggur di antaranya. HTTP ke line tetap di lapisan integration
(`notifications/line_client.py`), disuntik ke `ConsoleService` lewat konstruktor: service tidak
boleh tahu soal httpx, dan test menukar kolaboratornya, bukan menambal method privat.

---

