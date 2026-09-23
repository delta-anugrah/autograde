# CLAUDE.md — autograde

> **This is the MAP, not the manual.** It tells you *where to look*. For deep flows,
> diagrams, full invariants, worker/state model, and Docker/SDK internals, read
> **`docs/overview.md`** (on-demand, not auto-loaded).
> `AGENTS.md` is a symlink to this file (Codex/Copilot read the same map).
>
> **Belum pernah lihat repo ini sama sekali?** `docs/ONBOARDING.md` dulu — bahasa Indonesia,
> satu kali baca: sistemnya ngapain, alur satu janjang, isi tiap folder, jebakannya.

---

## System Role

`autograde` is the **Python AI camera service**. It runs as **3 Docker containers**
(one per camera line), each doing real-time YOLO ripeness detection on its own port and
delivering detection events to `palmgrade-api`. One of three repos:

Sejak Fase 2 (rencana yang dulu bernama PalmOS, sekarang **AutoERP**) ada **container ke-4 dari image yang sama**: konsol operator
offline, `APP_MODE=console`, port **8000**, layar di `http://localhost:8000/console`. Modul
ASGI-nya beda (`console_main.py`) supaya tidak ikut memuat torch/cv2 — satu line kamera mati
tidak menjatuhkan layar operator. Tiga line mengirim event ke konsol (`BACKEND_URL=http://localhost:8000`)
lewat kontrak §5 yang sama persis dengan palmgrade-api, jadi `palmgrade_api` lokal tidak perlu
hidup lagi di PC pabrik (7 → 4 container). Nol perubahan di kode line.

| Repo | Role | Tech | Port |
|---|---|---|---|
| **autograde** | **AI camera + inference (per line)** | **Python 3.11 / FastAPI** | **8001 / 8002 / 8003** |
| palmgrade-api | Business logic, auth, SSE broker | Node.js / Express | 2500 |
| palmgrade-frontend | Operator dashboard UI | Next.js 15 | 3050 |

Full system map: `../ARCHITECTURE.md`.

⚠️ **Repo ini dulu bernama `palmgrade-vision`** (diganti 2026-09-14, bareng `autoerp` pindah
ke org `delta-anugrah`). Yang **sengaja tidak ikut berubah**, jangan "dirapikan":

- **Nama image GHCR `ghcr.io/delta-anugrah/autograde`**, satu nama, tanpa warisan (keputusan
  2026-09-18: semuanya pindah ke AutoGrade, PC Lampung ikut; `palmgrade-vision` **dicabut**).
  Dipatok di `deploy.yml` dan dijaga `tests/unit/test_deploy_image_name.py`.
  ⚠️ **Urutan rilis pertama tidak boleh dibalik: `.env` PC Lampung dulu, tag kemudian.**
  Mesin itu tidak punya SSH masuk — `PALMGRADE_VISION_IMAGE` di `/opt/palmgrade/vision/.env`
  diedit tangan lewat AnyDesk ke nama baru. Menerbitkan tag lebih dulu membuat
  `palmgrade pull vision` menjawab "sudah terbaru" **selamanya**: nol error, pabrik berhenti
  menerima pembaruan, dan baru ketahuan saat ada yang bertanya kenapa versinya tidak naik.
- **Tag image lokal** `palmgrade-vision:latest` di `docker-compose.yml` + `Makefile`.
- **Paket Python** `src/palmgrade/`, **nama container** (`ripe_line_*`, `palmgrade_console`),
  dan path `/opt/palmgrade/vision/` di PC pabrik.

Semuanya baru berganti di **Fase 5**, saat PC pabrik memang dapat compose baru.

---

## Tech Stack

- Python 3.11, **FastAPI** + uvicorn
- **Ultralytics YOLO** (YOLOv8 + ByteTrack); torch/torchvision (CPU for dev, CUDA `cu126` for prod)
- OpenCV, NumPy
- **httpx** (cloud upload + realtime push), **APScheduler** (hourly batch upload), **SQLite**
  (`outbox.db` = antrean realtime ke API lokal; `UploadManifest` = state per-item batch R2), **boto3** (R2)
- **Hikrobot MVS SDK** (GigE industrial camera — prod only)
- **pymcprotocol** (MC Protocol ke CPU Mitsubishi — PLC integration, jalur hidup) + **pymodbus** (Modbus-TCP, jalur coupler ODOT lama, `PLC_PROTOCOL=modbus`); PC pabrik only, mati default
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
docs/              # overview.md (DETAIL), architecture.md, backend-overview.md, SETUP.md
tests/unit/        # unit test murni-logic (pytest, no torch/cv2)
models/release/    # best.pt (required, NOT committed)
artifacts/line-N/  # runtime output per line (NOT committed)
```

Tooling: `pyproject.toml` (pytest + ruff config, TIDAK untuk build), `.github/workflows/ci.yml` (lint + test).

Layer rule (strict): `route → controller → service → repository / pipeline / integration`.
Per-layer do/don't: `docs/overview.md` + `docs/architecture.md`.
**Pengecualian sadar:** konsol jalan `route → service → repository / integration`, tanpa
controller — controller di repo ini isinya cuma meneruskan argumen, dan konsol tidak punya
logika yang butuh tempat menganggur di antaranya. HTTP ke line tetap di lapisan integration
(`notifications/line_client.py`), disuntik ke `ConsoleService` lewat konstruktor: service tidak
boleh tahu soal httpx, dan test menukar kolaboratornya, bukan menambal method privat.

---

## Run / Build / Test

All via **`make`** (Docker only). From `autograde/`:

| Cmd | What |
|---|---|
| `make up` | prod: copy MVS SDK + build GPU (`cu126`) + build TensorRT engine + start 3 lines |
| `make up-dev` | dev: build CPU (no SDK) + start 3 lines |
| `make restart` | **code-only change** — kode di-bind-mount (`.:/app`), jadi **tidak perlu rebuild** |
| `make start` / `make up-1\|2\|3` | start without rebuild (all / single line) |
| `make up-console` / `make logs-console` | konsol operator saja (port 8000, `/console`) — aman di-restart tanpa mengganggu line |
| `make line` | satu line kamera **native tanpa Docker**, pasangan `make console` untuk develop di Mac (`make up` tidak bisa: butuh MVS SDK + CUDA + TensorRT). `make line N=2` untuk line kedua — **port DAN `MACHINE_ID` ikut berubah bersama**, karena konsol mencocokkan event lewat `machine_id`, bukan port: tiga line yang memakai `MACHINE_ID` sama dari `.env` semuanya mendarat di kartu line-1. **Sumber gambar dibaca dari `media.env`** (`LINE_N_CAMERA_TYPE`/`MEDIA_FILE`/`VIDEO_LOOP`), berkas yang ditulis layar Sumber Kamera — jadi pilihan per-line di layar berlaku di jalur native juga, bukan cuma di Docker. Tanpa `media.env` tidak ada yang ditimpa dan `.env` lama tetap jalan. **Target ini BERPUTAR sampai Ctrl-C**, meniru `restart: unless-stopped` Docker: layar merestart line dengan menyuruh prosesnya keluar, dan tanpa loop itu Simpan & Restart mematikan line tanpa pernah menghidupkannya (layar bilang tersimpan, kartu jadi OFFLINE, nol galat). `media.env` dibaca **ulang tiap putaran** — setelan baru itulah alasan prosesnya keluar. Yang ditimpa target ini juga `MACHINE_ID` dan `BACKEND_URL` (ke `make console`, bukan port Docker 8000 di `.env` — tanpa itu janjangnya tersimpan tapi tiap kiriman dibalas **404** dan layar tetap nol) |
| `make console` | konsol **native tanpa Docker** di `127.0.0.1:8100` — jalur develop di Mac (baca `.env`, `WEBHOOK_SECRET=devsecret`); target Docker tetap jalur Linux/pabrik |
| `make kiosk` | konsol layar penuh di PC ini (`scripts/console-kiosk.sh`) |
| `make operator` | akun **lokal** untuk login konsol: tambah / reset sandi (email + sandi). `AKSI=daftar\|matikan`. Akun milik AutoERP diurus di AutoERP. Di PC pabrik pakai `make operator-docker` (konsolnya di Docker, DB-nya beda berkas) |
| `make demo` | **data demo untuk showcase**: 10 truk, seminggu kunjungan, ratusan janjang, dua akun (`operator@`/`support@demo.autoerp.test`, sandi `sawit2026`). `HARI=3` memperpendek. Platnya **sama persis** dengan seeder AutoERP (`palm_mill/demo.py`) — satu truk = truk yang sama di dua layar. Menolak DB yang sudah punya data sungguhan. Di Docker: `make demo-docker`. ⚠️ jangan di PC pabrik |
| `make demo-reset` | hapus data demo lalu isi ulang bersih (`AKSI=reset` juga masih jalan, ini cuma nama yang dipakai sekarang — sama seperti AutoERP) |
| `make demo-off` | hapus data demo (sepuluh plat `PLATES`) dan **berhenti** di situ — beda dari `demo-reset` yang langsung mengisi ulang. Data sungguhan tidak disentuh (`wipe()` menyaring per plat). Jalankan sesudah showcase, **sebelum** uji coba sungguhan: janjang demo berstempel sampai mendekati jam sekarang, jadi selama masih ada dia menutupi baris yang baru digrading. AutoERP punya perintah nama sama (`make demo`/`demo-reset`/`demo-off`) |
| `make hash-sandi` | hash untuk dua akun bawaan image (`CONSOLE_DEFAULT_HASH`/`CONSOLE_SUPPORT_HASH`). Dipakai saat pasang PC pabrik — sandi mentah tidak pernah ditanam |
| `make rekonsiliasi-truk` | **OPS-2**, sekali saat pasang di PC yang **sudah** punya data palmgrade-api: satukan truk kembar. Tanpa `TULIS=1` cuma melihat. `--db <path>` untuk mencoba di salinan. Di Docker: `make rekonsiliasi-truk-docker`. PC baru (DB kosong) tidak perlu |
| `make build-engine` | build TensorRT FP16 engine **once per GPU** (one-shot, auto-skip kalau sudah ada) |
| `make logs` / `make logs-1` | tail logs (combined / per line) |
| `make reset-data` | **lihat dulu**: berapa foto dan basis data yang akan hilang. Tidak menghapus apa pun |
| `make reset-data-fresh` | **HAPUS SEMUA DATA** di PC ini: isi `artifacts/` (foto + sidecar) dan `state/` (semua SQLite). Minta **konfirmasi ketik `HAPUS`**. ⚠️ Menghapus lewat **container**, karena berkasnya **milik root** di Linux (`Dockerfile` tanpa `USER`) — `rm -rf` dari user biasa dijawab "Permission denied" ribuan kali. Di macOS ini tidak terlihat: Docker Desktop memetakan pemilik, jadi gagalnya cuma muncul di PC pabrik. Sisa yang tidak terhapus dilaporkan, bukan didiamkan. **Tanpa backup, tidak bisa dikembalikan.** ⚠️ Akun buatan `make operator`, antrean yang belum terkirim, dan foto yang belum naik R2 ikut hilang; **dua akun bawaan image dibuat ulang sendiri** saat konsol start, jadi cukup `make start` sesudahnya. ⚠️ Jangan di PC pabrik yang sedang produksi |
| `make down` / `make ps` / `make rebuild` / `make rebuild-clean` / `make clean` | stop / status / rebuild / clean rebuild (`--no-cache`) / cleanup |

- **TensorRT (GPU speedup, akurasi sama)**: engine FP16 (`engines/<model>.sm<cc>.engine`) **hardware-locked** (compute capability + versi TensorRT) → tidak di-commit, tidak di-bake ke image, dibangun **sekali per GPU** on-machine via `make build-engine` (~5–15 mnt, tidak butuh kamera). Engine tidak ada / tidak cocok → runtime **fallback ke `.pt`** otomatis (`pipelines/model_registry.py`), jadi kegagalan build bukan outage. Install TensorRT-nya ikut `Dockerfile` (`pypi.nvidia.com` — **wajib**, index PyPI publik cuma punya source stub yang bikin pip hang). Detail: `docs/overview.md` § Docker/SDK/GPU.
- **`make up` cuma perlu** kalau dependency / `Dockerfile` / SDK berubah; untuk ubah kode pakai `make restart`.
- **Dev without a camera — pilih dari layar, per line**: konsol → login **support** → tab
  **Sumber Kamera**. Taruh berkas di `media/` (host), pilih Video/Foto untuk line yang mau
  diganti, Simpan. Tiap line berdiri sendiri: line 1 boleh video sementara line 2–3 tetap
  kamera. Setelannya mendarat di **`media.env`** (di-`.gitignore`, keadaan per-mesin;
  `make` membuatnya dari `media.env.example` kalau belum ada). Cara pakainya:
  `docs/runbooks/2026-09-21-sumber-kamera-per-line.md`.
  ⚠️ **`media.env` wajib lewat `--env-file`, bukan `env_file:`** — Compose menyelesaikan
  `${LINE_1_CAMERA_TYPE}` dari shell + `--env-file` saja, sementara `env_file:` menyuntik
  environment container **sesudah** interpolasi. Dengan `env_file:` ketiga line selalu
  `hikrobot` tanpa satu pun error. `Makefile` sudah membawa kedua flag lewat `$(COMPOSE)`;
  pemanggil di luar Makefile harus membawanya sendiri.
  ⚠️ **Jalur lama sudah tidak ada**: mount `/videos` dicabut, dan `CAMERA_VIDEO_PATH` +
  `docker-compose.override.yml` bukan lagi cara menyetel video per line.
- **Verify**: `curl :8001/health`; `curl :8001/health/detail` (camera_connected, gpu_available, workers, current_assignment_id, `plc` = `null` kalau PLC mati); stream at `http://localhost:8001/api/video_feed`.
  ⚠️ **`capture_save_dropped` di `/health/detail` harus NOL.** Di atas nol berarti antrean penulis
  pernah penuh dan janjang yang sudah digrading — sudah dapat pulse PLC, sudah masuk rekap —
  tidak tersimpan sama sekali: tidak ada gambar, tidak ada sidecar, jadi tidak ada yang bisa
  ditemukan `BatchUploadWorker._scan()` belakangan. Tidak ada retry (menahan deteksi akan
  mengembalikan lag ~590 ms yang dihilangkan); yang harus dikejar penyebabnya — disk lambat atau
  laju grading melewati kemampuan menulis. `capture_save_pending` yang naik terus adalah
  peringatan dininya.
  ⚠️ `outbox_pending`/`outbox_failed` di `/health/detail` mengukur **jalur realtime ke API lokal**
  saja. Angka naik terus = API lokal tidak menjawab (cek `BACKEND_URL`). Angka itu **tidak**
  mengatakan apa-apa soal batch upload ke cloud — untuk itu baca log `Batch tick: N item eligible`
  dari `BatchUploadWorker` atau query `state/upload_manifest.db` langsung.
