FROM python:3.11-slim

WORKDIR /app

# System deps untuk OpenCV dan Hikrobot SDK. `tzdata` dipakai konsol operator:
# python:3.11-slim tidak punya basis data zona waktu, dan tanpa itu
# ZoneInfo("Asia/Jakarta") gagal — batas hari kerja balik ke UTC diam-diam.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libusb-1.0-0 \
    libgomp1 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_DEFAULT_TIMEOUT=3600 \
    PIP_RETRIES=10 \
    PIP_NO_CACHE_DIR=1

# TORCH_VARIANT:
#   cpu   — development / video testing (~193MB, fast build)
#   cu126 — production dengan NVIDIA GPU, CUDA 12.6 (~2.4GB, dari PyTorch CDN)
#           Compatible dengan driver >= 525 (host saat ini: 580, CUDA 13.0 ✅)
ARG TORCH_VARIANT=cpu
# The CPU pins carry no `+cpu` label on purpose. PyTorch publishes
# torchvision 0.22.0 for aarch64 (Apple Silicon Docker) without it, so
# `==0.22.0+cpu` cannot resolve there. A bare `==0.22.0` still matches
# `0.22.0+cpu` (PEP 440), so x86 installs the exact same wheels as before.
# The release image and the factory PC use cu126 (the else branch), untouched.
RUN if [ "${TORCH_VARIANT}" = "cpu" ]; then \
        pip install torch==2.7.0 torchvision==0.22.0 \
            --index-url https://download.pytorch.org/whl/cpu; \
    else \
        pip install torch==2.7.0+${TORCH_VARIANT} torchvision==0.22.0+${TORCH_VARIANT} \
            --index-url https://download.pytorch.org/whl/${TORCH_VARIANT}; \
    fi

# TensorRT + ONNX exporters (GPU only) — dipakai `scripts/build_engine.py` untuk
# export model .pt → .engine (FP16). Engine itu hardware-locked, jadi DIBANGUN
# on-machine via `make build-engine`, BUKAN di-bake ke image. Diletakkan setelah
# torch supaya layer-nya ikut ke-cache (hanya rebuild kalau torch berubah).
#
# PENTING: install `tensorrt-cu12` (varian CUDA-12) DARI INDEX NVIDIA
# (https://pypi.nvidia.com). Di PyPI publik, `tensorrt-cu12-libs`/`-bindings`
# cuma ada sebagai source stub (.tar.gz, Metadata 2.1) → pip wajib build dari
# source → HANG di "Preparing metadata (pyproject.toml)". Index NVIDIA nyediain
# wheel binary manylinux (.whl) sehingga install langsung, tanpa build/hang.
# Tanpa flag ini, `make build-engine` bakal nyangkut (Ultralytics juga auto-coba
# install tensorrt saat export kalau modulnya gak ada → hang yang sama).
RUN if [ "${TORCH_VARIANT}" != "cpu" ]; then \
        pip install --extra-index-url https://pypi.nvidia.com \
            onnx onnxslim "tensorrt-cu12==10.13.3.9"; \
    fi

# ── Hikrobot MVS SDK (production only) ──────────────────────────────────────
# Sebelum `make up`, jalankan di host:
#   cp -r /opt/MVS/lib/64/. sdk/lib64/
#   cp -r /opt/MVS/Samples/64/Python/MvImport sdk/MvImport
# SDK diletakkan setelah torch supaya perubahan SDK tidak invalidate cache torch.
ARG WITH_SDK=false
COPY sdk/ /tmp/sdk/
RUN if [ "${WITH_SDK}" = "true" ]; then \
        mkdir -p /opt/MVS/lib && \
        cp -r /tmp/sdk/lib64 /opt/MVS/lib/64 && \
        cp -r /tmp/sdk/MvImport /usr/local/lib/python3.11/site-packages/MvImport && \
        ldconfig; \
    fi && rm -rf /tmp/sdk

# MvImport Python SDK mencari .so via MVCAM_COMMON_RUNENV/64/libMvCameraControl.so
ENV MVCAM_COMMON_RUNENV=/opt/MVS/lib

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Folder artifacts dibuat di startup, tapi kita pastiin parent-nya ada
RUN mkdir -p artifacts/results

# Tag rilis di-bake sebagai APP_VERSION supaya GET /health bisa menyebutkan
# versi image yang benar-benar jalan tanpa SSH ke PC pabrik. Ditaruh paling
# bawah: nilainya berubah tiap rilis, jadi jangan sampai membatalkan cache pip.
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# Entrypoint di luar /app supaya tidak tertimpa volume mount .:/app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE ${APP_PORT:-8000}

ENTRYPOINT ["/entrypoint.sh"]
