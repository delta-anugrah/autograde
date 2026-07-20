# Spec — Batch Upload Hasil Deteksi ke Cloud (R2 + DB), Hourly & Durable

- **Tanggal:** 2026-07-10
- **Status:** Draft — menunggu review user
- **Repo terdampak:** `palmgrade-vision` (utama), `palmgrade-api` (1 file util), `palmgrade-frontend` (tanpa perubahan kode)

## 1. Latar belakang & tujuan

`palmgrade-api` + `palmgrade-frontend` dideploy ke droplet DigitalOcean; `palmgrade-vision` tetap on-prem di PC pabrik. Volume `captures_data` di cloud kosong (vision nulis gambar di disk pabrik), jadi FE cloud tidak bisa menampilkan gambar hasil deteksi.

**Tujuan:** hasil deteksi (teks) + gambar terunggah **bersamaan sebagai satu unit, tiap jam**, dari PC pabrik → gambar ke Cloudflare R2, teks ke DB cloud via API cloud.

**Dua audiens:**

- **Operator pabrik** — realtime hari-ini dari stack lokal (vision + API lokal + FE lokal), tidak butuh internet. Tidak berubah.
- **Bos** — data historis (delay ±1 jam) dari FE cloud, gambar diserve dari R2.

**Syarat ketahanan (non-negotiable):** internet mati **berapa lama pun** (72 jam cuma contoh — bisa kurang, bisa lebih) → nol data hilang, nol duplikat saat pulih. Satu-satunya batas = kapasitas disk PC pabrik (besar, bukan concern).

## 2. Keputusan arsitektur (locked)

```
PC PABRIK (per line — 3 instance vision, MACHINE_ID beda)
  frame_processing_worker
    ├─ tulis .webp + .json ke artifacts/results/...          (sudah ada, tetap)
    ├─ event_queue → webhook realtime API LOKAL              (TETAP — operator realtime + DB lokal)
    └─ enqueue outbox → /internal/vision/events API LOKAL    (DI-COMMENT, kode disimpan utuh)
  batch_upload_worker (BARU — APScheduler, tiap jam)
    ├─ scan artifacts/results → manifest SQLite
    ├─ upload gambar → R2 (boto3, S3-compatible)
    └─ POST teks → /internal/vision/events API CLOUD → Postgres cloud

CLOUD (droplet 188.166.178.75)
  API + Postgres + FE  ←  bos akses historis; <img src> langsung ke R2 public URL
```

- **1 item = 1 unit**: JSON ripeness (+ JSON tp ber-timestamp sama, kalau ada) + gambar → 1 PUT R2 + 1 POST API.
- **Urutan wajib per item: gambar dulu, teks belakangan.** Row DB tidak pernah menunjuk gambar yang belum ada di R2.
- **Outbox lama di-comment, bukan dihapus** — blok enqueue di `frame_processing_worker` dan startup `OutboxRetryWorker` di `main.py`, keduanya diberi penanda `# [DISABLED: batch-upload-r2 — lihat spec 2026-07-10]`. Modul `integrations/outbox/` tetap utuh. Rollback = uncomment.
- **Kanal webhook realtime lokal TIDAK disentuh** (`event_queue` → `/webhooks/qualitycontrols` API lokal) — operator tetap dapat SSE + history lokal seperti sekarang.
- R2 dipakai sebagai **public bucket + custom domain** (mis. `img.palmgrade.ai`). Kredensial & domain = **placeholder** di fase ini.

## 3. Komponen baru di `palmgrade-vision`

### 3.1 `integrations/upload/upload_manifest.py` — manifest SQLite

File DB: `artifacts/upload_manifest.db` (sejajar konvensi outbox; dibuat via factory ala `get_outbox_store()`). Pragma **WAL + `synchronous=FULL`** — sama persis dengan `outbox_store.py` yang sudah terbukti di prod, tahan mati listrik.

```sql
CREATE TABLE IF NOT EXISTS upload_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key      TEXT NOT NULL UNIQUE,  -- path relatif JSON (selalu ada & unik, termasuk item tanpa truck)
    event_id      TEXT,                  -- uuid5(NAMESPACE_URL, "{machine_id}:{timestamp}") — rumus sama dgn outbox
    image_path    TEXT,                  -- NULL untuk item TP-only
    r2_key        TEXT,
    status        TEXT DEFAULT 'pending',-- pending | image_uploaded | done | poisoned
    retry_count   INTEGER DEFAULT 0,
    next_retry_at REAL DEFAULT 0,
    last_error    TEXT,
    discovered_at REAL,
    uploaded_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_upload_status ON upload_items (status, next_retry_at);
```

**State machine:**

