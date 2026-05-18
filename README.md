# palmgrade-vision

AI camera service for the **Palmgrade** palm oil ripeness grading system.

Runs as **3 separate Docker containers** (one per camera line), each connected to a Hikrobot industrial camera. Performs real-time YOLO-based fruit ripeness detection and pushes results to `palmgrade-api` via webhook.

---

## Part of the Palmgrade System

| Repo | Role | Port |
|---|---|---|
| **`palmgrade-vision`** | AI camera + inference | 8001 / 8002 / 8003 |
| `palmgrade-api` | Business logic, auth, SSE broker | 2500 |
| `palmgrade-frontend` | Operator dashboard UI | 3050 |

> Full system architecture: see [`ARCHITECTURE.md`](../ARCHITECTURE.md)

---

## How It Works

```
Hikrobot Camera (USB)
    → FrameCaptureWorker  (thread) → frame_queue
    → FrameProcessingWorker (thread)
        → YOLOv8 + ByteTrack
        → detect: acc / rej / tp (tangkai panjang)
        → save JPEG + JSON to artifacts/results/
        → POST webhook → palmgrade-api
    → EventBroadcastWorker (asyncio task)
        → WebSocket /ws/results → frontend
```

**Detection model**: `best_3class.pt` — 3 classes: `acc` (accepted), `rej` (rejected), `tp` (long stalk)
**Minimum size**: 460,000 px² — objects below this area are forced to `rej`
**Tracking**: ByteTrack — each fruit gets a unique `track_id`, saved only once (single-trigger)

---

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Hikrobot camera SDK installed on host (production only)
- YOLO model file at `models/release/best_3class.pt`

---

## Project Structure

```
palmgrade-vision/
├── src/ripe_recognition/
│   ├── main.py                  # FastAPI app entry point
│   ├── core/                    # Config, logging, DI wiring
│   ├── routes/                  # FastAPI routers
│   ├── controllers/             # Request handlers
│   ├── services/                # Business logic
│   ├── repositories/            # File I/O (JPEG, JSON)
│   ├── pipelines/               # YOLO inference + frame processing
│   ├── workers/                 # Background threads & asyncio tasks
│   ├── integrations/
│   │   ├── camera/              # HikrobotCamera / OpenCVCamera / PhotoCamera
│   │   ├── notifications/       # WebhookClient (httpx)
│   │   ├── storage/             # LocalFileStorage
│   │   └── scheduler/           # APScheduler daily upload cron
│   ├── domain/                  # Pure business rules (no I/O)
│   ├── schemas/                 # Pydantic request/response models
│   └── license/                 # License guard (Ed25519 JWS, optional)
├── models/
│   └── release/
│       └── best_3class.pt       # YOLO model — required, not committed to git
├── artifacts/                   # Runtime output — not committed to git
│   ├── line-1/
│   ├── line-2/
│   └── line-3/
├── Dockerfile
├── docker-compose.yml           # 3 services: line-1 (8001), line-2 (8002), line-3 (8003)
├── requirements.txt
├── .env                         # Local env (copy from .env.example)
└── .env.example
```

---

## Setup

### 1. Clone & copy env

```bash
git clone git@github.com:delta-anugrah/palmgrade-vision.git
cd palmgrade-vision
cp .env.example .env
```

### 2. Edit `.env`

Key variables to fill in:

```env
# Backend (palmgrade-api)
BACKEND_URL=http://localhost:2500
WEBHOOK_SECRET=your-webhook-secret

# Machine UUIDs — must match machines.id in PostgreSQL (palmgrade-api)
LINE_1_MACHINE_ID=<uuid-from-db>
LINE_2_MACHINE_ID=<uuid-from-db>
LINE_3_MACHINE_ID=<uuid-from-db>

# Model
MODEL_FILE=best_3class.pt
CONF_THRESHOLD=0.75
MINIMUM_SIZE=460000
```

### 3. Place the model file

```bash
mkdir -p models/release
# copy best_3class.pt to models/release/
```

---

## Running

### Production — Docker (3 camera lines simultaneously)

```bash
docker compose up --build
```

| Container | Port | Camera Index | Machine ID env |
|---|---|---|---|
| `ripe_line_1` | 8001 | 0 | `LINE_1_MACHINE_ID` |
| `ripe_line_2` | 8002 | 1 | `LINE_2_MACHINE_ID` |
| `ripe_line_3` | 8003 | 2 | `LINE_3_MACHINE_ID` |

