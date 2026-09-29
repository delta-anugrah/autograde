# Backend Overview: autograde

Tabel lengkap endpoint, payload event, dan variabel lingkungan `autograde`. Alur di dalamnya
(worker, deteksi, garis capture, upload R2, invariant, layout artifacts, konsol): `docs/overview.md`.

## Tujuan Project

Menerima feed kamera industri Hikrobot, menjalankan model YOLO secara realtime,
mengklasifikasi kematangan buah sawit (4 kelas), menyimpan hasil inspeksi ke disk sebagai
bukti, dan mengirimnya lewat **dua jalur**: realtime per janjang ke **konsol operator** di PC
yang sama (`OutboxRetryWorker` → `BACKEND_URL`, poll 1 detik) dan foto **tiap jam** ke
Cloudflare R2 (`BatchUploadWorker`). Konsol yang bicara ke AutoERP: satu pesan per kunjungan
truk, tidak pernah per janjang. palmgrade-api dan palmgrade-frontend pensiun 2026-09-20.

Dijalankan sebagai **3 container line** (line 1/2/3, masing-masing satu port dan satu kamera)
plus **konsol**, instance ke-4 dari image yang sama (`APP_MODE=console`, tanpa kamera/GPU/PLC).

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Framework | FastAPI |
| Server | Uvicorn |
| Model inference | Ultralytics YOLO (YOLOv8), TensorRT engine per GPU |
| Computer vision | OpenCV |
| Deep learning | PyTorch |
| Camera SDK | MvImport (Hikrobot proprietary) |
| PLC | pymcprotocol (MC Protocol), pymodbus (jalur lama) |
| HTTP client | httpx |
| Scheduler | APScheduler |
| Config | python-dotenv + dataclass |
| Schema validation | Pydantic |
| Penyimpanan | berkas WebP + JSON (bukti), SQLite (outbox, manifest, konsol) |

---

## Folder Structure

```
autograde/
  src/
    palmgrade/
      main.py                  # FastAPI app line: middleware + lifespan + worker
      console_main.py          # FastAPI app konsol (APP_MODE=console), tanpa torch/cv2
      static/                  # console.html (layar operator), viewer.html

      routes/                  # Hanya deklarasi endpoint dan router wiring
      controllers/             # Terima request, panggil service, return response
      services/                # Orchestration dan business flow
      repositories/            # Baca/tulis file (JSON, WebP) dan store SQLite konsol
      pipelines/               # Logic YOLO inference + frame processing
      integrations/
        camera/                # HikrobotCamera / OpenCVCamera / PhotoCamera
        erp/                   # klien AutoERP + antrean kirim (erp_outbox)
        notifications/         # LineClient (konsol → line); WebhookClient lama
        outbox/                # OutboxStore: antrean realtime ke konsol
        storage/               # LocalFileStorage (read/write JSON + WebP)
        upload/                # R2Uploader (boto3) + UploadManifest (SQLite state per-item)
        scheduler/             # UploadScheduler: APScheduler cron, tiap jam @ UPLOAD_MINUTE
      plc/                     # MC Protocol / Modbus, pulse, heartbeat (docs/plc-integration.md)
      workers/                 # Background threads + asyncio tasks
      domain/                  # Business rule murni, tidak ada I/O
      schemas/                 # Pydantic request/response schemas
      core/                    # Config, logging, constants, DI wiring
      license/                 # License guard (Ed25519 JWS, optional)

  config/camera/hikrobot.mfs   # setelan kamera yang dimuat tiap connect
  images/                      # sample_sawit.jpg: gambar contoh untuk sumber Foto
  media/                       # berkas video/foto untuk sumber kamera per line
  models/release/              # Model .pt produksi: tidak di-commit ke git
  engines/                     # Engine TensorRT per GPU: tidak di-commit ke git
  artifacts/, state/           # Output runtime: tidak di-commit ke git
  docker-compose.yml           # line-1 (8001), line-2 (8002), line-3 (8003) + console (8000)
  docker-compose.prod.yml      # override pabrik: image immutable, konsol di 8100
  .env / .env.example, media.env / media.env.example
```

Batas tiap layer (boleh / tidak boleh): `docs/overview.md` §1.

---

## Detection Model

1 model per line (bawaan `best.pt`) mendeteksi 4 kelas sekaligus. Pemetaan kelas → verdict
hidup di satu tempat, `domain/grade_class.py`:
- `Ripe`: matang → ACC
- `Unripe`: mentah → REJ
- `JK`: janjang kosong → REJ
- `TP`: tangkai panjang, bukan janjang → tanpa verdict (menempel di `tp_confidence`)

Model dipilih per line dari konsol tab **Line → Model Deteksi** (`LINE_N_MODEL_FILE` di
`media.env`; kosong = `MODEL_FILE` di `.env`). Model yang kelasnya bukan tepat empat kelas
itu tidak bisa dipilih. Kelas diperiksa lagi oleh line saat boot, untuk jalur `.pt` maupun
engine TensorRT. Runbook: `docs/runbooks/2026-09-24-model-deteksi-per-line.md`.

Kapan janjang difoto (garis capture, ROI, `MINIMUM_SIZE`, pasangan TP ↔ janjang, single-trigger
per `track_id`): `docs/overview.md` §3.

---

## Endpoint line (port 8001 / 8002 / 8003)

