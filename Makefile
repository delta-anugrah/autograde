ENV_FILE=.env

# Jalankan semua 3 line (build + detach)
up:
	docker compose --env-file $(ENV_FILE) up -d --build

# Jalankan hanya 1 line tertentu
up-1:
	docker compose --env-file $(ENV_FILE) up -d --build ripe-line-1

up-2:
	docker compose --env-file $(ENV_FILE) up -d --build ripe-line-2

up-3:
	docker compose --env-file $(ENV_FILE) up -d --build ripe-line-3

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

# Rebuild image — CPU-only torch (dev/video test, ~193MB, cepat)
rebuild:
	docker compose --env-file $(ENV_FILE) build --build-arg TORCH_VARIANT=cpu

# Rebuild image — CUDA torch (production dengan NVIDIA GPU, ~2.4GB dari PyTorch CDN)
# TORCH_VARIANT=cu126 → compatible dengan driver >= 525 (host 580 ✅)
rebuild-gpu:
	docker compose --env-file $(ENV_FILE) build --build-arg TORCH_VARIANT=cu126

# Hapus semua container (data artifacts aman — di volume lokal)
clean:
	docker compose --env-file $(ENV_FILE) down --rmi local

# Jalankan line-1 secara lokal tanpa Docker (butuh Python env aktif)
dev:
	MACHINE_ID=$$(grep LINE_1_MACHINE_ID $(ENV_FILE) | cut -d= -f2) \
	uvicorn src.ripe_recognition.main:app --host 0.0.0.0 --port 8001 --reload
