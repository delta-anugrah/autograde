FROM python:3.11-slim

WORKDIR /app

# System deps untuk OpenCV dan Hikrobot SDK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Folder artifacts dibuat di startup, tapi kita pastiin parent-nya ada
RUN mkdir -p artifacts/captures artifacts/results artifacts/errors artifacts/logs

EXPOSE ${APP_PORT:-8000}

CMD ["python", "-m", "uvicorn", "src.ripe_recognition.main:app", "--host", "0.0.0.0", "--port", "8000"]
