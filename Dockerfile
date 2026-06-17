FROM python:3.11-slim

WORKDIR /app

# System deps untuk OpenCV dan Hikrobot SDK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libusb-1.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_DEFAULT_TIMEOUT=3600 \
    PIP_RETRIES=10 \
    PIP_NO_CACHE_DIR=1

# TORCH_VARIANT:
#   cpu   — development / video testing (~193MB, fast build)
#   cu126 — production dengan NVIDIA GPU, CUDA 12.6 (~2.4GB, dari PyTorch CDN)
#           Compatible dengan driver >= 525 (host saat ini: 580, CUDA 13.0 ✅)
ARG TORCH_VARIANT=cpu
RUN if [ "${TORCH_VARIANT}" = "cpu" ]; then \
        pip install torch==2.7.0+cpu torchvision==0.22.0+cpu \
            --index-url https://download.pytorch.org/whl/cpu; \
    else \
        pip install torch==2.7.0+${TORCH_VARIANT} torchvision==0.22.0+${TORCH_VARIANT} \
            --index-url https://download.pytorch.org/whl/${TORCH_VARIANT}; \
    fi

# TensorRT + ONNX exporters (GPU only) — dipakai `scripts/build_engine.py` untuk
# export model .pt → .engine (FP16). Engine itu hardware-locked, jadi DIBANGUN
# on-machine via `make build-engine`, BUKAN di-bake ke image. Diletakkan setelah
# torch supaya layer-nya ikut ke-cache (hanya rebuild kalau torch berubah).
# Catatan: versi tensorrt mungkin perlu disesuaikan dengan CUDA/driver target.
RUN if [ "${TORCH_VARIANT}" != "cpu" ]; then \
        pip install onnx onnxslim "tensorrt>=10.0.0,<10.8.0"; \
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
RUN mkdir -p artifacts/captures artifacts/results artifacts/errors artifacts/logs

# Entrypoint di luar /app supaya tidak tertimpa volume mount .:/app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE ${APP_PORT:-8000}

ENTRYPOINT ["/entrypoint.sh"]