**USB cameras in Docker** — uncomment `devices:` in `docker-compose.yml`:
```yaml
devices:
  - /dev/bus/usb:/dev/bus/usb
```

### Development — single instance, local

Switch camera source in `src/ripe_recognition/main.py` startup event:

```python
# Webcam
from .integrations.camera.opencv_camera import OpenCVCamera
camera = OpenCVCamera(source=0)

# Video file
# camera = OpenCVCamera(source="/path/to/video.mp4")

# Static image (for testing)
# from .integrations.camera.photo_camera import PhotoCamera
# camera = PhotoCamera(path="/path/to/image.jpg")
```

Then run:

```bash
pip install -r requirements.txt
uvicorn src.ripe_recognition.main:app --host 0.0.0.0 --port 8001 --reload
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Health check (always allowed, bypasses license guard) |
| `GET` | `/api/video_feed` | MJPEG live stream |
| `POST` | `/api/set_truck` | Set active truck ID for this line |
| `POST` | `/api/manual_capture` | Trigger manual reject capture |
| `GET` | `/api/inspection/status` | Model + device info |
| `GET` | `/api/results/today` | Today's grading results |
| `WS` | `/ws/results` | WebSocket result push (legacy) |
| `GET` | `/captures/results/...` | Static files — saved result images |

```bash
# Set truck example
curl -X POST http://localhost:8001/api/set_truck \
  -H "Content-Type: application/json" \
  -d '{"truck_id": "your-truck-uuid"}'
```

---

## Webhook Payload (sent to palmgrade-api on each detection)

```json
{
  "timestamp": "2026-05-18T10:30:00.123456",
  "image_path": "captures/results/2026-05-18/2026-05-18_103000_123456_auto.jpg",
  "ripeness_status": "acc",
  "ripeness_confidence": 0.92,
  "tp_status": "TP",
  "tp_confidence": 0.88,
  "capture_type": "auto",
  "truck_id": "uuid-or-null",
  "machine_id": "uuid-from-machines-table",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

`machine_id` is how the frontend knows which line panel to update.

---

## Artifact Output

```
artifacts/line-1/
├── captures/                  # Manual reject captures
├── results/
│   └── 2026-05-18/
│       ├── 2026-05-18_103000_auto.jpg          # Fruit image
│       ├── 2026-05-18_103000_auto_ripeness.json # Detection metadata
│       └── 2026-05-18_103000_auto_tp.json       # Long stalk metadata (if detected)
├── errors/                    # Copy of all rej results
└── logs/
```

Images are served as static files: `GET /captures/results/{date}/{filename}`

---

## License Guard (optional, disabled by default)

```env
LIC_ENABLED=true
LIC_SERVER_URL=https://your-license-server.com
LIC_API_KEY=your-api-key
LIC_PUBKEY_PEM=-----BEGIN PUBLIC KEY-----\nMCow...\n-----END PUBLIC KEY-----
```

When enabled, all routes (except `/healthz`) are blocked for expired licenses.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8000` | Internal container port |
| `FRONTEND_URL` | `*` | CORS allowed origin |
| `BACKEND_URL` | `http://localhost:2500` | palmgrade-api base URL |
| `WEBHOOK_SECRET` | — | HMAC secret — must match palmgrade-api |
| `ENABLE_WEBHOOK` | `true` | Toggle webhook posting |
| `MODEL_FILE` | `best_3class.pt` | YOLO model filename in `models/release/` |
| `CONF_THRESHOLD` | `0.75` | YOLO confidence threshold |
| `MINIMUM_SIZE` | `460000` | Min bounding box area in px² |
| `CAMERA_DEVICE_INDEX` | `0` | Hikrobot device index (0/1/2 per line) |
| `MACHINE_ID` | — | UUID from `machines` table — set per line |
| `LINE_1_MACHINE_ID` | — | Used by docker-compose for line 1 |
| `LINE_2_MACHINE_ID` | — | Used by docker-compose for line 2 |
| `LINE_3_MACHINE_ID` | — | Used by docker-compose for line 3 |
| `LIC_ENABLED` | `false` | Enable license guard middleware |
| `UPLOAD_HOUR` | `0` | Daily upload cron — hour |
| `UPLOAD_MINUTE` | `0` | Daily upload cron — minute |
