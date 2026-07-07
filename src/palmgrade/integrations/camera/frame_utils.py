"""Pure frame helpers — no cv2/numpy/SDK so they stay unit-testable.

Dipisah dari hikrobot_camera.py (yang import cv2 + MvImport SDK) supaya guard
validasi ukuran frame bisa di-test di CI ringan tanpa dependency berat.
"""
from __future__ import annotations


def _validate_frame_len(frame_len: int, width: int, height: int, channels: int) -> bool:
    """True kalau jumlah byte frame persis sesuai width*height*channels.

    GigE packet loss bisa mengirim frame parsial → reshape ke (h, w[, c]) akan
    ValueError. Guard ini dipakai sebelum reshape supaya frame korup di-drop
    bersih (return None di grab_frame) tanpa exception + penalty sleep 1 detik.
    """
    if width <= 0 or height <= 0 or channels <= 0:
        return False
    return frame_len == width * height * channels