### Publik (tanpa auth)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/video_feed` | MJPEG (`multipart/x-mixed-replace; boundary=frame`). Dimuat langsung oleh `<img src>` di konsol, jadi tidak bisa diberi header auth: dijaga firewall (`docs/SETUP.md` §10) |
| GET | `/api/results_today` | Hasil grading hari ini dari `_ripeness.json` di `artifacts/results/{tanggal}/` (`_tp.json` lama masih dibaca). Warisan palmgrade-frontend; konsol tidak memakainya |
| GET | `/health` | Hidup/tidak; dipakai healthcheck compose dan launcher |
| GET | `/health/detail` | Status operasional, lihat di bawah |
| WS | `/ws/results` | Push event per deteksi. Legacy: masih aktif, tidak ada pemakai di repo ini (konsol polling `/api/console/state`) |

### `GET /health/detail`

```json
{
  "status": "ok",
  "environment": "production",
  "camera_type": "hikrobot",
  "camera_connected": true,
  "plc": {
    "inputs": [false, false, false, false, false, false, false, false,
               false, false, false, false, false, false, false, false],
    "dropped_pulses": 0,
    "dropped_submissions": 0,
    "piston": null
  },
  "gpu_available": true,
  "gpu_device": "NVIDIA GeForce RTX 3060",
  "machine_id": "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01",
  "workers": [
    { "name": "capture", "alive": true },
    { "name": "display", "alive": true },
    { "name": "processing", "alive": true },
    { "name": "capture_save", "alive": true }
  ],
  "outbox_pending": 0,
  "outbox_failed": 0,
  "capture_save_pending": 0,
  "capture_save_dropped": 0,
  "tp_telat": 0,
  "current_assignment_id": "uuid-or-null",
  "last_successful_api_push": null,
  "model_file": "best.pt",
  "model_backend": "tensorrt",
  "model_kelas": ["JK", "Ripe", "TP", "Unripe"],
  "model_kelas_cocok": true,
  "gpu_sm": "86"
}
```

| Field | Artinya |
|---|---|
| `camera_type` | sumber yang **benar-benar** dipakai line (dari `media.env`), bukan `printenv` container |
| `outbox_pending` / `outbox_failed` | backlog jalur realtime ke **konsol** (`BACKEND_URL`). Naik terus = konsol tidak menjawab. **Bukan** backlog upload R2. `outbox_pending` `null` = tidak diketahui (lihat baris berikut) |
| `outbox_lama_tertinggal` | `true` = `artifacts/outbox.db` dari sebelum batch 1 gagal diserap ke `state/` (berkas rusak, disk penuh): barisnya belum terkirim dan tidak terhitung, jadi `outbox_pending` dilapor `null`. Danger Zone menahan hapus data (`outbox_lama`); restart line itu untuk mencoba lagi, lalu baca log line-nya |
| `capture_save_pending` | janjang yang menunggu ditulis `CaptureSaveWorker` (antrean 8 dalam). Naik terus = disk/CPU tidak mengimbangi laju grading |
| `capture_save_dropped` | **harus NOL.** Janjang yang dibuang karena antrean penuh: sudah dapat pulse PLC dan sudah masuk rekap, tapi **tidak punya gambar maupun sidecar**, jadi `BatchUploadWorker._scan()` tidak akan pernah menemukannya |
| `tp_telat` | **harus NOL.** TP yang muncul sesudah janjang terdekatnya difoto, jadi tangkainya tidak ikut ke mana pun |
| `last_successful_api_push` | waktu POST terakhir yang sukses ke konsol; `null` = belum pernah sejak start |
| `workers[]` | memuat `outbox_retry` dan `plc` (kalau aktif), tapi **tidak** `BatchUploadWorker`: itu job APScheduler, jadi watchdog `_watchdog` tidak memantaunya |
| `plc` | `null` kalau `PLC_ENABLED=false`. `inputs` = offset dari `PLC_DI_BASE` (0–10 motor fault, 11 E-stop); dua counter drop **naik monoton**, yang berarti selisih antar-polling. Detail: `docs/plc-integration.md` |
| `model_*`, `gpu_sm` | model yang **benar-benar dimuat** line ini, bukan pilihan di `media.env`. `model_kelas_cocok: false` = line **tidak menghitung janjang** (layar Model Deteksi menulisnya merah); `null` = tidak diketahui. `gpu_sm` = compute capability (nama engine `<model>.sm<cc>.engine`), `null` di CPU |

Backlog upload R2 tidak ada di sini: lihat blok `unggah` di `GET /internal/status`, atau query
`state/upload_manifest.db` (`SELECT status, COUNT(*) FROM upload_items GROUP BY status`).

### `/internal/*` (header `x-internal-secret` = `INTERNAL_SECRET`, kosong = `WEBHOOK_SECRET`)

Dipanggil konsol, tidak pernah oleh browser. Perbandingan constant-time dan fail closed:
secret yang dikonfigurasi kosong tidak pernah membuka lane (`routes/penjaga_rahasia.py`).

