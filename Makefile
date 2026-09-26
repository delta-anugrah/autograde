ENV_FILE=.env
# Production override: immutable image (no bind-mount of .:/app & /videos).
PROD_FILES=-f docker-compose.yml -f docker-compose.prod.yml

# Sumber kamera per line. `media.env` WAJIB lewat `--env-file`, tidak bisa lewat
# `env_file:` di compose: Compose menyelesaikan `${LINE_1_CAMERA_TYPE}` dari
# environment shell + berkas `--env-file` SAJA, sementara `env_file:` menyuntik
# environment container SESUDAH interpolasi selesai. Dengan `env_file:` seluruh
# fitur ini mati diam-diam — `docker compose config` menjawab `hikrobot` untuk
# ketiga line betapapun benar isi `media.env`.
#
# Dua flag, bukan satu: `--env-file` yang kedua MENAMBAH, tidak menggantikan,
# jadi `.env` tetap terbaca dan `media.env` cuma menimpa kunci `LINE_*_` miliknya.
MEDIA_ENV=media.env

# ⚠️ Compose menolak `--env-file` yang berkasnya tidak ada — persis seperti
# `env_file:`. `media.env` itu keadaan per-mesin dan sengaja di-`.gitignore`,
# jadi clone bersih dan PC pabrik yang baru `git pull` TIDAK punya berkas itu,
# dan tanpa penjaga ini `make up` / `restart` / `logs` / `down` semuanya mati
# dengan "env file not found". Dibuat dari contohnya (ketiga line `hikrobot`,
# bawaan yang benar untuk pabrik) supaya nol langkah manual.
#
# Order-only prerequisite (`| $(MEDIA_ENV)`) tidak dipakai: yang perlu dijamin
# cuma "berkasnya ada", bukan urutan build, dan target-target di bawah ini sudah
# terlanjur banyak. Satu baris `@test -f || cp` di `$(COMPOSE)` menjangkau
# SEMUA pemanggil sekaligus, termasuk yang ditambah nanti.
COMPOSE = $(shell test -f $(MEDIA_ENV) || cp media.env.example $(MEDIA_ENV)) \
	docker compose --env-file $(ENV_FILE) --env-file $(MEDIA_ENV)
COMPOSE_PROD = $(shell test -f $(MEDIA_ENV) || cp media.env.example $(MEDIA_ENV)) \
	docker compose $(PROD_FILES) --env-file $(ENV_FILE) --env-file $(MEDIA_ENV)

# Production — copy SDK, build GPU+SDK, build the TensorRT engine, start all lines.
# NOTE: for CODE changes alone `make restart` is enough — code is bind-mounted
# (.:/app), so NO rebuild is needed. `make up` is only for dependency /
# Dockerfile / SDK changes.
up: sync-sdk
	-$(COMPOSE) down
	$(COMPOSE) build \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true
	$(MAKE) build-engine
	$(COMPOSE) up -d
	-docker image prune -f

# Production IMMUTABLE — like `up` but with the docker-compose.prod.yml override,
# which REMOVES the .:/app & /videos bind-mounts, so containers run from the built
# image, not the working tree. Use this on the prod PC. Since code is NOT mounted,
# a code change in prod needs `make up-prod` again, not `make restart`.
up-prod: sync-sdk
	-$(COMPOSE_PROD) down
	$(COMPOSE_PROD) build \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true
	$(COMPOSE_PROD) up -d
	-docker image prune -f

# Copy the Hikrobot MVS SDK from the host into the build context. The SDK is
# committed now (so CI can build the image), so this is only needed when the
# host's MVS version changes. Both sources end in `/.`: without it, `cp -r` into
# a folder that ALREADY exists (and sdk/MvImport always does now) makes a nested
# sdk/MvImport/MvImport copy that ends up in the image.
sync-sdk:
	@test -d /opt/MVS || (echo "ERROR: Hikrobot MVS SDK not found at /opt/MVS. Install MVS first." && exit 1)
	mkdir -p sdk/lib64 sdk/MvImport
	cp -r /opt/MVS/lib/64/. sdk/lib64/
	cp -r /opt/MVS/Samples/64/Python/MvImport/. sdk/MvImport/

# Build the TensorRT FP16 engine ONCE per GPU (auto-skips if this GPU already has
# one). Runs as a single one-shot container → no race between the 3 lines.
# First run per PC takes 5-15 min; after that it is instant (cached in ./engines).
build-engine:
	$(COMPOSE) run --rm --no-deps \
		--entrypoint python ripe-line-1 scripts/build_engine.py

