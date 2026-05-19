FROM python:3.11-slim

WORKDIR /app

# System deps untuk OpenCV dan Hikrobot SDK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libusb-1.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ── Hikrobot MVS SDK (production only) ──────────────────────────────────────
# SDK harus di-copy manual dari host ke ./sdk/ sebelum build:
#   mkdir sdk && cp /opt/MVS/lib/64/libMvCameraControl.so* sdk/
#   cp -r /opt/MVS/Samples/64/Python/MvImport sdk/
# Uncomment baris di bawah untuk production:
# COPY sdk/libMvCameraControl.so* /usr/local/lib/
# COPY sdk/MvImport /usr/local/lib/python3.11/site-packages/MvImport
# RUN ldconfig

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Folder artifacts dibuat di startup, tapi kita pastiin parent-nya ada
RUN mkdir -p artifacts/captures artifacts/results artifacts/errors artifacts/logs

# Entrypoint di luar /app supaya tidak tertimpa volume mount .:/app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE ${APP_PORT:-8000}

ENTRYPOINT ["/entrypoint.sh"]
