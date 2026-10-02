# Commands: run, build, test (full table)

Moved verbatim from `CLAUDE.md` on 2026-09-30. `CLAUDE.md` §2 keeps the short list.

## Run / Build / Test

All via **`make`** (Docker only). From `autograde/`:

| Cmd | What |
|---|---|
| `make up` | prod: copy MVS SDK + build GPU (`cu126`) + build TensorRT engine + start 3 lines |
| `make up-dev` | dev: build CPU (no SDK) + start 3 lines |
| `make restart` | **code-only change**: kode di-bind-mount (`.:/app`), jadi **tidak perlu rebuild** |
| `make start` / `make up-1\|2\|3` | start without rebuild (all / single line) |
| `make up-console` / `make logs-console` | konsol operator saja (port 8000, `/console`): aman di-restart tanpa mengganggu line |
| `make line` | satu line kamera **native tanpa Docker**, pasangan `make console` untuk develop di Mac (`make up` tidak bisa: butuh MVS SDK + CUDA + TensorRT). `make line N=2` untuk line kedua: **port DAN `MACHINE_ID` ikut berubah bersama**, karena konsol mencocokkan event lewat `machine_id`, bukan port: tiga line yang memakai `MACHINE_ID` sama dari `.env` semuanya mendarat di kartu line-1. **Sumber gambar dibaca dari `media.env`** (`LINE_N_CAMERA_TYPE`/`MEDIA_FILE`/`VIDEO_LOOP`), berkas yang ditulis layar Sumber Kamera, jadi pilihan per-line di layar berlaku di jalur native juga, bukan cuma di Docker. Tanpa `media.env` tidak ada yang ditimpa dan `.env` lama tetap jalan. **Target ini BERPUTAR sampai Ctrl-C**, meniru `restart: unless-stopped` Docker: layar merestart line dengan menyuruh prosesnya keluar, dan tanpa loop itu Simpan & Restart mematikan line tanpa pernah menghidupkannya (layar bilang tersimpan, kartu jadi OFFLINE, nol galat). `media.env` dibaca **ulang tiap putaran** (setelan baru itulah alasan prosesnya keluar. Yang ditimpa target ini juga `MACHINE_ID`, `BACKEND_URL` (ke `make console`, bukan port Docker 8000 di `.env`) tanpa itu janjangnya tersimpan tapi tiap kiriman dibalas **404** dan layar tetap nol, dan **`STATE_DIR`** ke `state/line-N` sendiri: tanpa itu tiap line native berbagi satu `outbox.db` dengan yang lain) |
| `make console` | konsol **native tanpa Docker** di `127.0.0.1:8100`, jalur develop di Mac (baca `.env`, `WEBHOOK_SECRET=devsecret`); target Docker tetap jalur Linux/pabrik |
| `make kiosk` | konsol layar penuh di PC ini (`scripts/console-kiosk.sh`) |
| `make operator` | akun **lokal** untuk login konsol: tambah / reset sandi (email + sandi). `AKSI=daftar\|matikan`. Akun milik AutoERP diurus di AutoERP. Di PC pabrik pakai `make operator-docker` (konsolnya di Docker, DB-nya beda berkas). Sejak 2026-09-26 hal yang sama bisa dari layar: tab **Akun** (support), aturan 19 |
| `make demo` | **data demo untuk showcase**: 10 truk, seminggu kunjungan, ratusan janjang, dua akun (`operator@`/`support@demo.autoerp.test`, sandi `sawit2026`). `HARI=3` memperpendek. Platnya **sama persis** dengan seeder AutoERP (`palm_mill/demo.py`): satu truk = truk yang sama di dua layar. Menolak DB yang sudah punya data sungguhan. Di Docker: `make demo-docker`. ⚠️ jangan di PC pabrik |
| `make demo-reset` | hapus data demo lalu isi ulang bersih (`AKSI=reset` juga masih jalan, ini cuma nama yang dipakai sekarang, sama seperti AutoERP) |
| `make demo-off` | hapus data demo (sepuluh plat `PLATES`) dan **berhenti** di situ, beda dari `demo-reset` yang langsung mengisi ulang. Data sungguhan tidak disentuh (`wipe()` menyaring per plat). Jalankan sesudah showcase, **sebelum** uji coba sungguhan: janjang demo berstempel sampai mendekati jam sekarang, jadi selama masih ada dia menutupi baris yang baru digrading. AutoERP punya perintah nama sama (`make demo`/`demo-reset`/`demo-off`) |
| `make hash-sandi` | hash untuk dua akun bawaan image (`CONSOLE_DEFAULT_HASH`/`CONSOLE_SUPPORT_HASH`). Dipakai saat pasang PC pabrik, sandi mentah tidak pernah ditanam |
| `make rekonsiliasi-truk` | **OPS-2**, sekali saat pasang di PC yang **sudah** punya data palmgrade-api: satukan truk kembar. Tanpa `TULIS=1` cuma melihat. `--db <path>` untuk mencoba di salinan. Di Docker: `make rekonsiliasi-truk-docker`. PC baru (DB kosong) tidak perlu |
| `make build-engine` | build TensorRT FP16 engine **once per GPU** (one-shot, auto-skip kalau sudah ada) |
| `make browser-siap` | pasang Playwright dan dua browser (Chromium, Firefox) untuk tes browser, sekali per mesin |
| `make test-browser` | tes browser: konsol asli dari salinan kode di port acak, line palsu, data demo 10 hari; `BROWSER=firefox` untuk satu browser. Tidak menyentuh konsol, line, `.env` atau `state/` milik developer |
| `make logs` / `make logs-1` | tail logs (combined / per line) |
| `make reset-data` | **lihat dulu**: berapa foto dan basis data yang akan hilang. Tidak menghapus apa pun |
| `make reset-data-fresh` | Dari layar tanpa terminal: **Setelan → Danger Zone** (support; aturan 25). Tombol itu menyisakan setelan grading dan `license.db`, dan menolak saat ada line mati / truk terpasang / truk belum timbang keluar / antrean belum terkirim. Target ini sendiri: **HAPUS SEMUA DATA** di PC ini: isi `artifacts/` (foto + sidecar) dan `state/` (semua SQLite). Minta **konfirmasi ketik `HAPUS`**. ⚠️ Menghapus lewat **container**, karena berkasnya **milik root** di Linux (`Dockerfile` tanpa `USER`): `rm -rf` dari user biasa dijawab "Permission denied" ribuan kali. Di macOS ini tidak terlihat: Docker Desktop memetakan pemilik, jadi gagalnya cuma muncul di PC pabrik. Sisa yang tidak terhapus dilaporkan, bukan didiamkan. **Tanpa backup, tidak bisa dikembalikan.** ⚠️ Akun lokal (buatan `make operator` atau tab Akun), antrean yang belum terkirim, dan foto yang belum naik R2 ikut hilang; **dua akun bawaan image dibuat ulang sendiri** saat konsol start, jadi cukup `make start` sesudahnya. ⚠️ Jangan di PC pabrik yang sedang produksi |
| `make down` / `make ps` / `make rebuild` / `make rebuild-clean` / `make clean` | stop / status / rebuild / clean rebuild (`--no-cache`) / cleanup |