# Full clean rebuild (use ONLY when the cache is suspect — slow, no-cache).
rebuild-clean: sync-sdk
	-$(COMPOSE) down
	-docker image rm palmgrade-vision:latest 2>/dev/null || true
	$(COMPOSE) build --no-cache \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true

# Development — build without the SDK, CPU torch, then start all lines
up-dev:
	$(COMPOSE) build \
		--build-arg TORCH_VARIANT=cpu
	$(COMPOSE) up -d

# Start all lines without rebuilding (uses the existing image)
start:
	$(COMPOSE) up -d

# Start just one line, no rebuild
up-1:
	$(COMPOSE) up -d ripe-line-1

up-2:
	$(COMPOSE) up -d ripe-line-2

up-3:
	$(COMPOSE) up -d ripe-line-3

# Operator console only (APP_MODE=console, port 8000) — screen at /console.
# No camera/GPU, so it is safe to restart on its own without touching the lines.
up-console:
	$(COMPOSE) up -d console

# Operator console WITHOUT Docker — the development path on a Mac, where the
# Docker targets cannot run (no MVS SDK, no NVIDIA GPU, host networking).
# Port 8100 because a local AutoERP bench owns 8000. Settings come from .env
# (console_main.py loads it); only WEBHOOK_SECRET is forced to the dev value the
# seed script and E2E tests use. Override: make console CONSOLE_PORT=8200
#
# ⚠️ `MEDIA_DIR`/`MEDIA_ENV_PATH` WAJIB ditimpa di sini. Bawaannya `/media` dan
# `/config/media.env` — path DI DALAM container, yang di compose datang dari
# mount `./media:/media`. Tanpa mount itu (jalur native ini) keduanya menunjuk
# folder yang tidak ada di macOS, dan `MediaLibrary` memulangkan daftar KOSONG
# tanpa satu pun galat (folder hilang = kosong, itu memang perilakunya). Layar
# Sumber Kamera lalu bilang "belum ada berkas" walau `media/` di repo berisi —
# terbaca seperti fitur rusak, padahal cuma menatap folder yang salah.
CONSOLE_PORT ?= 8100
DEV_WEBHOOK_SECRET ?= devsecret
console:
	WEBHOOK_SECRET=$(DEV_WEBHOOK_SECRET) \
	MEDIA_DIR=$(CURDIR)/media MEDIA_ENV_PATH=$(CURDIR)/$(MEDIA_ENV) \
	PYTHONPATH=src .venv/bin/uvicorn \
		palmgrade.console_main:app --host 127.0.0.1 --port $(CONSOLE_PORT)

# Satu line kamera NATIVE tanpa Docker — pasangan `make console` untuk develop di
# Mac, di mana `make up` memang tidak bisa jalan (butuh MVS SDK, CUDA cu126, dan
# TensorRT; ketiganya Linux + GPU NVIDIA).
#
# Sumber gambarnya dibaca dari `.env` APA ADANYA — target ini sengaja tidak
# menyetel CAMERA_TYPE sendiri. ⚠️ Ini BEDA dengan jalur Docker (make up /
# up-dev / prod pabrik), yang sumbernya diatur per line dari layar Support
# lewat `media.env` — `make line` TIDAK membaca `media.env` sama sekali.
# Setel di `.env`:
#   CAMERA_TYPE=opencv + CAMERA_VIDEO_PATH=/path/video.mp4   -> file video
#   CAMERA_TYPE=photo  + CAMERA_PHOTO_PATH=images/x.jpg      -> satu gambar
#   CAMERA_TYPE=hikrobot                                     -> kamera pabrik
#
# Portnya 8001 dan itu TIDAK boleh diubah sembarangan: konsol mencari line-1 di
# 8001 (`core/config.py` _CONSOLE_LINE_DEFAULTS, dipatok di kode). Line di port
# lain akan menggrading dengan benar tapi kartunya tetap "Kamera tidak tersambung".
# N=1|2|3 memilih line mana yang dijalankan. Port DAN machine id ikut berubah
# bersama: konsol mencocokkan event ke line lewat `machine_id` (bukan port), jadi
# tiga line yang memakai MACHINE_ID sama dari `.env` akan semuanya mendarat di
# kartu line-1 dan dua kartu lain tetap kosong.
# UUID-nya sama persis dengan fallback docker-compose, supaya line native dan
# line Docker menunjuk baris `machines` yang sama.
N ?= 1
LINE_PORT ?= 800$(N)
LINE_1_ID ?= d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01
LINE_2_ID ?= a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02
LINE_3_ID ?= ad5f7bb9-c06d-4e87-8282-ce450ae331ec