- **Tests / CI**: `tests/unit/` = unit test murni-logic (`rules`, `outbox_store`, `event_id` uuid5, streaming keep-alive, config validation, **license**: JWS Ed25519 verify + state machine + SQLite hash-chain, **konsol**: `work_date` lewat tengah malam + `console_store` + invarian `console.html` + **timbangan**: neto dihitung bukan dipercaya + timbang-keluar menggabung bukan menimpa + plat beda tulisan tetap satu truk, **master data dari AutoERP**: field yang diminta persis milik DocType (ERP palsu membalas 417 seperti Frappe) + Sumber TBS mengikuti `sumber_for_supplier` + grup supplier disimpan mentah + truk ERP mengadopsi baris truk manual, **antrean ke AutoERP**: ditolak vs tidak terjangkau dibedakan + backoff 30 dtk→1 jam + pesan yang diganti saat masih di jalan tidak ditandai terkirim + truk manual masuk antrean + truk milik ERP read-only, **kunjungan truk**: bentuk pesan §4.C + `stage` diturunkan dari keadaan + bagian kosong tidak dikirim + grading ikut lewat tautan assignment + kirim ulang harian sekali sehari + `erp_name` tidak terhapus saat plat diketik ulang + kursor per-DocType tidak maju kalau ada baris gagal, **thumbnail + manifest kunjungan** (sejak 2026-09-16): varian `thumb` di `capture_layout` (twins/pasangan/kunci R2) + thumbnail 400px ditulis di `capture_writer` tanpa menggagalkan capture + `batch_upload_worker` ikut mengunggah dan menghapus thumbnail + `UPLOAD_API_URL` kosong = item `done` begitu foto sampai + bentuk JSON `visit_manifest` (murni, tanpa I/O) + `console_store.bunches_for_assignment` urut waktu + `visit_manifest_worker` (antrean sendiri, viewer diunggah sekali per proses, R2 mati menahan baris) + `detail_url` terkirim hanya kalau R2 terkonfigurasi + invarian statis `viewer.html` (nol dependensi eksternal, baca manifest relatif)) — jalan tanpa torch/cv2/SDK via **`pytest`** (config di `pyproject.toml`, `pythonpath=src`; async pakai `asyncio.run`, **bukan** pytest-asyncio). CI install deps ringan pure-python (`cryptography aiosqlite psutil httpx boto3 pydantic pyyaml fastapi` — `pyyaml` cuma untuk tes yang mencocokkan `docker-compose.yml` dengan `Settings`; `fastapi` cuma untuk penjaga sesi konsol, yang cuma bisa dibuktikan lawan app sungguhan) di samping `ruff pytest` — samakan venv lokal dengan daftar itu, kalau tidak 4 test batch upload gagal koleksi. Lint via **`ruff check`** (scope: `tests/`, `domain/`, `integrations/outbox/`, `integrations/upload/`, `license/`, `plc/`, `workers/batch_upload_worker.py`, `workers/master_data_worker.py`, seluruh modul konsol — `integrations/notifications/line_client.py`, `repositories/console_repository.py`, `services/console_service.py`, `routes/console.py`, `console_main.py` — diperluas bertahap per modul yang sudah bersih). Semua jalan otomatis di **`.github/workflows/ci.yml`** tiap PR/push ke `staging`/`main` (runner ringan, tanpa GPU). `tests/integration` masih `.gitkeep` (butuh Docker + hardware). **Nambah test → utamakan logic murni; jangan seret hardware, torch, atau cv2 ke CI.** FastAPI `TestClient` boleh, tapi hanya untuk hal yang memang cuma ada di lapisan HTTP (penjaga sesi): app-nya dirakit sendiri di test dengan dependensi di-override, **bukan** `create_console_app()` — yang itu menyentuh `state/console.db` milik developer.
- From-zero prod setup (NVIDIA toolkit, MVS install, camera IP): `docs/SETUP.md`.

---

