ENV_FILE=.env

# Production — copy SDK, build GPU+SDK, build TensorRT engine, start semua line.
# CATATAN: untuk perubahan KODE saja, cukup `make restart` — kode di-bind-mount
# (.:/app), jadi TIDAK perlu rebuild. `make up` cuma perlu kalau dependency /
# Dockerfile / SDK berubah.
up: sync-sdk
	-docker compose --env-file $(ENV_FILE) down
	docker compose --env-file $(ENV_FILE) build \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true
	$(MAKE) build-engine
	docker compose --env-file $(ENV_FILE) up -d
	-docker image prune -f

# Copy Hikrobot MVS SDK dari host ke build context (perlu kalau SDK berubah).
sync-sdk:
	@test -d /opt/MVS || (echo "ERROR: Hikrobot MVS SDK tidak ditemukan di /opt/MVS. Install MVS terlebih dahulu." && exit 1)
	mkdir -p sdk/lib64
	cp -r /opt/MVS/lib/64/. sdk/lib64/
	cp -r /opt/MVS/Samples/64/Python/MvImport sdk/MvImport

# Build TensorRT FP16 engine SEKALI per GPU (auto-skip kalau engine utk GPU ini
# sudah ada). Dijalankan sebagai 1 container one-shot → tidak ada race antar 3 line.
# Pertama kali per PC bisa 5-15 menit; berikutnya instan (engine ke-cache di ./engines).
build-engine:
	docker compose --env-file $(ENV_FILE) run --rm --no-deps \
		--entrypoint python ripe-line-1 scripts/build_engine.py

# Full clean rebuild (pakai HANYA kalau cache dicurigai rusak — lambat, no-cache).
rebuild-clean: sync-sdk
	-docker compose --env-file $(ENV_FILE) down
	-docker image rm palmgrade-vision:latest 2>/dev/null || true
	docker compose --env-file $(ENV_FILE) build --no-cache \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true

# Development — build tanpa SDK, CPU torch, lalu start semua line
up-dev:
	docker compose --env-file $(ENV_FILE) build \
		--build-arg TORCH_VARIANT=cpu
	docker compose --env-file $(ENV_FILE) up -d

# Start semua line tanpa rebuild (pakai image yang sudah ada)
start:
	docker compose --env-file $(ENV_FILE) up -d

# Start hanya 1 line tertentu tanpa rebuild
up-1:
	docker compose --env-file $(ENV_FILE) up -d ripe-line-1

up-2:
	docker compose --env-file $(ENV_FILE) up -d ripe-line-2

up-3:
	docker compose --env-file $(ENV_FILE) up -d ripe-line-3

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

# Logs gabungan semua line (dengan prefix container name)
logs:
	docker compose --env-file $(ENV_FILE) logs -f

ps:
	docker compose --env-file $(ENV_FILE) ps

# Rebuild image — CUDA torch (production dengan NVIDIA GPU, ~2.4GB dari PyTorch CDN)
# TORCH_VARIANT=cu126 → compatible dengan driver >= 525 (host 580 ✅)
rebuild:
	docker compose --env-file $(ENV_FILE) build --build-arg TORCH_VARIANT=cu126

rebuild-gpu:
	docker compose --env-file $(ENV_FILE) build --build-arg TORCH_VARIANT=cu126

# Hapus semua container (data artifacts aman — di volume lokal)
clean:
	docker compose --env-file $(ENV_FILE) down --rmi local

# Jalankan line-1 secara lokal tanpa Docker (butuh Python env aktif)
dev:
	MACHINE_ID=$$(grep LINE_1_MACHINE_ID $(ENV_FILE) | cut -d= -f2) \
	uvicorn src.palmgrade.main:app --host 0.0.0.0 --port 8001 --reload
