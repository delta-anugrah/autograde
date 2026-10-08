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

# Bounding box colors (BGR). Since 2026-10-08 the palette of the console design: the same
# green, red and amber as the Ripe/Unripe/TP counts under each line picture.
COLOR_PASS = (156, 217, 113)   # hijau #71d99c
COLOR_FAIL = (127, 116, 237)   # merah #ed747f
# Tangkai panjang: kuning, sengaja bukan hijau maupun merah. TP bukan janjang
# dan tidak punya verdict — menggambarnya hijau membuatnya terbaca "lolos",
# merah membuatnya terbaca "dibuang", dan dua-duanya bohong.
COLOR_TP = (99, 199, 246)   # kuning-amber #f6c763 (BGR)
# Class name on the filled label pill: near-black, as in the console design.
COLOR_LABEL_TEKS = (26, 16, 8)

# FPS pill top-right on the line picture: black at 55% over the picture, light text.
COLOR_FPS_LATAR = (0, 0, 0)
FPS_ALPHA = 0.55
COLOR_FPS_TEKS = (240, 232, 226)
FPS_FONT_SCALE = 0.8
FPS_FONT_THICKNESS = 2

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

# Garis pemicu capture — BIRU (BGR), diminta operator 2026-09-18.
# Sengaja biru, bukan hijau: hijau sudah dipakai kotak ROI dan bbox janjang yang
# lolos, dan operator perlu bisa menunjuk satu garis tanpa mengira itu bbox.
COLOR_TRIGGER = (255, 120, 0)   # biru terang
TRIGGER_THICKNESS = 3