## HTTP Surface (this service)

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/detail` | detail = camera / gpu / workers / current_assignment_id (+ `outbox_pending`/`outbox_failed`, always `0` — outbox disabled) |
| GET | `/api/video_feed` | MJPEG live (multi-viewer) |
| GET | `/api/results_today` | today's results (read from disk) |
| POST | `/internal/assignment` | ← from api: set current truck/assignment (`x-internal-secret`) |
| POST | `/internal/manual-reject` | ← from api: trigger manual reject (`x-internal-secret`) |
| WS | `/ws/results` | legacy result push. ⚠️ `image_url`-nya dikirim **sebelum** berkasnya ada di disk (deteksi menyerahkan janjang ke `CaptureSaveWorker` lalu lanjut) — jendelanya ratusan milidetik. Tidak ada yang memakai lane ini hari ini (`console.html` tidak membukanya), tapi siapa pun yang menghidupkannya harus menahan gambar sampai 404 pertama lewat. Jalur yang dipakai konsol aman: barisnya ditulis penulis **sesudah** gambarnya jadi |
| GET | `/captures/...` | static images (mount → `artifacts/`) |

**Konsol (`APP_MODE=console`, port 8000)** — surface yang berbeda total; `main.py` tidak dipakai.
**Semua `/api/console/*` butuh sesi** (Fase 4) kecuali tiga baris pertama di bawah; tanpa cookie
`konsol_sesi` jawabannya 401 `belum_masuk`. Lane mesin (`/internal/*`) tetap pakai webhook secret:

| Method | Path | Notes |
|---|---|---|
| GET | `/console` | layar operator (satu file HTML statis) — terbuka, dia yang menggambar gerbang login |
| GET | `/api/console/operators` | email + nama akun aktif untuk mengisi kolom email, **tanpa** hash — terbuka |
| POST | `/api/console/login` | `{email, sandi}` → cookie `konsol_sesi` HttpOnly, 12 jam. Sandi salah 401, login terkunci 429 |
| POST | `/api/console/logout` | akhiri sesi ini saja |
| GET | `/api/console/me` | operator yang sedang masuk |
| GET | `/api/console/state` | ringkasan hari kerja + 20 grading terakhir (di-polling 2 detik) + `lisensi` (severity/tanggal/sisa hari) untuk banner operator — **bukan** lane support, karena operator biasa yang melihat kamera berhenti |
| GET | `/api/console/history` | filter `work_date` / `line_code` / `truck_id`; `limit`+`offset` untuk pagination, dan `total` (jumlah baris yang cocok filter, bukan sepanjang halaman) ikut dibalas |
| GET | `/api/console/trucks` | master truk + supplier + `source_label` |
| POST | `/api/console/trucks` | truk manual (truk pinjaman / belum terdaftar) — id = uuid5 plat ternormalisasi |
| GET | `/api/console/trucks/{plat}/qr.png` | kartu QR untuk ditempel di truk / dikirim ke HP supir. **Dibuat di server** (`segno`, pure-Python) karena `console.html` nol referensi `https://` — pustaka CDN akan mati saat internet putus. Isinya plat ternormalisasi, divalidasi ulang sebelum dicetak. Truk yang belum terdaftar tetap dilayani: kartu dicetak dulu, truknya didaftarkan kemudian |
| POST | `/api/console/scan/keluar` | `{qr}` di gerbang keluar → tiket yang menunggu tara. **Dua tiket terbuka ditolak, tidak ditebak** (keputusan operator 2026-09-15): menebak bisa memasangkan tara ke kunjungan yang salah dan mencampur tonase dua kunjungan. Dibatasi hari kerja: tiket kemarin yang taranya kosong akan memberi neto dari bruto kemarin dan tara hari ini |
| POST | `/api/console/scan` | `{qr}` hasil scan di gerbang timbangan → truk yang sudah ada. Truk belum terdaftar dijawab **200 `ditemukan:false`** (truk pinjaman itu kasus normal, 404 terbaca seperti kerusakan); yang bukan plat **400**. **Tidak pernah membuat truk dan tidak pernah menulis berat** |
| GET | `/api/console/weighings` | tiket timbangan hari kerja (bruto / tara / neto) |
| POST | `/api/console/weighings` | operator mengetik bruto/tara sendiri — payload identik dengan kiriman program timbangan |
| GET | `/api/console/recap` | rekap per truk satu hari kerja (janjang, ACC/REJ, neto) — `?work_date=` opsional |
| POST | `/api/console/lines/{line}/assign-truck` | → diteruskan ke `/internal/assignment` line |
| POST | `/api/console/lines/{line}/release-truck` | truk pergi → `/internal/assignment` line dengan truk kosong |
| POST | `/api/console/lines/{line}/manual-reject` | → diteruskan ke `/internal/manual-reject` line |
| GET | `/api/console/dev/ping` | lane developer paling ringan — dipakai layar untuk memastikan akses masih hidup. **Semua tujuh baris di bawah ini butuh `role='support'`, dijawab 403 kalau bukan** |
| GET | `/api/console/dev/log` | isi `event_log` — filter `level`/`cari`, pagination `limit`+`offset` |
| GET | `/api/console/dev/diagnostik` | `/health/detail` ketiga line, digabung satu layar |
| GET | `/api/console/dev/antrean` | isi `erp_outbox` — jumlah pending/gagal + daftar yang gagal |
| POST | `/api/console/dev/antrean/kirim-ulang` | requeue semua baris gagal di `erp_outbox` |
| GET | `/api/console/dev/versi` | versi image + lisensi berjalan lengkap dengan nama perusahaan dan tanggal |
| GET | `/api/console/dev/plc/{line_code}` | snapshot DI + daftar coil yang boleh diuji untuk satu line — baca saja, aman dibuka kapan pun |
| POST | `/api/console/dev/plc/{line_code}/coil` | picu satu coil PLC line itu — **satu-satunya aksi konsol yang menggerakkan hardware fisik**, lihat Critical Rules |
| GET | `/api/console/dev/rekam` | status rekaman tiap line + setelan yang berlaku + sisa disk. Line yang tidak menjawab dilaporkan `terbaca:false`, bukan menjatuhkan seluruh jawaban |
| POST | `/api/console/dev/rekam/setelan` | ubah resolusi/fps/bitrate rekaman. Berlaku untuk rekaman **berikutnya** — mengubah resolusi di tengah berkas MP4 menghasilkannya rusak |
| POST | `/api/console/dev/rekam/{line_code}/mulai` | mulai merekam satu line. 409 kalau sudah merekam, **507 kalau disk mepet** (dua hal yang butuh tindakan berbeda, jadi tidak diratakan) |
| POST | `/api/console/dev/rekam/{line_code}/stop` | hentikan dan tutup berkasnya. Menahan ~2 detik: line menunggu encoder menutup berkas dengan rapi |
| POST | `{BACKEND_API_VER}/internal/vision/events` | ← dari tiga line (`x-webhook-secret`), kontrak §5 |
| POST | `{BACKEND_API_VER}/internal/scale/weighing` | ← dari program timbangan (`x-webhook-secret`), bentuk sementara kita |
| GET | `/captures/{line_code}/...` | gambar line, mount read-only, bentuk URL = `resolveCaptureUrl` api |
| GET | `/health` | ringan, sengaja bukan `routes/health.py` (yang itu menarik torch) |

**Layar penuh = urusan browser, BUKAN `console.html`.** `requestFullscreen()` wajib dipanggil
dari gestur pengguna, jadi tidak ada halaman web yang boleh memfullscreen dirinya sendiri saat
dimuat — kiosk datang dari `scripts/console-kiosk.sh` (Chrome `--kiosk`), dengan
`scripts/palmgrade-console.desktop` untuk jalan otomatis saat login. Tiga hal di skrip itu yang
tidak boleh hilang: `--user-data-dir` tetap (pilihan operator hidup di `localStorage`; profil
sementara atau `--incognito` = semuanya balik ke bawaan tiap pagi), tunggu konsol menjawab dulu
(sesudah listrik mati sesi desktop sering login sebelum Docker siap, dan kiosk yang mendarat di
halaman error tidak pernah memuat ulang sendiri), dan `xset s off -dpms` (layar yang dilihat dari
jauh tanpa disentuh berjam-jam akan ditidurkan screensaver).

---

## Integration Contracts (verified against palmgrade-api code)

**vision → api** — **dua jalur paralel, sengaja**:

| Jalur | Tujuan | Kapan | Gambar |
|---|---|---|---|
| `OutboxRetryWorker` (realtime) | `BACKEND_URL` = API **lokal** PC pabrik | poll 1 detik | path relatif → api meng-serve dari mount `artifacts/` |
| `BatchUploadWorker` (batch) | `UPLOAD_API_URL` = API **cloud** | tiap jam menit `UPLOAD_MINUTE` | di-`PUT` ke R2 dulu, event bawa URL R2 absolut |

`event_id` keduanya identik (uuid5 `machine_id:file_timestamp`), jadi kalaupun dua jalur ini
menunjuk API yang sama, POST kedua dibalas `already_processed` — bukan baris dobel.
⚠️ `BACKEND_URL` **wajib** API lokal. Menunjuknya ke `api.smagri.id` adalah yang membanjiri
produksi dengan ~1098 event tes pada 2026-08-09.

Kontrak jalur batch (gambar dulu ke R2, lalu teks ke API cloud):
- Image first: `PUT` to Cloudflare R2, then the text event references the public R2 URL.
- `POST {UPLOAD_API_URL}{BACKEND_API_VER}/internal/vision/events`
  → cloud `https://api.smagri.id/api/v1/internal/vision/events`
- Header **`x-webhook-secret: UPLOAD_API_SECRET`** (must equal the cloud API's `WEBHOOK_SECRET`)
- **Kill switch**: empty `R2_BUCKET` makes the whole batch a no-op (one `logger.warning` on the
  first tick, then quiet — easy to miss in a long-running log) — nothing reaches
  the cloud, and `/health/detail` will not tell you.
- Payload field contract (api validates via `VisionEventRequest` DTO):
  - `prediction` `"Acc"|"Rej"` (**required**)
  - `ripeness_status` `"ACC"|"REJ"` (**UPPERCASE**, `@IsIn`)
  - `tp_status` `"PASS"` or `null` (never `"TP"`)
  - `capture_type` `"auto"|"manual"`
  - `machine_id` UUID (must equal a `machines.id`)
  - `event_id` UUID (idempotency; **selalu** uuid5 deterministik, auto maupun manual), `timestamp` ISO **UTC-aware**, `truck_id` optional, `bounding_box` `{x_min,y_min,x_max,y_max}`
- api responds `200/201` or `{status:"already_processed"}` (both treated as delivered).

**api → vision** — header **`x-internal-secret: WEBHOOK_SECRET`**:
- `POST /internal/assignment` body `{machine_id, assignment_id, truck_id, assigned_at}`
- `POST /internal/manual-reject` body `{machine_id, assignment_id, requested_by, requested_at}`
- `GET /health` (line health check in api `getLines()`)

**Shared config:**
- `WEBHOOK_SECRET` — **one** secret, both directions; must equal `palmgrade-api` `WEBHOOK_SECRET`. **Fail-fast:** `Settings.validate_for_runtime()` raise saat `APP_ENV=production` & secret masih default (`supersecret123`) → container tolak start. **Wajib isi `WEBHOOK_SECRET` di `.env` PC prod** (dev tetap boleh default, cuma warning).
- `machine_id` — `LINE_1/2/3_MACHINE_ID` in `.env` = the three `machines.id` UUIDs in api Postgres.
  docker-compose falls back to seed UUIDs if unset.
- Saved images: api maps `machine_id → machines.line_code` and serves at
  `/api/v1/captures/<line_code>/...` (vision's `image_path` has no line segment).

**SSE events** api broadcasts to frontend after ingest: `inspection_saved`, `new_quality_control` (alias), `assignment_changed`.

Full endpoint / payload / env tables: `docs/backend-overview.md`.

---

## Critical Rules (full rationale → `docs/overview.md` § Invariants)

0. **Model 4 kelas; kelas BUKAN verdict.** `best.pt` mendeteksi `Ripe`, `Unripe`,
   `JK` (janjang kosong), `TP` (tangkai panjang). Pemetaannya hidup di **satu**
   tempat, `domain/grade_class.py`: `Ripe`→ACC, `Unripe`/`JK`→REJ, `TP`→tidak
   punya verdict (bukan janjang; menempel di `tp_confidence`). Dua hal di hilir
   sengaja tetap biner: **PLC cuma punya dua coil** (OK/NG — kategori ketiga itu
   kabel, bukan kode) dan **AutoERP cuma membukukan tiga kriteria** (`Mentah` /
   `Tangkai Panjang` / `Matang`, kontrak beku). Jadi satu baris membawa
   **keduanya**: `ripeness_status` = verdict yang menggerakkan piston dan dibayar,
   `grade_class` = rincian yang dibaca layar.
   ⚠️ **`JK` tidak dikirim ke AutoERP.** Tidak ada kriterianya di sana, dan dua
   kandidat terdekat sama-sama salah lapor: `Sampah` itu **ditimbang**, bukan
   dilihat kamera (jawaban Samuel 2026-09-16), dan menggabung JK ke `Mentah`
   membesarkan porsi mentah yang dipotong dari supplier. Angkanya berhenti di
   edge sampai ada perubahan kontrak yang disepakati.
   ⚠️ Kelas dibaca dari **nama**, bukan urutan id. `cls_id in (0, 1)` dulu
   dipakai buat menentukan `area`, dan model yang dilatih ulang boleh menukar
   urutan kelas — `area` jadi 0 untuk buah dan penjaga `MINIMUM_SIZE` berhenti
   bekerja tanpa satu pun error. `domain/rules.py` **pensiun** karena alasan yang
   sama: aturannya mencocokkan substring `"rej"`, yang tidak pernah cocok dengan
   `Unripe` maupun `JK`.

1. **Disk before API** — never POST events directly from a worker; **antrean yang bicara ke
   jaringan, bukan worker deteksi**. `CaptureSaveWorker` (jalur auto) dan `capture_service` (manual)
   menulis WebP + JSON ke `artifacts/results/` lalu **satu baris** ke `outbox.db`
   (`build_event_payload()` dari `domain/vision_event.py`). Dua konsumen mengirimnya:
   - `OutboxRetryWorker` → API **lokal** (`BACKEND_URL`), poll 1 detik. Ini yang bikin operator
     lihat Grading History + gambar seketika, dan satu-satunya jalur yang hidup saat internet mati.
   - `BatchUploadWorker` → R2 + API **cloud** (`UPLOAD_API_URL`), tiap jam. Menemukan item lewat
     `_scan()` folder `results/` (**bukan** outbox), state per-item di `UploadManifest`.

   `event_id` = **uuid5 deterministik** (`machine_id:file_timestamp`) di **semua** jalur, jadi
   kirim ulang dibalas `already_processed`, bukan baris dobel. Jangan pernah pakai uuid4 di sini.

   `image_path` dari kedua worker deteksi **harus relatif** (`captures/results/<tgl>/<file>.webp`);
   api merakitnya jadi `{apiPrefix}/captures/{line_code}/...`. Hanya `BatchUploadWorker` yang
   menukarnya dengan URL R2 absolut, dan itu untuk cloud saja.

   Kelas kegagalan batch bersifat load-bearing: `_PoisonError` → poisoned + **continue** (satu item
   busuk tidak menyandera batch; file TIDAK dihapus); `_RequeueError` → requeue, lalu **break**
   kalau `batch_fatal=True` (jaringan/5xx/429/401/403 — kondisi global) tapi **continue** kalau
   `batch_fatal=False` (HTTP 404 = truck belum sinkron, kondisi per-item — break di situ bikin
   antrean `ORDER BY discovered_at ASC` kelaparan di belakangnya).
1b. **Thread deteksi tidak pernah menunggu disk** (sejak 2026-09-18). Encode WebP frame sensor penuh
   memakan **~285 ms per gambar**, dan satu janjang menulis tiga gambar + sidecar + baris outbox —
   **~590 ms** diukur di PC Lampung 2026-09-17. Selama itu dulu deteksi BERHENTI, dan tiga akibatnya
   semuanya senyap: `frame_queue` (drop-oldest, nol log) membuang ~12 frame per janjang di kamera 20
   fps, ByteTrack kehilangan jejak lalu memberi track id baru pada janjang yang sama (tonase dobel),
   dan layar operator membeku ~1 detik. Sekarang `FrameProcessingWorker` cuma `submit()` satu
   `SaveJob` ke `CaptureSaveWorker` lalu lanjut ke frame berikutnya.
   **Yang HARUS tetap di jalur deteksi**, jangan dipindah ke penulis: pulse PLC (piston menyortir
   buah yang lewat sekarang, bukan buah setengah detik lalu), penandaan `plc_signalled`/`processed`,
   event ke `event_queue` (angka di layar), dan **penetapan `timestamp`** — nama berkas adalah sumber
   `event_id` uuid5, dan `BatchUploadWorker` menghitung ulang id yang sama dari nama itu berjam-jam
   kemudian. Penulis yang menstempel jamnya sendiri memutus idempotensi dan satu janjang terhitung
   dua kali di angka yang dibayar ke petani.
   `image_url` untuk layar dihitung di depan lewat `CaptureWriter.annotated_url()` — **rumus yang
   sama** yang dikembalikan `write_pair()`, jadi tautan yang tampil dan berkas yang ditulis tidak
   bisa menyimpang (kalau menyimpang: gambar 404 di konsol, nol error di line).
   Antrean **8 dalam, drop yang terbaru + `logger.error`**: menahan deteksi sampai antrean lega akan
   mengembalikan persis lag yang dihilangkan. Angkanya dari dua ukuran — beban nyata **300
   janjang/jam/line** (satu tiap 12 detik, sementara penulis butuh ~0,6 detik, jadi antrean ini
   untuk **lonjakan**, bukan laju rata-rata) dan biaya memorinya: tiap job menahan dua frame 14,3 MB,
   jadi 8 dalam = 230 MB per line, 689 MB untuk tiga line dari RAM 31 GB. Antrean yang sering penuh
   berarti disk/CPU tidak mengimbangi laju grading — itu yang harus dibaca dari log, bukan ditambal
   dengan antrean lebih dalam lagi. Satu janjang >1 detik diadukan `logger.warning`
   (`tulis … ms, antre … ms, antrean=N`) — itu alat ukur lapangannya.
1c. **TP dipasangkan lewat JARAK, bukan urutan waktu** (sejak 2026-09-18,
   `domain/garis_capture.tp_untuk_janjang`). Saat janjang difoto, TP yang dipakai adalah yang
   pusatnya paling dekat dan masih dalam `_JANGKAUAN_TP` × setengah diagonal janjang —
   ambang RELATIF, karena janjang dekat kamera jauh lebih besar daripada yang di ujung frame.
   TP dikumpulkan di **pra-pindai**, sebelum loop janjang: urutan kotak dalam satu frame tidak
   dijamin, jadi TP yang disebut sesudah janjangnya akan terlewat kalau dibaca sambil jalan.
   ⚠️ **Ambang saja tidak cukup**: dua janjang berdempetan bisa sama-sama berada dalam
   jangkauan TP yang sama, dan yang menang tinggal siapa yang kebetulan diproses lebih dulu.
   Karena itu TP diberikan hanya kalau janjang itu yang **paling dekat di antara semua**
   janjang di frame (`janjang_lain`) — tanpa itu janjang B dikreditkan tangkai milik A dan
   tangkai A yang asli tidak tercatat, dan `tp_confidence > 0.8` itu kriteria Tangkai Panjang
   yang dibukukan AutoERP. Janjang yang **sudah difoto** ikut jadi saingan: tangkai milik
   janjang yang baru selesai tidak boleh pindah ke tetangganya.
   ⚠️ **Alur LAMA yang diganti** (jangan dihidupkan lagi): satu slot `_last_tp` berisi "TP
   terakhir yang terlihat", diberikan ke janjang berikutnya yang menyentuh garis, tanpa pernah
   melihat posisi. Dua akibatnya sama-sama salah bayar dan sama-sama senyap: TP milik janjang A
   menempel ke janjang B yang lewat garis lebih dulu, dan TP yang terlihat sesudah janjangnya
   difoto menempel ke janjang berikutnya.
   ⚠️ **TP yang datang SESUDAH janjang terdekatnya difoto memang tidak ikut** — itu harga yang
   sadar dibayar dari "capture apa adanya". Dihitung di `tp_telat` (`/health/detail`) supaya
   keputusan menambah jendela tunggu nanti diambil dari angka Lampung, bukan dugaan. Tiga jalan
   yang sudah ditimbang dan ditunda: tahan simpan ~0,5 dtk, biarkan hilang, atau kirim susulan
   (yang terakhir menyentuh kontrak ingest idempotent + rekap kunjungan AutoERP).
2. **`_processed_objects`** — never `discard()` an active track (single-trigger). Trim only IDs that are inactive (gone from `track_history`) **and** stale >300s.
3. **`state.lock`** around all physical camera access (`FrameCaptureWorker` + `capture_manual_reject`).
4. **MJPEG** — only `DisplayWorker` writes `state.latest_frame`, via `threading.Condition.notify_all()` (multi-viewer). It renders `last_yolo_frame` (paired with results) and runs at `STREAM_FPS` (default 12), decoupled from `CAMERA_FPS`.
5. **DI** (`core/dependencies.py`) — `@lru_cache` singletons **except** `get_capture_service()` / `get_health_service()` (camera injected at startup). `get_outbox_store()` may cache (SQLite singleton).
6. **Lifespan** (not `@app.on_event`); `repo_root = parents[3]`; every worker `run_loop` wraps `run_once` in `try/except`; `FrameCaptureWorker` needs `device_index` (so line-2/3 reconnect to the correct camera).
7. **`tp_status`: boolean di sidecar, `"PASS"`/`null` di kawat.** Dua kosakata, satu
   fakta (`domain/vision_event.TP_PASS`): DTO palmgrade-api memvalidasi field ini
   dengan `@IsIn(["PASS"])` dan kontrak itu beku, sementara sidecar di disk kita
   sendiri menyimpan `true`/`false`. **Satu janjang = SATU sidecar** (sejak
   2026-09-20): nilai TP — termasuk `tp_bounding_box`, kotak tangkainya — menumpang
   di berkas ripeness-nya, dan `_auto_tp.json` tidak ditulis lagi. Nama lama masih
   dikenali retensi karena berkasnya masih ada di disk pabrik; berhenti mengenalinya
   membuat berkas itu yatim abadi sampai disk penuh.
   ⚠️ **TP cuma dicari untuk janjang ACC.** Unripe dan JK dibuang piston, jadi
   tangkainya tidak dibayar dan tidak dicatat — angka TP karena itu lebih kecil
   daripada sebelum tanggal itu, dan turunnya disengaja.
   **`image_url` = `captures/results/{date}/{HHMMSS}_{plat}_{assign8}/bbox/{Ripe|Unripe|JK}[/TP]/{ts}_auto.webp`** (consistent with `/captures` mount) — folder KELAS, bukan verdict (sejak 2026-09-20: `acc`/`rej` melebur Unripe dan JK, membuang persis yang dibeli retrain 4 kelas), dan janjang Ripe bertangkai panjang turun satu level lagi ke `Ripe/TP/` supaya mencari hasil TP cukup membuka satu folder. Capture manual → `unknown/` (tidak pernah lewat model). ⚠️ **Tidak ada pembaca yang boleh mematok kedalaman folder** — `Ripe/TP/` satu level lebih dalam, dan `_twin()` yang dulu menganggap verdict tepat di bawah `bbox` mengembalikan `None` untuknya: kembaran yang tidak ketemu adalah kembaran yang tidak dihapus siapa pun, karena `clean/` dan `thumb/` tidak punya baris manifest sendiri. Satu folder per truk, **tiga berkas per janjang**: `bbox/` (bergambar kotak, ini yang ditunjuk `image_path` dan yang naik R2), `clean/` (polos, buat latih model ulang; **tidak** diupload), dan `thumb/` (sejak 2026-09-16: 400px WebP q60 dari frame `bbox/`, naik ke R2 berdampingan dengan `bbox/` — apa yang dimuat grid `viewer.html`). Jam folder pakai `FACTORY_TZ`, **bukan** UTC — folder dibaca manusia, nama berkas dibaca mesin. Truk belum di-assign → `_belum-assign/`. **JSON sidecar-nya TETAP datar di folder tanggal**: `BatchUploadWorker._scan()` mencarinya dengan `glob("*/*_ripeness.json")` (kedalaman dipatok dua), jadi sidecar yang ikut masuk subfolder bikin upload cloud berhenti **tanpa error**. Aturannya di `domain/capture_layout.py` (`CaptureVariant.THUMB`, `twins_of()`), penulisnya `services/capture_writer.py` (satu-satunya yang menulis gambar, dipakai jalur auto maupun manual). Gambar disimpan **WebP** quality 65 (`JPEG_QUALITY_SAVE`), thumbnail quality 60; folder `errors/`, `captures/`, dan `logs/` **sudah tidak ada** — dulu dibuat saat startup tapi tidak pernah ditulis (REJ ditemukan via metadata `ripeness_status`, log ke stdout). Startup cuma membuat `results/`, dijaga `tests/unit/test_artifact_dirs.py`.