# Sumber kamera line ini, dibaca dari `media.env` — berkas yang ditulis layar
# Sumber Kamera di konsol. Di Docker, compose yang meneruskan `LINE_N_*` lewat
# `--env-file`; jalur native tidak lewat compose sama sekali, jadi tanpa itu
# `make line` jatuh ke `CAMERA_TYPE` di `.env` — SATU nilai untuk ketiga line,
# dan pilihan per-line di layar diam-diam tidak berlaku. Gejalanya: pilih Foto
# di Line 2, jalankan `make line N=2`, yang muncul video dari `.env`. Nol galat,
# karena `.env` memang berisi setelan yang sah.
#
# Pembacaannya ada DI DALAM resep `line`, bukan di sini sebagai variabel make:
# resep itu berputar, dan tiap putaran harus membaca ulang berkasnya — setelan
# baru itulah alasan line-nya keluar.
LINE_ID = $(LINE_$(N)_ID)
# ARTIFACTS_DIR dipisah per line, meniru volume compose
# (`./artifacts/line-N:/app/artifacts`). Tanpa ini tiga line native menulis ke
# satu folder yang sama, sementara konsol menyajikan `/captures/{line_code}` dari
# `artifacts/{line_code}` — gambarnya tersimpan tapi tiap tautan dijawab 404.
#
# BACKEND_URL ikut diarahkan ke `make console` (127.0.0.1:$(CONSOLE_PORT)), bukan
# dibiarkan memakai nilai `.env`. Alasannya: `.env` menunjuk port Docker (8000)
# karena di pabrik konsol memang di situ, sedangkan `make console` jalan di 8100.
# Tanpa ini janjangnya TERSIMPAN di disk tapi tiap kiriman dibalas 404 — layar
# tetap nol dan yang terlihat cuma baris "Outbox delivery failed ... HTTP 404"
# di log line, jauh dari layar yang sedang ditonton.
# ⚠️ Berputar sampai Ctrl-C, meniru `restart: unless-stopped` milik Docker.
# Layar Sumber Kamera merestart line dengan menyuruh prosesnya KELUAR
# (`POST /internal/restart`) — di pabrik Docker yang menyalakannya lagi dengan
# environment yang dibaca ulang. Jalur native tidak punya siapa-siapa, jadi
# tanpa loop ini "Simpan & Restart" mematikan line dan tidak pernah
# menghidupkannya: layar bilang tersimpan, kartunya berubah OFFLINE, dan
# tidak ada satu pun galat yang menjelaskan.
#
# `media.env` dibaca ULANG di tiap putaran, bukan dipakai dari variabel make
# yang dihitung sekali saat start — justru setelan BARU itu alasan line-nya
# keluar. Keluar bersih (exit 0) tetap berputar; Ctrl-C (130) dan kegagalan
# start (mis. berkas media rusak) berhenti, supaya salah setelan tidak jadi
# loop gagal-nyala yang memenuhi layar.
line:
	@while true; do \
		TYPE=$$(sed -n 's/^LINE_$(N)_CAMERA_TYPE=//p' $(MEDIA_ENV) 2>/dev/null); \
		FILE=$$(sed -n 's/^LINE_$(N)_MEDIA_FILE=//p' $(MEDIA_ENV) 2>/dev/null); \
		LOOP=$$(sed -n 's/^LINE_$(N)_VIDEO_LOOP=//p' $(MEDIA_ENV) 2>/dev/null); \
		env WEBHOOK_SECRET=$(DEV_WEBHOOK_SECRET) MACHINE_ID=$(LINE_ID) \
			BACKEND_URL=http://127.0.0.1:$(CONSOLE_PORT) \
			ARTIFACTS_DIR=$(CURDIR)/artifacts/line-$(N) \
			MEDIA_DIR=$(CURDIR)/media \
			$${TYPE:+CAMERA_TYPE=$$TYPE} \
			$${TYPE:+MEDIA_FILE=$$FILE} \
			$${TYPE:+CAMERA_VIDEO_PATH=} $${TYPE:+CAMERA_PHOTO_PATH=} \
			$${LOOP:+CAMERA_VIDEO_LOOP=$$LOOP} \
			PYTHONPATH=src \
			.venv/bin/uvicorn palmgrade.main:app --host 127.0.0.1 --port $(LINE_PORT); \
		RC=$$?; \
		if [ $$RC -ne 0 ]; then \
			echo "line-$(N) berhenti (exit $$RC) — tidak dinyalakan ulang"; \
			exit $$RC; \
		fi; \
		echo "line-$(N) keluar atas permintaan konsol — menyalakan ulang dengan setelan baru"; \
		sleep 1; \
	done

