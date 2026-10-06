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
        klien_http.py          # KlienBersama: one kept httpx.AsyncClient for LineClient and ErpClient (batch 6.5), no cookies stored
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
| GET | `/health` | Hidup/tidak; 200, atau **503 kalau AI mati atau frame berhenti** (badan membawa `ai`, dipakai healthcheck compose dan launcher `autograde.sh`) |
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
  "gpu_sm": "86",
  "ai": {
    "keadaan": "sehat",
    "mati": false,
    "kode": null,
    "sejak": null,
    "umur_detik": 0.8,
    "ambang_detik": 30,
    "galat_terakhir": null,
    "galat_at": null
  },
  "fps_kamera": 14.9,
  "fps_deteksi": 7.2,
  "frame_umur_detik": 0.1,
  "suhu_kamera_c": 47.3,
  "suhu_kamera_didukung": true,
  "fps_kamera_target": 15.0,
  "fps_kamera_turun": false,
  "frame_hilang": {"hilang": 0, "total": 9000, "persen": 0.0, "tingkat": "aman"},
  "putus_kamera": {"jumlah": 0, "tingkat": "aman"},
  "kamera_tingkat": "aman",
  "disk": {
    "tingkat": "aman",
    "kode": null,
    "bebas_gb": 232.0,
    "total_gb": 468.0,
    "persen_bebas": 49.6,
    "jalur": "/app/artifacts",
    "ambang_peringatan_gb": 15.0,
    "ambang_kritis_gb": 5.0,
    "sejak": null
  },
  "lisensi": {"aktif": true, "grading_diblokir": false, "berlaku_sampai": 1822000000}
}
```

| Field | Artinya |
|---|---|
| `camera_type` | sumber yang **benar-benar** dipakai line (dari `media.env`), bukan `printenv` container |
| `outbox_pending` / `outbox_failed` | backlog jalur realtime ke **konsol** (`BACKEND_URL`). `outbox_pending` = semua janjang belum sampai (`COUNT(*)`), termasuk baris yang versi lama pernah menyerah dan sekarang dicoba lagi. Naik terus = konsol tidak menjawab, rinciannya di tab Status → Antrean line. **Bukan** backlog upload R2. `outbox_failed` tetap ada di bentuk jawaban tapi **selalu 0 sejak batch 2.4** (antrean ini tidak punya batas nyerah lagi). `outbox_pending` `null` = tidak diketahui (lihat baris berikut) |
| `outbox_lama_tertinggal` | `true` = `artifacts/outbox.db` dari sebelum batch 1 gagal diserap ke `state/` (berkas rusak, disk penuh): barisnya belum terkirim dan tidak terhitung, jadi `outbox_pending` dilapor `null`. Danger Zone menahan hapus data (`outbox_lama`); restart line itu untuk mencoba lagi, lalu baca log line-nya |
| `capture_save_pending` | janjang yang menunggu ditulis `CaptureSaveWorker` (antrean 8 dalam). Naik terus = disk/CPU tidak mengimbangi laju grading |
| `capture_save_dropped` | **harus NOL.** Janjang yang dibuang karena antrean penuh: sudah dapat pulse PLC dan sudah masuk rekap, tapi **tidak punya gambar maupun sidecar**, jadi `BatchUploadWorker._scan()` tidak akan pernah menemukannya |
| `tp_telat` | **harus NOL.** TP yang muncul sesudah janjang terdekatnya difoto, jadi tangkainya tidak ikut ke mana pun |
| `last_successful_api_push` | waktu POST terakhir yang sukses ke konsol; `null` = belum pernah sejak start |
| `workers[]` | memuat `outbox_retry` dan `plc` (kalau aktif), tapi **tidak** `BatchUploadWorker`: itu job APScheduler, jadi watchdog `_watchdog` tidak memantaunya |
| `plc` | `null` kalau `PLC_ENABLED=false`. `inputs` = offset dari `PLC_DI_BASE` (0–10 motor fault, 11 E-stop); dua counter drop **naik monoton**, yang berarti selisih antar-polling. Detail: `docs/plc-integration.md` |
| `model_*`, `gpu_sm` | model yang **benar-benar dimuat** line ini, bukan pilihan di `media.env`. `model_kelas_cocok: false` = line **tidak menghitung janjang** (layar Model Deteksi menulisnya merah); `null` = tidak diketahui. `gpu_sm` = compute capability (nama engine `<model>.sm<cc>.engine`), `null` di CPU |
| `ai` | penjaga AI mati (batch 2.1, `services/penjaga_ai.py`): `keadaan` (`sehat`/`memulai`/`kamera_putus`/`lisensi`/`sumber_selesai`/`frame_berhenti`/`ai_mati`; line versi 2.1 masih bisa mengirim `sumber_diam`), `mati` (bool, **AI saja**), `kode` (`AI_MATI`, `FRAME_BERHENTI`, atau `null`), `sejak` (epoch mulai diam, cuma saat `ai_mati`/`frame_berhenti`), `umur_detik` (detik sejak frame terakhir selesai digrading), `ambang_detik` (`AI_MATI_DETIK` yang berlaku), `galat_terakhir` + `galat_at` (galat deteksi TERAKHIR sejak boot dan umurnya, **bukan** bukti ada galat sekarang). `mati:true` (AI mati) dan `keadaan:"frame_berhenti"` menaikkan coil ERROR dan membuat `/health` 503; `/health/detail` sendiri **tetap 200** walau keduanya |
| `fps_kamera` / `fps_deteksi` | laju TERUKUR gambar masuk / frame selesai digrading (batch 3.6). **0** kalau yang terakhir lebih tua dari 5 detik, jadi angka lama tidak pernah tampil sebagai laju sekarang |
| `frame_umur_detik` | detik sejak gambar terakhir masuk dari kamera; `null` = belum pernah |
| `suhu_kamera_c` | suhu badan kamera Hikrobot (°C, node `DeviceTemperature`), dibaca thread capture tiap 10 detik selama gambar mengalir. `null` = tidak tahu: webcam/video/foto, kamera menolak menjawab (WARNING sekali dengan kode SDK di tab Log), atau bacaan terakhir lebih tua dari 60 detik |
| `suhu_kamera_didukung` | `false` = kamera menjawab `DeviceTemperature` tidak diimplementasikan (akses NI, mis. MV-CS050-10GC Lampung): kartu menulis "tidak didukung kamera" dan line berhenti bertanya sampai sambung berikutnya. `true` = pernah terbaca, `null` = belum tahu atau bukan Hikrobot |
| `fps_kamera_target` / `fps_kamera_turun` | laju yang dijanjikan kamera (`camera_fps_terukur`, `null` kalau sumber tanpa laju) dan apakah `fps_kamera` tertahan di bawah 90% target selama 2 menit (pulih sesudah 1 menit normal). `false` begitu gambar berhenti (aturan 35) |
| `frame_hilang` | frame yang hilang di jaringan dalam 10 menit terakhir (GigE `MV_MATCH_TYPE_NET_DETECT`): `hilang`, `total` (diterima + hilang), `persen`, `tingkat` (`aman` 0, `waspada` ada, `kritis` mulai 5%). `null` = sumber tidak menghitung (webcam/video/foto) atau belum ada bacaan |
| `putus_kamera` | kejadian kamera berhenti mengirim gambar dalam 24 jam terakhir: `jumlah`, `tingkat` (`aman` 0, `waspada` 1-2, `kritis` 3 ke atas) |
| `kamera_tingkat` | tingkat terburuk dari tiga di atas (laju tertahan = `waspada`), untuk tanda "perlu dicek" di judul grup kartu. `null` = line versi lama |
| `disk` | pemantau disk (batch 3.7, `services/pemantau_disk.py`), partisi foto + DB line yang PALING sempit: `tingkat` (`aman`/`peringatan`/`kritis`/`tidak_terbaca`), `kode` (`DISK_HAMPIR_PENUH`/`DISK_KRITIS`/`null`), `bebas_gb`, `total_gb`, `persen_bebas`, `jalur`, ambang yang berlaku, `sejak` (epoch mulai tingkat sekarang). Jalan **tanpa R2** dan tidak menghapus apa pun; `null` = line versi lama |
| `lisensi` | lisensi line ini: `aktif` (`LICENSE_ENABLED`), `grading_diblokir` (gerbang yang sama dengan thread grading), `berlaku_sampai` (epoch akhir tenggang) |

Backlog upload R2 tidak ada di sini: lihat blok `unggah` di `GET /internal/status`, atau query
`state/upload_manifest.db` (`SELECT status, COUNT(*) FROM upload_items GROUP BY status`).

### `/internal/*` (header `x-internal-secret` = `INTERNAL_SECRET`, kosong = `WEBHOOK_SECRET`)

Dipanggil konsol, tidak pernah oleh browser. Perbandingan constant-time dan fail closed:
secret yang dikonfigurasi kosong tidak pernah membuka lane (`routes/penjaga_rahasia.py`).

| Method | Path | Notes |
|---|---|---|
| POST | `/internal/assignment` | `{machine_id, assignment_id, truck_id, assigned_at, ffb_source?, plate?}` → `{accepted, machine_id, truck_id, assignment_id}`. Set `current_truck_id` + `current_assignment_id`; `plate` + `assigned_at` menamai folder capture truk (`domain/capture_layout.py`). ⚠️ `plate` itu label, bukan identitas; opsional supaya konsol lama tidak ditolak saat upgrade separuh jalan |
| GET | `/internal/status` | Dipanggil tiap 1 detik (`LineStatusWorker`) → `{machine_id, truck_id, ffb_source, piston, alarms, unggah, ai, disk}`. `unggah` = ringkasan upload R2 untuk **Last Sync** (`aktif`, `terakhir`, `gagal_sejak`, `pesan`, `antre`, `rusak`), dihitung sekali per batch; `null` sebelum worker upload ada. `ai` = blok penjaga AI mati (sama bentuknya dengan `/health/detail` tapi tanpa `galat_terakhir`/`galat_at`), dibaca kartu line konsol (`pitaAi`). `disk` = blok pemantau disk (sama dengan `/health/detail`), dibaca pita disk konsol (`pitaDisk`) Since batch 6.5 the three lines are asked side by side, each in its own loop (`asyncio.gather`), over one kept HTTP client: a line that hangs until its 1.5 s timeout is read less often and holds up no other line. |
| POST | `/internal/manual-reject` | `{machine_id, assignment_id, requested_by, requested_at}` → `{accepted, message}`. `capture_manual_reject()` lewat executor: WebP + JSON + satu baris outbox, sampai di konsol ~1 detik |
| GET / POST | `/internal/setelan` | Setelan grading yang berlaku / timpa tanpa restart (`conf_threshold`, `minimum_size`, `garis_capture`, `sumbu_garis`, `mode_dev`, plus `tampil_garis` dan `tampil_roi`: cuma gambar garis capture dan kotak ROI di video, bawaan `true`, deteksi tidak membacanya; dan `roi_x1`, `roi_y1`, `roi_x2`, `roi_y2`: kotak area deteksi dalam ruang stream, `null` = line memakai `ROI_*` dari `.env`, `0` semua = seluruh frame; dan `ukuran_label`: ukuran tulisan kelas di kotak pada video dalam persen, 25 sampai 400, bawaan 100, cuma tampilan, sejak 2026-10-05; nilai di luar batas dijawab 400; GET juga membawa `roi_env`: kotak `.env` line ini, apa pun yang disetel konsol, untuk ditampilkan sebagai bawaan PC di tab Setelan). Disimpan di `RuntimeState`; konsol pemegang nilai sebenarnya |
| GET | `/internal/outbox` | Ringkasan antrean line untuk tab Status → Antrean line: `{line_code, aktif, menunggu, tertua_at, ditolak, ditolak_at, ditolak_alasan, lama_tertinggal, tersambung, putus_sejak, sebab_putus, coba_lagi_at, galat, galat_at}` (`ditolak` = baris yang percobaan terakhirnya ditolak konsol 400/422). Router `routes/internal_outbox.py`, tanpa torch |
| POST | `/internal/outbox/requeue` | Kirim Ulang: semua baris outbox jatuh tempo sekarang, jeda sambungan dibatalkan → `{requeued}`. URL dan bentuk sama dengan sebelum batch 2.4 |
| POST | `/internal/piston` | Piston manual (fitur mati selama `PLC_COIL_MANUAL` kosong) |
| POST | `/internal/camera/reconnect` | Reconnect camera button (2026-10-04): `{requested_by?}` → **202** `{status: "requested"}` at once. The route never touches the camera: it raises a flag on `RuntimeState` and `FrameCaptureWorker` reconnects on its next turn (disconnect + connect under `state.lock`, rule 3, no backoff wait; a press during the automatic backoff cuts it short). **409** `{detail: {kode: "kamera_tanpa_sambung_ulang"}}` for a video file or photo source (`supports_reconnect` false). One INFO line on request and one on the outcome (WARNING if the connect fails). Router `routes/internal_kamera.py`, without torch |
| GET | `/internal/camera/settings` | Camera settings phase 1 (2026-10-05, read only) → **200** `{berkas_tersimpan, berkas_fitur, setelan: [{kunci, node, jenis, satuan, bisa_diubah, didukung, nilai, min, max, langkah, pilihan}]}`, rows in the order of `domain/setelan_kamera.SETELAN_KAMERA` (seven nodes; a node the camera refuses is one row with `didukung: false`, its SDK code only in the line log). The route never calls the SDK: it queues the read on `state.perintah_kamera`, which `FrameCaptureWorker` runs between two grabs under `state.lock` (rule 3), and waits up to `BATAS_PERINTAH_KAMERA_DETIK` 2 s. **409** `{detail: {kode: "kamera_tanpa_setelan"}}` for a video, photo or webcam source (no queue entry). **503** `kamera_tidak_menjawab` when the camera is disconnected, refuses every node (a cable just pulled), or the capture thread did not get to it in time (a command the route gave up on is skipped, never run late). `berkas_tersimpan` = `<CAMERA_SETELAN_DIR>/<line_code>.mfs` exists; `berkas_fitur` = the `.mfs` pushed at the last connect |
| GET | `/internal/plc` | Snapshot DI + coil yang boleh diuji |
| POST | `/internal/plc/coil` | Picu satu coil uji; ditolak 409 selama line punya truk terpasang |
| POST | `/internal/restart` | ← dari konsol (Sumber Kamera, Model Deteksi, Danger Zone): jawab dulu, 1 detik kemudian urutan tutup yang SAMA dengan SIGTERM (coil PLC mati bersamaan dengan antrean simpan dihabiskan, lalu kamera + penjadwal R2), lalu antrean log line dikuras (batch 3.2, maks 1 detik), maks 10 detik total, baru `os._exit(0)`. `restart: unless-stopped` menyalakan lagi dan line membaca ulang `media.env`. Aturan 29 |
| GET | `/internal/log` | ← dari konsol tiap 10 detik (`TarikLogLineWorker`, batch 3.2): `?setelah=<seq>&generasi=<g>&batas=<n>` → `{generasi, entri[{id, seq, first_at, last_at, level, source, message, detail, count}], seq_akhir, lagi, dibuang}`. WARNING/ERROR line dari `log_line.db` (folder DB line, maks 2.000 baris, selamat dari Danger Zone). Terbuka walau lisensi habis (gerbang lisensi mengizinkan path ini persis); router `routes/internal_log.py`, tanpa torch |
| POST / GET | `/internal/rekam/mulai`, `/stop`, `/status` | Rekam video developer (tab Line → Rekam Video) ke `REKAMAN_DIR` |
| GET / POST | `/internal/rekam/berkas`, `/internal/rekam/hapus` | Hitung / hapus rekaman line ini (Danger Zone); hapus ditolak selama merekam |
| POST | `/internal/hapus-data` | Danger Zone: tulis penanda lalu keluar lewat urutan tutup yang sama, data dihapus saat boot berikutnya. 409 `truk_terpasang` kalau line sedang memproses truk |

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
| POST | `/api/v1/internal/vision/events` | Event per janjang dari tiga line (kontrak beku, sama dengan palmgrade-api dulu). 401 secret salah, 400 payload cacat (outbox line menahannya dan terus mencoba, tab Status → Antrean line) → 201 `{status, work_date}` |
| GET | `/api/v1/internal/setelan` | Setelan grading, dibaca line saat start |
| GET | `/api/v1/internal/penugasan?machine_id=` | Truk terpasang untuk satu line, dibaca line saat start |
| POST | `/api/v1/internal/scale/weighing` | Payload program timbangan (`plate_number`, `gross_kg`, `tare_kg`, `entered_at`, `exited_at`, `ref?`); format sebenarnya belum diketahui |

### Lane operator (butuh sesi login)

| Method | Path | Notes |
|---|---|---|
| GET | `/console` | Halaman `console.html`, dengan `Cache-Control: no-cache` (#236, batch 5.3): browser selalu bertanya dulu, jadi kiosk yang memuat ulang dirinya sesudah pembaruan mendapat halaman versi baru |
| GET | `/api/console/operators` | Daftar akun untuk kolom email (tanpa hash), bisa dibaca sebelum masuk |
| POST | `/api/console/login`, `/api/console/logout` · GET `/api/console/me` | Sesi cookie `konsol_sesi`, geser 12 jam sejak aktivitas terakhir; login dan `/me` membawa `sisa_detik` |
| POST | `/api/console/session/renew` | Batch 5.7: perpanjang sesi ini 12 jam dari sekarang (layar mengirimnya untuk sentuhan dan tombol, bukan untuk polling); `{sisa_detik}` + cookie baru, 401 `belum_masuk` kalau sudah habis |
| GET | `/api/console/state` | Ringkasan hari kerja + langganan + `sinkron` (Last Sync) + `antrean_bongkar` (`[{weighing_id, plate_number, menit}]`, truk yang menunggu line) + `penugasan_otomatis` (`{aktif, lines}`) + `cutoff_shift` (`"HH:MM"`, awal hari kerja, batch 5.11) + `scanner_qr` (bool, saklar Scanner QR); layar polling tiap 2 detik |
| GET | `/api/console/history` | Janjang per hari kerja (`work_date`, `line_code`, `truck_id`, `limit` ≤ 200); tiap baris membawa `image_url` (foto penuh) dan `thumb_url` (salinan 400 px di `thumb/`, `null` untuk foto sebelum tata letak bbox/clean/thumb) |
| GET / POST | `/api/console/trucks` | Daftar truk / truk ketik operator (masuk antrean ERP) |
| POST | `/api/console/scan`, `/api/console/scan/keluar` | Scan QR gerbang timbang isi / timbang kosong |
| POST | `/api/console/arrivals`, `/api/console/departures` | Scan 1 (datang) / scan 4 (keluar gerbang), aturan 37; hanya di PC pabrik, tidak ke AutoERP |
| POST | `/api/console/arrivals/{arrival_id}/cancel` | Batal datang (2026-10-03): tandai kedatangan yang masih menunggu sebagai dibatalkan (barisnya disimpan sebagai riwayat), aturan 37; tidak ke AutoERP |
| GET | `/api/console/trucks/{plate_number}/qr.png` | Kartu QR, dibuat server |
| GET / POST | `/api/console/weighings` | Timbangan; POST membawa `dipasang` (aturan 36); bruto/tara di bawah 1.000 kg ditolak (`MINIMUM_WEIGHT_KG`). Baris GET membawa `erp_perlu_dicek` (`tiket_final_berbeda` / `tiket_dibatalkan` / null, batch 2.3), `arrived_at`, `left_at`, `antre_menit`, `total_menit`, `tanpa_scan_1`, `tanpa_scan_4`, `tahap`; jawaban GET membawa `waiting` dengan `id` tiap kedatangan dan `dibatalkan` (riwayat Batal datang hari kerja yang tampil) (aturan 37). Urut timbang isi terbaru menurut waktu sebenarnya (`julianday`) |
| GET | `/api/console/recap` | Rekap per truk satu hari. Tidak dipanggil layar sejak tab digabung 2026-09-28; endpoint tetap |
| POST | `/api/console/lines/{line_code}/assign-truck`, `/release-truck`, `/manual-reject`, `/piston` | Diteruskan ke `/internal/*` line; line yang tidak menjawab → 502 |
| POST | `/api/console/lines/{line_code}/force-release` | **Lepas paksa** (rule 13), every account (`require_operator`), no body. Tries the normal release first (`TIMEOUT_LEPAS_PAKSA_S` 3 s): the line answers → released as `/release-truck` does, **200** `{line_code, truck_id: null, paksa: false, dipasang}`. The line gives no answer at all (refused connection, timeout; `domain/lepas_paksa.boleh_paksa`) → the console clears the assignment itself with the same link to the visit ticket and the same AutoERP message, remembers the truck in `sync_state` `lepas_paksa_tertunda`, logs one WARNING naming the account, line and plate, **200** `paksa: true`. A line that answers with a refusal → **502** `line_menolak`; no truck on the line → **200** `paksa: false`, nothing sent; **404** `line_tidak_dikenal`. Router `routes/console_lepas_paksa.py`, service `services/lepas_paksa.py` |
| POST | `/api/console/lines/{line_code}/reconnect-camera` | Every account (`require_operator`), no body → **202** `{line_code, status: "requested"}` once the line accepted (`/internal/camera/reconnect`, timeout `TIMEOUT_SAMBUNG_ULANG_S` 5 s). **409** `kamera_tanpa_sambung_ulang` (param `line`), **404** `line_tidak_dikenal`, **502** `line_tidak_menjawab` / `line_menolak`. One WARNING naming the account before the call (Log tab). Router `routes/console_kamera.py`, service `services/sambung_ulang_kamera.py` |
| POST | `/api/console/unloading-queue/{weighing_id}/assign` | Operator. **Tugaskan sekarang** di antrean bongkar: truk itu HANYA ke line pilihan yang bebas (tidak pernah mengambil line dari truk lain), tanpa pemeriksaan satu-truk-satu-waktu → `{dipasang: [{line_code, plate_number, terpasang}]}`; line yang masih memegang truk yang sudah timbang kosong ikut dilaporkan `{terpasang: false, tertahan: true, plate_lama}`. 409 `bukan_antrean` (antrean sudah berubah) / `line_semua_terpakai` (tidak ada line pilihan yang bebas, atau timbang kosong truk lain masih melepas line) / `penugasan_tanpa_line` (support tidak menyimpan satu line pun) (aturan 36) |
| POST | `/api/console/unloading-queue/{weighing_id}/skip` | Operator. **Lewati**: truk yang tidak jadi bongkar keluar dari antrean bongkar → `{weighing_id, dilewati: true}`. 409 `bukan_antrean` (juga selama truk itu sedang dipasang ke line) |
| GET | `/api/console/update` · POST `/api/console/update/install` | Update now (batch 4.6), lihat § Update now di bawah |

### Rekap (tab Rekap, 2026-09-26; dulu tab Riwayat)

Lane operator biasa (butuh sesi, **bukan** `require_support`), kecuali impor. Rinciannya:
`docs/rules.md`, Critical Rule 26.

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
Rinciannya: `docs/rules.md`, Critical Rule 27.

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

### Update now (batch 4.6, 2026-10-03)

Lane operator biasa (semua akun). Aturannya: `docs/rules.md`, Critical Rule 38. Konsol cuma
membaca dan menulis tiga berkas kecil di `UPDATE_DIR`; penunggu systemd di host yang memasang.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/console/update` | `{terpasang, versi_jalan, siap, berjalan, hasil}`; sama dengan kunci `pembaruan` di `/api/console/state` |
| POST | `/api/console/update/install` | `{target}` = versi yang dilihat operator → **202** `{id, target}` (penanda tertulis). **409** `pembaruan_ada_truk` (`params.line` = kode line, dipisah koma), `pembaruan_tidak_ada` (target bukan versi siap), `pembaruan_berjalan`; **503** `pembaruan_belum_terpasang` (tidak ada penunggu); **500** folder tidak bisa ditulis |

`assign-truck` dan `unloading-queue/{weighing_id}/assign` menjawab **409** `pembaruan_berjalan` selama pemasangan berjalan; penugasan otomatis sesudah timbang isi atau Lepas menahan truk di antrean bongkar sampai pemasangan selesai.

`pembaruan`: `terpasang` = `status.json` ada dengan `watcher: true`; `versi_jalan` = `APP_VERSION`
konsol (bukan berkas); `siap` = versi yang boleh dipasang atau `null`; `berjalan` = penanda belum
dijawab dan belum 20 menit; `hasil` = `{state, target, installed, at}` selama 24 jam, `state`
`ok` / `rolled_back` / `failed` / `nothing` / `timeout` (`timeout` dibuat konsol).

Kontrak berkas (skema 1, semua ditulis tmp lalu rename; sisi host: `sawit/docs/runbooks/files/autograde.sh`):

```json
status.json  {"schema": 1, "installed": "v1.22.0", "staged": "v1.22.1", "checked_at": "2026-10-20T07:00:00+07:00", "watcher": true}
request.json {"schema": 1, "id": "<uuid>", "target": "v1.22.1", "by": "op@pks.test", "at": "2026-10-20T08:00:00+07:00"}
result.json  {"schema": 1, "id": "<uuid>", "state": "ok", "target": "v1.22.1", "installed": "v1.22.1", "at": "2026-10-20T08:03:10+07:00"}
```

`.result-logged.json` milik konsol saja: hasil mana yang sudah ditulis ke tab Log.

| Komponen | Peran |
|---|---|
| `domain/pembaruan.py` | aturan murni: urai tiga berkas, `keadaan_pembaruan`, `boleh_pasang`, `line_bertruk`, `baris_log_hasil` |
| `services/pembaruan_service.py` | `PembaruanService`: baca berkas, tulis penanda atomik, `kunci` + `menugaskan` (assign mendaftar diri tanpa memegang kunci selama memanggil line), catat hasil sekali |
| `routes/console.py` | dua endpoint di atas + kunci `pembaruan` di `/state` + 409 di assign-truck |

### Lane support (`require_support`)

Melayani tab support: **Log**, **Status** (lima sub-tab: Versi & pembaruan, Diagnostik, Antrean line ke konsol, Antrean ERP, Manifest R2), **Akun**, **Line**
(Sumber Kamera, Model Deteksi, Uji PLC, Rekam Video), dan **Setelan** (termasuk Danger Zone).
Semuanya dijawab **403** kalau operator yang masuk bukan `role='support'`. Rasionalnya:
`docs/rules.md`, Critical Rule 21.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/console/dev/ping` | cek akses masih hidup, tanpa membaca apa pun |
| GET | `/api/console/dev/log` | `event_log`: filter `level`/`cari`, `limit`+`offset`. Sejak batch 3.2 baris tarikan line membawa `line_code` (null = konsol) dan `asal` |
| GET | `/api/console/dev/lapor-discord` | Keadaan lapor Discord (`mati`/`url_salah`/`rusak`/`aktif`/`tertahan`/`ditolak`/`isi_ditolak`) + antrean (`kiriman`, `disisihkan`) + galat terakhir (aturan 34). Alamat webhook tidak pernah ikut |
| GET | `/api/console/dev/diagnostik` | `/health/detail` ketiga line, digabung satu jawaban; line yang tidak terbaca: `{terjangkau: false, sebab, sebab_kode}` (`sebab_kode` dari `domain/line_tak_terbaca.py`, yang diterjemahkan layar; `sebab` mentah cuma untuk curl) |
| GET | `/api/console/dev/antrean` | `erp_outbox`: jumlah pending/gagal + daftar gagal (tiap baris `last_error` mentah + `error_kind` yang diterjemahkan layar: `tak_terjangkau`, `kunci_ditolak`, `ditolak`, `galat_tujuan`, `galat_konsol`, kosong di baris lama; Kirim Ulang mengosongkannya, dan build lama yang dipakai sesudah mundur versi mengabaikan kolom itu). `ErpClient` membalas empat jawaban (`ErpRejected` 4xx, `ErpServerError` 5xx beramplop Frappe, `ErpUnavailable` tidak terjangkau, atau terkirim); dua yang pertama dicatat per pesan dan batch lanjut, `ErpUnavailable` menahan batch dan Last Sync membaca putus (`integrations/erp/client.py`) |
| GET | `/api/console/dev/antrean/manifest` | antrean manifest R2 (DB terpisah dari `erp_outbox`, supaya R2 mati tidak menahan pesan AutoERP) |
| POST | `/api/console/dev/antrean/kirim-ulang` | requeue semua baris gagal di `erp_outbox`. **`attempts` sengaja tidak di-reset**: itu yang membedakan "macet selamanya" dari "gangguan sesaat" |
| GET | `/api/console/dev/antrean/line` | antrean janjang tiap line ke konsol, satu baris per line; line mati atau menolak kunci tetap 200 dengan `kode`/`status`/`pesan`/`sebab_kode` (layar cuma memakai `sebab_kode`) |
| POST | `/api/console/dev/antrean/line/{line}/kirim-ulang` | → `/internal/outbox/requeue` line itu → `{line_code, dijadwalkan}`. **404** `line_tidak_dikenal`, **502** `line_tidak_menjawab`/`line_menolak`. Tiap tekanan satu WARNING menyebut pelakunya |
| GET | `/api/console/dev/versi` | versi image + status lisensi |
| GET | `/api/console/dev/akun` | `{akun:[{email, nama, role, asal: "lokal"\|"erp", keadaan: "aktif"\|"mati"\|"terkunci", terkunci_detik, sedang_masuk, dibuat}]}`: semua akun di PC ini, aktif dulu. **Tanpa hash sandi** (kolomnya disebut satu per satu) |
| POST | `/api/console/dev/akun` | `{email, nama, sandi, sandi_ulang, role}` → 201 `{akun:{email, role}}`: akun **lokal** baru. 409 `akun_sudah_ada` / `akun_milik_erp`, 400 `akun_email_tidak_sah` / `akun_nama_kosong` / `akun_sandi_beda` / `sandi_pendek` |
| POST | `/api/console/dev/akun/sandi` | `{email, sandi, sandi_ulang}` → `{status:"ok"}`: sandi baru akun lokal, semua sesinya berakhir, status akun tidak berubah |
| POST | `/api/console/dev/akun/status` | `{email, aktif: bool}` → `{status:"active"\|"off"}`: matikan (sesinya berakhir) / aktifkan akun lokal. `aktif` bukan boolean → 400 `input_tidak_sah` |
| POST | `/api/console/dev/akun/role` | `{email, role}` → `{role}`: ubah role akun lokal (role asing jadi `operator`). Status/role **akun sendiri** ditolak 409 `akun_diri_sendiri`; akun AutoERP 409 `akun_milik_erp`; email tak dikenal 404 `akun_tidak_ada` |
| GET / POST | `/api/console/dev/setelan` | setelan grading dari tab Setelan (plus kotak area deteksi `roi_x1..roi_y2`, empat angka diisi bersama atau `null` semua = ikut `.env` line; kotak tanpa luas ditolak 400): `conf_threshold`, `minimum_size`, `garis_capture`, `sumbu_garis`, `mode_dev`, `tampil_garis`, `tampil_roi` (dua terakhir cuma tampilan, bawaan `true`). Tersimpan di konsol, disebar ke tiga line, berlaku tanpa restart |
| GET | `/api/console/dev/roi-bawaan` | Kotak area deteksi bawaan PC (`ROI_*` dari `.env` line), ditanya ke ketiga line bersamaan, jawaban line pertama yang menjawab dipakai (`services/roi_bawaan.py`): `roi_x1..roi_y2` + `line_code`, semua `null` kalau tidak ada line yang menjawab. Support. Sejak 2026-10-05 |
| GET | `/api/console/slip` | batch 5.9, semua akun: slip grading satu truk satu hari kerja (`work_date`, `truck_id`): `perusahaan` (`ERP_COMPANY`), plat, supplier, sumber, `mulai`/`selesai`, `kelas` (ripe/unripe/jk/tp/tanpa_kelas/total), `rasio_ripe` (persen dari verdict, satu desimal), `neto_kg` (jumlah tiket hari itu, `null` tanpa tiket), `tiket`. 403 `slip_mati` selama saklar mati, 404 `slip_tidak_ada` |
| GET / POST | `/api/console/dev/slip` | **support**, saklar slip grading `{aktif}` (disimpan di `sync_state` `setelan_slip_cetak`, bertahan melewati Danger Zone seperti setelan lain, bawaan mati); `/api/console/state` membawa `slip_cetak` untuk semua akun |
| GET / POST | `/api/console/dev/scanner-qr` | **support**, saklar Scanner QR `{aktif}` / badan `{aktif}` (tanpa `aktif` = mati). Bawaan **mati**. Tersimpan di `sync_state` kunci `setelan_scanner_qr` (bertahan melewati Danger Zone), perubahan dicatat WARNING beserta siapa. `/api/console/state` membawa `scanner_qr` supaya semua layar memunculkan empat kolom QR di tab Timbangan tanpa muat ulang |
| GET / POST | `/api/console/dev/shift` | **support**, awal hari kerja `{cutoff: "HH:MM"}` (batch 5.11; 00:00 sampai 23:59, `5:00` dan `05.00` juga dibaca, layar minta konfirmasi lewat 12:00, kosong = 00:00; selain itu 400 `cutoff_tidak_sah`). Disimpan di `sync_state` `setelan_cutoff_shift`, bertahan melewati Danger Zone, bawaan 00:00. Berlaku untuk baris berikutnya; baris tersimpan tidak dihitung ulang (aturan 10). Tiap perubahan dicatat di log (WARNING: lama -> baru, email support). Impor CSV menerima jam janjang di tanggal kerjanya atau tanggal sesudahnya. `/api/console/state` membawa `cutoff_shift` untuk semua akun |
| GET / POST | `/api/console/dev/auto-assign` | **support**, penugasan line otomatis: `{aktif, lines, lines_tersedia}` / badan `{aktif, lines}`. Bawaan **mati**. Tersimpan di `sync_state` kunci `setelan_penugasan_line` (selamat dari Danger Zone), perubahan dicatat WARNING beserta siapa. POST menjawab setelan plus `dipasang`: disimpan nyala, truk yang sudah menunggu langsung dipasang ke line yang bebas (`async def`, aturan 30). 400 `penugasan_tanpa_line` (nyala tanpa satu line) / `line_tidak_dikenal` (aturan 36) |
| GET / POST | `/api/console/dev/sumber-kamera` | sumber tiap line + berkas di folder media / simpan ke `media.env`, restart line yang berubah saja. 400 untuk kombinasi yang tidak sah |
| GET | `/api/console/dev/camera-settings` | **support**, tab Line > Setelan Kamera (phase 1, read only): `/internal/camera/settings` of the three lines at once → `{lines: {line_code: {terjangkau: true, berkas_tersimpan, berkas_fitur, setelan} \| {terjangkau: false, sebab_kode}}}`. `sebab_kode`: `bukan_kamera` (409), `kamera_tidak_menjawab` (503), else the `domain/line_tak_terbaca.py` codes (`bukan_line` for a line older than this route). One line that fails never empties the others. Router `routes/console_kamera.py`, service `services/setelan_kamera_konsol.py` |
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
| `AI_MATI_DETIK` | `30` | Detik gambar masuk tanpa frame yang selesai digrading sebelum AI mati; dijepit 10..600. Nilai yang bukan bilangan bulat atau di luar batas jatuh ke bawaan/dijepit dengan WARNING, tidak pernah menahan boot |
| `GARIS_CAPTURE` | `300` | Garis capture (px, ruang **stream**). `0` = tanpa garis. Nilai awal |
| `SUMBU_GARIS` | `tegak` | `tegak` (conveyor mendatar, px dari **kiri**) / `mendatar` (conveyor menurun, px dari **atas**). Nilai awal |
| `MODE_DEV` | `false` | `true` = angka keyakinan ikut digambar di kotak janjang. Untuk support, bukan operator. Nilai awal |
| `YOLO_SKIP_FRAMES` | `1` | Jalankan YOLO tiap N frame (`1` = produksi) |
| `DEBUG_MODEL_OUTPUT` | - | Log raw output model tiap inferensi (berisik) |
| `ROI_X1` / `ROI_Y1` / `ROI_X2` / `ROI_Y2` | `0` | Kotak wilayah deteksi (px, ruang stream). `0,0,0,0` = full frame; `X2`/`Y2` `0` = lebar/tinggi penuh. Nilai awal: kotak yang disetel dari tab Setelan menang |
| `STREAM_WIDTH` / `STREAM_HEIGHT` / `STREAM_FPS` | `1280` / `720` / `12` | MJPEG stream (setelah resize); tidak menyentuh kamera maupun hasil simpan |
| `BORDER_THICKNESS` / `FONT_SCALE` / `FONT_THICKNESS` | `2` / `0.7` / `2` | Kotak dan label deteksi; frame kamera besar (1224×1024 di Lampung, binning 2×2) butuh angka jauh lebih besar |
| `CAMERA_TYPE` | `hikrobot` | Jenis sumber. Di Docker diisi compose dari `LINE_N_CAMERA_TYPE` di `media.env` (tab Line → Sumber Kamera), dan line membaca ulang `media.env` sendiri saat boot |
| `MEDIA_FILE` / `MEDIA_DIR` / `MEDIA_ENV_PATH` | - / `/media` / `/config/media.env` (compose) | Nama berkas video/foto (bukan path), foldernya, dan berkas setelan sumber kamera |
| `UPDATE_DIR` | `<repo>/update`; compose `/app/update` | Konsol saja: folder Update now (`./update:/app/update`). Demo droplet mengisinya tanpa mount, jadi tombol tidak pernah muncul |
| `CAMERA_VIDEO_LOOP` | `false` | `true` = video diulang terus (uji performa); tiap putaran me-reset ByteTrack. Dari `LINE_N_VIDEO_LOOP` |
| `CAMERA_VIDEO_PATH` / `CAMERA_PHOTO_PATH` | - | Path penuh sumber video/foto untuk `make line` (native, tanpa `media.env`). `MEDIA_FILE` menang kalau ada |
| `CAMERA_SERIAL` | - | Pilih kamera Hikrobot by serial. Dari `LINE_N_CAMERA_SERIAL` di `.env`; kosong = fallback index |
| `CAMERA_DEVICE_INDEX` | `0` | Index device (fallback kalau serial kosong). Compose memberi `0` / `1` / `2` per line |
| `CAMERA_FEATURE_FILE` | - | `.mfs` yang dimuat ke kamera tiap connect. Dari `LINE_N_FEATURE_FILE`, bawaan compose `config/camera/hikrobot.mfs` |
| `CAMERA_SETELAN_DIR` | kosong | Folder of camera settings files saved from the console, one per line (`line-1.mfs`). At each connect `<dir>/<line_code>.mfs` wins when it exists; else `CAMERA_FEATURE_FILE` is used, which stays the baseline (`integrations/camera/berkas_fitur.py`). Empty = off, today's behaviour. Set by the factory compose together with the folder mount in phase 2 |
| `CAMERA_WIDTH` / `CAMERA_HEIGHT` | `320` / `240` | Hanya sumber OpenCV dan pemanasan model; Hikrobot memakai ukuran dari `.mfs`. Compose: `2448` / `2048` |
| `CAMERA_FPS` | `20` | Cadangan untuk sumber yang tidak bisa melaporkan lajunya (webcam, video). Hikrobot: laju dari `.mfs` (15). Video: kosongkan / `0` supaya diputar pada laju aslinya |
| `REKAMAN_DIR` | `<repo>/videos` | Folder rekaman video developer (compose: `/app/videos`) |
| `UPLOAD_MINUTE` | `0` | Menit tiap jam batch uploader jalan |
| `UPLOAD_MAX_ITEMS_PER_TICK` | `2000` | Jumlah maksimal item per batch run |
| `UPLOAD_RETENTION_DAYS` | `7` | Umur arsip lokal item `done` (pabrik: 180) |
| `UPLOAD_DISK_MIN_FREE_GB` | `20` | Lantai sisa disk: di bawahnya item `done` tertua dibuang lebih awal. `0` = mati |
| `DISK_PERINGATAN_GB`, `DISK_KRITIS_GB` | `15`, `5` | Pemantau disk (batch 3.7): alert konsol + kartu Diagnostik saat sisa disk di bawah angka ini, dengan atau tanpa R2, tanpa menghapus apa pun. `0` = tingkat itu mati. Peringatan wajib di bawah `UPLOAD_DISK_MIN_FREE_GB` (dengan R2 sisa disk dijaga di sekitar lantai itu); salah ketik jatuh ke bawaan dengan WARNING |
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
| `LOG_LEVEL` | `INFO` | Level keluaran proses (`docker logs`) line dan konsol; salah ketik = INFO + satu WARNING; tab Log tetap WARNING/ERROR |
| `DISCORD_WEBHOOK_URL` | kosong | Konsol, opsional. Kosong = fitur Lapor Discord mati total (aturan 34); rahasia, tidak pernah dicatat atau dikirim ke layar. Lampung: tambahkan di blok `console:` compose host DAN `.env` PC, lalu `autograde restart` |
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


## Endpoint notes moved from CLAUDE.md (2026-09-30)

Verbatim copy of the former `CLAUDE.md` sections "HTTP Surface" and "Integration Contracts". The tables above are the reference; this block carries the per-endpoint notes and warnings that only lived in `CLAUDE.md`. A later pass may merge the two.

## HTTP Surface (this service)

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/detail` | `/health` ringan, **503 kalau AI mati atau frame berhenti** (`ai` = keadaan penjaga AI, `routes/health_ringan.py`, tanpa torch); detail = camera / gpu / workers / current_assignment_id (+ `outbox_pending` = semua janjang belum sampai konsol, `outbox_failed` selalu `0` sejak batch 2.4, rincian di tab Status → Antrean line) + `model_file`/`model_backend`/`model_kelas`/`model_kelas_cocok`/`gpu_sm` = model yang benar-benar dimuat + `ai` (keadaan + `galat_terakhir`) + `fps_kamera`/`fps_deteksi` (terukur, 0 kalau basi) + `frame_umur_detik` + `suhu_kamera_c` (°C, `null` kalau basi atau tidak terbaca) + `suhu_kamera_didukung` + kesehatan kamera (`fps_kamera_turun`, `frame_hilang`, `putus_kamera`, `kamera_tingkat`) + `disk` (pemantau disk) + `lisensi` + `plc.connected` (aturan 35) |
| GET | `/api/video_feed` | MJPEG live (multi-viewer) |
| GET | `/api/results_today` | today's results (read from disk) |
| POST | `/internal/assignment` | ← from api: set current truck/assignment (`x-internal-secret`) |
| GET | `/internal/status` | ← dari konsol tiap 1 detik (`LineStatusWorker`): truk, piston, `alarms` PLC (aturan 24), dan `unggah` = ringkasan upload foto ke R2 untuk Last Sync (`aktif`/`terakhir`/`gagal_sejak`/`antre`, aturan 27). `unggah` dihitung **sekali per batch**, bukan per panggilan; `null` di line tanpa worker upload. Bawa juga `ai` = blok penjaga AI mati (keadaan, `mati`, `kode`, `sejak`, `ambang_detik`), tanpa galat mentah, dan `disk` = blok pemantau disk (aturan 35). `x-internal-secret` |
| POST | `/internal/manual-reject` | ← from api: trigger manual reject (`x-internal-secret`) |
| POST | `/internal/hapus-data` | ← dari konsol (Danger Zone): tulis penanda `artifacts/.hapus-data` lalu keluar lewat urutan tutup yang sama (aturan 29); data line dihapus **saat boot berikutnya**, sebelum store mana pun membuka berkasnya. **409** kalau line sedang dipasangi truk. Selama penandanya ada, `/internal/assignment` menolak truk baru (**409** `hapus_berjalan`). Router `routes/internal_bahaya.py`: **tanpa torch**, jadi teruji di CI |
| POST | `/internal/restart` | ← dari konsol (Sumber Kamera, Model Deteksi, Danger Zone): jawab dulu, 1 detik kemudian urutan tutup yang SAMA dengan SIGTERM (coil PLC mati bersamaan dengan antrean simpan dihabiskan, lalu kamera + penjadwal R2), lalu antrean log line dikuras (batch 3.2, maks 1 detik), maks 10 detik total, baru `os._exit(0)`. Aturan 29 |
| GET / POST | `/internal/rekam/berkas`, `/internal/rekam/hapus` | ← dari konsol (Danger Zone): hitung / hapus rekaman **milik line ini** (`{line_code}_*.mp4`, folder `videos/` dipakai bersama). Hapus **409** selama merekam |
| WS | `/ws/results` | legacy result push. ⚠️ `image_url`-nya dikirim **sebelum** berkasnya ada di disk (deteksi menyerahkan janjang ke `CaptureSaveWorker` lalu lanjut), jendelanya ratusan milidetik. Tidak ada yang memakai lane ini hari ini (`console.html` tidak membukanya), tapi siapa pun yang menghidupkannya harus menahan gambar sampai 404 pertama lewat. Jalur yang dipakai konsol aman: barisnya ditulis penulis **sesudah** gambarnya jadi |
| GET | `/captures/...` | static images (mount → `artifacts/`), tanpa sesi (line tidak punya konsep login): `.db`/berkas tersembunyi dijawab 404 (`domain/berkas_captures.py`) |
| GET | `/internal/outbox` | ← dari konsol (tab Status → Antrean line): `{line_code, aktif, menunggu, tertua_at, ditolak, ditolak_at, ditolak_alasan, lama_tertinggal, tersambung, putus_sejak, sebab_putus, coba_lagi_at, galat, galat_at}` (`ditolak` = baris yang percobaan terakhirnya ditolak konsol 400/422). Router `routes/internal_outbox.py`, **tanpa torch**. `x-internal-secret` |
| POST | `/internal/outbox/requeue` | ← Kirim Ulang: semua baris jatuh tempo sekarang, jeda sambungan dibatalkan → `{requeued}`. URL dan bentuk sama dengan sebelum batch 2.4. `x-internal-secret` |
| GET | `/internal/log` | ← dari konsol tiap 10 detik (`TarikLogLineWorker`, batch 3.2): `?setelah=<seq>&generasi=<g>&batas=<n>` → `{generasi, entri[{id, seq, first_at, last_at, level, source, message, detail, count}], seq_akhir, lagi, dibuang}`. WARNING/ERROR line ini dari `log_line.db` (folder DB line, maks 2.000 baris, selamat dari `--force-recreate` dan Danger Zone). Terbuka walau lisensi habis, tetap `x-internal-secret`. Router `routes/internal_log.py`, **tanpa torch** |

**Konsol (`APP_MODE=console`, port 8100 image produksi dan `make console`, 8000 dari source)**: surface yang berbeda total; `main.py` tidak dipakai.
**Semua `/api/console/*` butuh sesi** (Fase 4) kecuali tiga baris pertama di bawah; tanpa cookie
`konsol_sesi` jawabannya 401 `belum_masuk`. Lane mesin (`/internal/*` di line, dan yang masuk
konsol dari line/program timbangan) tetap pakai secret di header, bukan sesi: `x-internal-secret`
(`INTERNAL_SECRET`, kosong = `WEBHOOK_SECRET`) untuk perintah konsol → line, `x-webhook-secret`
(`WEBHOOK_SECRET`) untuk line/timbangan → konsol:

| Method | Path | Notes |
|---|---|---|
| GET | `/console` | layar operator (satu file HTML statis): terbuka, dia yang menggambar gerbang login. `Cache-Control: no-cache`: tanpa itu kiosk menyimpan halaman versi lama sesudah update (Lampung 2026-10-05) |
| GET | `/api/console/operators` | email + nama akun aktif untuk mengisi kolom email, **tanpa** hash, terbuka |
| POST | `/api/console/login` | `{email, sandi}` → cookie `konsol_sesi` HttpOnly, 12 jam. Sandi salah 401, login terkunci 429 |
| POST | `/api/console/logout` | akhiri sesi ini saja |
| GET | `/api/console/me` | operator yang sedang masuk + `sisa_detik` sesinya |
| POST | `/api/console/session/renew` | geser sesi ini 12 jam dari sekarang (aturan 19, batch 5.7) |
| GET | `/api/console/state` | ringkasan hari kerja (di-polling 2 detik; tanpa baris grading sejak batch 6.4: kunci `recent` dibuang, tabel Grading cuma dari `/api/console/history`) + `antrean_bongkar` + `penugasan_otomatis` (aturan 36) + `lisensi` (severity/tanggal/sisa hari) untuk banner operator + `plc.alarms` per line (motor fault / E-stop) untuk pita alarm + `sinkron` untuk **Last Sync** (`autoerp` dan `cloud`: `keadaan`/`terakhir`/`sejak`/`antre`, aturan 27). + `versi` image, untuk baris versi + lisensi di bawah tulisan AUTOGRADE (semua akun, 2026-09-28). Semuanya di sini, **bukan** lane support: yang melihat kamera berhenti, motor mati, atau sambungan putus itu operator biasa |
| GET | `/api/console/history` | filter `work_date` / `line_code` / `truck_id`; `limit`+`offset` untuk pagination, dan `total` (jumlah baris yang cocok filter, bukan sepanjang halaman) ikut dibalas; `thumb_url` per baris untuk tabel (batch 5.12), juga di `/api/console/riwayat` tampilan janjang |
| GET | `/api/console/trucks` | master truk + supplier + `source_label` + `di_lokasi` (batch 5.6: sudah timbang isi, belum timbang kosong, dalam jendela kunjungan 12 jam; layar menaruh truk itu di bagian **Di lokasi** paling atas daftar Pilih Truk kartu line) |
| POST | `/api/console/trucks` | truk manual (truk pinjaman / belum terdaftar), id = uuid5 plat ternormalisasi |
| GET | `/api/console/trucks/{plat}/qr.png` | kartu QR untuk ditempel di truk / dikirim ke HP supir. **Dibuat di server** (`segno`, pure-Python) karena `console.html` nol referensi `https://`, pustaka CDN akan mati saat internet putus. Isinya plat ternormalisasi, divalidasi ulang sebelum dicetak. Truk yang belum terdaftar tetap dilayani: kartu dicetak dulu, truknya didaftarkan kemudian |
| POST | `/api/console/scan/keluar` | `{qr}` scan 3 (timbang kosong) → tiket yang menunggu tara. **Dua tiket terbuka ditolak, tidak ditebak** (keputusan operator 2026-09-15): menebak bisa memasangkan tara ke kunjungan yang salah dan mencampur tonase dua kunjungan. Dibatasi jendela kunjungan 12 jam sebelum jam konsol pada waktu timbang isi sebenarnya (`awal_kunjungan`), bukan hari kerja: truk yang timbang isi 23:50 ditemukan pukul 00:10, sedangkan tiket yang taranya kosong sejak lebih dari 12 jam tidak (netonya akan memakai bruto lama dan tara malam ini) |
| POST | `/api/console/scan` | `{qr}` hasil scan di gerbang timbangan → truk yang sudah ada. Truk belum terdaftar dijawab **200 `ditemukan:false`** (truk pinjaman itu kasus normal, 404 terbaca seperti kerusakan); yang bukan plat **400**. **Tidak pernah membuat truk dan tidak pernah menulis berat** |
| GET | `/api/console/weighings` | tiket timbangan hari kerja (bruto / tara / neto); untuk hari ini juga kunjungan hari kerja lain (sebelumnya, atau sesudahnya kalau cutoff hari kerja dinaikkan malam hari, batch 5.11) yang belum keluar gerbang (`left_at` kosong): tanpa tara kalau timbang isi dalam 12 jam terakhir, bertara kalau timbang kosong dalam 24 jam terakhir dan belum selesai tanpa scan 4, di ujung `items` dengan `work_date` miliknya sendiri (2026-10-02), plus `erp_perlu_dicek` (`tiket_final_berbeda` / `tiket_dibatalkan` / null). Sejak aturan 37 tiap tiket membawa `arrived_at`, `left_at`, `antre_menit` (scan 2 dikurangi scan 1), `total_menit` (scan 4 dikurangi scan 1, atau dari scan 2 kalau scan 1 terlewat) dan `tanpa_scan_1`; menit yang tak bisa dihitung `null`, bukan 0. Sejak 2026-10-02 tiap tiket juga membawa `tahap` (`bongkar` = timbang isi tanpa tara, `timbang_kosong` = sudah ditara belum keluar, `selesai` = sudah keluar, atau selesai tanpa scan 4; `domain/gerbang.tahap_tiket`). Sejak 2026-10-03 tiap tiket membawa `tanpa_scan_4`: `true` untuk tiket bertara yang tidak pernah Keluar dan timbang kosongnya lebih dari 24 jam lalu, atau yang truknya sudah datang lagi (scan 1 menunggu) atau timbang isi lagi sesudah timbang kosongnya (`domain/gerbang.selesai_tanpa_scan_4`). Tahapnya `selesai`, `total_menit` dihitung sampai timbang kosong, dan `left_at` tetap kosong: tidak ada jam keluar yang dikarang, dan `items` urut timbang isi terbaru menurut waktu sebenarnya (`julianday(entered_at)`, cadangan `received_at`, lalu `rowid`), bukan menurut teks ISO: `Z` dan `+07:00` tercampur. Jawabannya juga membawa `waiting`: `[{id, plate_number, arrived_at, menit, tahap}]` (`id` dipakai tombol Batal datang) (`tahap` selalu `datang`, tertua dulu menurut waktu sebenarnya), truk yang sudah scan 1 dan belum timbang isi, dalam jendela klaim 12 jam dari sekarang (bukan hari kerja; parameter `work_date` tidak berlaku untuk `waiting`) (`menit` dari jam server, `null` kalau jam tersimpan tak terbaca atau di masa depan). Sejak 2026-10-03 (round 4) jawabannya juga membawa `dibatalkan`: `[{plate_number, arrived_at, cancelled_at, cancelled_by, cancelled_by_name}]`, kedatangan hari kerja `work_date` (menurut `arrivals.work_date`) yang dibatalkan lewat Batal datang, terbaru dibatalkan dulu menurut waktu sebenarnya; `cancelled_at` jam server, `cancelled_by` email operator, `cancelled_by_name` nama operator yang disimpan saat batal (`null` kalau tak ada; kolom Oleh menampilkan nama, jatuh ke email kalau `null`); layar memformat jamnya sendiri |
| POST | `/api/console/arrivals` | Operator. `{qr, at?}` scan 1. `hasil`: `tercatat`, `sudah_tercatat` (truk itu masih menunggu), `masih_di_dalam` (sudah timbang isi dan belum timbang kosong, tidak ditulis). Bukan plat dan bukan truk terdaftar 400 `bukan_plat` (truk terdaftar berplat tak biasa diterima); jam tak terbaca 400 `input_tidak_sah`. Truk belum terdaftar boleh datang. Tabel `arrivals`, **tidak pernah ke AutoERP** |
| POST | `/api/console/arrivals/{arrival_id}/cancel` | Operator. Batal datang (2026-10-03): truk salah pilih atau ditolak di gerbang. Cuma kedatangan yang masih menunggu (`weighing_id` kosong, `cancelled_at` kosong) yang dibatalkan. Barisnya **tidak dihapus** (round 4): kolom `arrivals.cancelled_at` (jam server) `arrivals.cancelled_by` (email operator, identitas) dan `arrivals.cancelled_by_name` (nama operator dari sesi saat tombol ditekan, salinan yang bertahan walau akunnya nanti diganti nama atau dihapus; kosong kalau tak ada nama) diisi, skema `console.db` versi 5, dan setiap pembaca kedatangan menunggu (daftar `waiting`, klaim timbang isi, jejak "truk datang lagi") melewatinya; riwayatnya dibaca lewat `dibatalkan` di `GET /api/console/weighings`. Jawaban 200 `{hasil: "dibatalkan", plate_number}` atau `{hasil: "tidak_ada"}` (sudah timbang isi, sudah dibatalkan, id tak dikenal). Satu baris log berisi plat dan email operator juga tetap ditulis. **Tidak pernah ke AutoERP** |
| POST | `/api/console/departures` | Operator. `{qr?, weighing_id?, at?}` scan 4: `weighing_id` (tombol **Keluar** di baris) atau `qr` (tiket tanpa tara 12 jam, tiket bertara 24 jam dari timbang kosong). Tiket bertara yang sudah selesai tanpa scan 4 (lewat 24 jam, atau truknya sudah datang atau timbang isi lagi) dijawab `sudah_keluar` dan tidak ditulis, jadi Keluar kunjungan baru tidak pernah menutup kunjungan lama. `hasil`: `tercatat` (menulis `weighings.left_at`, jawaban membawa `left_at`), `belum_timbang_kosong` (**ditolak, tidak ditulis**), `sudah_keluar`, `tidak_ada_tiket`. 400 `input_tidak_sah` untuk jam rusak. Jam tanpa zona dibaca UTC. **Tidak pernah ke AutoERP** |
| POST | `/api/console/weighings` | operator mengetik bruto/tara sendiri: payload identik dengan kiriman program timbangan. Jawabannya membawa `dipasang`: per line yang dicoba penugasan otomatis `{line_code, plate_number, terpasang}` (`[]` kalau saklar mati atau truk menunggu; line yang tidak menjawab `terpasang: false`, timbangan tetap tersimpan; aturan 36) |
| GET | `/api/console/recap` | rekap per truk satu hari kerja (janjang, ACC/REJ, neto): `?work_date=` opsional. **Tidak dipakai layar lagi** sejak tab Rekap = Riwayat (2026-09-28) |
| GET | `/api/console/riwayat` | tab **Rekap** (dulu Riwayat; operator biasa, bukan support): `dari`/`sampai` (tanggal kerja, maks **31 hari**, tanpa tanggal = 7 hari terakhir), `line_code`, `plat` (potongan plat), `hasil` (`ripe`/`unripe`/`jk`/`tp`, Per janjang saja), `tampilan=hari\|truk\|janjang`, `ringkasan=true\|false`. Per hari & per truk dikirim utuh, per janjang `limit`+`offset`. **400** kode `riwayat_*` untuk tanggal yang salah, **400** `input_tidak_sah` untuk tampilan/hasil asing. Aturan 26 |
| GET | `/api/console/riwayat/csv` | filter yang sama + `bahasa=id\|en` → lampiran CSV (BOM UTF-8, jam pabrik), **semua** baris filter itu, dialirkan per potongan |
| POST | `/api/console/dev/riwayat/impor/periksa` | **support**: badan = CSV Per janjang apa adanya (bukan multipart), `?nama=` → hitungan baru / sudah ada / hari berjalan / ganda / salah + `sidik` sha256. Tidak menyimpan apa pun. **400** kode `impor_*` untuk berkas yang ditolak, **413** lebih dari 50 MB |
| POST | `/api/console/dev/riwayat/impor` | **support**: berkas yang SAMA + `?sidik=` hasil periksa → **201** `{batch}`. **409** kalau berkas berubah, ada baris salah, tidak ada yang baru, impor lain berjalan, atau Danger Zone sedang menghapus |
| GET | `/api/console/dev/riwayat/impor` | **support**: 20 impor terakhir |
| POST | `/api/console/dev/riwayat/impor/{id}/batal` | **support**: hapus janjang satu impor. **404** tidak ada, **409** sudah dibatalkan |
| POST | `/api/console/lines/{line}/assign-truck` | → diteruskan ke `/internal/assignment` line. **409** `hapus_berjalan` selama Danger Zone menghapus data (line tidak disentuh), **409** `pembaruan_berjalan` selama Update now berjalan |
| GET / POST | `/api/console/update`, `/api/console/update/install` | Update now (batch 4.6): § Update now di atas |
| POST | `/api/console/lines/{line}/release-truck` | truk pergi → `/internal/assignment` line dengan truk kosong. Jawabannya membawa `dipasang` (truk berikutnya yang naik otomatis, `[]` kalau tidak ada atau saklar mati; aturan 36) |
| POST | `/api/console/lines/{line}/force-release` | Lepas paksa for a line that does not answer; see the operator table above. Once a line that was only cut off answers again, `LineStatusWorker` sees the forced truck in its `/internal/status` `truck_id` and the console sends the release again (one WARNING) |
| POST | `/api/console/unloading-queue/{weighing_id}/assign`, `/skip` | **Tugaskan sekarang** / **Lewati** pada antrean bongkar, lihat tabel konsol di atas (aturan 36) |
| POST | `/api/console/lines/{line}/manual-reject` | → diteruskan ke `/internal/manual-reject` line |
| POST | `/api/console/lines/{line}/piston` | `{open}` → diteruskan ke `/internal/piston` line. Menggerakkan hardware, jadi butuh sesi operator seperti lane operator lain (batch 1.1), dan tiap percobaan dicatat WARNING menyebut siapa yang menekan (tab Log), dipicu atau ditolak |
| POST | `/api/console/lines/{line}/reconnect-camera` | Sambung ulang on the line card, every account → `/internal/camera/reconnect` line; see the operator table above |
| GET | `/api/console/dev/ping` | lane developer paling ringan: dipakai layar untuk memastikan akses masih hidup. **Semua baris `/dev/*` di bawah ini butuh `role='support'`, dijawab 403 kalau bukan** |
| GET | `/api/console/dev/log` | isi `event_log`: filter `level`/`cari`, pagination `limit`+`offset`. Sejak batch 3.2 baris tarikan line membawa `line_code` (null = konsol) dan `asal`; `cari` juga mencocokkan kode line |
| GET | `/api/console/dev/lapor-discord` | **support**: keadaan lapor Discord (`mati`/`url_salah`/`rusak`/`aktif`/`tertahan`/`ditolak`/`isi_ditolak`) + antrean (`kiriman`, `disisihkan`) + galat terakhir. Alamat webhook tidak pernah ikut |
| GET | `/api/console/dev/diagnostik` | `/health/detail` ketiga line, digabung satu layar |
| GET | `/api/console/dev/antrean` | isi `erp_outbox`: jumlah pending/gagal + daftar yang gagal |
| POST | `/api/console/dev/antrean/kirim-ulang` | requeue semua baris gagal di `erp_outbox` |
| GET | `/api/console/dev/antrean/line` | **support**: antrean janjang tiap line ke konsol, satu baris per line; line mati atau menolak kunci tetap 200 dengan `kode`/`status`/`pesan` |
| POST | `/api/console/dev/antrean/line/{line}/kirim-ulang` | **support**: → `/internal/outbox/requeue` line itu → `{line_code, dijadwalkan}`. **404** `line_tidak_dikenal`, **502** `line_tidak_menjawab`/`line_menolak`. Tiap tekanan satu WARNING menyebut pelakunya |
| GET | `/api/console/dev/versi` | versi image + lisensi berjalan lengkap dengan nama perusahaan dan tanggal |
| GET | `/api/console/dev/akun` | semua akun yang bisa masuk konsol di PC ini (aktif, mati, terkunci; asal `lokal`/`erp`; sedang masuk atau tidak). **Tanpa hash sandi**, kolomnya disebut satu per satu (`domain/daftar_akun.py`) |
| POST | `/api/console/dev/akun` | `{email, nama, sandi, sandi_ulang, role}` → **201** akun **lokal** baru. Email yang sudah ada **409** `akun_sudah_ada` (tidak diganti sandinya), email milik AutoERP **409** `akun_milik_erp`, isian salah **400**. Aturan 19 |
| POST | `/api/console/dev/akun/sandi` · `/status` · `/role` | ganti sandi (semua sesi akun itu berakhir; status tetap) · `{email, aktif}` matikan/aktifkan (`aktif` wajib boolean, teks bebas 400 `input_tidak_sah`) · ubah role. **Akun lokal saja** (409 `akun_milik_erp`); matikan dan ubah role **bukan untuk akun sendiri** (409 `akun_diri_sendiri`); email tak dikenal 404 `akun_tidak_ada`. Tiap perubahan satu WARNING menyebut pelakunya |
| GET | `/api/console/dev/plc/{line_code}` | snapshot DI + daftar coil yang boleh diuji untuk satu line, baca saja, aman dibuka kapan pun |
| POST | `/api/console/dev/plc/{line_code}/coil` | picu satu coil PLC line itu, **satu-satunya aksi konsol yang menggerakkan hardware fisik**, lihat `docs/rules.md` § Critical Rules |
| GET | `/api/console/dev/rekam` | status rekaman tiap line + setelan yang berlaku + sisa disk. Line yang tidak menjawab dilaporkan `terbaca:false`, bukan menjatuhkan seluruh jawaban |
| POST | `/api/console/dev/rekam/setelan` | ubah resolusi rekaman. Berlaku untuk rekaman **berikutnya**: mengubah resolusi di tengah berkas MP4 menghasilkannya rusak. `bitrate_kbps` dicabut 2026-09-25 (tidak pernah sampai ke `cv2.VideoWriter`); kiriman yang masih membawanya diabaikan |
| POST | `/api/console/dev/rekam/{line_code}/mulai` | mulai merekam satu line. 409 kalau sudah merekam, **507 kalau disk mepet** (dua hal yang butuh tindakan berbeda, jadi tidak diratakan) |
| POST | `/api/console/dev/rekam/{line_code}/stop` | hentikan dan tutup berkasnya. Menahan ~2 detik: line menunggu encoder menulis frame yang sudah antre (maks 30) lalu menutup berkas dengan rapi |
| GET | `/api/console/dev/model-deteksi` | pilihan model tiap line + semua `.pt` di `models/release` dengan kelas, engine per GPU, `cocok`/`alasan` |
| POST | `/api/console/dev/model-deteksi` | ganti model per line (`LINE_N_MODEL_FILE` di `media.env`), restart line yang berubah. **400** untuk model yang tidak ada atau kelasnya asing, tanpa menulis apa pun |
| GET | `/api/console/dev/bahaya` | Danger Zone: angka (janjang, tiket, truk, akun, sesi, rekaman) + hambatan + peringatan untuk kelima aksi, dari keadaan line saat itu |
| POST | `/api/console/dev/bahaya/restart-line` · `/logout-semua` | restart ketiga line · hapus semua sesi (termasuk yang menekan). Tidak diblokir; hasil per line |
| POST | `/api/console/dev/bahaya/hapus-rekaman` | `{konfirmasi:"HAPUS"}`: tiap line menghapus rekamannya; yang merekam/mati dilewati dan disebut |
| POST | `/api/console/dev/bahaya/hapus-data` | `{mode:"transaksi"\|"semua", konfirmasi:"HAPUS"}`. **400** konfirmasi/mode salah, **409** `bahaya_ditolak` (+`params.hambatan`), **409** `semua_line_menolak` (+`params.lines`, mis. `line-1:lisensi`): ketiganya tidak mengubah apa pun. **200** membawa hasil per line; `ok:true` + `kode:"belum_mati"` = diterima tapi line belum restart. Lihat aturan 25 |
| POST | `{BACKEND_API_VER}/internal/vision/events` | ← dari tiga line (`x-webhook-secret`), kontrak §5; janjang baru untuk penugasan yang sudah dilepas mengantre ulang kunjungannya (batch 2.3) |
| POST | `{BACKEND_API_VER}/internal/scale/weighing` | ← dari program timbangan (`x-webhook-secret`), bentuk sementara kita |
| GET | `/captures/{line_code}/...` | gambar line, mount read-only, bentuk URL = `resolveCaptureUrl` api. Butuh sesi operator (401 `belum_masuk` tanpa cookie `konsol_sesi`, batch 1.3); `.db`/berkas tersembunyi tetap 404 apa pun sesinya |
| GET | `/health` | ringan, sengaja bukan `routes/health.py` (yang itu menarik torch) |

**Layar penuh = urusan browser, BUKAN `console.html`.** `requestFullscreen()` wajib dipanggil
dari gestur pengguna, jadi tidak ada halaman web yang boleh memfullscreen dirinya sendiri saat
dimuat: kiosk datang dari `scripts/console-kiosk.sh` (Chrome `--kiosk`), dengan
`scripts/palmgrade-console.desktop` untuk jalan otomatis saat login. Tiga hal di skrip itu yang
tidak boleh hilang: `--user-data-dir` tetap (pilihan operator hidup di `localStorage`; profil
sementara atau `--incognito` = semuanya balik ke bawaan tiap pagi), tunggu konsol menjawab dulu
(sesudah listrik mati sesi desktop sering login sebelum Docker siap, dan kiosk yang mendarat di
halaman error tidak pernah memuat ulang sendiri), dan `xset s off -dpms` (layar yang dilihat dari
jauh tanpa disentuh berjam-jam akan ditidurkan screensaver).

---

## Integration Contracts

**line → konsol** (`OutboxRetryWorker`, poll 1 detik, tanpa batas nyerah, aturan 31): `POST {BACKEND_URL}{BACKEND_API_VER}/internal/vision/events`
dengan header **`x-webhook-secret: WEBHOOK_SECRET`**. Kontraknya kontrak §5 lama palmgrade-api,
dipertahankan persis supaya kode line tidak berubah. Konsol menyimpan ke `console.db` dan
mengabaikan kiriman ulang (`INSERT OR IGNORE` per `event_id`).
⚠️ `BACKEND_URL` **wajib** konsol lokal. Menunjuknya ke `api.smagri.id` adalah yang membanjiri
produksi dengan ~1098 event tes pada 2026-08-09.

- Payload: `prediction` `"Acc"|"Rej"`, `ripeness_status` `"ACC"|"REJ"` (**UPPERCASE**, divalidasi
  saat ingest, aturan 18), `grade_class`, `tp_status` `"PASS"` atau `null` (never `"TP"`),
  `capture_type` `"auto"|"manual"`, `machine_id` (= `LINE_N_MACHINE_ID`, cara konsol mengenali
  line), `event_id` UUID (**selalu** uuid5 deterministik `machine_id:file_timestamp`),
  `timestamp` ISO **UTC-aware**, `truck_id` opsional, `bounding_box` `{x_min,y_min,x_max,y_max}`.
- `image_path` relatif; konsol meng-serve gambar tiap line di `/captures/{line_code}/...`
  (mount read-only).

**konsol → line** (header **`x-internal-secret: INTERNAL_SECRET`**, kosong = `WEBHOOK_SECRET`):
`POST /internal/assignment` `{machine_id, assignment_id, truck_id, assigned_at}`, `POST
/internal/manual-reject`, `POST /internal/piston`, `POST /internal/camera/reconnect`, `GET /internal/status` (tiap 1 detik), `GET
/health` dan `/health/detail` (tab Status). Kunci yang beda antara konsol dan satu line tidak
membuat line itu OFFLINE: kartunya menulis "kunci ditolak" (`LINE_MENOLAK`), karena line hidup
dan menjawab, cuma menolak headernya (`integrations/notifications/line_client.py`,
`workers/line_status_worker.py`). Danger Zone masih membaca line begitu sebagai "line mati"
kalau ditolak saat hapus data (follow-up yang belum dikerjakan).

**Batch ke cloud** (`BatchUploadWorker`, tiap jam menit `UPLOAD_MINUTE`): foto (`bbox/` + `thumb/`)
di-`PUT` ke **Cloudflare R2**. Teks per janjang dulu ikut dikirim ke `UPLOAD_API_URL`
(palmgrade-api cloud, **pensiun**): di pabrik dikosongkan, dan kosong = item `done` begitu fotonya
sampai. **Kill switch**: `R2_BUCKET` kosong membuat seluruh batch no-op (satu `logger.warning`
di tick pertama, lalu diam) dan `/health/detail` tidak memberi tahu.

**Shared config: dua secret, bukan satu.** `WEBHOOK_SECRET` tetap dipegang line ↔ konsol
(`x-webhook-secret`, jalur §5 di atas) **dan** program timbangan pihak ketiga. `INTERNAL_SECRET`
(sejak batch 1, `x-internal-secret`) memisahkan perintah konsol → line (restart, hapus data, coil
PLC uji, piston, dsb.) dari kunci yang dipegang pihak ketiga: kosong atau sama dengan
`WEBHOOK_SECRET` = perintah konsol masih memakai kunci lama (`.env` PC yang dipasang sebelum
batch 1 tetap jalan tanpa diubah), beda = terpisah. Perbandingan **constant-time**
(`domain/rahasia.py`) dan **fail closed**: secret yang dikonfigurasi kosong tidak pernah membuka
lane, di line maupun di konsol (`routes/penjaga_rahasia.py`).
**Fail-fast:** `Settings.validate_secrets()` (dipanggil line **dan** konsol) raise saat
`APP_ENV=production` & `WEBHOOK_SECRET` masih bawaan (`supersecret123`) **atau** kosong.
`INTERNAL_SECRET` **kosong atau tidak diisi cuma warning** (jatuh ke `WEBHOOK_SECRET`, `.env` lama
tetap jalan); kalau **diisi**, nilainya ikut aturan yang sama (bawaan atau kosong-setelah-dipangkas
= menolak start). `LINE_1/2/3_MACHINE_ID` harus sama di line dan di konsol; compose membawa UUID
bawaan kalau kosong.

Full endpoint / payload / env tables: `docs/backend-overview.md`.

---