8. **`cv2.imwrite` failure → `LocalFileStorage.write_image` raises `OSError`** (no orphaned JSON records pointing at an image that was never written). Kegagalan menulis **`thumb/`** khusus TIDAK melempar — janjang tetap tersimpan tanpa thumbnail, `logger.error` saja (lihat rule 7).
   **Nama folder TANGGAL selalu UTC** (`FrameProcessingWorker._save_ripeness`,
   `capture_repository`) — pembacanya wajib UTC juga. ⚠️ Yang pakai `FACTORY_TZ`
   cuma **folder truk di dalamnya** (aturan 7); dua zona dalam satu pohon itu
   disengaja, jangan "diseragamkan" ke salah satunya. `datetime.now()` naive di
   `ResultRepository` kebetulan cocok cuma karena container ini kebetulan
   `TZ=UTC`; set `TZ=Asia/Jakarta` dan `/api/results_today` menunjuk folder yang
   belum ada lalu melapor nol hasil. Jangan pernah pakai `datetime.now()` telanjang.
9. **Retention deletes source files** — `BatchUploadWorker._retention()` unlinks **ketiga** WebP (`bbox/` + `clean/` + `thumb/`, dipasangkan `domain/capture_layout.twins_of`) + JSON once an item is `done` and older than `UPLOAD_RETENTION_DAYS` (default 7; PC pabrik 180). Local artifacts are therefore **not** a long-term archive; the cloud + R2 are.
   Umur saja tidak cukup begitu angkanya jadi hitungan bulan, jadi
   `_retention_by_disk()` jadi pagar terakhir: di bawah `UPLOAD_DISK_MIN_FREE_GB`
   (default 20) ia membuang `done` **tertua** lebih awal sampai sisa disk lega.
   Hanya `done` yang pernah disentuh — item lain adalah satu-satunya salinan yang
   ada, jadi kalau `done` habis dan disk masih mepet, penjaga **berhenti dan
   `logger.error`** (antrean upload macet — itu urusan operator, bukan hapus data).
   ⚠️ Seluruh `_retention()` cuma jalan kalau `R2_BUCKET` terisi (`run_batch_once`
   pulang lebih awal tanpanya), jadi dengan R2 mati tidak ada yang membersihkan
   disk sama sekali — dan memang tidak boleh ada, karena tidak ada yang `done`.
   ⚠️ **Salinan `clean/` tidak punya baris manifest sendiri** — dia dihapus di sini
   atau tidak sama sekali. Menambah gambar ketiga tanpa ikut menambahnya ke
   `_delete_item_files` berarti penjaga disk menyapu item `done` sambil cuma
   membebaskan separuh byte-nya, sampai disk penuh dan grading berhenti menyimpan.

