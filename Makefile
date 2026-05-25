ENV_FILE=.env

# Production — copy SDK dari host, build GPU + SDK, lalu start semua line
up:
	@test -d /opt/MVS || (echo "ERROR: Hikrobot MVS SDK tidak ditemukan di /opt/MVS. Install MVS terlebih dahulu." && exit 1)
	mkdir -p sdk/lib64
	cp -r /opt/MVS/lib/64/. sdk/lib64/
	cp -r /opt/MVS/Samples/64/Python/MvImport sdk/MvImport
	docker compose --env-file $(ENV_FILE) build \
		--build-arg TORCH_VARIANT=cu126 \
		--build-arg WITH_SDK=true
	docker compose --env-file $(ENV_FILE) up -d

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
	uvicorn src.ripe_recognition.main:app --host 0.0.0.0 --port 8001 --reload