# Fullscreen on this PC. A page cannot fullscreen itself (requestFullscreen
# needs a user gesture), so the browser is what gets configured.
kiosk:
	./scripts/console-kiosk.sh

# Operator accounts for the console login (Fase 4). Name and PIN are asked for
# interactively, so the PIN never lands in shell history.
#   make operator                        add a local account, or reset a forgotten
#                                         password — role `operator` unless ROLE=support
#   make operator AKSI=daftar            list the active accounts and where each came from
#   make operator AKSI=matikan           switch one off (their sessions end at once)
#   make operator AKSI=role ROLE=support
#                                         change an EXISTING account's role, without
#                                         touching its password
# `operator` is the native console (Mac). `operator-docker` runs inside the console
# container on the factory PC, against the database that console really reads.
AKSI ?= tambah
ROLE ?= operator
operator:
	PYTHONPATH=src .venv/bin/python scripts/console-operator.py $(AKSI) $(ROLE)

operator-docker:
	$(COMPOSE) exec console python scripts/console-operator.py $(AKSI) $(ROLE)

# Data demo untuk showcase ke klien. Truk, kunjungan, janjang, dan dua akun untuk
# masuk konsol. Platnya sama persis dengan seeder AutoERP (`palm_mill/demo.py`),
# jadi satu truk adalah truk yang sama di dua layar.
#   make demo                jalankan (7 hari riwayat)
#   make demo HARI=3         riwayat lebih pendek
#   make demo-reset          hapus data demo lama dulu, lalu isi ulang
#   make demo-off            hapus data demo, berhenti di situ (sesudah demo selesai)
# `AKSI=reset` masih jalan (dipakai dokumen lama), tapi `make demo-reset` yang dipakai
# sekarang — namanya sejajar dengan AutoERP, jadi satu nama untuk dua repo.
# ⚠️ JANGAN di PC pabrik. Skripnya menolak database yang sudah punya data
# sungguhan; PAKSA=1 melewati penolakan itu — jangan dipakai kecuali yakin.
HARI ?= 7
demo:
	PYTHONPATH=src .venv/bin/python scripts/seed-console-demo.py \
		--hari $(HARI) $(if $(filter reset,$(AKSI)),--reset,) $(if $(PAKSA),--paksa,)

# Bersihkan data demo sesudah showcase. Menghapus baris milik sepuluh plat demo
# saja — timbangan dan janjang truk sungguhan tidak disentuh. Wajib dijalankan
# sebelum uji coba: janjang seeder berstempel sampai ~20 jam ke depan, jadi selama
# masih ada dia selalu berada di atas baris yang baru saja digrading.
demo-reset:
	PYTHONPATH=src .venv/bin/python scripts/seed-console-demo.py --hari $(HARI) --reset

demo-off:
	PYTHONPATH=src .venv/bin/python scripts/seed-console-demo.py --hapus

demo-docker:
	$(COMPOSE) exec console python scripts/seed-console-demo.py \
		--hari $(HARI) $(if $(filter reset,$(AKSI)),--reset,) $(if $(PAKSA),--paksa,)

# Hash untuk dua akun bawaan konsol. Dipakai waktu pasang PC pabrik: sandinya beda
# per PKS, dan yang masuk ke image atau .env cuma hash-nya, bukan sandi mentah.
hash-sandi:
	PYTHONPATH=src .venv/bin/python scripts/hash-sandi.py

# OPS-2: satukan truk kembar di PC pabrik yang SUDAH punya data dari palmgrade-api.
# Truk lama ber-id acak, AutoGrade menurunkan id dari plat, dan plat tidak punya
# indeks unik - tanpa ini tarikan pertama membelah tonase satu truk jadi dua baris.
# Dijalankan sekali saat pasang. PC baru (DB kosong) tidak perlu.
# Tanpa TULIS=1 cuma melihat; di Docker pakai rekonsiliasi-truk-docker.
rekonsiliasi-truk:
	PYTHONPATH=src .venv/bin/python scripts/rekonsiliasi-truk.py $(if $(TULIS),--tulis,)