10. **Konsol: `work_date` dihitung saat ingest, lalu DISIMPAN** (§6.1). Pabrik jalan ~20
    jam/hari **lewat tengah malam**, jadi batas hari UTC memotong satu shift jadi dua tanggal.
    `domain/working_day.py` menurunkannya dari timestamp event itu sendiri di `FACTORY_TZ` —
    **jangan pernah** dari `now()`, `creation`, atau nama folder. Timestamp cacat → `ValueError`
    → ingest balas **400** → outbox line menahan dan menandainya `outbox_failed`; sengaja
    terlihat gagal daripada mendarat di hari yang salah. `python:3.11-slim` butuh `tzdata`
    (sudah di Dockerfile) — tanpa itu `ZoneInfo` gagal dan tanggal diam-diam balik ke UTC.
11. **Konsol tidak boleh memindai direktori** (§6.2) — semua yang dibaca layar operator datang
    dari **index SQLite** `state/console.db` (`repositories/console_repository.py`, konvensi
    sama dengan `OutboxStore`: WAL + `synchronous=FULL` + satu lock + `INSERT OR IGNORE`).
    Gambar tetap di disk line-nya, di-mount read-only dan di-serve statis. Polling `listdir`
    tiap 2 detik akan memakan I/O yang dipakai grading.
12. **Sumber TBS: edge cuma mencerminkan aturan AutoERP, tidak pernah menebak** (§3.5b). AutoERP
    menurunkannya dari supplier saja (`sumber_for_supplier`: punya supplier = External, tidak
    punya = Internal). `domain/ffb_source.py` mencerminkannya persis: truk ber-supplier →
    External; truk yang **sudah ada di ERP** tanpa supplier → Internal; truk tanpa supplier yang
    belum dilihat ERP → `—`. Kelima query store memakai satu `_SOURCE_FACTS`, jadi tidak ada tab
    yang berlabel beda. **Jangan** menurunkan sumber dari nama grup supplier. Grup tetap disimpan
    **mentah** di `suppliers.source_group` karena beda Plasma vs agen hidup di sana; **jangan pernah**
    bikin boolean `is_internal`.
13. **Penugasan truk: line dulu, baru dicatat.** `assign_truck` menunggu line menerima sebelum
    menyimpan. Layar yang menampilkan truk terpasang padahal line tidak tahu apa-apa membuat
    operator mengira sudah beres, dan tandan berikutnya terhitung tanpa truk.
    **Melepasnya juga harus sampai ke line** (`lepas_truk`): penugasan yang tidak pernah
    berakhir bikin tandan truk berikutnya nempel ke truk yang sudah pulang — salah yang tidak
    kelihatan salah di layar. Kontrak `/internal/assignment` beku, jadi kosong dikirim sebagai
    string kosong dan line-lah yang mengubahnya jadi `None` (`schemas/internal_schema.py`);
    `""` yang lolos apa adanya akan ditolak validasi UUID palmgrade-api.
14. **Konsol yang memanggil AutoERP; AutoERP tidak pernah memanggil ke pabrik.** PC pabrik
    tidak punya inbound sama sekali. Kontraknya `autoerp/docs/autograde-integration.md`, dan
    **per janjang tidak pernah dikirim** (§2: *"Not synced: per-bunch rows, images"*) — janjang
    dan gambar tetap di edge sebagai bukti. AutoERP menerima tiga hal saja: tarikan master data
    (§4.A), truk baru dari pabrik lewat `upsert_truck` (§4.B), dan satu pesan per kunjungan truk
    lewat `upsert_visit` (§4.C). Semua field yang diminta ke `/api/resource` harus persis milik
    DocType — Frappe membalas 417 untuk satu field asing. `ERP_URL` kosong = semua worker ERP
    mati diam-diam, dan itu default: jalur ini tidak boleh jadi syarat hidupnya layar operator.
    Kolom `inspections.erp_state` sisa jalur per janjang yang dihapus; tidak dipakai.