| Method | Path | Notes |
|---|---|---|
| POST | `/internal/assignment` | `{machine_id, assignment_id, truck_id, assigned_at, ffb_source?, plate?}` → `{accepted, machine_id, truck_id, assignment_id}`. Set `current_truck_id` + `current_assignment_id`; `plate` + `assigned_at` menamai folder capture truk (`domain/capture_layout.py`). ⚠️ `plate` itu label, bukan identitas; opsional supaya konsol lama tidak ditolak saat upgrade separuh jalan |
| GET | `/internal/status` | Dipanggil tiap 1 detik (`LineStatusWorker`) → `{machine_id, truck_id, ffb_source, piston, alarms, unggah}`. `unggah` = ringkasan upload R2 untuk **Last Sync** (`aktif`, `terakhir`, `gagal_sejak`, `pesan`, `antre`, `rusak`), dihitung sekali per batch; `null` sebelum worker upload ada |
| POST | `/internal/manual-reject` | `{machine_id, assignment_id, requested_by, requested_at}` → `{accepted, message}`. `capture_manual_reject()` lewat executor: WebP + JSON + satu baris outbox, sampai di konsol ~1 detik |
| GET / POST | `/internal/setelan` | Setelan grading yang berlaku / timpa tanpa restart (`conf_threshold`, `minimum_size`, `garis_capture`, `sumbu_garis`, `mode_dev`). Disimpan di `RuntimeState`; konsol pemegang nilai sebenarnya |
| POST | `/internal/outbox/requeue` | Antre ulang baris outbox yang gagal |
| POST | `/internal/piston` | Piston manual (fitur mati selama `PLC_COIL_MANUAL` kosong) |
| GET | `/internal/plc` | Snapshot DI + coil yang boleh diuji |
| POST | `/internal/plc/coil` | Picu satu coil uji; ditolak 409 selama line punya truk terpasang |
| POST | `/internal/restart` | Keluar sesudah 1 detik (`os._exit`), `restart: unless-stopped` menyalakan lagi dan line membaca ulang `media.env` |
| POST / GET | `/internal/rekam/mulai`, `/stop`, `/status` | Rekam video developer (tab Line → Rekam Video) ke `REKAMAN_DIR` |
| GET / POST | `/internal/rekam/berkas`, `/internal/rekam/hapus` | Hitung / hapus rekaman line ini (Danger Zone); hapus ditolak selama merekam |
| POST | `/internal/hapus-data` | Danger Zone: tulis penanda lalu keluar, data dihapus saat boot berikutnya. 409 `truk_terpasang` kalau line sedang memproses truk |

### Dihapus

