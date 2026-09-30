# autograde

AI camera service for the **Palmgrade** palm oil ripeness grading system.

Runs as **3 camera containers** (one per line, each on its own Hikrobot industrial camera) plus a **4th container dari image yang sama**: konsol operator offline (`APP_MODE=console`, port **8100** di PC pabrik). Line melakukan deteksi ripeness YOLO real-time, menulis tiap hasil ke disk, lalu mengirimkannya lewat **dua jalur paralel**: realtime ke konsol lokal (poll 1 detik) dan **batch tiap jam** ke Cloudflare R2 (foto). Konsol mengirim satu rekap per kunjungan truk ke AutoERP.

> **Baru pertama kali buka repo ini?** Baca [`docs/MANUAL.md`](docs/MANUAL.md) dulu (bahasa
> Indonesia, versi cetak `docs/MANUAL.pdf`): sistem ini ngapain, cara pakai konsol, pasang,
> operasional, peta folder (§9.1), dan langkah pertama (§9.2).

---

## Quick Start: pilih jalur

Ada **dua jalur yang sengaja dipisah**. Produksi selalu jalan di Linux; develop boleh di Mac.
Jalur Linux tidak pernah diubah demi Mac, yang untuk Mac cuma tambahan.

| | **Develop di Mac** (tanpa kamera) | **Linux / PC pabrik** (produksi) |
|---|---|---|
| Yang jalan | konsol operator, native (tanpa Docker) | 3 line kamera + konsol, di Docker |
| Butuh | Python 3.12 | Docker, GPU NVIDIA + Container Toolkit, SDK MVS di `/opt/MVS`, model `.pt` |
| Start | `make console` | `make up` (dari source) atau launcher `autograde` (image produksi, Lampung) |
| Layar | http://127.0.0.1:8100/console | http://localhost:8000/console dari source, `:8100` image produksi |

### Develop di Mac: dari nol

```bash
git clone git@github.com:delta-anugrah/autograde.git
cd autograde
cp .env.example .env

# venv khusus konsol + tes. Sengaja TIDAK memasang torch / ultralytics / opencv:
# konsol tidak memakainya, dan requirements.txt penuh itu untuk image Docker.
# `segno` (77 KB, pure-Python) dipakai membuat kartu QR truk di server: console.html
# nol referensi https://, jadi pustaka QR dari CDN mati saat internet putus.
python3.12 -m venv .venv
.venv/bin/pip install "fastapi==0.115.12" "uvicorn[standard]==0.34.0" "python-dotenv==1.1.0" \
  "httpx==0.28.1" "pydantic==2.11.3" "segno==1.6.6" \
  pytest ruff cryptography aiosqlite psutil boto3 pyyaml

make operator                     # sekali: akun lokal buat login (tanya email + nama + sandi)
make demo                         # opsional: isi layar dengan data contoh (lihat "Coba di lokal")
make demo-reset                   # hapus data demo lalu isi ulang bersih
make demo-off                     # sesudah showcase: hapus data demo, data sungguhan tidak disentuh
make console                      # http://127.0.0.1:8100/console — Ctrl-C untuk berhenti
.venv/bin/pytest tests/unit       # unit test, tidak butuh konsol maupun AutoERP
```

- **Tanpa AutoERP** konsol tetap jalan penuh dari data lokal (`ERP_URL` kosong di `.env`).
  Tiga kartu kamera tampil **OFFLINE**, itu benar, di Mac tidak ada line kamera.