```
pending ──PUT R2 ok──▶ image_uploaded ──POST API ok──▶ done ──retensi──▶ file + row dihapus
   │ └─(item tanpa gambar: langsung POST)──────────────▶ done
   └─input cacat (JSON korup / file gambar hilang)─────▶ poisoned  (di-skip, file TIDAK dihapus)

error jaringan di state mana pun → state TIDAK berubah; retry_count++, next_retry_at = backoff
```

- Scan pakai `INSERT OR IGNORE` → scan berulang idempoten, nol duplikat.
- Pasangan `{ts}_auto_ripeness.json` + `{ts}_auto_tp.json` (timestamp identik — ditulis dalam frame yang sama) digabung jadi 1 item saat discovery; tp yang pasangannya belum `done` ikut digabung. JSON tp tanpa pasangan = item sendiri tanpa gambar. Kalau tp telat muncul setelah item ripeness `done` (praktis ~0, beda milidetik vs tick per jam), ia jadi item sendiri → POST kedua ber-`event_id` sama dibalas `already_processed` → tetap nol duplikat.

### 3.2 `integrations/upload/r2_uploader.py` — klien R2 bodoh & stateless

- boto3 S3 client, `endpoint_url = https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com`.
- Satu method utama: `put(local_path, r2_key)` → PUT object (content-type `image/webp`). Tanpa state, tanpa retry sendiri — retry urusan manifest.
- **`r2_key` deterministik**: `{MACHINE_ID}/{image_path tanpa prefix "captures/"}` → mis. `SIT-L1/results/2026-07-10/{ts}_auto.webp`. Path sama = key sama = re-upload menimpa dirinya sendiri (S3 PUT overwrite) → tidak pernah ada file dobel di R2. Prefix `MACHINE_ID` menjamin 3 line tidak saling tabrak.
- URL publik yang dikirim ke API: `{R2_PUBLIC_URL}/{r2_key}`.

### 3.3 `workers/batch_upload_worker.py` — orkestrasi per tick

```
run_batch_once():
  1. scan results dir → INSERT OR IGNORE item baru ke manifest
  2. ambil item status IN (pending, image_uploaded) AND next_retry_at <= now
     ORDER BY discovered_at ASC LIMIT UPLOAD_MAX_ITEMS_PER_TICK
  3. per item:
       a. pending & punya gambar → PUT R2 → status = image_uploaded
       b. rekonstruksi payload dari JSON disk → POST API cloud → status = done
       c. error kelas requeue (jaringan/5xx/401/403 — tabel §5) → requeue
          item ini, BREAK (kondisi eksternal lagi rusak, percuma lanjut;
          sisa antrean nunggu tick berikut)
       d. input cacat → poisoned, CONTINUE (satu item busuk tidak
          menyandera batch)
  4. retensi: item done dgn uploaded_at > UPLOAD_RETENTION_DAYS hari
     → hapus gambar+JSON lokal, lalu hapus row
```

**Payload POST** direkonstruksi penuh dari JSON disk: `event_id` (dihitung ulang, deterministik), `machine_id` (env), `timestamp`, `image_path` = URL R2 penuh, `ripeness_status/confidence`, `tp_status/confidence`, `capture_type`, `truck_id`, `bounding_box`, `assignment_id` (field baru di JSON — §4.1), `prediction` diturunkan dari `ripeness_status`. Header auth internal sama seperti dispatcher outbox sekarang, tapi nilai `UPLOAD_API_SECRET`, target `UPLOAD_API_URL`.

### 3.4 Scheduler

`integrations/scheduler/upload_scheduler.py` **diganti total** (isi lama = archiver `copytree`+`rmtree` lokal, berbahaya untuk alur R2 dan tidak dipakai lagi). Isi baru: APScheduler `BackgroundScheduler` + `CronTrigger(minute=UPLOAD_MINUTE)` → tiap jam, `max_instances=1` + `coalesce=True` (tick sebelumnya belum kelar → tick baru di-skip, tidak numpuk). Kalau `R2_BUCKET` kosong → worker start tapi tick no-op dengan warning sekali per start (berfungsi sebagai saklar off untuk dev).

## 4. Perubahan pada kode yang sudah ada

### 4.1 `workers/frame_processing_worker.py`

1. **`_save_ripeness` & `_save_tp`: +1 field `assignment_id`** ke dict `meta` yang ditulis ke JSON. Nilai = assignment aktif yang sama dengan yang sekarang dikirim ke payload outbox (boleh `None` → ditulis `null`). Tanpa ini batch worker tidak bisa merekonstruksi payload lengkap — di alur lama `assignment_id` cuma lewat outbox yang kini di-comment.
2. **Blok enqueue outbox (±baris 307-334) di-comment** dengan penanda. Push `event_queue` (±baris 300-305) **tidak disentuh**.
3. `event_id` dan `prediction` **tidak** disimpan ke JSON — keduanya derivable (uuid5 deterministik; prediction dari status). Disk hanya menyimpan yang tidak bisa direkonstruksi.

