ENV_FILE=.env
# Production override: immutable image (no bind-mount of .:/app & /videos).
PROD_FILES=-f docker-compose.yml -f docker-compose.prod.yml

# Production — copy SDK, build GPU+SDK, build the TensorRT engine, start all lines.
# NOTE: for CODE changes alone `make restart` is enough — code is bind-mounted
# (.:/app), so NO rebuild is needed. `make up` is only for dependency /
# Dockerfile / SDK changes.
up: sync-sdk
	-docker compose --env-file $(ENV_FILE) down
	docker compose --env-file $(ENV_FILE) build \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true
	$(MAKE) build-engine
	docker compose --env-file $(ENV_FILE) up -d
	-docker image prune -f

# Production IMMUTABLE — like `up` but with the docker-compose.prod.yml override,
# which REMOVES the .:/app & /videos bind-mounts, so containers run from the built
# image, not the working tree. Use this on the prod PC. Since code is NOT mounted,
# a code change in prod needs `make up-prod` again, not `make restart`.
up-prod: sync-sdk
	-docker compose $(PROD_FILES) --env-file $(ENV_FILE) down
	docker compose $(PROD_FILES) --env-file $(ENV_FILE) build \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true
	docker compose $(PROD_FILES) --env-file $(ENV_FILE) up -d
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
	docker compose --env-file $(ENV_FILE) run --rm --no-deps \
		--entrypoint python ripe-line-1 scripts/build_engine.py

# Full clean rebuild (use ONLY when the cache is suspect — slow, no-cache).
rebuild-clean: sync-sdk
	-docker compose --env-file $(ENV_FILE) down
	-docker image rm palmgrade-vision:latest 2>/dev/null || true
	docker compose --env-file $(ENV_FILE) build --no-cache \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true

# Development — build without the SDK, CPU torch, then start all lines
up-dev:
	docker compose --env-file $(ENV_FILE) build \
		--build-arg TORCH_VARIANT=cpu
	docker compose --env-file $(ENV_FILE) up -d

# Start all lines without rebuilding (uses the existing image)
start:
	docker compose --env-file $(ENV_FILE) up -d

# Start just one line, no rebuild
up-1:
	docker compose --env-file $(ENV_FILE) up -d ripe-line-1

up-2:
	docker compose --env-file $(ENV_FILE) up -d ripe-line-2

up-3:
	docker compose --env-file $(ENV_FILE) up -d ripe-line-3

# Operator console only (APP_MODE=console, port 8000) — screen at /console.
# No camera/GPU, so it is safe to restart on its own without touching the lines.
up-console:
	docker compose --env-file $(ENV_FILE) up -d console

# Operator console WITHOUT Docker — the development path on a Mac, where the
# Docker targets cannot run (no MVS SDK, no NVIDIA GPU, host networking).
# Port 8100 because a local AutoERP bench owns 8000. Settings come from .env
# (console_main.py loads it); only WEBHOOK_SECRET is forced to the dev value the
# seed script and E2E tests use. Override: make console CONSOLE_PORT=8200
CONSOLE_PORT ?= 8100
DEV_WEBHOOK_SECRET ?= devsecret
console:
	WEBHOOK_SECRET=$(DEV_WEBHOOK_SECRET) PYTHONPATH=src .venv/bin/uvicorn \
		palmgrade.console_main:app --host 127.0.0.1 --port $(CONSOLE_PORT)

# Fullscreen on this PC. A page cannot fullscreen itself (requestFullscreen
# needs a user gesture), so the browser is what gets configured.
kiosk:
	./scripts/console-kiosk.sh

# Operator accounts for the console login (Fase 4). Name and PIN are asked for
# interactively, so the PIN never lands in shell history.
#   make operator                        add a local account, or reset a forgotten
#                                         password — role `operator` unless PERAN=support
#   make operator AKSI=daftar            list the active accounts and where each came from
#   make operator AKSI=matikan           switch one off (their sessions end at once)
#   make operator AKSI=peran PERAN=support
#                                         change an EXISTING account's role, without
#                                         touching its password
# `operator` is the native console (Mac). `operator-docker` runs inside the console
# container on the factory PC, against the database that console really reads.
AKSI ?= tambah
PERAN ?= operator
operator:
	PYTHONPATH=src .venv/bin/python scripts/console-operator.py $(AKSI) $(PERAN)

operator-docker:
	docker compose --env-file $(ENV_FILE) exec console python scripts/console-operator.py $(AKSI) $(PERAN)

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
	docker compose --env-file $(ENV_FILE) exec console python scripts/rekonsiliasi-truk.py $(if $(TULIS),--tulis,)

down:
	docker compose --env-file $(ENV_FILE) down

restart:
	docker compose --env-file $(ENV_FILE) restart

# Logs per line
logs-1:
	docker compose --env-file $(ENV_FILE) logs -f ripe-line-1

logs-2:
	docker compose --env-file $(ENV_FILE) logs -f ripe-line-2

logs-3:
	docker compose --env-file $(ENV_FILE) logs -f ripe-line-3

logs-console:
	docker compose --env-file $(ENV_FILE) logs -f console

# Combined logs for all lines (prefixed with the container name)
logs:
	docker compose --env-file $(ENV_FILE) logs -f

ps:
	docker compose --env-file $(ENV_FILE) ps

# Rebuild the image — CUDA torch (production with an NVIDIA GPU, ~2.4GB from the
# PyTorch CDN). TORCH_VARIANT=cu126 → needs driver >= 525 (host 580 ✅)
rebuild:
	docker compose --env-file $(ENV_FILE) build --build-arg TORCH_VARIANT=cu126

rebuild-gpu:
	docker compose --env-file $(ENV_FILE) build --build-arg TORCH_VARIANT=cu126

# Remove all containers (data artifacts are safe — they live in local volumes)
clean:
	docker compose --env-file $(ENV_FILE) down --rmi local

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
	docker compose --env-file $(ENV_FILE) restart console