`POST /api/set_truck` dan `POST /api/capture_reject` dihapus 2026-09-20 (#122, #123): nol
pemanggil, dan keduanya tanpa auth. Penggantinya `/internal/assignment` (yang juga menetapkan
`current_assignment_id`) dan `/internal/manual-reject`. Dijaga
`tests/unit/test_jalur_set_truck_dibuang.py`.

---

## Endpoint konsol (`APP_MODE=console`; port 8100 di PC pabrik dan `make console`, 8000 di compose dev)

### Lane mesin (header `x-webhook-secret`, prefiks `BACKEND_API_VER`)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/internal/vision/events` | Event per janjang dari tiga line (kontrak beku, sama dengan palmgrade-api dulu). 401 secret salah, 400 payload cacat (outbox line menandainya gagal) → 201 `{status, work_date}` |
| GET | `/api/v1/internal/setelan` | Setelan grading, dibaca line saat start |
| GET | `/api/v1/internal/penugasan?machine_id=` | Truk terpasang untuk satu line, dibaca line saat start |
| POST | `/api/v1/internal/scale/weighing` | Payload program timbangan (`plate_number`, `gross_kg`, `tare_kg`, `entered_at`, `exited_at`, `ref?`); format sebenarnya belum diketahui |

### Lane operator (butuh sesi login)

| Method | Path | Notes |
|---|---|---|
| GET | `/console` | Halaman `console.html` |
| GET | `/api/console/operators` | Daftar akun untuk kolom email (tanpa hash), bisa dibaca sebelum masuk |
| POST | `/api/console/login`, `/api/console/logout` · GET `/api/console/me` | Sesi cookie `konsol_sesi`, 12 jam |
| GET | `/api/console/state` | Ringkasan hari kerja + langganan + `sinkron` (Last Sync); layar polling tiap 2 detik |
| GET | `/api/console/history` | Janjang per hari kerja (`work_date`, `line_code`, `truck_id`, `limit` ≤ 200) |
| GET / POST | `/api/console/trucks` | Daftar truk / truk ketik operator (masuk antrean ERP) |
| POST | `/api/console/scan`, `/api/console/scan/keluar` | Scan QR gerbang masuk / keluar |
| GET | `/api/console/trucks/{plate_number}/qr.png` | Kartu QR, dibuat server |
| GET / POST | `/api/console/weighings` | Timbangan; bruto/tara di bawah 1.000 kg ditolak (`MINIMUM_WEIGHT_KG`). Baris GET membawa `erp_perlu_dicek` (`tiket_final_berbeda` / `tiket_dibatalkan` / null, batch 2.3) |
| GET | `/api/console/recap` | Rekap per truk satu hari. Tidak dipanggil layar sejak tab digabung 2026-09-28; endpoint tetap |
| POST | `/api/console/lines/{line_code}/assign-truck`, `/release-truck`, `/manual-reject`, `/piston` | Diteruskan ke `/internal/*` line; line yang tidak menjawab → 502 |

### Rekap (tab Rekap, 2026-09-26; dulu tab Riwayat)

Lane operator biasa (butuh sesi, **bukan** `require_support`), kecuali impor. Rinciannya:
CLAUDE.md, Critical Rule 26.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/console/riwayat` | `dari`, `sampai` (tanggal kerja `YYYY-MM-DD`, maks 31 hari; kosong = 7 hari terakhir), `line_code`, `plat` (potongan), `hasil` (`""`\|`ripe`\|`unripe`\|`jk`\|`tp`), `tampilan` (`hari`\|`truk`\|`janjang`), `ringkasan` (bool), `limit`/`offset` (Per janjang saja) → `{dari, sampai, hari_ini, maks_hari, tampilan, items, total, ringkasan?}`. Ringkasan: `total, acc, rej, ripe, unripe, jk, tanpa_kelas, tp, hari, truk, neto_kg` (`neto_kg` null kalau disaring per line). 400 `riwayat_tanggal_tidak_sah` / `riwayat_rentang_terbalik` / `riwayat_rentang_panjang` |
| GET | `/api/console/riwayat/csv` | filter yang sama + `bahasa` (`id`\|`en`) → `text/csv` lampiran `riwayat-grading-<tampilan>-<dari>_<sampai>.csv`, semua baris (bukan satu halaman) |
| POST | `/api/console/dev/riwayat/impor/periksa` | **support**, badan = CSV Per janjang mentah (`content-type: text/csv`), `nama` → `{sidik, baris, baru, sudah_ada, ganda, hari_berjalan, salah, contoh_salah[{nomor, kode, params}], dari, sampai, per_line[{line_code, jumlah, dikenal}], truk_baru, truk_baru_jumlah, bisa_impor}`. 400 `impor_kosong` / `impor_bukan_utf8` / `impor_bukan_janjang` / `impor_rusak`, 413 `impor_terlalu_besar` |
| POST | `/api/console/dev/riwayat/impor` | **support**, berkas yang sama + `nama`, `sidik` → 201 `{batch}` (`grading_imports`: `added`, `skipped_existing`, `skipped_today`, `duplicates`, `date_from`, `date_to`, `new_trucks`, `status`). 409 `impor_sidik_beda` / `impor_ada_salah` / `impor_tidak_ada_baru` / `impor_berjalan` / `impor_hapus_berjalan` |
| GET | `/api/console/dev/riwayat/impor` | **support** → `{items}`: 20 impor terakhir, terbaru dulu |
| POST | `/api/console/dev/riwayat/impor/{id}/batal` | **support** → `{batch}` berstatus `undone`, `removed` = janjang yang dihapus. 404 `impor_tidak_ada`, 409 `impor_sudah_dibatalkan` |

Impor CSV: `domain/impor_grading.py` (baca + aturan per baris, murni), `services/impor_grading_service.py` (periksa, impor per potongan, batal), tabel `grading_imports` + kolom `inspections.import_batch` di `ConsoleStore`. Janjang per janjang di layar membawa `import_batch` untuk label "impor".

### Last Sync (2026-09-27)

Tidak ada endpoint baru: `GET /api/console/state` membawa `sinkron` untuk semua operator.
Rinciannya: CLAUDE.md, Critical Rule 27.

```json
"sinkron": {
  "autoerp": {"keadaan": "tersambung", "terakhir": 1790492400.0, "sejak": null, "antre": 0},
  "cloud":   {"keadaan": "terputus", "terakhir": 1790488800.0, "sejak": 1790490600.0, "antre": 5,
              "per_line": [{"line_code": "line-1", "terbaca": true, "aktif": true,
                            "terakhir": 1790488800.0, "sejak": null, "antre": 0}]}
}
```

`keadaan`: `tersambung` | `terputus` | `tidak_dipakai` (`ERP_URL` / `R2_BUCKET` kosong) |
`memeriksa` (baru menyala, belum ada kontak). `terakhir` = data terakhir yang benar-benar lewat
(epoch, disimpan di `sync_state`), `sejak` = awal deretan gagal, `antre` = yang menunggu dikirim.

| Komponen | Peran |
|---|---|
| `domain/sinkron.py` | aturan murni: `Jejak`, `keadaan`, `ringkas`, `gabung_cloud` |
| `services/status_sinkron.py` | `StatusSinkron`: satu pencatat bersama, per sumber (`cek`/`tarik`/`kirim`/`manifest`, plus `jaringan`), jam di `sync_state`, satu WARNING per putus/pulih |
| `workers/cek_sinkron_worker.py` | tiap 60 detik: `ErpClient.ping()` + `R2Uploader.cek()` (`head_object viewer.html`, 404 = tersambung) |
| `MasterDataWorker`, `ErpOutboxWorker`, `VisitManifestWorker` | mencatat hasil kirim/tarik (`berhasil` / `gagal`) |
| `LineStatusWorker` | membawa blok `unggah` tiap line + mencatat putus/pulih upload foto line ke tab Log |

### Lane support (`require_support`)

Melayani tab support: **Log**, **Status** (Versi, Diagnostik, Antrean ERP), **Akun**, **Line**
(Sumber Kamera, Model Deteksi, Uji PLC, Rekam Video), dan **Setelan** (termasuk Danger Zone).
Semuanya dijawab **403** kalau operator yang masuk bukan `role='support'`. Rasionalnya:
CLAUDE.md, Critical Rule 21.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/console/dev/ping` | cek akses masih hidup, tanpa membaca apa pun |
| GET | `/api/console/dev/log` | `event_log`: filter `level`/`cari`, `limit`+`offset` |
| GET | `/api/console/dev/diagnostik` | `/health/detail` ketiga line, digabung satu jawaban |
| GET | `/api/console/dev/antrean` | `erp_outbox`: jumlah pending/gagal + daftar gagal. `ErpClient` membalas empat jawaban (`ErpRejected` 4xx, `ErpServerError` 5xx beramplop Frappe, `ErpUnavailable` tidak terjangkau, atau terkirim); dua yang pertama dicatat per pesan dan batch lanjut, `ErpUnavailable` menahan batch dan Last Sync membaca putus (`integrations/erp/client.py`) |
| GET | `/api/console/dev/antrean/manifest` | antrean manifest R2 (DB terpisah dari `erp_outbox`, supaya R2 mati tidak menahan pesan AutoERP) |
| POST | `/api/console/dev/antrean/kirim-ulang` | requeue semua baris gagal di `erp_outbox`. **`attempts` sengaja tidak di-reset**: itu yang membedakan "macet selamanya" dari "gangguan sesaat" |
| GET | `/api/console/dev/versi` | versi image + status lisensi |
| GET | `/api/console/dev/akun` | `{akun:[{email, nama, role, asal: "lokal"\|"erp", keadaan: "aktif"\|"mati"\|"terkunci", terkunci_detik, sedang_masuk, dibuat}]}`: semua akun di PC ini, aktif dulu. **Tanpa hash sandi** (kolomnya disebut satu per satu) |
| POST | `/api/console/dev/akun` | `{email, nama, sandi, sandi_ulang, role}` → 201 `{akun:{email, role}}`: akun **lokal** baru. 409 `akun_sudah_ada` / `akun_milik_erp`, 400 `akun_email_tidak_sah` / `akun_nama_kosong` / `akun_sandi_beda` / `sandi_pendek` |
| POST | `/api/console/dev/akun/sandi` | `{email, sandi, sandi_ulang}` → `{status:"ok"}`: sandi baru akun lokal, semua sesinya berakhir, status akun tidak berubah |
| POST | `/api/console/dev/akun/status` | `{email, aktif: bool}` → `{status:"active"\|"off"}`: matikan (sesinya berakhir) / aktifkan akun lokal. `aktif` bukan boolean → 422 |
| POST | `/api/console/dev/akun/role` | `{email, role}` → `{role}`: ubah role akun lokal (role asing jadi `operator`). Status/role **akun sendiri** ditolak 409 `akun_diri_sendiri`; akun AutoERP 409 `akun_milik_erp`; email tak dikenal 404 `akun_tidak_ada` |
| GET / POST | `/api/console/dev/setelan` | lima setelan grading dari tab Setelan: `conf_threshold`, `minimum_size`, `garis_capture`, `sumbu_garis`, `mode_dev`. Tersimpan di konsol, disebar ke tiga line, berlaku tanpa restart |
| GET / POST | `/api/console/dev/sumber-kamera` | sumber tiap line + berkas di folder media / simpan ke `media.env`, restart line yang berubah saja. 400 untuk kombinasi yang tidak sah |
| GET / POST | `/api/console/dev/model-deteksi` | pilihan model tiap line (`""` = bawaan PC) + semua `.pt` di `models/release` beserta kelas, ukuran, engine per GPU, dan `cocok`/`alasan`; `folder.terbaca: false` = mount `./models` belum ada. POST `{"line-1": "...", ...}` menulis `LINE_N_MODEL_FILE` dan merestart line yang berubah; **400** untuk model yang tidak ada atau kelasnya bukan empat kelas yang dikenal, tanpa menulis apa pun |
| GET | `/api/console/dev/plc/{line_code}` | snapshot DI + coil yang boleh diuji, baca saja |
| POST | `/api/console/dev/plc/{line_code}/coil` | picu satu coil: satu-satunya lane yang menggerakkan hardware. Ditolak 409 selama line punya truk terpasang; tiap percobaan dicatat WARNING. Ketikan konfirmasi dicabut 2026-09-24 |
| GET | `/api/console/dev/rekam` | status rekaman tiap line, setelan, sisa disk |
| POST | `/api/console/dev/rekam/setelan`, `/api/console/dev/rekam/{line_code}/mulai`, `/stop` | ubah resolusi (berlaku untuk rekaman berikutnya) / mulai / berhenti merekam |
| GET | `/api/console/dev/bahaya` | Danger Zone: `{lines, data, antrean_erp, aksi:{restart, logout, rekaman, transaksi, semua}}`: tiap aksi membawa `hambatan`/`peringatan` (daftar `{kode, line?, jumlah?}`) |
| POST | `/api/console/dev/bahaya/restart-line` | restart ketiga line → `{lines:[{line_code, ok, alasan?}]}` |
| POST | `/api/console/dev/bahaya/logout-semua` | hapus semua sesi → `{sesi_dihapus}` |
| POST | `/api/console/dev/bahaya/hapus-rekaman` | `{konfirmasi}` → `{lines, berkas, bytes}`; 400 konfirmasi salah |
| POST | `/api/console/dev/bahaya/hapus-data` | `{mode, konfirmasi}` → `{mode, lines, konsol}`; 400 konfirmasi/mode salah, 409 `bahaya_ditolak` dengan `params.hambatan`, 409 `semua_line_menolak` dengan `params.lines` (`line-1:lisensi,…`): tidak ada yang dihapus. Tiap baris `lines` = `{line_code, ok, kode?}`; `kode` pada `ok:true` = `belum_mati` (diterima, line belum restart), pada `ok:false` = `line_mati` / `versi_lama` (404) / `lisensi` (403) / kode dari badan 409 line |

---

## Payload event

Satu rumus, `build_event_payload()` di `domain/vision_event.py`, dipakai jalur realtime ke
konsol. Nama field dan nilainya HARUS tepat:

```json
{
  "event_id": "uuid5(machine_id:timestamp nama file)",
  "grade_class": "Ripe | Unripe | JK | null",
  "machine_id": "uuid",
  "assignment_id": "uuid-or-null",
  "truck_id": "uuid-or-null",
  "timestamp": "2026-05-18T10:30:00.123456+00:00",
  "prediction": "Acc | Rej",
  "ripeness_status": "ACC | REJ",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS | null",
  "tp_confidence": 0.88,
  "capture_type": "auto | manual",
  "image_path": "captures/results/{date}/{HHMMSS}_{plat}_{assign8}/bbox/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

**Kontrak penting:**
- `event_id`: kunci idempotensi di sisi penerima. uuid5 deterministik dari `machine_id:timestamp`
  untuk **auto maupun manual**; `BatchUploadWorker` menghitungnya ulang dari **nama file**, jadi
  dua jalur tidak pernah dobel.
- `timestamp`: ISO-8601 **UTC-aware** (`datetime.now(timezone.utc)`).
- `ripeness_status` UPPERCASE; `prediction` wajib; `tp_status` `"PASS"` atau `null`, BUKAN `"TP"`.
- `grade_class` menemani verdict, tidak menggantikannya: piston dan AutoERP tetap biner.
- `truck_id` boleh `null`: deteksi tanpa truk aktif tetap dikirim.
- `image_path` **relatif** di jalur realtime; konsol menyajikannya dari mount artifacts line
  (`/captures/<line_code>/...`), jadi gambar tetap tampil saat internet mati.

**Jalur batch (`BatchUploadWorker`)** mengirim payload yang sama ke
`{UPLOAD_API_URL}{BACKEND_API_VER}/internal/vision/events` (header `x-webhook-secret:
UPLOAD_API_SECRET`) dengan dua beda: `image_path` = URL absolut R2 (`{R2_PUBLIC_URL}/{machine_id}/
results/...`), dan `assignment_id` di-omit kalau kosong. **Di pabrik `UPLOAD_API_URL` kosong**,
jadi POST ini tidak terjadi: item selesai begitu gambar mendarat di R2. Alur, kelas kegagalan,
dan retensi: `docs/overview.md` §4.

> ⚠️ **Jangan tertukar dua pasang variabel ini.** `BACKEND_URL` + `WEBHOOK_SECRET` = konsol lokal
> (jalur realtime). `UPLOAD_API_URL` + `UPLOAD_API_SECRET` = penerima teks cloud, dan hanya itu
> yang dipakai batch worker. **`R2_BUCKET` kosong = batch jadi no-op**, cuma `logger.warning`
> sekali lalu diam.

---

## Environment Variables

Nilai bawaan = bawaan kode; compose dan `.env.example` bisa menimpanya (disebut kalau beda).

Semua variabel di `.env.example` memang dibaca (diaudit 2026-09-15). Pola di bawah kelihatan
seperti variabel mati padahal bukan: jangan dihapus karena `grep os.getenv` tidak menemukannya.

| Kelihatan mati | Kenyataannya |
|---|---|
| `LINE_1/2/3_CAMERA_SERIAL`, `LINE_N_FEATURE_FILE`, `LINE_N_MACHINE_ID` | Dipetakan **compose** jadi `CAMERA_SERIAL` / `CAMERA_FEATURE_FILE` per container; `LINE_N_MACHINE_ID` dibaca f-string di `config.py`. Inilah yang bikin tiap line dapat kamera yang benar |
| Semua `PLC_*` selain `PLC_ENABLED`/`PLC_HOST` | Lewat helper `_plc_int()` / `parse_coil_list()`, bukan `os.getenv` literal |
| `APP_MODE`, `APP_VERSION`, `CAMERA_SERIAL`, `CAMERA_FEATURE_FILE`, `PLC_COIL_ALIVE`, `PLC_COIL_BASE` | **Sengaja tidak ada** di `.env.example`: compose/Dockerfile yang mengisinya, dan literal compose selalu menang atas berkas ini (alasan lengkap di komentar `.env.example` § PLC) |
| `CONSOLE`, `CONSOLE_EMAIL`, `CONSOLE_SANDI` | Variabel **skrip dev** (`smoke-console.sh`), bukan setelan runtime. `make demo` tidak butuh satu pun dari ini |

**Line**

| Variable | Default | Keterangan |
|---|---|---|
| `APP_MODE` | `line` | `console` = `entrypoint.sh` menjalankan `console_main:app` |
| `APP_PORT` | `8000` | Di-set compose: line `8001/8002/8003`, konsol `8000` (dev) / `8100` (`docker-compose.prod.yml`, PC pabrik). Mengisinya di `.env` tidak berefek |
| `APP_ENV` | `development` | `production` = fail-fast kalau secret masih bawaan |
| `FRONTEND_URL` | `*` | CORS allowed origin |
| `ENABLE_WEBHOOK` | `true` | Saklar jalur realtime ke konsol. `false` = hasil mengendap di `outbox.db` sampai dinyalakan |
| `BACKEND_URL` | `http://localhost:2500` | Konsol penerima event. Bawaan kode dan compose = alamat palmgrade-api yang sudah mati, **wajib diisi**: `http://localhost:8100` di PC pabrik (`.env.example`) |
| `BACKEND_API_VER` | `/api/v1` | Prefiks URL event |
| `WEBHOOK_SECRET` | `supersecret123` | Secret bersama line ↔ konsol (`x-webhook-secret`, dua arah) dan program timbangan. Perintah konsol → line memakai `x-internal-secret`: lihat `INTERNAL_SECRET` di baris berikut |
| `INTERNAL_SECRET` | kosong | Kunci perintah konsol → line (`x-internal-secret`), terpisah dari `WEBHOOK_SECRET` sejak batch 1 keamanan (2026-09-28). Kosong atau sama dengan `WEBHOOK_SECRET` = perintah konsol masih memakai kunci yang juga dipegang program timbangan (`.env` lama tetap jalan); diisi beda di `.env` **dan** compose host (empat blok: tiga line + konsol) = terpisah. Dibaca line dan konsol sekaligus (`Settings.internal_secret`) |
| `STATE_DIR` | `<repo>/state` | SQLite di LUAR mount statis `/captures`: `console.db` (konsol) dan `outbox.db`/`license.db` (line, sejak batch 1 keamanan; dulu di `artifacts/`). Compose: `./state/line-N:/app/state` per line, `./state/console:/app/state` konsol. Jalur native (`make line N=`) memberi tiap line foldernya sendiri, tanpa itu line berbagi satu `outbox.db` |
| `MACHINE_ID` | - | Identitas line, unik dan tetap. Di-set compose dari `LINE_N_MACHINE_ID` (bawaan UUID di compose) |
| `LINE_1/2/3_MACHINE_ID` | UUID bawaan di compose | Dipetakan compose jadi `MACHINE_ID` tiap line; konsol memakai yang sama untuk mengenali line pengirim. Harus sama di line dan konsol |
| `APP_VERSION` | `unknown` | Versi image, diisi build (`deploy.yml`) dan launcher dari tag. `unknown` = dijalankan dari source. Tampil di header konsol |
| `MODEL_FILE` | `best.pt` | Nama file model di `models/release/`, **bawaan PC** untuk ketiga line |
| `LINE_N_MODEL_FILE` (di `media.env`) | kosong | Model line N, ditulis tab Line → Model Deteksi. Menang atas `MODEL_FILE` untuk line itu |
| `CONF_THRESHOLD` | `0.75` | Minimum confidence YOLO. **Nilai awal**: yang dipakai diatur tab Setelan |
| `MINIMUM_SIZE` | `460000` | Minimum area bounding box (px²): di bawah ini auto rej. Nilai awal |
| `GARIS_CAPTURE` | `300` | Garis capture (px, ruang **stream**). `0` = tanpa garis. Nilai awal |
| `SUMBU_GARIS` | `tegak` | `tegak` (conveyor mendatar, px dari **kiri**) / `mendatar` (conveyor menurun, px dari **atas**). Nilai awal |
| `MODE_DEV` | `false` | `true` = angka keyakinan ikut digambar di kotak janjang. Untuk support, bukan operator. Nilai awal |
| `YOLO_SKIP_FRAMES` | `1` | Jalankan YOLO tiap N frame (`1` = produksi) |
| `DEBUG_MODEL_OUTPUT` | - | Log raw output model tiap inferensi (berisik) |
| `ROI_X1` / `ROI_Y1` / `ROI_X2` / `ROI_Y2` | `0` | Kotak wilayah deteksi (px, ruang stream). `0,0,0,0` = full frame; `X2`/`Y2` `0` = lebar/tinggi penuh |
| `STREAM_WIDTH` / `STREAM_HEIGHT` / `STREAM_FPS` | `1280` / `720` / `12` | MJPEG stream (setelah resize); tidak menyentuh kamera maupun hasil simpan |
| `BORDER_THICKNESS` / `FONT_SCALE` / `FONT_THICKNESS` | `2` / `0.7` / `2` | Kotak dan label deteksi; frame 2448×2048 butuh angka jauh lebih besar |
| `CAMERA_TYPE` | `hikrobot` | Jenis sumber. Di Docker diisi compose dari `LINE_N_CAMERA_TYPE` di `media.env` (tab Line → Sumber Kamera), dan line membaca ulang `media.env` sendiri saat boot |
| `MEDIA_FILE` / `MEDIA_DIR` / `MEDIA_ENV_PATH` | - / `/media` / `/config/media.env` (compose) | Nama berkas video/foto (bukan path), foldernya, dan berkas setelan sumber kamera |
| `CAMERA_VIDEO_LOOP` | `false` | `true` = video diulang terus (uji performa); tiap putaran me-reset ByteTrack. Dari `LINE_N_VIDEO_LOOP` |
| `CAMERA_VIDEO_PATH` / `CAMERA_PHOTO_PATH` | - | Path penuh sumber video/foto untuk `make line` (native, tanpa `media.env`). `MEDIA_FILE` menang kalau ada |
| `CAMERA_SERIAL` | - | Pilih kamera Hikrobot by serial. Dari `LINE_N_CAMERA_SERIAL` di `.env`; kosong = fallback index |
| `CAMERA_DEVICE_INDEX` | `0` | Index device (fallback kalau serial kosong). Compose memberi `0` / `1` / `2` per line |
| `CAMERA_FEATURE_FILE` | - | `.mfs` yang dimuat ke kamera tiap connect. Dari `LINE_N_FEATURE_FILE`, bawaan compose `config/camera/hikrobot.mfs` |
| `CAMERA_WIDTH` / `CAMERA_HEIGHT` | `320` / `240` | Hanya sumber OpenCV dan pemanasan model; Hikrobot memakai ukuran dari `.mfs`. Compose: `2448` / `2048` |
| `CAMERA_FPS` | `20` | Cadangan untuk sumber yang tidak bisa melaporkan lajunya (webcam, video). Hikrobot: laju dari `.mfs` (15). Video: kosongkan / `0` supaya diputar pada laju aslinya |
| `REKAMAN_DIR` | `<repo>/videos` | Folder rekaman video developer (compose: `/app/videos`) |
| `UPLOAD_MINUTE` | `0` | Menit tiap jam batch uploader jalan |
| `UPLOAD_MAX_ITEMS_PER_TICK` | `2000` | Jumlah maksimal item per batch run |
| `UPLOAD_RETENTION_DAYS` | `7` | Umur arsip lokal item `done` (pabrik: 180) |
| `UPLOAD_DISK_MIN_FREE_GB` | `20` | Lantai sisa disk: di bawahnya item `done` tertua dibuang lebih awal. `0` = mati |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` / `R2_PUBLIC_URL` | - | Cloudflare R2, dipakai tiga line (foto) dan konsol (manifest per truk + `viewer.html`). `R2_BUCKET` kosong = keduanya mati |
| `UPLOAD_API_URL` / `UPLOAD_API_SECRET` | - | Penerima teks per janjang di cloud. **Kosongkan**: palmgrade-api pensiun; kosong = item selesai begitu gambar mendarat di R2 |
| `LICENSE_ENABLED` | `false` | Aktifkan license guard + gerbang grading |
| `LICENSE_PUBLIC_KEY` | kunci bawaan image | Isi hanya untuk memverifikasi pakai keypair lain |
| `LICENSE_TOKEN` | - | Token langganan terbitan AutoERP; dipasang `autograde licence <token>`, nempel saat container dibuat ulang |
| `PLC_COIL_BASE` | `1000` | Coil OK line ini; NG = +1, ERROR = +2. Dipatok literal per line di compose: 1000 / 1003 / 1006 |
| `PLC_COIL_ALIVE` | `1009` | Bit heartbeat PC. Maksudnya cuma line 1 (compose mengosongkannya untuk line 2 dan 3), tapi nilai kosong jatuh ke bawaan `1009` di `config.py`, jadi hari ini ketiga line memegangnya (ketahuan 2026-09-28, belum diperbaiki) |
| `PLC_ENABLED` | `false` | Aktifkan integrasi PLC. `false` = nol thread tambahan, `submit_grading()` langsung `return` |
| `PLC_PROTOCOL` | `mc` | `mc` = MC Protocol langsung ke CPU Mitsubishi; `modbus` = coupler ODOT lama |
| `PLC_HOST` | - | IP PLC (Lampung `192.168.0.14`). Kosong + `PLC_ENABLED=true` → worker tidak jalan, warning |
| `PLC_PORT`, `PLC_COIL_*`, `PLC_DI_*`, `PLC_PULSE_*`, `PLC_HOLD_MS`, `PLC_QUEUE_MAX`, `PLC_POLL_MS`, `PLC_ALIVE_TOGGLE_MS`, `PLC_UNIT_ID`, `PLC_DEVICE_PREFIX` | lihat tautan | Tabel lengkap dan alasannya: `docs/plc-integration.md` §Env vars. Port dan alamat coil literal per line di compose, jangan diisi di `.env` |

**Konsol saja**

| Variable | Default | Keterangan |
|---|---|---|
| `FACTORY_TZ` | `Asia/Jakarta` | Batas tanggal kerja (pabrik jalan lewat tengah malam) |
| `CONSOLE_LINE_HOST` | `http://localhost` | Base URL line dilihat dari konsol (port 8001-8003 ditambahkan sendiri). macOS: `http://127.0.0.1` |
| `CONSOLE_SYNC_INTERVAL_S` | `300` | Interval tarik master data dari AutoERP |
| `CONSOLE_DEFAULT_HASH` / `CONSOLE_SUPPORT_HASH` | - | Hash dua akun bawaan (`make hash-sandi`). Di compose tulis `$$` untuk tiap `$` |
| `ERP_URL` / `ERP_API_KEY` / `ERP_API_SECRET` | - | Sambungan AutoERP. `ERP_URL` kosong = mati, konsol jalan dari salinan terakhir |
| `ERP_COMPANY` | - | Company AutoERP; kosong = company bawaan site |
| `ERP_ALLOWED_ROLES` | `support` | Peran mana yang boleh datang dari AutoERP (`domain/role.py`, `filter_erp_role`). Kosong = tolak semua akun ERP dari lane support |
| `LOG_RETENSI_HARI` | `180` | Umur baris `log_kejadian` (tab Log) |
| `REKAMAN_TAMPIL` | `/opt/palmgrade/autograde/videos` (compose) | Jalur rekaman yang **ditampilkan** di Rekam Video: jalur host, bukan `/app/videos` |
| `CONSOLE_MACHINE_ID` | `konsol` (compose prod) | Diteruskan sebagai `MACHINE_ID` konsol, untuk kartu Versi |

---

## Models

| File | Keterangan |
|---|---|
| `models/release/best.pt` | Model utama: 4 kelas: `Ripe`, `Unripe`, `JK`, `TP` (sejak 2026-09-16) |
| `models/release/best_3class_v2.pt` | Model lama 3 kelas (`ACC`, `Rej`, `TP`). Disimpan, **tidak bisa dipilih** di layar Model Deteksi |

Model di-load saat startup. Jika file tidak ditemukan, line gagal start. Model tidak di-commit ke
git (ada di `.gitignore` via `*.pt`) dan tidak ikut image: disalin ke `models/release/` di host.
