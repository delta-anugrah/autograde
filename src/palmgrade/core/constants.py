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
JPEG_QUALITY_STREAM = 42
JPEG_QUALITY_SAVE = 80

# Frame queue
FRAME_QUEUE_MAXSIZE = 5
RESULT_QUEUE_MAXSIZE = 5
EVENT_QUEUE_MAXSIZE = 10

# Zone line display thickness (px)
REF_LINE_THICKNESS = 7

# ROI detection zone highlight (overlay semi-transparan di antara entry/exit line)
COLOR_ROI = (0, 200, 0)    # hijau (BGR)
ROI_ALPHA = 0.25             # opacity 25%