- **Menyambung ke AutoERP lokal:** nyalakan dari repo `autoerp` (`make up`, lalu `make key-show`),
  lalu tempel kuncinya ke `.env`. Langkah lengkap + tes end-to-end ada di
  [Konsol operator](#konsol-operator-app_modeconsole); untuk E2E, `CONSOLE_LINE_HOST` di `.env`
  harus `http://127.0.0.1` (di macOS `localhost` menunjuk `::1` dulu).
- **Port 8100**, bukan 8000: AutoERP lokal memakai 8000.

⚠️ **Target Docker bukan untuk Mac:**
- `make up` / `make up-prod` butuh SDK MVS + GPU NVIDIA, jadi berhenti di
  `Hikrobot MVS SDK not found at /opt/MVS`. Itu memang seharusnya.
- `make up-dev` bisa dibuild di Apple Silicon, tapi container konsol memakai `network_mode: host`
  di port 8000 (rebutan dengan AutoERP), dan line-nya tidak punya kamera.

### Linux / PC pabrik

Pasang dulu lewat [Setup](#setup) dan [Production Deployment](#production-deployment-pindah-ke-pc-baru),
lalu `make up` (daftar perintah lengkap di [Running](#running)). PC pabrik Lampung sehari-hari
memakai launcher `autograde` di host (`autograde pull`, `autograde status`), bukan `make`, lihat `sawit/docs/runbooks/`.

---

## Part of the Palmgrade System

| Repo | Role | Port |
|---|---|---|
| **`autograde`** | AI camera + inference (per line) | 8001 / 8002 / 8003 |
| **`autograde`** (`APP_MODE=console`) | Konsol operator offline: grading + timbangan | **8100** di PC pabrik & `make console`; 8000 di compose dev |
| `palmgrade-api` | Business logic, auth, SSE broker, **pensiun**, diganti AutoERP | 2500 |
| `palmgrade-frontend` | Operator dashboard UI: **pensiun**, konsol pindah ke sini | 3050 |

> Sejak Fase 2 (rencana yang dulu bernama PalmOS, sekarang AutoERP) konsol menggantikan
> peran `palmgrade_api` lokal di PC pabrik:
> tiga line menyetel `BACKEND_URL` ke konsol (`http://console:8000` di dalam Docker,
> `http://localhost:8100` kalau konsolnya native) dan mengirim event dengan kontrak yang
> sama persis (7 → 4 container). **Nol perubahan di kode line.**

> Full system architecture: see [`ARCHITECTURE.md`](../ARCHITECTURE.md)

---

## How It Works

```
Camera (Hikrobot / OpenCV / Photo)
    → FrameCaptureWorker  (thread) → frame_queue
    → FrameProcessingWorker (thread)
        → YOLOv8 + ByteTrack
        → detect: Ripe / Unripe / JK (janjang kosong) / TP (tangkai panjang)
        → janjang MENYENTUH garis capture → pulse PLC + serahkan SaveJob, lalu LANJUT
    → CaptureSaveWorker (thread, antrean 8)     ← sejak 2026-09-18
        → encode WebP bbox + clean + thumb, tulis JSON sidecar, satu baris outbox
        → file di disk ITU antriannya untuk jalur cloud
    → OutboxRetryWorker (poll 1 dtk) → POST BACKEND_URL = konsol lokal
    → BatchUploadWorker (tiap jam, jalur terpisah ke cloud)
        → _scan() → UploadManifest (SQLite, state/upload_manifest.db)
        → PUT image ke Cloudflare R2
        → POST teks ke UPLOAD_API_URL cuma kalau diisi (api cloud pensiun; di pabrik kosong)
        → _retention(): hapus WebP+JSON yg `done` & lewat UPLOAD_RETENTION_DAYS
    → StreamingService
        → MJPEG /api/video_feed (multi-viewer via Condition broadcast)

konsol → POST /internal/assignment → update state.current_truck_id + assignment_id
konsol → POST /internal/manual-reject → trigger capture_manual_reject()
```

**Konsol operator** (container ke-4, `console_main.py`: sengaja tidak memuat torch/cv2,
jadi satu line kamera mati tidak menjatuhkan layar operator):

```
3 line → POST /api/v1/internal/vision/events ┐
program timbangan → POST .../scale/weighing  ├→ index SQLite state/console.db
                                             │  (konsol TIDAK pernah memindai direktori)
                                             └→ MasterDataWorker  ← supplier + truk dari AutoERP  (kalau ERP_URL diisi)
                                                ErpOutboxWorker   → truk baru (§4.B) + kunjungan truk (§4.C)
                                                VisitResendWorker → kunjungan kemarin, sekali sehari

/console  → satu file HTML statis, vanilla JS, tanpa build/Node/CDN
            stream kamera = <img> MJPEG langsung ke :8001/8002/8003, bukan lewat konsol
```

**Model deteksi**: `best.pt`: 4 kelas: `Ripe`, `Unripe`, `JK` (janjang
kosong), `TP` (tangkai panjang).

Putusannya **diturunkan** dari kelas, bukan sama dengan kelasnya
(`domain/grade_class.py`). PLC punya dua coil dan AutoERP tiga kriteria, jadi
`ripeness_status` yang biner tetap menjadi hal yang memicu piston dan yang
dibukukan; `grade_class` adalah rincian 4 arah yang tampil di layar:

| Kelas model | Verdict | Coil | Piston |
|---|---|---|---|
| `Ripe` | ACC | `PLC_COIL_BASE + 0` | tidak |
| `Unripe` | REJ | `PLC_COIL_BASE + 1` | ya |
| `JK` | REJ | `PLC_COIL_BASE + 1` | ya |
| `TP` | tidak ada | tidak ada pulse | tidak |

`PLC_COIL_BASE` per line: line 1 = M1000, line 2 = M1003, line 3 = M1006 (MC Protocol, peta `docs/plc-mc-handoff.md`). `Unripe` dan `JK`
menembak coil yang sama: panel tidak bisa membedakannya, dan memisahkannya
butuh piston ketiga. `TP` tidak pernah menyentuh PLC: dia properti sebuah
janjang, bukan janjang. Satu pengecualian lagi: janjang REJ milik truk
**Internal** sengaja tidak dipulse sama sekali (`domain/plc_signal.py`) karena
tetap masuk ramp: jadi penghitung NG di PLC memang lebih kecil dari angka REJ
di konsol saat truk internal lewat.
**Ukuran minimum**: 460.000 px²: objek di bawah luas ini dipaksa jadi `rej`
**Pelacakan**: ByteTrack: tiap buah dapat `track_id` unik, disimpan sekali saja (single-trigger)
**Zona deteksi**: kotak ROI (`ROI_X1/Y1/X2/Y2`): cuma objek yang titik tengahnya jatuh di dalam kotak yang dihitung. Bawaannya `0,0,0,0` = satu frame penuh. Kelas TP dikecualikan dari pemeriksaan ROI.
**Titik ambil foto**: satu janjang difoto ketika kotaknya **menyentuh** garis capture (`GARIS_CAPTURE`, diatur dari layar support di konsol). ROI menjawab *di mana* (ini konveyornya), garis menjawab *kapan*. Sejak 2026-09-18 ini menggantikan "titik tengah masuk kotak ROI", yang baru memicu waktu separuh janjang sudah lewat, dan dengan ROI bawaan satu layar penuh, memicu begitu janjang terdeteksi di mana pun. `0` = tanpa garis, perilaku lama. `SUMBU_GARIS` memilih garis tegak (konveyor mendatar, px dari kiri) atau garis mendatar (konveyor tegak, px dari atas).
**Tangkai panjang (TP)**: dipasangkan ke janjang **terdekat** dalam jarak 1,5 × setengah diagonal kotaknya, dan cuma kalau tidak ada janjang lain di frame itu yang lebih dekat (`domain/garis_capture.tp_untuk_janjang`). Satu janjang difoto apa adanya, punya tangkai atau tidak; TP yang muncul belakangan dihitung di `tp_telat` pada `/health/detail`.
**Aturan buah bertumpuk**: >1 buah (belum diproses) berada dalam ROI di frame yang sama → semuanya di-force `rej`.
**Label kotak**: kelasnya saja (`Ripe` / `Unripe` / …), tanpa persentase keyakinan, dari jarak beberapa meter "54%" terbaca sebagai tingkat kematangan. Saklar `mode_dev` di layar setelan mengembalikannya untuk menyetel ambang batas.

---

## Prerequisites

- Docker & Docker Compose
- `make` (GNU Make)
- Hikrobot MVS SDK installed at `/opt/MVS/` on the host, `make up` auto-copies all required libs
- NVIDIA Container Toolkit: untuk GPU passthrough ke Docker (lihat [Production Deployment](#production-deployment-pindah-ke-pc-baru))
- YOLO model file at `models/release/best.pt`

> **Linux / PC pabrik tidak perlu Python/venv lokal.** Semua dijalankan via Docker, `python:3.11-slim` base image sudah include semua dependencies. Develop di Mac memakai venv kecil: lihat [Quick Start](#quick-start-pilih-jalur).

---

## Project Structure

```
autograde/
├── src/palmgrade/
│   ├── main.py                  # FastAPI app entry point line kamera (lifespan)
│   ├── console_main.py          # app entry point KONSOL (APP_MODE=console) — tanpa torch/cv2
│   ├── static/console.html      # layar operator: satu file, vanilla JS, tanpa build & tanpa CDN
│   ├── core/                    # Config, logging, DI wiring
│   ├── routes/                  # FastAPI routers
│   ├── controllers/             # Request handlers
│   ├── services/                # Business logic
│   ├── repositories/            # File I/O (JPEG, JSON)
│   ├── pipelines/               # YOLO inference + frame processing
│   ├── workers/                 # Background threads & asyncio tasks
│   ├── integrations/
│   │   ├── camera/              # HikrobotCamera / OpenCVCamera / PhotoCamera
│   │   ├── notifications/       # WebhookClient (httpx)
│   │   ├── storage/             # LocalFileStorage
│   │   ├── upload/              # R2Uploader (boto3) + UploadManifest (SQLite per-item state)
│   │   ├── outbox/              # OutboxStore — antrean realtime ke BACKEND_URL
│   │   ├── erp/                 # ErpClient + ErpOutboxStore — antrean kirim ke AutoERP
│   │   └── scheduler/           # UploadScheduler — APScheduler cron, hourly @ UPLOAD_MINUTE
│   ├── domain/                  # Pure business rules (no I/O) — working_day, ffb_source, plate,
│   │                            #   erp_master (dokumen ERP → baris konsol), erp_messages (§4.B/§4.C)
│   ├── plc/                     # PLC: MC Protocol ke CPU Mitsubishi (Modbus/ODOT lama masih bisa dipilih), mati by default
│   ├── schemas/                 # Pydantic request/response models
│   └── license/                 # License guard (Ed25519 JWS, optional)
├── models/
│   └── release/
│       └── best.pt    # YOLO model — required, not committed to git
├── images/
│   └── sample_sawit.jpg         # gambar contoh lama untuk CAMERA_TYPE=photo — lihat media/ untuk jalur baru
├── media/                       # Video/foto sumber kamera per line, dipilih dari layar Support — not committed to git
├── artifacts/                   # Runtime output — not committed to git
│   ├── line-1/
│   ├── line-2/
│   └── line-3/
├── state/                       # console.db + erp_outbox.db (konsol); outbox.db + license.db per line — not committed to git
├── scripts/                     # console-kiosk.sh + palmgrade-console.desktop
├── Makefile
├── Dockerfile
├── docker-compose.yml           # 4 services: line-1..3 (8001-8003) + console (8000; prod menimpanya jadi 8100)
├── requirements.txt
├── .env                         # Local env (copy from .env.example)
├── .env.example
├── media.env                    # Sumber kamera per line (Docker), ditulis layar Support — not committed to git
└── media.env.example
```

---

## Setup

### 1. Clone & copy env

```bash
git clone git@github.com:delta-anugrah/autograde.git
cd autograde
cp .env.example .env
```

### 2. Edit `.env`

Key variables to fill in:

```env
# Sumber kamera pindah ke `media.env` (per line, diatur layar Support).
# Salin contohnya sekali saat pemasangan:
cp media.env.example media.env
# Berkas video/foto ditaruh di folder `media/`.

# Backend — ke mana line mengirim event.
# Di PC pabrik ini adalah KONSOL, bukan palmgrade-api (yang sudah pensiun):
#   di dalam Docker      → http://console:8000
#   `make line` native   → http://localhost:8100
# Bawaan di kode masih :2500 (palmgrade-api) karena belum diganti; isi sendiri.
BACKEND_URL=http://localhost:8100
WEBHOOK_SECRET=your-webhook-secret   # wajib ganti dari default!

# INTERNAL_SECRET (opsional, sejak batch 1 keamanan): kunci perintah KONSOL → line
# (restart, hapus data, coil PLC, piston), terpisah dari WEBHOOK_SECRET yang juga
# dipegang program timbangan. Kosong = ikut WEBHOOK_SECRET, .env lama tetap jalan.
INTERNAL_SECRET=

# Machine UUIDs — dulu harus cocok dengan machines.id di PostgreSQL palmgrade-api.
# Sejak api pensiun, compose sudah membawa UUID bawaan; konsol mencocokkan event
# berdasarkan machine_id, bukan port.
LINE_1_MACHINE_ID=<uuid-from-db>
LINE_2_MACHINE_ID=<uuid-from-db>
LINE_3_MACHINE_ID=<uuid-from-db>

# Model
MODEL_FILE=best.pt
CONF_THRESHOLD=0.75
MINIMUM_SIZE=460000

# Stream (MJPEG — tidak mempengaruhi hasil simpan)
STREAM_WIDTH=1280
STREAM_HEIGHT=720
```

### 3. Place the model file

```bash
mkdir -p models/release
# copy best.pt ke models/release/
```

### 4. Siapkan Hikrobot SDK (production only)

Install Hikrobot MVS SDK di host (`/opt/MVS/`). `make up` akan otomatis copy **seluruh** `/opt/MVS/lib/64/` (termasuk GigE transport layer) ke `sdk/lib64/` dan include ke Docker image.

> Lihat panduan lengkap: [`docs/SETUP.md`](docs/SETUP.md)

---

## Production Deployment (Pindah ke PC Baru)

Checklist ini menyiapkan mesinnya: GPU, SDK kamera, model, `.env`. **Tapi PC
pabrik tidak menjalankan `make up`**: di sana tidak ada source code sama
sekali. Yang jalan adalah image GHCR
`ghcr.io/delta-anugrah/autograde:vX.Y.Z` lewat launcher di `/opt/palmgrade/`,
dengan tiga berkas compose (`base` + `prod` + `factory`) yang hidup di host,
bukan di repo.

Langkah pemasangan sebenarnya: `sawit/docs/runbooks/2026-08-21-checklist-pasang-pc-pabrik.md`
dan skill `install-factory-pc`.

⚠️ **Konsol operator di PC pabrik ada di port `8100`, bukan `8000`**,
`docker-compose.prod.yml` menimpanya karena 8000 adalah port bench Frappe, dan
PC yang kelak juga menjalankan ERP lokal akan bentrok diam-diam. Tiga konteks,
tiga angka: `make console` native **8100**, compose dev **8000**, compose prod
(PC pabrik) **8100**.

⚠️ **Override Compose MENGGANTI blok dasar sebuah service, bukan menambahinya.**
Begitu `prod` menyebut `environment:`, seluruh `environment:` di base dibuang,
`network_mode` dan `container_name` ikut hilang. Terbukti di Lampung (Compose
v2.40.3): 18 variabel konsol jadi 4. Karena itu blok konsol di `prod` ditulis
**utuh**, dan menambah variabel konsol berarti menambahnya di situ juga.
`docker compose config` di Mac (Compose v5.x) menggabungkan dengan benar, jadi
tidak bisa dipakai membuktikan apa pun soal ini.

Status (2026-09-28): PC Lampung menjalankan **AutoGrade saja** sejak 2026-09-20 (api dan
frontend lama di-`stop`, volumenya utuh) dan tersambung ke AutoERP sejak 2026-09-22.
`BACKEND_URL` menunjuk konsol lokal; `UPLOAD_API_URL` dikosongkan (api cloud pensiun).

Menyiapkan mesinnya (NVIDIA Container Toolkit, SDK Hikrobot, model, `.env`, build image):
[`docs/MANUAL.md`](docs/MANUAL.md) §5 dan [`docs/SETUP.md`](docs/SETUP.md). Compose dan launcher di
host yang tidak ikut `autograde pull`: skill `.claude/skills/compose-host-pabrik/`.

---

## Running

### Semua command via `make`

```bash
make up          # production: copy SDK dari /opt/MVS/, build GPU+SDK, start semua line
make up-dev      # development: build CPU tanpa SDK, start semua line
make start       # start semua line tanpa rebuild (pakai image yang sudah ada)
make restart     # restart semua container — cukup untuk perubahan KODE (bind-mount .:/app)
make up-1        # start line-1 saja tanpa rebuild
make up-2        # start line-2 saja tanpa rebuild
make up-3        # start line-3 saja tanpa rebuild
make down        # stop semua
make logs        # tail logs gabungan semua line
make logs-1      # tail logs line-1 saja
make logs-2      # tail logs line-2 saja
make logs-3      # tail logs line-3 saja
make ps          # status semua container
make up-console  # konsol operator saja (port 8000) — aman di-restart tanpa ganggu line
make logs-console # tail logs konsol
make kiosk       # buka konsol layar penuh di PC ini (scripts/console-kiosk.sh)
make rebuild     # rebuild image GPU/CUDA (tanpa SDK, tanpa start) — selalu GPU
make rebuild-gpu # sama dengan make rebuild (alias, untuk kompatibilitas)
make rebuild-clean # full rebuild --no-cache (hanya kalau cache dicurigai rusak — lambat)
make build-engine  # build TensorRT FP16 engine — sekali per GPU, auto-skip kalau sudah ada
make clean       # down + hapus image lokal
make reset-data       # lihat dulu: berapa foto + basis data yang akan hilang
make reset-data-fresh # HAPUS SEMUA DATA (artifacts/ + state/) — minta ketik HAPUS
```

> ⚠️ **`make reset-data-fresh` tidak bisa dibatalkan dan tidak membuat backup.** Yang hilang:
> semua foto dan sidecar (`artifacts/`), dan semua SQLite (`state/`): riwayat grading, truk,
> timbangan, antrean yang belum terkirim, dan akun buatan `make operator`. **Dua akun bawaan
> image dibuat ulang sendiri** saat konsol start, jadi cukup `make start` sesudahnya; layar
> tidak terkunci. Container dimatikan lebih dulu: menghapus berkas SQLite di bawah proses yang
> masih membukanya meninggalkan basis data separuh jadi, bukan basis data kosong.
> Jangan di PC pabrik yang sedang produksi. AutoERP punya dua target nama sama
> (`bench reinstall`, bukan `drop-site`).
>
> **Tanpa terminal:** konsol → login support → tab **Setelan** → **Danger Zone**. Ada dua
> tombol hapus: **data transaksi** (grading, foto, timbangan, antrean, log; truk/akun tetap)
> dan **semua data**: plus restart semua line, logout paksa, dan hapus rekaman video.
> Bedanya dengan target di atas: setelan grading dan `license.db` tidak ikut terhapus, dan
> tombolnya menolak kalau ada line mati, truk terpasang, truk yang belum timbang keluar
> hari ini, atau antrean yang belum terkirim.

> **Satu image, tiga container**, hanya line-1 yang punya `build:` di docker-compose. Line-2 dan line-3 reuse image `palmgrade-vision:latest`. Jadi `make rebuild` cukup untuk update semua line (tinggal `make start` setelahnya).
>
> **`make rebuild` selalu GPU**: tidak ada variant CPU untuk rebuild. Jika ingin build CPU (khusus dev tanpa GPU), gunakan `make up-dev`.

> **Hot-reload**: source code di-mount via `.:/app`. Perubahan Python langsung terdeteksi tanpa rebuild image (saat `APP_ENV=development`). Di production cukup `make restart` untuk perubahan kode, `make up` hanya perlu kalau dependency / `Dockerfile` / SDK berubah.

> **TensorRT**: engine FP16 (`engines/<model>.sm<cc>.engine`) **hardware-locked** (compute capability + versi TensorRT), jadi tidak di-commit dan tidak di-bake ke image: dibangun **sekali per GPU** on-machine (`make up` sudah memanggilnya; ~5–15 menit, tidak butuh kamera). Engine tidak ada / tidak cocok → runtime otomatis **fallback ke `.pt`** (`pipelines/model_registry.py`) (akurasi sama, hanya lebih lambat, jadi gagal build bukan outage. Install TensorRT-nya lewat index NVIDIA (`pypi.nvidia.com`)) **wajib**, index PyPI publik cuma punya source stub yang bikin pip hang.

> **Video file**: kalau `CAMERA_TYPE=opencv` dan `CAMERA_VIDEO_PATH` diisi, path harus di dalam container. Semua 3 line sudah di-mount `/home/nexio/Desktop/Projects/sawit:/videos:ro`. Gunakan `CAMERA_VIDEO_PATH=/videos/namafile.mp4`.

### Container per line

| Container | Port | Camera Index | Machine ID env |
|---|---|---|---|
| `ripe_line_1` | 8001 | 0 | `LINE_1_MACHINE_ID` |
| `ripe_line_2` | 8002 | 1 | `LINE_2_MACHINE_ID` |
| `ripe_line_3` | 8003 | 2 | `LINE_3_MACHINE_ID` |
| `palmgrade_console` | 8000 | - | ketiganya (pemetaan `machine_id` → line) |

### Konsol operator (`APP_MODE=console`)

Layar di **`/console`**: port 8100 di PC pabrik (image produksi) dan `make console`, 8000 lewat `make up` / `make up-console` dari source. Satu berkas HTML statis: vanilla JS, **tanpa
build step, tanpa Node, tanpa CDN, tanpa webfont**, harus tetap kebuka saat internet mati.
Isinya strip total hari kerja (dengan **Last Sync**: jam sinkron terakhir dan status sambungan ke
AutoERP dan Cloud Photo), kartu kamera per line (assign/lepas truk, reject manual, piston),
dan 5 tab operator: Grading, Truk, Timbangan, Rekap, **Riwayat** (grading hari-hari sebelumnya,
maks 31 hari, ringkasan periode + unduh CSV). Akun support melihat 10 tab tambahan (Log sampai
Setelan). Dwibahasa ID/EN, tema terang (default) / gelap, pilihan operator disimpan di
`localStorage`.

- **Login (Fase 4).** Layar tertutup gerbang sampai ada yang masuk: operator mengetik **email
  dan sandi** (tombol nama yang ada cuma mengisi kolom email, sandinya tetap wajib), dan topbar
  menampilkan namanya plus tombol **Keluar**. Semua `/api/console/*` menjawab 401 tanpa cookie
  `konsol_sesi`; yang tetap terbuka cuma `/console`, daftar akun, dan `login`. Sesi 12 jam, dan
  Reject Manual tercatat atas nama yang sedang masuk.

  Akun datang dari **dua tempat**: AutoERP (DocType `AutoGrade Operator`, ditarik bareng master
  data) dan **lokal** di PC ini (akun bawaan + akun support, supaya pabrik yang belum pernah
  dapat internet tetap bisa dibuka). Keduanya **diverifikasi di pabrik**, jadi login tetap jalan
  saat internet mati: yang ditarik hash-nya, bukan sandinya. Sandi minimal 8 karakter.

  **Dua akun bawaan di tiap image**: `operator@autograde.local` (dipegang pabrik) dan
  `support@autograde.local` (jalur masuk kita lewat AnyDesk). Email-nya sama di semua PKS
  supaya support tidak perlu nanya dulu; **sandinya beda tiap PKS**, dibuat waktu pasang PC
  dengan `make hash-sandi` lalu diisi ke `CONSOLE_DEFAULT_HASH` / `CONSOLE_SUPPORT_HASH`,
  yang tertanam **hash**-nya, sandi mentah tidak pernah masuk image atau `.env`. Akun cuma
  dibuat kalau email-nya belum ada, jadi **sandi yang sudah diganti pabrik tidak ketimpa
  restart**, dan akun yang sudah dimatikan tidak dihidupkan lagi.
  Akun lokal dibuat dari layar: login **support** → tab **Akun** → **Tambah akun** (sejak
  2026-09-26). Di tabel yang sama ada **Ganti sandi**, **Matikan/Aktifkan**, dan **Jadikan
  support/operator** untuk akun lokal; akun sendiri cuma bisa ganti sandi. Akun lokal **tidak
  masuk ke AutoERP**: cuma ada di PC ini.
  Dari terminal masih bisa: `make operator`, atau `make operator-docker` kalau konsolnya di
  Docker. `AKSI=daftar` melihat daftar beserta asal tiap akun, `AKSI=matikan` mematikan satu
  akun: sesinya langsung berakhir. Reset sandi lokal = `make operator` lagi dengan email yang
  sama; sandi akun milik AutoERP direset **di AutoERP** (layar dan CLI-nya menolak, karena
  tarikan berikutnya akan membatalkannya).

⚠️ **Memasang AutoGrade di PC yang SUDAH jalan dengan palmgrade-api butuh satu langkah
  tambahan: `make rekonsiliasi-truk` (OPS-2), dikerjakan SEBELUM `ERP_URL` diisi.** Truk
  lama ber-id acak dari palmgrade-api, AutoGrade menurunkan id dari plat, dan kolom plat
  tidak punya indeks unik: jadi tarikan pertama membuat baris kedua untuk truk yang sama
  dan tonase satu truk terbelah dua tanpa pesan apa pun. Tanpa `TULIS=1` perintahnya cuma
  melihat; `--db <path>` untuk mencoba di salinan dulu. PC baru (DB kosong) tidak perlu.
  Langkah lengkapnya: `../docs/runbooks/2026-09-15-checklist-ops2-rekonsiliasi-truk-lampung.md`.

- **Stream kamera tidak lewat konsol**: kartunya `<img>` MJPEG langsung ke `:8001/8002/8003`.
  Kartu dirender **sekali** lalu ditambal tiap 2 detik; urutan pakai CSS `order`. Memindah DOM =
  stream putus lalu buka lagi. Status kamera dicek tiap 5 detik dan muncul sebagai
  **ONLINE / OFFLINE** di judul kartu, warna tidak pernah jadi satu-satunya sinyal.
- **Reject manual tanpa mouse**: tahan `SPACE` lalu tekan `1` / `2` / `3`.
- **Tab Rekap** (sejak 2026-09-28 = Rekap + Riwayat) = yang diserahkan ke supplier: dibuka di
  hari ini, satu baris per truk: janjang, Ripe/Unripe/JK/TP, rasio, dan neto timbangan. Grading dan timbangan tetap **dua sumber
  terpisah** yang cuma disandingkan; neto dijumlah per truk di Python, bukan di-JOIN ke query
  grading (satu truk bisa punya lebih dari satu tiket sehari, dan join itu akan mengalikan
  jumlah janjang dengan jumlah tiket). Janjang yang ter-grading sebelum truk dipasang muncul
  sebagai baris **Tanpa truk**: dibuang justru menyembunyikan yang perlu dilihat operator.
- **Hari-hari sebelumnya** di tab yang sama: ganti tanggal (maks 31 hari) + **Unduh CSV** untuk
  semua operator. **Impor CSV** untuk akun support saja: CSV Per janjang hasil unduhan (PC ini atau PC
  lain) diperiksa dulu, lalu diimpor utuh atau ditolak utuh; janjang hari ini tidak diimpor, yang
  sudah ada dilewati, dan satu impor bisa dibatalkan (`docs/rules.md` aturan 26).
- **Coba di lokal tanpa kamera**: `make up-console` lalu buka
  <http://localhost:8000/console>. DB-nya kosong, jadi tab-tabnya masih polos,
  isi dengan **`make demo`**: 10 truk, ~6 kunjungan per hari selama seminggu, ratusan
  janjang dengan ACC/REJ/JK terbagi, dan dua akun untuk masuk. **Dev dan demo saja,
  jangan pernah di PC pabrik**: skrip itu menulis ke database yang sama dengan punya
  operator. Dia menolak database yang sudah punya data sungguhan (truk ber-id bukan
  turunan plat, atau akun dari AutoERP), tapi jangan bergantung pada penolakan itu.

  ```bash
  make demo                       # 7 hari riwayat
  make demo HARI=3                # lebih pendek
  make demo-reset                 # hapus data demo lama dulu, lalu isi ulang (AKSI=reset juga masih jalan)
  make demo-off                   # sesudah showcase: hapus data demo, berhenti di situ (tidak isi ulang)
  make console                    # → http://127.0.0.1:8100/console
  ```

  Masuk dengan `operator@demo.autoerp.test` atau `support@demo.autoerp.test`, sandi
  `sawit2026`. Di PC pabrik (konsol di Docker) pakai `make demo-docker`.

  **Platnya sama persis dengan seeder AutoERP** (`erpnext/palm_mill/demo.py`), jadi
  seed dua-duanya dan satu truk adalah truk yang sama di dua layar: kunjungan di konsol
  pabrik, tiketnya di ERP Desk. Ganti plat di sini → ganti di sana dalam PR yang sama.
  AutoERP punya tiga perintah `make` yang sama persis (`demo`/`demo-reset`/`demo-off`),
  jadi urutan showcase di dua layar tidak perlu dihafal beda-beda.

  Skripnya menulis ke SQLite langsung, jadi konsolnya **tidak perlu hidup** dan tidak ada
  secret yang dilewatkan di baris perintah. Versi lama butuh `WEBHOOK_SECRET`, tiga
  machine id, dan sandi operator cuma untuk mulai.

  Kamera akan tampil **OFFLINE**: itu benar, tidak ada line yang jalan. Semua id-nya
  uuid5 deterministik, jadi dijalankan dua kali tidak menambah baris. Ubah `console.html`
  → cukup refresh browser (berkasnya bind-mount); ubah kode **Python** → `make restart-console`.
  `make up-console` tidak cukup: `up -d` itu no-op kalau kontainernya sudah jalan, jadi
  proses lama tetap memegang kode lama.

  Sesudah seed, jalankan `CONSOLE_EMAIL=operator@demo.autoerp.test CONSOLE_SANDI=sawit2026
  scripts/smoke-console.sh`: dia memeriksa gembok dulu (lane data 401 tanpa sesi, lane
  gerbang terbuka), lalu masuk dan mengetuk semua endpoint yang dipakai UI, memastikan
  halaman yang dilayani memang berkas di working tree (bukan salinan di dalam image), dan
  mengecek tiga jebakan yang pernah menggigit: baris "Tanpa truk" tidak dibuang, neto truk
  bertiket-dua **dijumlah** bukan dikali, dan `bruto_kg` "14.820" ditolak. Harus **nol FAIL**;
  tanpa `CONSOLE_EMAIL` bagian sesudah gembok dilewati, dan dua jebakan rekap memang
  butuh seed dijalankan dulu.
- **Tersambung ke AutoERP, di MacBook tanpa Docker.** AutoERP dinyalakan dari repo
  `autoerp` (bench native), kuncinya diambil dengan `make key-show` lalu ditempel ke `.env`
  di sini. Konsol membaca `.env` sendiri, jadi perintahnya pendek:

  ```bash
  cd ../autoerp && make up && make key-show   # tempel ERP_API_KEY + ERP_API_SECRET ke .env
  cd ../autograde
  make console                                # = uvicorn native di 127.0.0.1:8100
  ```

  **Kenapa bukan target Docker di Mac:** `make up` butuh SDK MVS + GPU NVIDIA (PC pabrik),
  dan container konsol memakai `network_mode: host` di port 8000 yang dipegang AutoERP.
  `make up-dev` sekarang bisa dibuild di Apple Silicon, tapi untuk develop konsol jalur
  native inilah yang dipakai. Target Docker adalah jalur Linux/pabrik dan tidak diubah.

  Baris ERP di `.env`: `ERP_URL=http://pks.localhost:8000`, `ERP_API_KEY`, `ERP_API_SECRET`,
  `ERP_COMPANY`, dan `CONSOLE_LINE_HOST=http://127.0.0.1` (di macOS `localhost` menunjuk `::1`
  dulu, line cuma IPv4). Port **8100** karena 8000 milik AutoERP. `WEBHOOK_SECRET=devsecret`
  (dipasang `make console`) menimpa `.env`: variabel lingkungan selalu menang atas berkas,
  supaya cocok dengan secret yang dipakai tes. **Jangan** `bench start` dua kali dan jangan
  jalankan `create_integration_user` ulang untuk melihat kunci (itu merotasi secret).

  Tes end-to-end lawan AutoERP asli, 11 tes, membersihkan datanya sendiri, butuh port 8001
  kosong dan satu operator (`make operator`) karena API konsol sekarang butuh sesi:

  ```bash
  E2E_CONSOLE_URL=http://127.0.0.1:8100 E2E_WEBHOOK_SECRET=devsecret \
  E2E_EMAIL=operator@pks.test E2E_SANDI=<sandi> \
  E2E_ERP_URL=http://pks.localhost:8000 E2E_ERP_API_KEY=<key> E2E_ERP_API_SECRET=<secret> \
  E2E_ERP_ADMIN_PASSWORD=admin .venv/bin/pytest tests/e2e -v
  ```
- **Layar penuh = urusan browser**, bukan halaman. `make kiosk` menjalankan Chrome `--kiosk`
  lewat `scripts/console-kiosk.sh`; untuk jalan otomatis saat login pasang
  `scripts/palmgrade-console.desktop`. Tiga hal di skrip itu jangan dihapus: `--user-data-dir`
  tetap (pilihan operator hidup di `localStorage`), tunggu konsol menjawab dulu (sesudah listrik
  mati desktop sering login sebelum Docker siap), dan `xset s off -dpms`.

### Camera type (dikontrol via env var `CAMERA_TYPE`)

| `CAMERA_TYPE` | Sumber | Dikontrol oleh |
|---|---|---|
| `hikrobot` | Kamera industrial Hikrobot via **RJ45 LAN** (GigE Vision) | `CAMERA_DEVICE_INDEX` |
| `opencv` | Webcam **atau** video file | `CAMERA_VIDEO_PATH` (jika diisi) → video file; jika kosong → webcam via `CAMERA_DEVICE_INDEX` |
| `photo` | Gambar statis, di-loop terus | `CAMERA_PHOTO_PATH` |

`opencv` menggunakan `cv2.VideoCapture()` yang bisa terima `int` (webcam index) maupun `str` (path file video): satu class, dua source.

**Tidak perlu edit kode** saat switch environment, cukup ubah env var di `.env`.

**Hikrobot (GigE Vision) di Docker**: kamera terhubung via RJ45 LAN, bukan USB. Docker-compose sudah dikonfigurasi dengan `network_mode: host` sehingga container bisa langsung discover kamera via UDP broadcast. Tidak perlu konfigurasi tambahan selain pastikan kamera dan host ada di subnet yang sama.

**Graceful startup**: app tetap jalan meskipun kamera belum terhubung saat startup. `health.detail.camera_connected` akan `false`, dan `FrameCaptureWorker` otomatis retry sampai kamera terdeteksi. Begitu kamera dicolok (dan MVS di-close), `camera_connected` berubah jadi `true` tanpa restart container.

**MJPEG stream**: default encode di 1280×720 (dikontrol via `STREAM_WIDTH`/`STREAM_HEIGHT`). Frame asli Hikrobot 4K tetap disimpan ke disk; resize hanya untuk stream.

---

## API Endpoints

Daftar endpoint line dan konsol yang selalu mutakhir ada di `docs/backend-overview.md` bagian **HTTP Surface**
(konsol: semua `/api/console/*` butuh sesi, lane support `/api/console/dev/*` butuh peran
`support`). Payload, event, dan variabel lingkungan lengkap ada di berkas yang sama.

```bash
# Line
curl http://localhost:8001/health
curl http://localhost:8001/health/detail     # capture_save_dropped dan tp_telat harus 0

# Konsol (8100: image produksi dan `make console`; 8000: dari source)
curl -s -c /tmp/konsol.jar -H 'content-type: application/json' \
  -d '{"email":"operator@pks.test","sandi":"<sandi>"}' http://localhost:8100/api/console/login
curl -b /tmp/konsol.jar http://localhost:8100/api/console/state
curl -b /tmp/konsol.jar 'http://localhost:8100/api/console/riwayat?tampilan=truk'   # per truk, 7 hari terakhir
```

⚠️ `neto_kg` **dihitung, tidak pernah dipercaya mentah** (beda > 1 kg dari `bruto − tara` ditolak
400), dan `MINIMUM_BERAT_KG` = **1 ton** menangkap pemisah ribuan (`14.820` terbaca 14,82 kg).
Rinciannya `docs/rules.md` aturan 15 dan 20.

---

## Event Payload (`BatchUploadWorker`, cuma kalau `UPLOAD_API_URL` diisi)

Setiap deteksi ditulis ke disk (`artifacts/results/`) sebagai WebP + JSON. **File di disk itulah
antriannya**: tidak ada write ke outbox lagi. Sejam sekali `BatchUploadWorker` men-scan folder itu,
mencatat tiap item di `UploadManifest`, PUT gambar beranotasi + thumbnail-nya ke Cloudflare R2, lalu
baru POST payload teks di bawah ke `POST /api/v1/internal/vision/events`. Artinya event sampai ke
cloud dengan **lag sampai ~1 jam**, bukan near-real-time.

> ⚠️ **`UPLOAD_API_URL` kosong = tanpa penerima teks, dan itu setelan Lampung.** `palmgrade-api`
> dimatikan (Opsi B): gambar yang sampai di R2 **itulah** upload-nya, jadi item langsung `done`
> begitu PUT gambar sukses, POST di bawah ini **tidak pernah terjadi**, dan retensi tetap jalan.
> Sebelum ini kosong berarti tiap item macet selamanya di `image_uploaded` dan disk pabrik penuh
> (`upload_events_url` di `core/config.py`).

```json
{
  "event_id": "uuid",
  "assignment_id": "uuid",
  "machine_id": "uuid-from-machines-table",
  "truck_id": "uuid-or-null",
  "timestamp": "2026-05-18T10:30:00.123456+00:00",
  "image_path": "https://captures.smagri.id/<machine_id>/2026-05-18/083000_B1234XY_a3f9c201/bbox/rej/2026-05-18_103000_123456_auto.webp",
  "prediction": "Acc",
  "ripeness_status": "ACC",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS",
  "tp_confidence": 0.88,
  "capture_type": "auto",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

**Field contracts:**
- `event_id`: UUID: used by API for idempotency. **Auto detection** = uuid5 deterministik (`machine_id:timestamp` dari nama file) supaya re-upload item yang sama menghasilkan `event_id` sama → API balas `already_processed`, no double count. Formulanya **sengaja identik** dengan outbox lama, jadi event yang sudah terkirim di era outbox tidak dobel kalau file-nya ikut ter-scan lagi; **manual reject** = uuid4
- `assignment_id`: key-nya **hanya ada kalau meta punya `assignment_id`**, di-omit, bukan dikirim `null`
- `image_path`: **URL absolut R2** (`{R2_PUBLIC_URL}/{r2_key}`), bukan path relatif. Gambarnya di-PUT ke R2 lebih dulu; POST baru jalan setelah PUT sukses
- `timestamp`: ISO-8601 **UTC-aware** (`datetime.now(timezone.utc)`)
- `prediction`: `"Acc"` / `"Rej"`: required
- `ripeness_status`: `"ACC"` / `"REJ"` UPPERCASE
- `tp_status`: `"PASS"` atau `null`: bukan `"TP"`
- `truck_id`: boleh `null`. `_scan()` **tidak** memfilter truck: event tanpa truck aktif ikut ter-upload dengan `truck_id: null` (beda dari perilaku outbox lama yang men-skip-nya). API tetap menyimpan event, truck fields di MongoDB null
- Event tahan restart karena **file-nya ada di disk**, bukan karena SQLite queue. Progres per-item ada di `state/upload_manifest.db` (`pending` → `image_uploaded` → `done`, atau `poisoned`). Retry **tidak ada batasnya**: item gagal tidak pernah menyerah, statusnya tetap dan hanya backoff-nya yang maju

---

## Artifact Output

```
artifacts/line-1/
├── results/                   # Satu-satunya sumber kebenaran (auto + manual)
│   └── 2026-05-18/                                   # tanggal = UTC
│       ├── 2026-05-18_103000_auto_ripeness.json      # Detection metadata — DATAR, lihat ⚠️
│       ├── 2026-05-18_103000_auto_tp.json            # Long stalk metadata (if detected)
│       ├── 2026-05-18_104500_manual_ripeness.json
│       ├── 083000_B1234XY_a3f9c201/                  # satu folder per kunjungan truk
│       │   ├── bbox/acc/ · bbox/rej/                 # bergambar kotak — ini yang ditunjuk
│       │   │   └── 2026-05-18_103000_auto.webp       #   image_path, dan yang naik ke R2
│       │   ├── clean/acc/ · clean/rej/               # polos — buat latih model ulang
│       │   │   └── 2026-05-18_103000_auto.webp       #   nama berkasnya SAMA persis
│       │   └── thumb/acc/ · thumb/rej/               # 400px WebP q60 dari bbox/ — naik ke R2
│       │       └── 2026-05-18_103000_auto.webp       #   juga, buat grid viewer.html
│       └── _belum-assign/                            # ter-grading sebelum truk dipasang

state/line-1/                  # SIBLING artifacts/, sengaja di LUAR mount statis /captures
├── upload_manifest.db         # state per-item BatchUploadWorker (pending/image_uploaded/done/poisoned)
├── outbox.db                  # antrean realtime ke BACKEND_URL (OutboxRetryWorker, poll 1 dtk)
└── license.db                 # penjaga jam lisensi (satu penanda jam tertinggi), kalau LICENSE_ENABLED
```

> Sejak batch 1 keamanan (2026-09-28) `outbox.db` dan `license.db` hidup di `state/`, bukan
> `artifacts/`: keduanya dulu ikut tersaji lewat mount statis `/captures` (aturan berkas DB /
> tersembunyi 404 baru ditambahkan belakangan). PC yang sedang upgrade menyerap isi berkas lama
> ke lokasi baru saat boot pertama (`services/pindah_db_line.py`), bukan memindah berkasnya.
> Serapan yang gagal tidak disembunyikan: `/health/detail` melapor `outbox_lama_tertinggal: true`
> dengan `outbox_pending: null`, Danger Zone menahan hapus data (hambatan `outbox_lama`), dan
> hapus data tidak membuang `artifacts/outbox.db` itu. Boot berikutnya mencoba menyerapnya lagi.

> ⚠️ **Sidecar JSON WAJIB tetap datar di folder tanggal.** `BatchUploadWorker._scan()`
> mencarinya dengan `glob("*/*_ripeness.json")`: kedalaman dipatok dua. Sidecar yang ikut
> masuk subfolder tidak akan pernah ketemu, dan upload ke R2 + cloud berhenti **tanpa error
> dan tanpa log**. Yang pindah ke subfolder cuma gambar; pengunggah membaca letaknya dari
> `image_path` di dalam JSON, bukan dari letak JSON-nya.
>
> ⚠️ **Nama folder truk pakai `FACTORY_TZ`, nama berkas tetap UTC.** Nama berkas menurunkan
> `event_id` (uuid5) jadi tidak boleh bergeser; nama folder itu satu-satunya tempat manusia
> membaca jam. Truk yang bongkar 16:00 WIB terarsip `090000` bikin folder ini tidak berguna.
> Dua zona dalam satu pohon memang disengaja, **folder buat manusia, berkas buat mesin**.
> Aturannya di `src/palmgrade/domain/capture_layout.py`, penulisnya `services/capture_writer.py`.
>
> ⚠️ **Salinan `clean/` tidak diupload ke mana pun**, dia bukti mentah buat melatih model
> ulang, dan model tidak boleh dilatih pakai gambar yang sudah dicoret prediksinya sendiri.
> `thumb/` beda: dia **memang** naik ke R2 berdampingan dengan `bbox/` (§ detail per truk di
> bawah). Konsekuensinya pemakaian disk **tiga kali lipat**; retensi menghapus ketiganya
> bersamaan (`domain/capture_layout.twins_of`). Gagal menulis thumbnail cuma di-log, tidak
> pernah menggagalkan capture: line tidak boleh berhenti karena pratinjau tidak muat.

> Folder `captures/`, `errors/`, dan `logs/` **sudah tidak ada**. Dulu dibuat saat startup tapi tidak pernah ditulis: manual reject disimpan ke `results/`, foto REJ ditemukan via metadata (`ripeness_status: "REJ"`) bukan salinan terpisah, dan log keluar ke stdout supaya `docker logs` yang mengurus. Startup cuma membuat `results/`: dijaga `tests/unit/test_artifact_dirs.py`.

> ⚠️ **`results/` bukan arsip permanen.** `BatchUploadWorker._retention()` menghapus WebP + JSON yang
> statusnya `done` dan sudah lewat `UPLOAD_RETENTION_DAYS` (default **7**). Setelah itu satu-satunya
> salinan gambar ada di R2 (`captures.smagri.id`). Item `poisoned` **tidak** dihapus: file-nya
> sengaja ditinggal biar bisa diperiksa manual.

Images are served as static files: `GET /captures/results/{date}/{HHMMSS}_{plat}_{assign8}/{bbox|clean|thumb}/{acc|rej}/{filename}`

---

## Detail Grading per Truk (R2)

Sejak 2026-09-16, tiap truk yang dilepas dari line dapat **satu halaman detail** yang bisa
dibuka dari tiket AutoERP di kantor, bukan cuma dari PC pabrik. PC pabrik nol inbound (cuma
AnyDesk), jadi halamannya tidak bisa hidup di konsol; dia hidup di R2, domain publik yang sama
dengan foto (`captures.smagri.id`).

Alurnya, saat konsol melepas truk dari line (`_queue_grading`):

1. Konsol membaca semua janjang assignment itu dari SQLite-nya sendiri
   (`ConsoleStore.bunches_for_assignment`), lalu merakit **satu JSON per kunjungan**
   (`domain/visit_manifest.py`, murni: tanpa I/O) di kunci `visits/<visit_id>.json`.
   `visit_id` = id baris `weighings`, angka yang sama dengan `autograde_visit_id` di tiket ERP.
2. JSON itu masuk **antrean sendiri** (`workers/visit_manifest_worker.py`, `ErpOutboxStore` yang
   sama dengan outbox AutoERP, tapi berkas DB beda, `manifest_outbox.db`). Alasannya sederhana:
   R2 mati tidak boleh menahan pesan ke AutoERP, dan AutoERP mati tidak boleh menahan manifest.
   Worker juga mengunggah `static/viewer.html` sekali per proses ke kunci `viewer.html`, jadi
   viewer dan manifest tidak pernah drift, keduanya ikut naik lewat jalur yang sama.
3. `detail_url` = `{R2_PUBLIC_URL}/viewer.html?visit=<visit_id>` **deterministik**: bisa dikirim
   ke AutoERP tanpa menunggu upload manifest selesai. Kalau fotonya belum sampai, viewer cukup
   menampilkan "belum terunggah" untuk gambar itu.
4. `static/viewer.html` (±16 KB, **nol dependensi eksternal**, di belakang Cloudflare Access,
   halaman ini tidak boleh menoleh ke host lain sama sekali) mem-fetch manifestnya sendiri
   (relatif, `visits/<id>.json`) dan menampilkan grid foto: header plat/pemasok/tanggal/line +
   `counts`, filter Semua/ACC/REJ/Tangkai Panjang, grid `thumb` (jatuh ke `image` kalau thumbnail-nya
   hilang), dan klik untuk memperbesar ke foto penuh.

> ⚠️ **`detail_url` dikirim lagi ke AutoERP, tapi cuma kalau R2 terkonfigurasi.** Sebelum ini
> field-nya sengaja dikosongkan, karena satu-satunya halaman detail hidup di konsol, LAN-only.
> Sekarang: dengan R2 terisi, `detail_url` ikut payload `grading`; tanpa R2 key-nya **absen**,
> bukan string kosong: tiap kiriman ke AutoERP mengganti seluruh bagian yang dibawanya, jadi
> string kosong akan **menghapus** URL yang sudah dipunya AutoERP dari kiriman sebelumnya
> (`domain/erp_messages.py` `_grading()`).
>
> ⚠️ **`R2_BUCKET` kosong = bukan cuma manifest yang mati.** Sama seperti retensi foto (lihat
> blockquote di atas), `run_batch_once()` pulang lebih awal sebelum `_retention()` kalau
> `R2_BUCKET` kosong: mematikan R2 tanpa pengganti berarti tidak ada yang membersihkan disk
> pabrik sama sekali, bukan cuma kehilangan tautan detail.

Layar **Antrean** di menu developer (`role=support`) punya baris kedua untuk antrean ini
(`GET /api/console/dev/antrean/manifest`): dan baris itu membaca `aktif: false` saat R2 belum
diisi, **bukan** nol pending/nol gagal: antrean yang belum pernah mulai dan antrean yang macet
kelihatan sama-sama nol kalau tidak ada penanda eksplisit itu.

⚠️ **Belum bisa dibuka dari kantor hari ini.** Kodenya siap, tapi tiga langkah pasang belum
dikerjakan: Cloudflare Access di `captures.smagri.id` (domain itu **publik** sekarang), aturan
lifecycle R2 90 hari, dan `.env` PC Lampung (`R2_*` di konsol, `UPLOAD_API_URL` dikosongkan).
Rencana lengkap + urutan: `../docs/runbooks/2026-09-16-rencana-detail-grading-r2.md`.

---

## License Guard (optional, disabled by default)

```env
LICENSE_ENABLED=true
LICENSE_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\nMCow...\n-----END PUBLIC KEY-----
LICENSE_TOKEN=<token from the cloud API>
```

Kalau dinyalakan, semua rute (kecuali `/health`, `/api/video_feed`, `/captures`) diblokir untuk
lisensi yang kedaluwarsa, **dan** `FrameProcessingWorker` berhenti menjalankan inferensi,
pemblokiran di HTTP saja akan membiarkan kamera tetap grading dan PLC tetap menyortir buah. Coil
alive PLC ikut dijatuhkan, jadi langganan yang kedaluwarsa kelihatan dari lantai pabrik.

Token dipasang offline dengan `palmgrade license <token>`; tidak ada server lisensi yang dihubungi.

---

## Testing

Unit test di sini **sengaja murni-logic**, tidak butuh torch / OpenCV / MVS SDK / GPU, jadi cepat dan jalan di runner CI ringan. Pengujian yang butuh hardware/model asli (inference YOLO, kamera fisik) tetap di luar CI. `tests/integration/` berisi rangkaian komponen sungguhan tanpa hardware (konsol ↔ line lewat transport ASGI, berkas di folder sementara, render layar lewat node) dan jalan di CI.

### Menjalankan test

Dari `autograde/`:

```bash
# CI menjalankan keduanya (lihat .github/workflows/ci.yml).
# Di Mac, venv dari Quick Start sudah berisi semua paket ini — cukup .venv/bin/pytest tests/unit
pip install ruff pytest cryptography aiosqlite psutil httpx boto3 pydantic pyyaml fastapi
ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/integrations/upload/ \
  src/palmgrade/license/ src/palmgrade/plc/ src/palmgrade/workers/batch_upload_worker.py \
  src/palmgrade/workers/master_data_worker.py \
  src/palmgrade/integrations/notifications/line_client.py src/palmgrade/repositories/console_repository.py \
  src/palmgrade/services/console_service.py src/palmgrade/routes/console.py src/palmgrade/console_main.py
pytest tests/unit/
```

> Konfigurasi pytest ada di `pyproject.toml` (`pythonpath=["src"]`): tidak perlu set `PYTHONPATH` manual. Tidak memakai `pytest-asyncio`: kode async diuji lewat `asyncio.run` stdlib supaya dependency CI minimal.

### Cakupan (`tests/unit/`)

| Area | File | Yang dikunci |
|---|---|---|
| Domain rules | `test_rules.py` | Klasifikasi ripeness (inti keputusan bisnis) |
| Idempotency | `test_event_id.py` | `event_id` uuid5 deterministik (anti double-count) |
| **Batch upload** | `test_batch_upload_worker.py`, `test_upload_manifest.py`, `test_r2_uploader.py`, `test_batch_upload_thumb.py` | Discovery + rekonstruksi payload; manifest `pending → image_uploaded → done` (+ `poisoned`) **tanpa retry cap & tanpa TTL**; `r2_key` deterministik + prefix `machine_id` yang mengisolasi antar-line; thumbnail naik bersama `bbox/` dan tidak jadi racun kalau tidak ada; `UPLOAD_API_URL` kosong → item `done` begitu foto sampai, tanpa POST teks |
| **Outage & crash** | `test_batch_upload_outage.py`, `test_batch_upload_crash.py` | Jantung requirement "internet mati berapa lama pun → nol data hilang, nol duplikat"; `os._exit` di tengah transisi state → manifest tetap konsisten (WAL + `synchronous=FULL`) |
| **Tutup line & bukti utuh (batch 2A)** | `test_capture_save_kuras.py`, `test_penutup_line.py`, `test_langkah_tutup_line.py`, `test_upload_scheduler_stop.py`, `test_main_penutup_wiring.py`, `test_bahaya_tunggu_tutup_line.py`, `test_berkas_utuh.py`, `test_tulis_atomik.py`, `test_local_file_storage_atomik.py`, `test_batch_upload_nol_byte.py` | Semua jalan keluar line lewat satu urutan tutup berbatas waktu; `os._exit` cuma di `penutup_line`; listrik padam tidak meninggalkan berkas 0 byte bernama sah; bukti yang tidak utuh tidak diunggah dan tidak dihapus |
| Timestamp TZ | `test_capture_timestamp.py` | Regression guard geser 7 jam: timestamp **wajib** tz-aware (vision UTC vs API `TZ=Asia/Jakarta`) |
| Outbox realtime | `test_outbox_store.py`, `test_outbox_requeue.py`, `test_outbox_migrasi.py`, `test_outbox_retry_worker.py`, `test_kirim_antrean_line.py`, `test_edge_realtime_outbox.py` | Persist → jeda per baris 5 dtk sampai 10 mnt, TANPA batas nyerah; baris failed versi lama dihidupkan saat dibuka; konsol mati = satu percobaan per ≤30 dtk; tersambung lagi = semua dikirim sekarang |
| **Konsol** | `test_console_store.py`, `test_working_day.py`, `test_console_html.py` | Index SQLite (konsol tidak pernah memindai direktori); `work_date` lewat tengah malam; invarian `console.html` (tanpa `on*=` inline, `esc()` meloloskan `& < > " ' \``, `data-line=` tetap ada) |
| **Timbangan** | `test_weighing.py` | `neto_kg` dihitung bukan dipercaya; timbang-keluar **menggabung** bukan menimpa; plat beda tulisan tetap satu truk; koma = desimal, pemisah ribuan ditolak |
| **Master data AutoERP** | `test_erp_master_data.py`, `test_ffb_source.py` | Field yang diminta persis milik DocType (Frappe balas 417 kalau tidak); truk ERP mengadopsi baris yang diketik operator; kursor per-DocType tidak maju kalau ada baris gagal; Sumber TBS mengikuti `sumber_for_supplier` AutoERP |
| **Antrean ke AutoERP** | `test_erp_client.py`, `test_erp_outbox_store.py`, `test_erp_outbox_worker.py`, `test_erp_link.py`, `test_manual_truck_to_erp.py` | Ditolak (4xx) vs tidak terjangkau (jaringan/5xx) dibedakan; backoff 30 dtk → 1 jam; pesan yang diganti saat masih di jalan tidak ditandai terkirim; ERP mati = batch berhenti, bukan dihajar terus; truk manual naik lewat `upsert_truck`; truk milik AutoERP read-only |
| **Kunjungan truk** | `test_visit_message.py`, `test_erp_queue.py`, `test_visit_triggers.py`, `test_visit_resend.py` | Bentuk pesan §4.C; `stage` diturunkan dari keadaan kunjungan; bagian yang tidak ada tidak dikirim; grading ikut lewat tautan assignment yang ditulis saat truk dilepas; kirim ulang harian sekali sehari |
| **Detail grading per truk (R2)** | `test_capture_layout.py`, `test_visit_manifest.py`, `test_console_store.py` (`bunches_for_assignment`), `test_visit_manifest_worker.py`, `test_viewer_html.py`, `test_console_compose_env.py` | Varian `thumb` + pasangan/kunci R2 (`twins_of`, `thumb_key_of`); bentuk JSON manifest murni tanpa I/O; janjang satu assignment urut waktu; antrean manifest sendiri (`manifest_outbox.db`): R2 mati menahan baris, viewer diunggah sekali per proses; invarian statis `viewer.html` (nol dependensi eksternal, manifest dibaca relatif); env `R2_*` konsol wajib ada di `docker-compose.yml` |
| **End-to-end** | `tests/e2e/test_console_autoerp.py` | Konsol + AutoERP sungguhan: truk dibuat di ERP lalu ditarik konsol, truk diketik di konsol lalu muncul di ERP, timbangan jadi Weighbridge Ticket, grading mendarat di tiket saat truk dilepas dari line. Di-skip tanpa variabel `E2E_*` |
| Lepas truk | `test_release_truck.py` | Penugasan yang tidak pernah berakhir bikin tandan truk berikutnya nempel ke truk yang sudah pulang |
| PLC | `tests/unit/plc/`, `tests/e2e/test_mc_protocol_lane.py` | Klien MC Protocol + Modbus, state machine pulse/heartbeat/piston, alamat M ≡ compose |
| Config | `test_config_validation.py` | Fail-fast saat secret masih default di `APP_ENV=production` |
| Camera selector | `test_device_selector.py` | Pilih kamera by-serial (enum GigE tidak deterministik) |
| Streaming | `test_streaming_service.py` | MJPEG keep-alive multi-viewer |
| SDK boundary | `test_hikrobot_frame.py`, `test_mvs_error.py` | Konversi frame + mapping error SDK |
| **License** | `test_license_manager.py`, `test_license_local_repo.py` | Verifikasi JWS **Ed25519 asli** (tamper/kid/foreign-key ditolak), state machine efektif (ACTIVE/TRIAL/EXPIRED/CANCEL/GRACE, online↔offline, anti-rollback `server_time`, device-id, `nbf`), warning window, dan hash-chain + high-water-mark di SQLite |

**Prinsip menambah test:**
- Uji **logic murni** (domain, state machine, persistence SQLite), hindari test yang menyeret framework berat/hardware ke CI.
- Untuk async, ikuti pola `asyncio.run` (lihat `test_event_broadcast_worker.py` / `test_license_local_repo.py`).
- Kalau menambah modul baru ke lint, perluas juga scope `ruff check` di `ci.yml` (bertahap per modul yang sudah bersih).

---

## Environment Variables Reference

Tabel lengkap (line, konsol, PLC, R2, AutoERP, lisensi) beserta variabel yang kelihatan mati
padahal dipakai: [`docs/backend-overview.md`](docs/backend-overview.md) bagian Environment
Variables. Contoh isian: `.env.example` (dev dan produksi) dan `media.env.example` (sumber kamera
dan model per line).

---

## Git Workflow

- **Default branch**: `staging`: all development goes here first
- **Branch protection**: org ruleset blocks direct push to `main` and `staging`, use PR
- **Flow**: branch baru dari `staging` → PR **squash merge** ke `staging` → PR **merge commit** ke `main`
- PR rilis `staging` → `main` **jangan** di-squash: `main` sengaja menyimpan merge commit-nya.
  Cek isi pakai `git diff --stat origin/staging origin/main` (kosong = nol beda), bukan `git cherry`
- Commit message: **tidak boleh** ada baris `Co-Authored-By: Claude` atau referensi AI apa pun
