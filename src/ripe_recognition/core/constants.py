import cv2

# Capture
MANUAL_CAPTURE_PREDICTION = "rej"
MANUAL_CAPTURE_STATUS = "rej"
MANUAL_CAPTURE_CONFIDENCE = 1.0
MANUAL_CAPTURE_SUFFIX = "manual"
AUTO_CAPTURE_SUFFIX = "auto"

# Bounding box colors (BGR)
COLOR_PASS = (0, 255, 0)   # hijau
COLOR_FAIL = (0, 0, 255)   # merah

# Annotation font
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_COLOR = (255, 255, 255)  # putih

# Streaming
JPEG_QUALITY_STREAM = 60
JPEG_QUALITY_SAVE = 80

# Frame queue
FRAME_QUEUE_MAXSIZE = 5
RESULT_QUEUE_MAXSIZE = 5
EVENT_QUEUE_MAXSIZE = 10

# Reference line (pixel) — identik dengan sawit-update predict.py
REF_LINE_OFFSET = 500
REF_LINE_LEFT_EXTRA = 650
REF_LINE_RIGHT_OFFSET = 100
REF_LINE_THICKNESS = 7

# Detection zone: hanya track objek yang sudah masuk dari kanan sejauh ini
DETECTION_START_X_OFFSET = 2200

# Threshold x saat box dianggap sudah melewati garis kiri (exit zone)
ENTRY_MARGIN = 100
