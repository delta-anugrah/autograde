# cv2 is imported lazily, below `FONT`. Importing it at module level made every
# constant here cost an OpenCV import, which kept the capture path out of the
# unit suite (it runs without cv2 on purpose — CLAUDE.md § Tests). Only drawing
# code needs `FONT`, and that code already imports cv2 itself.

# Capture
MANUAL_CAPTURE_PREDICTION = "rej"
MANUAL_CAPTURE_STATUS = "rej"
MANUAL_CAPTURE_CONFIDENCE = 1.0
MANUAL_CAPTURE_SUFFIX = "manual"
AUTO_CAPTURE_SUFFIX = "auto"

# Bounding box colors (BGR)
COLOR_PASS = (0, 255, 0)   # hijau
COLOR_FAIL = (0, 0, 255)   # merah
# Tangkai panjang: kuning, sengaja bukan hijau maupun merah. TP bukan janjang
# dan tidak punya verdict — menggambarnya hijau membuatnya terbaca "lolos",
# merah membuatnya terbaca "dibuang", dan dua-duanya bohong.
COLOR_TP = (0, 215, 255)   # kuning-amber (BGR)

# Annotation font. Resolved on first access (PEP 562) rather than at import, so
# that importing any other constant here does not require OpenCV. Its value is
# unchanged: `cv2.FONT_HERSHEY_SIMPLEX`.
FONT_COLOR = (255, 255, 255)  # putih


def __getattr__(name: str):
    if name == "FONT":
        import cv2

        return cv2.FONT_HERSHEY_SIMPLEX
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Streaming
JPEG_QUALITY_STREAM = 42
# Kualitas encode untuk gambar yang disimpan (WebP/JPEG, skala 0–100 sama untuk keduanya).
# 65 = sweet-spot bukti visual: ukuran jauh lebih kecil, detail buah masih jelas.
JPEG_QUALITY_SAVE = 65

# Frame queue
FRAME_QUEUE_MAXSIZE = 5
RESULT_QUEUE_MAXSIZE = 5
EVENT_QUEUE_MAXSIZE = 10

# Zone line display thickness (px)
REF_LINE_THICKNESS = 7

# ROI detection zone highlight (overlay semi-transparan di antara entry/exit line)
COLOR_ROI = (0, 200, 0)    # hijau (BGR)
ROI_ALPHA = 0.25             # opacity 25%