- **TensorRT (GPU speedup, akurasi sama)**: engine FP16 (`engines/<model>.sm<cc>.engine`) **hardware-locked** (compute capability + versi TensorRT) → tidak di-commit, tidak di-bake ke image, dibangun **sekali per GPU** on-machine via `make build-engine` (~5–15 mnt, tidak butuh kamera). Engine tidak ada / tidak cocok → runtime **fallback ke `.pt`** otomatis (`pipelines/model_registry.py`), jadi kegagalan build bukan outage. Install TensorRT-nya ikut `Dockerfile` (`pypi.nvidia.com`: **wajib**, index PyPI publik cuma punya source stub yang bikin pip hang). Detail: `docs/overview.md` § Docker/SDK/GPU.
- **`make up` cuma perlu** kalau dependency / `Dockerfile` / SDK berubah; untuk ubah kode pakai `make restart`.
- **Dev without a camera, pilih dari layar, per line**: konsol → login **support** → tab
  **Line → Sumber Kamera**. Taruh berkas di `media/` (host), pilih Video/Foto untuk line yang mau
  diganti, Simpan. Tiap line berdiri sendiri: line 1 boleh video sementara line 2–3 tetap
  kamera. Setelannya mendarat di **`media.env`** (di-`.gitignore`, keadaan per-mesin;
  `make` membuatnya dari `media.env.example` kalau belum ada). Cara pakainya:
  `docs/runbooks/2026-09-21-sumber-kamera-per-line.md`.
  ⚠️ **`media.env` wajib lewat `--env-file`, bukan `env_file:`**, Compose menyelesaikan
  `${LINE_1_CAMERA_TYPE}` dari shell + `--env-file` saja, sementara `env_file:` menyuntik
  environment container **sesudah** interpolasi. Dengan `env_file:` ketiga line selalu
  `hikrobot` tanpa satu pun error. `Makefile` sudah membawa kedua flag lewat `$(COMPOSE)`;
  pemanggil di luar Makefile harus membawanya sendiri.
  ⚠️ **Jalur lama sudah tidak ada**: mount `/videos` dicabut, dan `CAMERA_VIDEO_PATH` +
  `docker-compose.override.yml` bukan lagi cara menyetel video per line.