### 4.2 `main.py`

- Startup `OutboxRetryWorker` (±baris 140-147) di-comment dengan penanda yang sama.
- Start `batch_upload_worker` + scheduler-nya.

### 4.3 `core/config.py`

Lihat tabel env §6. Tambahan: kalau `APP_ENV=production` dan `R2_BUCKET` kosong → **warning** (bukan crash — sistem memang boleh jalan lokal-only dulu selama R2 belum ada). `destination_upload` dan `upload_hour` dihapus dari `Settings` (§6).

### 4.4 `palmgrade-api` — `src/utils/captureUrl.ts`

Guard 3 baris di awal `resolveCaptureUrl`: `image_path` yang sudah URL absolut (`/^https?:\/\//i`) dikembalikan apa adanya. Sisanya (path relatif legacy) tetap dirakit ke `{apiPrefix}/captures/{lineCode}/...` seperti sekarang → **backward-compatible**: row lama tetap jalan, row baru (URL R2) lewat langsung.

### 4.5 Checkpoint validasi endpoint (tugas implementasi, bukan ambiguitas)

Pastikan `/internal/vision/events` di `palmgrade-api` menerima `image_path` berupa URL absolut. Kalau ada validasi yang menolak (mis. regex path relatif), longgarkan di PR API yang sama dengan §4.4.

## 5. Error handling & ketahanan

**Prinsip: tahan durasi outage berapa pun — beda dari outbox lama.** Outbox lama punya `_MAX_RETRIES=50` → dead-letter setelah ±8 jam. Manifest **tidak punya batas retry, tidak punya TTL, dan tidak pernah menghapus file sebelum `done`**. Data menunggu di disk selamanya sampai terkirim.

**Klasifikasi error:**

| Error | Aksi |
|---|---|
| ConnectionError / timeout / 5xx / 429 | requeue tanpa batas — backoff eksponensial, cap 600 dtk (angka sama dgn outbox) |
| 401 / 403 dari API | requeue + log ERROR (secret salah → benerin `.env`, antrean jalan lagi sendiri) |
| 400 / 422 dari API | `poisoned` (payload cacat — retry tidak akan menolong) |
| Respons `already_processed` | sukses — lanjut `done` |
| JSON korup / field wajib hilang / file gambar hilang | `poisoned`, file TIDAK dihapus (bisa diperiksa manual), item lain jalan terus |

**Anti-duplikat 3 lapis** (semua deterministik, tidak butuh koordinasi):

1. **Manifest** — item `done` tidak pernah diproses ulang; scan `INSERT OR IGNORE`.
2. **R2** — key deterministik dari path → re-upload = overwrite objek yang sama, bukan file baru.
3. **API/DB** — `event_id` = uuid5 deterministik → POST ulang dibalas `already_processed`, tidak ada row kedua.

**Mati listrik (crash kapan pun):** WAL + `synchronous=FULL` menjamin state manifest selamat. Skenario terburuk — mati persis setelah PUT R2 sukses tapi sebelum status tersimpan → restart mengulang PUT (overwrite, tidak dobel) lalu lanjut normal. Mati setelah `image_uploaded` → restart langsung lanjut POST teks, gambar tidak di-upload ulang.

**First-run backfill:** scan pertama menemukan seluruh backlog file lama di `results/` → diproses bertahap `UPLOAD_MAX_ITEMS_PER_TICK` per jam sampai habis. Aman: DB cloud masih kosong, dan kalaupun ada yang pernah terkirim, idempoten.

**Catatan operasional (bukan risiko):** selama outage, disk tumbuh sebesar produksi harian gambar WebP — PC prod punya storage besar, retensi 7 hari berjalan lagi otomatis begitu item `done`.

## 6. Konfigurasi — `.env` `palmgrade-vision`

Semua nilai tunable lewat env, pola `os.getenv` + default di `config.py` (konsisten dgn yang sudah ada):