rekonsiliasi-truk-docker:
	$(COMPOSE) exec console python scripts/rekonsiliasi-truk.py $(if $(TULIS),--tulis,)

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

# Logs per line
logs-1:
	$(COMPOSE) logs -f ripe-line-1

logs-2:
	$(COMPOSE) logs -f ripe-line-2

logs-3:
	$(COMPOSE) logs -f ripe-line-3

logs-console:
	$(COMPOSE) logs -f console

# Combined logs for all lines (prefixed with the container name)
logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

# Rebuild the image — CUDA torch (production with an NVIDIA GPU, ~2.4GB from the
# PyTorch CDN). TORCH_VARIANT=cu126 → needs driver >= 525 (host 580 ✅)
rebuild:
	$(COMPOSE) build --build-arg TORCH_VARIANT=cu126

rebuild-gpu:
	$(COMPOSE) build --build-arg TORCH_VARIANT=cu126

# Menghapus ISI `artifacts/` dan `state/`, bukan foldernya.
#
# ⚠️ Berkasnya milik ROOT di Linux. `Dockerfile` tidak punya `USER`, jadi
# container jalan sebagai root dan semua foto + SQLite yang ditulisnya jadi milik
# root; `rm -rf` dari user biasa dijawab "Permission denied" ribuan kali dan
# target-nya berhenti dengan Error 1 (kejadian di PC Lampung 2026-09-18).
# Di macOS ini tidak pernah terlihat: Docker Desktop memetakan pemilik ke user
# yang menjalankan, jadi penghapusan terasa berhasil di laptop dan gagal di
# pabrik — satu-satunya tempat yang penting.
#
# Jadi yang menghapus adalah container yang memang root.
#
# `docker run` langsung, BUKAN `docker compose run`: tiap service di compose
# me-mount `./artifacts/line-N` ke `/app/artifacts`, jadi container line hanya
# melihat foldernya sendiri dan dua line lain luput. Di sini `$(CURDIR)` di-mount
# utuh sekali, sehingga satu perintah menjangkau ketiganya plus `state/console`.
#
# `busybox` dipakai, bukan image proyek: tugasnya cuma menghapus berkas, dan
# image ini 4 MB sementara `palmgrade-vision` beberapa GB — tapi kalau busybox
# belum ada di PC yang offline, `|| true` di bawah membuat kegagalan tarik tidak
# menghentikan target, dan `rm -rf` host sesudahnya masih menyapu apa yang bisa
# dia hapus.
#
# Isinya saja yang dibuang — foldernya tetap, sehingga kepemilikan dan izin
# mount-nya tidak berubah. `find -mindepth 1 -delete` dipakai daripada
# `rm -rf .../*` karena glob shell melewatkan berkas tersembunyi.
HAPUS_ISI = docker run --rm -v "$(CURDIR)":/kerja busybox \
	sh -c 'find /kerja/artifacts /kerja/state -mindepth 1 -delete 2>/dev/null; true'

# HAPUS SEMUA DATA AutoGrade di PC ini: foto, JSON, semua SQLite.
#
#   make reset-data          lihat dulu: berapa yang akan hilang, tidak menghapus
#   make reset-data-fresh    hapus sungguhan (minta konfirmasi ketik)
#
# Yang hilang, semuanya PERMANEN dan tanpa backup:
#   artifacts/       foto bbox+clean+thumb dan sidecar JSON tiap janjang
#   state/           console.db (grading, truk, timbangan, akun, sesi),
#                    outbox.db tiap line, erp_outbox.db, log_kejadian.db,
#                    upload_manifest.db
#
# Tiga akibat yang harus disadari sebelum mengetiknya:
#   1. AKUN LOKAL BUATAN SENDIRI HILANG. Dua akun bawaan image
#      (`operator@`/`support@autograde.local`) dibuat ulang sendiri saat konsol
#      start, jadi layar tetap bisa dibuka. Yang TIDAK kembali: akun yang dibuat
#      `make operator`. Akun milik AutoERP turun lagi saat sinkron berikutnya.
#   2. ANTREAN YANG BELUM TERKIRIM HILANG. Janjang di `outbox.db` dan kunjungan
#      truk di `erp_outbox.db` yang belum sampai tidak bisa dikirim ulang.
#   3. FOTO YANG BELUM NAIK R2 HILANG. Retensi bekerja lewat manifest, jadi
#      menghapus DB saja akan meninggalkan foto yatim — makanya keduanya
#      dihapus bersama, bukan salah satu.
#
# ⚠️ JANGAN di PC pabrik yang sedang produksi. Ini alat untuk PC uji coba atau
# PC baru sebelum dipakai sungguhan.
reset-data:
	@echo "Akan menghapus PERMANEN (tanpa backup):"
	@echo "  artifacts/:  $$(find artifacts -type f 2>/dev/null | wc -l | tr -d ' ') berkas foto + JSON"
	@echo "  state/:      $$(find state -name '*.db' 2>/dev/null | wc -l | tr -d ' ') basis data SQLite"
	@echo ""
	@echo "Akun buatan 'make operator', antrean yang belum terkirim, dan foto yang"
	@echo "belum naik R2 ikut hilang. Tidak ada cara mengembalikannya."
	@echo "(Dua akun bawaan image dibuat ulang sendiri saat konsol start.)"
	@echo ""
	@echo "Kalau memang itu yang diinginkan: make reset-data-fresh"