- **Model per line: juga dari layar** (sejak 2026-09-24): konsol → **support** → tab
  **Line → Model Deteksi**. Menulis `LINE_N_MODEL_FILE` ke `media.env` yang sama; kosong = `MODEL_FILE`
  di `.env` (bawaan PC). Layar menampilkan kelas tiap model (dibaca **tanpa torch**,
  `services/model_library.py`), status engine per GPU, dan model yang **benar-benar** dimuat
  tiap line (`/health/detail` → `model_file`/`model_backend`/`model_kelas`/`model_kelas_cocok`,
  yang terakhir `false` = line tidak menghitung, ditulis merah; plus `gpu_sm` supaya layar tahu
  engine mana yang cocok dengan GPU line). Model yang kelasnya
  bukan tepat `Ripe/Unripe/JK/TP` **tidak bisa dipilih** (400 di server). Simpan lewat modal
  konfirmasi, lalu cuma line yang berubah yang restart. ⚠️ Konsol butuh mount
  `./models:/app/models:ro` + `./engines:/app/engines:ro`: sudah di kedua compose repo, tapi
  compose di PC pabrik hidup di host dan harus ditambah tangan. Engine dibangun per model lewat
  service line yang memakainya (`run ... ripe-line-N scripts/build_engine.py`).
  Runbook: `docs/runbooks/2026-09-24-model-deteksi-per-line.md`.
- **Verify**: `curl :8001/health`; **503 selama AI mati (sejak batch 2.1) atau frame berhenti (sejak batch 3.6)**, badan jawabannya menyebut yang mana (`ai.keadaan`, `ai.kode`). `curl :8001/health/detail` (camera_connected, gpu_available, workers, current_assignment_id, `plc` = `null` kalau PLC mati); stream at `http://localhost:8001/api/video_feed`.
  ⚠️ **`capture_save_dropped` di `/health/detail` harus NOL.** Di atas nol berarti antrean penulis
  pernah penuh dan janjang yang sudah digrading, sudah dapat pulse PLC, sudah masuk rekap,
  tidak tersimpan sama sekali: tidak ada gambar, tidak ada sidecar, jadi tidak ada yang bisa
  ditemukan `BatchUploadWorker._scan()` belakangan. Tidak ada retry (menahan deteksi akan
  mengembalikan lag ~590 ms yang dihilangkan); yang harus dikejar penyebabnya: disk lambat atau
  laju grading melewati kemampuan menulis. `capture_save_pending` yang naik terus adalah
  peringatan dininya.
  ⚠️ `outbox_pending`/`outbox_failed` di `/health/detail` mengukur **jalur realtime ke API lokal**
  saja. `outbox_pending` = semua janjang yang belum sampai ke konsol (`COUNT(*)`), termasuk baris
  yang versi lama pernah menyerah dan sekarang dicoba lagi (aturan 31). `outbox_failed` tetap ada
  di bentuk jawaban tapi **selalu 0 sejak batch 2.4**: antrean ini tidak punya batas nyerah lagi.
  Angka `outbox_pending` naik terus = konsol tidak menjawab (cek `BACKEND_URL`); rinciannya
  (per line: menunggu, umur tertua, keadaan sambungan) ada di tab **Status → Antrean line**, bukan
  di sini. Angka itu **tidak** mengatakan apa-apa soal batch upload ke cloud, untuk itu baca log
  `Batch tick: N item eligible` dari `BatchUploadWorker` atau query `state/upload_manifest.db`
  langsung.