18. **Kunjungan truk: satu pesan, dibangun ulang tiap kali, tidak pernah ditambal** (§4.C).
    `ErpQueue` satu-satunya yang merakit pesan — pemicu langsung dan kirim ulang harian memakai
    jalan yang sama, jadi tidak bisa berbeda isi. Tiga pemicunya kejadian yang memang terjadi:
    timbang masuk, truk dilepas dari line, timbang keluar. **`stage` diturunkan dari keadaan
    kunjungan**, bukan ditentukan pemanggil. Bagian yang tidak kita punya **tidak dikirim** —
    tiap kiriman mengganti bagian yang dibawanya, jadi bagian kosong menghapus isi ERP.
    Grading ditautkan lewat `weighings.assignment_id` yang **ditulis saat truk dilepas**; tanpa
    tautan itu tiket kedua di hari yang sama mewarisi janjang tiket pertama. Kriteria: mentah =
    REJ, tangkai panjang = ACC dengan `tp_confidence > 0.8`, matang diturunkan AutoERP sendiri.
    Karena angka itu dijumlah dari `ripeness_status`, **`ripeness_status` divalidasi saat ingest**
    (`domain/vision_event.verdict_of`, satu kosakata untuk penulis dan pembaca field ini): di luar
    `{ACC, REJ}` → 400, seperti timestamp cacat. Nilai asing dulu ikut `total` tapi tidak masuk
    `acc` maupun `rej` — rekap yang dibayar tidak menjumlah, dan tidak ada yang bilang. `prediction`
    tetap dibawa apa adanya, tapi yang **bertentangan** dengan verdict-nya ikut ditolak.
    ⚠️ AutoERP **mengadopsi tiket terbuka milik truk yang sama** dalam jendela ±2 jam, jadi dua
    kunjungan truk itu di jam yang sama memang mendarat di satu tiket — itu perilaku ERP,
    bukan bug konsol. Dulu adopsi itu bisa **menimpa** bruto, jam masuk, dan nomor timbangan
    kunjungan pertama sampai netonya jadi campuran dua kunjungan; dibuktikan live 2026-09-14.
    **Sudah diperbaiki di AutoERP** (autoerp PR #7, merge 2026-09-16): kunjungan dengan
    `scale_ticket_no` berbeda tidak lagi mengadopsi tiket milik kunjungan lain. Tidak ada yang
    perlu ditambal dari sisi konsol — dulu maupun sekarang.
15. **Timbangan: `net_kg` dihitung, tidak pernah dipercaya mentah** (§3.5c). Pengirim boleh
    menyertakannya; kalau bedanya dari `bruto − tara` lewat `TOLERANSI_NETO_KG` (1 kg) kiriman
    **ditolak 400**. Ini angka yang dibayar ke petani — dua sumber kebenaran yang diam-diam
    berbeda adalah cara paling rapi untuk salah bayar berbulan-bulan.
    Timbang-masuk dan timbang-keluar adalah **dua POST untuk satu baris**, digabung lewat
    `COALESCE` per kolom: kiriman kedua yang cuma membawa tara tidak boleh menghapus bruto.
    Kuncinya `ref` kalau ada, kalau tidak uuid5 dari (plat ternormalisasi + `entered_at`) —
    tanpa salah satu dari keduanya kiriman **ditolak**, karena timbang-keluar tidak akan bisa
    menemukan barisnya dan satu tiket pecah jadi dua.
    Pemisah ribuan tanpa desimal (`"14.820"` untuk empat belas ton) parse **bersih** jadi
    14,82 dan tidak ada apa pun di payload yang membantahnya, jadi yang menangkapnya lantai
    `MINIMUM_BERAT_KG` = 100 kg pada `gross_kg`/`tare_kg` — truk kosong saja sudah berton-ton,
    berat sungguhan melewatinya dua orde besaran.
    ⚠️ Format asli program timbangan **belum diketahui** (`../docs/PERTANYAAN-TERBUKA.md` X1).
    Yang dibekukan di sini bentuk KITA; begitu formatnya turun, yang ditambah **adapter**,
    bukan bongkar tabel.
17. **Rekap: grading dan timbangan dua sumber terpisah, cuma disandingkan.** `rekap()`
    menjumlah `net_kg` per truk **di Python**, bukan mem-JOIN agregat `weighings` ke query
    GROUP BY grading: satu truk bisa punya lebih dari satu tiket sehari, dan join itu
    mengalikan jumlah janjang dengan jumlah tiket. Baris `truck_id IS NULL` **tetap
    ditampilkan** ("Tanpa truk") — janjang yang ter-grading sebelum truk dipasang justru yang
    perlu dilihat operator, bukan yang perlu disembunyikan.
16. **Truk manual naik lewat antrean; truk milik AutoERP read-only.**
    `POST /api/console/trucks` menyimpan lokal (`status='manual'`) lalu menaruh satu baris di
    `erp_outbox` (kontrak §4.B): AutoERP membuat truk **tanpa pemilik**, backoffice yang
    melengkapi supplier dan kelasnya. Id-nya uuid5 plat ternormalisasi, dan **dua ruang id itu
    sengaja bertemu** dengan ERP (aturan normalisasi sama persis), jadi truk hasil tarik
    **mengadopsi** baris yang diketik operator, bukan bikin kembar yang membelah tonase sehari.
    Tarikan tidak pernah mengosongkan `erp_name` (`COALESCE`).
    ⚠️ **Truk yang sudah punya `erp_name` tidak boleh diubah dari konsol** (kontrak §4, FE-1):
    mengetik ulang platnya mengembalikan baris apa adanya. Sebelum ini ketik ulang menghapus
    suppliernya dan diam-diam mengubah label Sumber jadi Internal — termasuk di baris grading
    yang sudah lewat, karena label dibaca dari truk, bukan disalin ke barisnya.
    ⚠️ **Yang di atas cuma berlaku untuk truk yang id-nya sudah turunan plat.** PC pabrik yang
    sudah jalan menyimpan truk ber-id **acak** dari palmgrade-api (`gen_random_uuid()`), dan
    `plate_number` **tidak punya indeks unik** — jadi di PC itu tarikan pertama tetap membuat
    baris kedua. Itu yang dibereskan **OPS-2** (`make rekonsiliasi-truk`,
    `services/rekonsiliasi.py`), dijalankan **sekali saat pasang**, sebelum `ERP_URL` diisi.
    Id acak lama tidak bisa dihitung ulang dari apa pun, jadi jembatannya cuma plat
    ternormalisasi. `pindahkan_truk` memindahkan **tiga** tabel (`inspections`, `assignments`,
    `weighings`) dalam **satu transaksi**: separuh pindah lebih buruk daripada tidak pindah,
    karena baris yang menggantung ke id terhapus hilang dari rekap — dan rekap itu yang
    dibayar. Baris berplat kosong **dilewati dan dicetak**, bukan bikin seluruh rekonsiliasi
    gagal. `trucks_semua()` dipakai, bukan `trucks()`: yang terakhir menyembunyikan baris
    `inactive`, dan baris inactive ber-id lama tetap akan kembar begitu platnya ditarik.
20. **Scan QR: isinya nomor plat, tidak lebih** (keputusan operator 2026-09-15).
    **Dua** tahap scan, dua-duanya di gerbang timbangan (masuk + keluar), karena cuma
    di situ scan menggantikan ketikan yang sungguhan ada. Tahap sortir **tidak**
    di-scan: yang tahu bak sudah kosong itu operator line, bukan supir yang datang
    membawa HP, dan tombol Lepas sudah ada di depan mata operator. Empat scan menambah
    dua langkah tanpa menambah satu data pun.
    **QR isinya cuma plat ternormalisasi** (`domain/qr.py`). Bukan seluruh data truk:
    supplier dan nama sopir berubah di ERP **sesudah** QR dicetak, jadi QR yang
    membawanya jadi bohong tanpa ada yang tahu — dan nama sopir itu data pribadi yang
    menempel di kaca truk. Bukan id truk ERP: truk **pinjaman** belum terdaftar, jadi
    belum punya id, jadi tidak bisa di-scan — padahal itu kasus yang mau dipecahkan
    (S4). Nama sopir tetap diambil, tapi dari `Truck.driver_name` di ERP, dan boleh
    ditimpa ketikan operator per kunjungan (`upsert_visit` sudah menerimanya).
    `ScanService` **cuma mencari**: tidak membuat truk (satu QR salah baca akan
    menambah truk hantu yang naik ke AutoERP lewat interface B) dan tidak menulis berat
    (dua penulis untuk angka yang dibayar adalah cara paling rapi untuk salah bayar
    berbulan-bulan). Id truknya diturunkan dari plat, **aturan yang sama** dengan
    `catat_timbangan` — kalau beda, satu kunjungan bisa mendarat di dua truk.
    **Kartu QR dibuat di server, bukan pustaka CDN** (`services/qr_cetak.py`, `segno`
    pure-Python 77 KB): `console.html` nol referensi `https://` dengan sengaja, dan QR
    yang gagal dimuat berarti gerbang timbangan berhenti. Koreksi kesalahan `m` (15%) —
    kartunya hidup di kaca truk, dan `l` (7%) terlalu tipis untuk hujan dan debu sawit.
    Kartunya **dipatok putih dengan tulisan hitam**, tidak ikut tema: QR gelap di latar
    gelap tidak terbaca scanner mana pun. Halaman cetak menunggu semua gambar dimuat
    sebelum `print()` — dialog yang muncul terlalu cepat mencetak kotak kosong, dan itu
    setumpuk kertas terbuang yang baru terlihat sesudahnya. `@media print`
    menyembunyikan kamera, tally, tab, dan tabel: tanpa itu puluhan lembar terbuang
    sebelum kartu pertama muncul.
    **Kolom scan di tab Timbangan** mengisi plat lalu memindahkan kursor ke Bruto —
    itu satu sentuhan layar yang dihemat per truk, dan itulah gunanya scan. Enter
    datang dari scanner sendiri (scanner = papan ketik), jadi tidak ada tombol; kolomnya
    juga menerima ketikan, yang membuatnya bisa dipakai sebelum scanner datang.
    `scanSibuk` menolak bacaan kedua dalam sekejap: scanner kadang membaca satu QR dua
    kali dalam beberapa ratus milidetik. **Hasil scan punya `#scan-pesan` sendiri, bukan
    banner global** — `refresh()` membersihkan banner tiap kali berhasil, jadi pesan
    scan hilang dalam 2 detik dan operator yang sedang memegang HP supir tidak pernah
    membacanya (ketemu di browser). **`BUKAN_PLAT` kode tersendiri, bukan `PLAT_KOSONG`**:
    layar menerjemahkan per kode, dan QR berisi URL yang dijawab "tidak boleh kosong"
    adalah pesan salah di depan operator gerbang.
    **Tara diisi di kolom yang muncul DI BARIS ALAT, bukan dialog yang menutup layar**
    (dua kali dilaporkan operator 2026-09-15). `prompt()` bawaan browser ditolak lebih
    dulu: kotaknya kecil untuk jempol bersarung tangan, ukurannya tidak bisa diatur, dan
    menerima teks apa pun tanpa validasi. Lalu dialog sendiri **juga** ditolak, dan
    alasannya lebih penting: lapisan yang menutup layar menghilangkan kamera line dan
    strip tally sampai tara selesai diisi, dan di gerbang yang sibuk itu kehilangan
    pandangan justru saat paling butuh. Kolomnya **tersembunyi sampai scan berhasil** -
    kolom yang bisa diisi tanpa tiket adalah kolom yang tidak tahu harus menulis ke mana.
    Platnya disebut di sebelahnya: operator melihat beberapa truk sehari sambil memegang
    HP supir. Angkanya divalidasi **di layar** sebelum dikirim, karena bolak-balik
    jaringan untuk hal yang terlihat di tempat itu satu detik yang hilang di gerbang;
    server tetap yang berwenang. Gagal kirim **tidak menutup kolomnya**: angkanya masih
    di situ, jadi bisa dibetulkan tanpa mengetik ulang. Koma diterima sebagai desimal
    (papan ketik Indonesia).
    ⚠️ **`MINIMUM_BERAT_KG` = 1 ton, bukan 100 kg.** Lantai lama meloloskan `100` persis
    (perbandingannya `<`), dan itu mendarat di layar pabrik sebagai tiket sungguhan.
    Truk teringan yang benar-benar datang sekitar 2,5 t kosong, jadi satu ton masih
    melewati setiap timbangan nyata sambil menangkap salah ketik pemisah ribuan.
    **Input manual tetap ada dan tidak boleh dihapus**: truk pinjaman, dan layar HP
    retak / gelap / kena matahari langsung adalah kasus nyata di gerbang.
19. **Login konsol: email + sandi, dua sumber akun, diverifikasi offline** (Fase 4, §6.5).
    Akun datang dari dua tempat dan barisnya menyimpan yang mana (`operators.origin`):
    `erp` ditarik dari DocType **`AutoGrade Operator`** (dibuat 2026-09-15, §4.A —
    `name, email, full_name, active, password_hash, modified`, kursor `erp_cursor_operator`),
    `lokal` ditulis `make operator` di PC itu (akun bawaan + akun support, satu-satunya cara
    membuka pabrik yang belum pernah dapat internet). **Tidak ada yang boleh menimpa milik
    yang lain**: tarikan yang meratakan akun lokal mematikan jalan masuk justru saat internet
    mati, dan CLI yang menimpa akun ERP bikin pabrik beda dengan pembukuan sampai ada yang
    sadar. `active=0` dari ERP → status `off` **dan** sesinya dihapus.
    **`password_hash` sengaja field `Data` yang bisa dibaca REST**, bukan `Password`:
    fieldtype `Password` hidup di `__Auth` yang tidak pernah dilayani REST, jadi tidak ada
    yang bisa ditarik dan login offline mustahil. Yang keluar dari ERP hash, bukan sandi.
    **Dua skema hash hidup bersebelahan**: `pbkdf2_sha256` milik passlib AutoERP (diverifikasi
    pakai `hashlib` saja — tidak ada dependensi baru di pabrik; ⚠️ passlib menulis base64
    dialeknya sendiri, `.` untuk `+` tanpa padding, dan salah decode = separuh akun ditolak
    padahal sandinya benar) dan `scrypt` untuk akun lokal. `_verify_scrypt` **hanya** menerima
    parameter yang ditulis build ini (barisnya data dan bisa diubah); rounds pbkdf2 **diikuti**
    di atas lantai minimum, karena AutoERP yang punya biaya itu dan boleh menaikkannya.
    Sesi 12 jam di `sesi`. Hitungan sandi salah di disk (lockout 5× lalu berlipat dua sampai
    15 menit), karena di memori muat-ulang halaman akan mengosongkannya. Reset sandi **dan**
    mematikan operator sama-sama menghapus sesinya — menyaring status saja akan menghidupkan
    token lama begitu akun diaktifkan lagi. Satu jawaban untuk sandi salah / akun tidak ada /
    akun mati, supaya layar bersama tidak bisa dipakai memetakan siapa yang punya akun.
    Sandi minimal 8 karakter, tanpa aturan jenis karakter (aturan yang memaksa simbol di
    layar sentuh luar ruangan berakhir jadi tulisan di monitor). **Tidak ada lane web untuk
    membuat akun**: `make operator` di PC itu sendiri, dan itu cuma mengurus akun `lokal`.
    **Dua akun bawaan di tiap image** (`services/akun_bawaan.py`, dipanggil di lifespan
    konsol): `operator@autograde.local` + `support@autograde.local`. Alasannya PC yang baru
    dipasang belum pernah dapat internet, jadi akun AutoERP belum turun — tanpa ini
    konsolnya layar terkunci di hari dia paling dibutuhkan. Email dipatok supaya support
    tidak perlu menebak; **sandi beda per PKS** (keputusan operator 2026-09-15), dibuat
    `make hash-sandi` saat pasang PC. Yang ditanam **hash** lewat build arg
    `CONSOLE_DEFAULT_HASH`/`CONSOLE_SUPPORT_HASH`, **jangan pernah sandi mentah**: PC pabrik
    bisa diakses AnyDesk dan layer image terbaca siapa pun yang pegang image. Hash yang
    tidak berawalan `$pbkdf2-sha256$`/`scrypt$` **ditolak dan di-`logger.error`** — itu yang
    menangkap `$` dimakan compose (`$$` untuk satu `$`) dan sandi mentah yang keliru
    dimasukkan. Seed **cuma bikin kalau email belum ada**: restart tidak boleh memulihkan
    sandi pabrikan di akun yang sandinya sudah diganti, dan tidak boleh menghidupkan akun
    yang sudah sengaja dimatikan.
21. **Lane developer: backend yang menjaga, layar cuma merapikan** (Task 14, 2026-09-15).
    Ketujuh `/api/console/dev/*` (tabel di atas) lewat `require_support` — itu yang
    sebenarnya menolak 403, dan tab developer yang disembunyikan dari operator biasa di
    `console.html` cuma kerapian, bukan pengaman: siapa pun yang tahu URL-nya tetap
    ditolak backend kalau `role` bukan `support`.
    **`ERP_ALLOWED_ROLES`** (bawaan `support`) membatasi role mana yang boleh datang
    dari AutoERP (`domain/role.py`, `filter_erp_role`) — **satu-satunya rem sisi
    pabrik**: kosongkan lalu restart, dan tidak ada akun ERP yang bisa membuka layar
    developer lagi, tanpa perlu menyentuh AutoERP sama sekali. Akun `lokal` (dibuat
    `make operator`) tidak lewat penyaring ini.
    **`event_log` cuma menyimpan ERROR dan WARNING**, retensi 180 hari
    (`LOG_RETENSI_HARI`). Pesan identik yang datang dalam 60 detik **digabung** jadi satu
    baris dengan hitungan naik, bukan baris baru per kejadian — tanpa itu satu loop yang
    gagal tiap detik akan memenuhi tabel dalam semenit dan mendorong keluar galat lain
    yang lebih tua. `redaksi()` (`domain/log_redaksi.py`) menyaring rahasia **sebelum**
    baris menyentuh disk, bukan saat ditampilkan: berkasnya dibaca lewat AnyDesk
    berbulan-bulan kemudian, dan sandi/token yang sempat mendarat di disk sudah bocor
    walau layarnya sendiri tidak pernah menampilkannya.
    **Uji PLC satu-satunya aksi konsol yang menggerakkan hardware fisik**, dan bawa tiga
    pengaman sekaligus: **ditolak selama line itu punya assignment** — dicek di proses
    line yang memegang `RuntimeState`-nya sendiri, **bukan** di konsol, karena konsol
    tidak pernah tahu keadaan line sebenarnya selain lewat jawabannya; **konfirmasi
    ketik**, bukan klik, karena layar sentuh bisa mendaftarkan sentuhan tak sengaja
    sebagai klik tapi tidak akan pernah mengetik kata yang benar tanpa maksud; dan
    **setiap percobaan dicatat WARNING** menyebut operator, coil, dan line — baik
    dipicu maupun ditolak — supaya ada jejak siapa menekan apa kalau ada insiden,
    ditolak atau tidak.
    **PKS tanpa satu pun akun `support` tidak bisa membuka lane developer sama sekali** —
    bukan cuma tab yang hilang, seluruh menunya buntu di 403. Lifespan konsol memeriksa
    ini saat startup dan `logger.warning` kalau kosong, supaya yang pasang PC tahu
    sebelum AnyDesk pertama yang butuh layar ini datang.
22. **Lisensi: pabrik MEMERIKSA, AutoERP yang MENERBITKAN** (2026-09-22).
    Token JWS Ed25519 dicetak DocType `AutoGrade Licence` di AutoERP (dulu
    palmgrade-api, yang mati 2026-09-20) dan dipasang teknisi dengan
    `autograde.sh licence <token>`. Repo ini **tidak berubah sedikit pun** di sisi
    verifikasi: kunci publik yang sama, `LicenseManager` yang sama, nol HTTP.
    ⚠️ **Fail closed di tiga titik**, dan ketiganya harus tetap ada: worker deteksi
    (`grading_blocked`, gerbang sesungguhnya), heartbeat PLC (`license_ok`), dan
    middleware HTTP line. Gate login saja tidak cukup — grading jalan di thread
    background yang tidak lewat HTTP, jadi dashboard mati sementara kamera tetap
    menyortir buah.
    **Konsol memverifikasi tokennya SENDIRI**, tidak bertanya ke line: konsol proses
    terpisah tapi memakai `.env` dan image yang sama, jadi sumbernya satu — dan line
    yang sedang restart tidak boleh membuat langganan terlihat rusak.
    `license/summary.py` sengaja modul sendiri dan murni (alasan yang sama dengan
    `gate.py`): aturan yang memutuskan apa yang dibaca operator saat pabrik berhenti
    harus punya test yang benar-benar jalan di CI.
    ⚠️ **Banner operator menumpang `/api/console/state`, BUKAN `/api/console/dev/*`.**
    Yang melihat kamera berhenti itu operator biasa, dan lane dev menjawab 403 untuk
    mereka — layar akan diam persis di saat penjelasan paling dibutuhkan. Yang ikut ke
    operator cuma tingkat keparahan dan tanggal; nomor token tetap support-only, dan
    ada test yang menjaganya.
    ⚠️ **Token yang tidak terbaca diperlakukan sama dengan habis.** Kebalikannya
    berarti token rusak = gratis.

23. **Rekam video developer: grading tidak pernah melambat karenanya** (2026-09-22).
    Layar **Rekam Video** (`role=support`) merekam frame kamera ke MP4, satu tombol
    per line, jalan sampai ditekan Stop. Titik sadapnya `FrameCaptureWorker` —
    **sebelum** inference — jadi yang terekam **clean tanpa bbox** tanpa kerja
    tambahan, dan itu memang yang berguna (bbox adalah prediksi model sendiri).
    ⚠️ **Encode WAJIB di thread sendiri, dan antrean penuh MEMBUANG frame.**
    `VideoRecorder.tulis()` dipanggil tiap frame dari thread capture dan harus
    kembali seketika; menahannya akan mengembalikan persis lag ~590 ms yang
    dihilangkan autograde#112. Yang dikorbankan videonya (bolong), bukan
    deteksinya — `frame_dibuang` di layar adalah alat ukurnya. Diukur 2026-09-22:
    fps deteksi **+0,1%** dengan rekaman jalan, `frame_dibuang` nol
    (`docs/runbooks/2026-09-22-ukur-biaya-encode-rekam.md`).
    ⚠️ **Recorder yang rusak tidak boleh menjatuhkan line**: panggilannya
    dibungkus `try` di capture worker. Fitur developer tidak boleh bisa
    mematikan produksi.
    **Codec `avc1` (H.264), fallback `mp4v`** — diukur 5x lebih kecil (0,48 vs
    2,40 GB/jam pada 1280x1024 @ 5 fps). Fallback-nya bukan hiasan: `avc1` tidak
    ada di setiap build OpenCV, dan `VideoWriter` yang gagal membuka **tidak
    melempar** — tanpa pemeriksaan `isOpened()` hasilnya berkas 0 byte yang baru
    ketahuan berjam-jam kemudian.
    **Setelan (resolusi/fps/bitrate) hidup di konsol**, satu baris `sync_state`,
    pola yang sama dengan `setelan_grading` — dan dikirim ulang tiap kali mulai.
    Itu yang membuat **restart container = rekaman mati** jadi sifat, bukan kode
    tambahan. Setelan baru sengaja **tidak** menyentuh rekaman yang sedang jalan:
    mengubah resolusi di tengah berkas MP4 menghasilkan berkas rusak.
    ⚠️ **`videos/` di luar `artifacts/` dan TIDAK ikut retensi otomatis.**
    `BatchUploadWorker._retention()` menyapu `artifacts/`; rekaman yang duduk di
    sana akan terhapus diam-diam di tengah penelusuran masalah. Harganya:
    berkasnya menumpuk sampai ada yang menghapusnya — karena itu layar
    mengatakannya, dan rekaman berhenti sendiri di bawah
    `UPLOAD_DISK_MIN_FREE_GB` (20 GB). Disk penuh berarti grading berhenti
    menulis, yaitu pabrik berhenti.

---

## Conventions

⚠️ **Env var proses MENANG atas `.env`.** `load_dotenv(override=False)` di
`main.py` dan `console_main.py` berarti apa pun yang sudah ada di lingkungan
tidak akan ditimpa berkas `.env`. Jadi `CAMERA_TYPE=opencv ... uvicorn ...`
mengalahkan `CAMERA_TYPE=hikrobot` di `.env`, dan itu **tidak terlihat** di mana
pun kecuali `/health/detail`. Urutannya: env var proses → `.env` → default di
`core/config.py`. Kalau bingung kenapa setelan tidak berlaku, cek env var proses
lebih dulu.

**Tiga sumber gambar, bukan dua** (`CAMERA_TYPE`): `hikrobot` (kamera GigE
pabrik), `opencv` (file video lewat `CAMERA_VIDEO_PATH`, atau webcam), `photo`
(satu gambar diam, diulang terus). Video pakai **`opencv`**, bukan `photo`.

**`docker-compose.override.yml` tidak ada di repo dan tidak wajib** — dia
`.gitignore`, berkas pribadi per mesin. Compose membacanya otomatis kalau ada dan
menimpa `docker-compose.yml`. ⚠️ **Bukan lagi cara menyetel sumber per line** — itu
sekarang layar Sumber Kamera + `media.env`. Sisakan override untuk hal lain yang
memang khas satu mesin.


- `snake_case` files/functions, `PascalCase` classes, `UPPER_SNAKE` constants (`core/constants.py`) & env vars.
- All paths via `Settings` (`core/config.py`) — never hardcode. New env var → add to `core/config.py` with a sane default.
- `CAMERA_TYPE`: `hikrobot` (prod) / `opencv` (dev: webcam or video file) / `photo` (test). Switching needs **no code edit**.
- ROI (`ROI_X1/Y1/X2/Y2`) coordinates are in **stream space** (`STREAM_WIDTH×STREAM_HEIGHT`, default 1280×720), not sensor space.
- **Garis capture (biru, bertanda `CAPTURE`) menentukan KAPAN janjang difoto; ROI menentukan DI MANA.**
  Dua hal berbeda, sengaja dipisah sejak 2026-09-18. Janjang difoto saat kotaknya **menyentuh**
  garis (`domain/garis_capture.menyentuh_garis`) — bukan lagi saat titik tengahnya masuk kotak ROI,
  yang memfoto janjang saat separuhnya sudah lewat. ROI tetap menyaring wilayah conveyor, dan `TP`
  tetap dikecualikan dari keduanya.
  **Disetel dari layar support konsol** (Setelan → Garis capture), satu angka untuk semua line,
  berlaku tanpa restart lewat `/internal/setelan` — jalur yang sama dengan `CONF_THRESHOLD` dan
  `MINIMUM_SIZE`. `GARIS_CAPTURE` di `.env` cuma nilai awal. **`0` = tidak ada garis**, dan itu
  perilaku sebelum fitur ini ada (semua janjang di dalam ROI difoto).
  ⚠️ Angkanya ruang **stream** (`STREAM_WIDTH`, bawaan 1280), diskalakan ke ruang sensor saat
  menyaring (`skala_garis_ke_frame`) — melewatkan penskalaan itu bug yang sudah pernah terjadi di
  ROI (`bdcb300`): garis terlihat benar di layar sementara yang menyaring sepertiga frame.
  Kalau capture terasa terlalu cepat, **geser garisnya**, jangan sentuh `CONF_THRESHOLD`.
  **Janjang difoto APA ADANYA begitu menyentuh garis**, ada TP atau tidak (keputusan operator
  2026-09-18): tidak ada penundaan, tidak ada jendela tunggu. Yang menggerakkan mesin (pulse
  PLC) dan yang dilihat operator sama-sama seketika.
  **Arah conveyor** ikut disetel di layar yang sama (`sumbu_garis`): `tegak` = conveyor
  mendatar, garis vertikal, angka px dari **kiri**; `mendatar` = conveyor menurun, garis
  horizontal, angka px dari **atas**. Arah gerak DI DALAM satu sumbu tidak perlu disetel —
  pemicunya perpotongan, jadi conveyor yang membalik arah tetap jalan. ⚠️ Sumbu mendatar
  diskalakan dengan **tinggi** frame, bukan lebar (`skala_garis`): frame 2448x2048 tidak
  persegi, jadi memakai lebar meleset ~19% tanpa satu pun error.
- **Label janjang tidak memuat angka confidence** (permintaan operator 2026-09-18): dari beberapa
  meter "54%" terbaca seperti "54% matang", padahal itu keyakinan model dan sudah lolos
  `CONF_THRESHOLD`. Nilainya tetap ditulis ke sidecar dan dikirim ke API.
  **Saklar `mode_dev`** di layar setelan menghidupkannya lagi — untuk support yang sedang
  menyetel ambang, bukan untuk operator. Bawaannya mati.
- **Frame rate hidup di SATU tempat: `config/camera/hikrobot.mfs`.** File itu dikirim ke
  kamera tiap connect, lalu `FrameCaptureWorker.adopt_camera_frame_rate()` menanyakan
  balik laju sebenarnya (`ResultingFrameRate`) dan memakai itu sebagai jeda ambil frame.
  `CAMERA_FPS` **cuma cadangan** untuk sumber yang tidak bisa melapor (webcam, file video).
  Dulu keduanya hidup bersama dan yang lebih kecil menang — menurunkan `.mfs` terasa
  bekerja, menaikkannya tidak, dan itu terbaca berbulan-bulan sebagai "`CAMERA_FPS` mandul".

---

## Git Workflow

- **Judul dan isi PR wajib bahasa Inggris** (sejak 2026-09-12). Format ada di
  `.github/pull_request_template.md`; judul `<type>(<scope>): <ringkas>`.
  Pesan commit boleh tetap Indonesia — yang dibaca ulang berbulan-bulan kemudian
  itu PR-nya, dan sesi MacBook ikut membacanya.
- Default branch `staging`; **PR-only** (main & staging protected). Alur rilis:
  branch baru dari `staging` → PR **squash merge** ke `staging` → PR **merge commit** ke `main`.
  Rilis ke `main` sengaja BUKAN squash: `main` harus menyimpan tiap PR staging sebagai
  commit tersendiri. Karena itu `main` selalu punya merge commit yang tidak ada di
  `staging` — itu normal, bukan divergensi. Cek isinya dengan
  `git diff --stat origin/staging origin/main` (kosong = nol beda), jangan `git cherry`.
- Commit messages: **never** include "Co-Authored-By: Claude" or any AI reference.

---

## Pointers

- **`docs/MANUAL.md`** — manual untuk orang yang ikut memegang AutoGrade: cara pakai konsol, fitur, setup dari nol (laptop + PC pabrik), operasional, troubleshooting, aturan. PDF-nya dibuat sama seperti ONBOARDING (`scripts/md_to_pdf.py docs/MANUAL.md`, diagram di `docs/assets/manual/`). Skill ringkasnya `.claude/skills/panduan-autograde/` (juga tersambung di `.agents/skills/` untuk Codex).
- **`docs/ONBOARDING.md`** — titik masuk buat orang/agent baru: sistem ini ngapain, perjalanan satu janjang, fungsi tiap folder, jebakan, kamus istilah. PDF resminya `docs/ONBOARDING.pdf` — jangan diedit langsung: ubah `.md`-nya lalu `scripts/md_to_pdf.py docs/ONBOARDING.md` (butuh Chrome + `pip install markdown pypdf`). Blok ```` ```diagram:<nama> ```` di `.md` sengaja tetap ASCII untuk pembaca teks; PDF menukarnya dengan `docs/assets/onboarding/<nama>.svg`, jadi ubah keduanya bersamaan.
- **`docs/overview.md`** — deep flows, ASCII diagrams, all invariants with rationale, worker/state model, Docker/SDK/GPU internals, prod deployment checklist, edge cases.
- `docs/architecture.md` — layer boundaries (final design; don't change without discussion).
- `docs/backend-overview.md` — full endpoint + event + env-var tables.
- `docs/plc-integration.md` — referensi teknis PLC (env vars, pulse, throughput, commissioning); `docs/plc-mc-handoff.md` — dokumen tim PLC, peta alamat M final (Ocit 2026-09-23); skill `plc-mc-protocol`.
- `docs/SETUP.md` — from-zero prod setup (NVIDIA toolkit, MVS, camera IP, Docker build).
- `../ARCHITECTURE.md` — 3-repo system architecture.