# Konfirmasi diketik, bukan ditekan. Layar sentuh bisa mendaftarkan sentuhan tak
# sengaja sebagai klik, dan Enter bisa terkirim dari perintah sebelumnya yang
# masih di riwayat — tapi tidak ada yang mengetik satu kata tertentu tanpa maksud.
# Pola yang sama dipakai Uji PLC di konsol, satu-satunya aksi lain yang tidak
# bisa dibatalkan.
reset-data-fresh:
	@echo "SEMUA data AutoGrade di PC ini akan dihapus permanen, tanpa backup."
	@echo "Jalankan 'make reset-data' dulu kalau ingin melihat rinciannya."
	@echo ""
	@printf "Ketik HAPUS untuk melanjutkan: "
	@read jawab; [ "$$jawab" = "HAPUS" ] || { echo "Dibatalkan."; exit 1; }
	$(COMPOSE) down
	@echo "Menghapus lewat container (berkasnya milik root di Linux)..."
	-@$(HAPUS_ISI)
	@# Jaring kedua: sisa apa pun yang memang milik user ini — dan satu-satunya
	@# jalan kalau busybox tidak bisa ditarik di PC yang offline. `-` di depan
	@# supaya "Permission denied" pada sisa milik root tidak menghentikan target,
	@# karena baris di atas sudah mengurus yang itu.
	-@rm -rf artifacts/* artifacts/.[!.]* state/* state/.[!.]* 2>/dev/null
	mkdir -p artifacts state
	@# Kalau masih ada isinya, penghapusan TIDAK berhasil dan diam saja akan
	@# membuat orang mengira datanya sudah bersih.
	@sisa=$$(find artifacts state -mindepth 1 2>/dev/null | wc -l | tr -d ' '); \
	if [ "$$sisa" != "0" ]; then \
		echo ""; \
		echo "GAGAL: masih ada $$sisa berkas tersisa."; \
		echo "Berkasnya milik root dan container tidak bisa dijalankan."; \
		echo "Coba: sudo rm -rf artifacts state && mkdir -p artifacts state"; \
		exit 1; \
	fi
	@echo ""
	@echo "Data dihapus. Jalankan 'make start', dua akun bawaan dibuat ulang sendiri."

# Remove all containers (data artifacts are safe — they live in local volumes)
clean:
	$(COMPOSE) down --rmi local

# Run line-1 locally without Docker (needs an active Python env).
# MACHINE_ID is deliberately NOT overridden here: main.py calls load_dotenv(), so
# MACHINE_ID comes straight from $(ENV_FILE) (fill it with line-1's UUID). An older
# version exported `MACHINE_ID=$$(grep LINE_1_MACHINE_ID ...)`; if that key is
# missing from .env the result is an EMPTY string, and load_dotenv(override=False)
# will not replace it — machine_id becomes "" and the API rejects every event.
dev:
	uvicorn src.palmgrade.main:app --host 0.0.0.0 --port 8001 --reload

# Reload the console after a Python change. Bind-mounted code means HTML is
# served fresh on refresh, but the running process keeps the old Python until
# it is restarted. `up -d console` does NOT do this - it is a no-op when the
# container already runs.
restart-console:
	$(COMPOSE) restart console