- **Tests / CI**: `tests/unit/` = unit test murni-logic (`rules`, `outbox_store`, `event_id` uuid5, streaming keep-alive, config validation, **license**: JWS Ed25519 verify + state machine + SQLite hash-chain, **konsol**: `work_date` lewat tengah malam + `console_store` + invarian `console.html` + **timbangan**: neto dihitung bukan dipercaya + timbang-keluar menggabung bukan menimpa + plat beda tulisan tetap satu truk, **master data dari AutoERP**: field yang diminta persis milik DocType (ERP palsu membalas 417 seperti Frappe) + Sumber TBS mengikuti `sumber_for_supplier` + grup supplier disimpan mentah + truk ERP mengadopsi baris truk manual, **antrean ke AutoERP**: ditolak vs tidak terjangkau dibedakan + backoff 30 dtk→1 jam + pesan yang diganti saat masih di jalan tidak ditandai terkirim + truk manual masuk antrean + truk milik ERP read-only, **kunjungan truk**: bentuk pesan §4.C + `stage` diturunkan dari keadaan + bagian kosong tidak dikirim + grading ikut lewat tautan assignment + kirim ulang harian sekali sehari + `erp_name` tidak terhapus saat plat diketik ulang + kursor per-DocType tidak maju kalau ada baris gagal, **thumbnail + manifest kunjungan** (sejak 2026-09-16): varian `thumb` di `capture_layout` (twins/pasangan/kunci R2) + thumbnail 400px ditulis di `capture_writer` tanpa menggagalkan capture + `batch_upload_worker` ikut mengunggah dan menghapus thumbnail + `UPLOAD_API_URL` kosong = item `done` begitu foto sampai + bentuk JSON `visit_manifest` (murni, tanpa I/O) + `console_store.bunches_for_assignment` urut waktu + `visit_manifest_worker` (antrean sendiri, viewer diunggah sekali per proses, R2 mati menahan baris) + `detail_url` terkirim hanya kalau R2 terkonfigurasi + invarian statis `viewer.html` (nol dependensi eksternal, baca manifest relatif), **janjang susulan** (batch 2.3, AutoERP palsu `tests/autoerp_palsu.py` dengan aturan finalisasi `upsert_visit`): requeue cuma pada insert sungguhan + tiket final ditandai `erp_perlu_dicek` + WARNING sekali per catatan berbeda, dan **query konsol berindeks** (`tests/rencana_query.py`, `EXPLAIN QUERY PLAN` sebelum/sesudah tiap query `ConsoleStore` + `ErpOutboxStore`)), jalan tanpa torch/cv2/SDK via **`pytest`** (config di `pyproject.toml`, `pythonpath=src`; async pakai `asyncio.run`, **bukan** pytest-asyncio). CI memasang `requirements-ci.txt`: paket ringan tanpa torch/SDK, **semua dikunci `==` ke versi yang sama dengan `requirements.txt`** (sejak batch 4.4, dijaga `tests/unit/test_requirements_ci_terkunci.py`; menaikkan versi = ubah dua berkas di PR yang sama), termasuk `pymcprotocol` + `pymodbus` supaya `tests/e2e/test_mc_protocol_lane.py` ikut jalan. Samakan venv lokal: `.venv/bin/pip install -r requirements-ci.txt`.
⚠️ **`load_dotenv()` naik dari folder kode sampai ketemu `.env` pertama** (`find_dotenv()`), jadi
di **worktree** itu bukan `.env` worktree ini, tapi `.env` checkout utama: dua test yang lulus
sendirian tapi merah bersamaan adalah gejalanya, bukan test yang rapuh. `tests/conftest.py`
membersihkan kunci di SEMUA `.env` sepanjang jalur itu (`tests/dotenv_mesin.py`), bukan cuma
`<repo>/.env`. Lint via **`ruff check src/ tests/`** (seluruh kode sejak batch 4.4; ruff tidak mengimpor modul, jadi yang butuh torch/SDK tetap dilint). Semua jalan otomatis di **`.github/workflows/ci.yml`** tiap PR/push ke `staging`/`main` (runner ringan, tanpa GPU). `tests/integration/` = beberapa komponen SUNGGUHAN dirangkai tanpa Docker/hardware (konsol ↔ line lewat transport ASGI, berkas di folder sementara, render layar lewat node), jalan di CI sebagai langkah sendiri (`pytest tests/integration/ -rs`). Yang butuh kamera/GPU/Docker tetap di luar CI. **Nambah test → utamakan logic murni; jangan seret hardware, torch, atau cv2 ke CI.** FastAPI `TestClient` boleh, tapi hanya untuk hal yang memang cuma ada di lapisan HTTP (penjaga sesi): app-nya dirakit sendiri di test dengan dependensi di-override, **bukan** `create_console_app()`, yang itu menyentuh `state/console.db` milik developer.
- **Langkah CI tambahan (sejak batch 3)**: `python tests/cek_skrip_konsol.py src/palmgrade/static/console.html` mem-parse SEMUA blok `<script>` konsol seperti browser (salah ketik di luar fungsi yang diuji tetap bikin CI merah); `pytest tests/unit/ -rs` menampilkan alasan tiap skip; import yang hilang di `main.py` (berkas yang dipakai tiap line saat boot) tertangkap ruff seluruh `src/` (aturan F821). Tag rilis `vX.Y.Z`: `deploy.yml` memanggil `ci.yml` dulu pada commit yang di-tag; image pabrik dan image demo `-cpu` baru dibangun sesudah CI hijau (CI merah = tidak ada image, nomor versi itu hangus). Sejak batch 4.2 image itu mula-mula cuma `candidate-vX.Y.Z`; tag rilis + `latest` ditulis sesudah `image-smoke.yml` lulus (`scripts/smoke_image.py`, rincian `docs/rules.md`).
- From-zero prod setup (NVIDIA toolkit, MVS install, camera IP): `docs/SETUP.md`.

---