| Var | Default | Keterangan |
|---|---|---|
| `R2_ACCOUNT_ID` | `""` | **placeholder** — diisi saat bucket dibuat |
| `R2_ACCESS_KEY_ID` | `""` | **placeholder** |
| `R2_SECRET_ACCESS_KEY` | `""` | **placeholder** — tidak pernah di-commit |
| `R2_BUCKET` | `""` | **placeholder**; kosong = uploader no-op (saklar off) |
| `R2_PUBLIC_URL` | `""` | **placeholder** — mis. `https://img.palmgrade.ai` |
| `UPLOAD_API_URL` | `""` | **placeholder** — base URL API cloud, mis. `https://api.palmgrade.ai` (BARU — target POST teks; `BACKEND_URL` tetap menunjuk API lokal) |
| `UPLOAD_API_SECRET` | `""` | **placeholder** — `WEBHOOK_SECRET` milik API cloud |
| `UPLOAD_MAX_ITEMS_PER_TICK` | `2000` | throttle per tick (Q1-A) |
| `UPLOAD_RETENTION_DAYS` | `7` | umur file lokal setelah `done` (Q2-A) |
| `UPLOAD_MINUTE` | `0` | (sudah ada) menit ke-berapa tiap jam batch jalan |
| ~~`UPLOAD_HOUR`~~ | — | **dihapus** — jadwal hourly tidak butuh jam; ikut keluar bareng scheduler lama |
| ~~`DESTINATION_UPLOAD`~~ | — | **dihapus** — archiver lokal lama tidak dipakai lagi |

`.env.example` di-update mengikuti tabel ini. Dependensi baru: `boto3` (runtime), tanpa `moto` (test pakai `unittest.mock` murni).

## 7. Testing

Semua test jalan **tanpa jaringan & tanpa kredensial** — R2 dan HTTP client di-inject lalu di-mock. SQLite pakai `tmp_path` asli (bukan mock). Target ±18-20 test baru di vision + 2 di API.

**7.1 Manifest state machine** — `test_scan_idempotent` (scan 2× → 0 duplikat), `test_state_transitions` (urutan legal), `test_resume_after_image_uploaded` (restart lanjut dari teks, gambar tidak re-upload), `test_done_never_reprocessed`, `test_poisoned_isolated` (file tidak dihapus, item lain jalan), `test_tp_merged_into_ripeness` (1 item = 1 POST).

**7.2 Simulasi outage** — `test_network_error_requeues` (status balik pending, tanpa dead-letter), `test_no_retry_cap` (gagal 100× tetap pending — inilah "tahan durasi apa pun"), `test_batch_break_not_abort` (item ke-3 dari 5 gagal → 1-2 tetap done, sisa nunggu tick depan), `test_recovery_uploads_all` (50 item numpuk → R2 "nyala" → semua done, 50 key unik).

**7.3 Simulasi mati listrik** — `test_crash_mid_batch_no_partial_write` (`os._exit` di tengah loop → DB konsisten), `test_wal_survives_reopen`.

**7.4 Anti-duplikat** — `test_uuid5_deterministic`, `test_r2_key_deterministic`; lapis manifest sudah tercakup di 7.1.

**7.5 API (runner sesuai setup repo)** — `resolveCaptureUrl` URL absolut → passthrough; path relatif → dirakit seperti lama.

**Tidak di-test (sengaja):** R2 asli (smoke test manual nanti saat bucket ada), timing APScheduler (cukup panggil `run_batch_once()` langsung), FE (tidak berubah).

## 8. Di luar cakupan

- Pembelian domain / pembuatan bucket R2 / kredensial asli — menyusul; spec ini jalan penuh dengan placeholder.
- Perubahan `palmgrade-frontend` — FE cuma merender URL yang diberikan API.
- Penghapusan permanen jalur outbox — hanya di-comment.
- Dashboard monitoring uploader — cukup log + query manual ke `upload_manifest.db`.

## 9. Prasyarat & alur implementasi

1. **Sebelum kode apa pun ditulis:** branch backup dari `staging` di **ketiga** repo — `backup/staging-pre-batch-upload` (palmgrade-vision, palmgrade-api, palmgrade-frontend; FE ikut di-backup sesuai permintaan walau tidak berubah).
2. Feature branch dari `staging` per repo → PR ke `staging` (konvensi proyek).
3. Kredensial R2 tidak pernah masuk git — `.env` di-gitignore (sudah), `.env.example` hanya placeholder.

## 10. Kriteria penerimaan

- [ ] Simulasi outage (mock gagal N tick lalu pulih) → semua item `done`, R2 menerima key unik per gambar, DB tidak punya row duplikat (`already_processed` terverifikasi di test).
- [ ] Kill process di tengah batch → restart → lanjut tanpa upload/POST dobel.
- [ ] Item JSON korup → `poisoned`, file utuh, item lain tetap terkirim.
- [ ] Backlog > `UPLOAD_MAX_ITEMS_PER_TICK` terkuras bertahap lintas tick, urutan tertua-dulu.
- [ ] Kanal realtime lokal (webhook + SSE operator) tetap berfungsi persis seperti sebelum perubahan.
- [ ] File lokal tidak pernah terhapus sebelum `done` + lewat retensi; `poisoned` tidak pernah terhapus.
- [ ] `resolveCaptureUrl` lulus dua kasus (absolut passthrough, relatif legacy).
- [ ] CI vision & API hijau tanpa akses jaringan/kredensial.
