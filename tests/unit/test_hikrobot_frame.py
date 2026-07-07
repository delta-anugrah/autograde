"""Unit tests for Hikrobot frame-length validation (M5).

GigE packet loss produces partial frames. Reshaping a partial buffer raises
ValueError deep in grab_frame → caught as "unhandled" in the worker loop with a
1s sleep penalty (capture stalls, log noise). _validate_frame_len is the pure
guard used before every reshape so a corrupt frame is dropped cleanly (return
None) instead. No numpy/cv2/SDK needed — pure integer check.
"""
from __future__ import annotations

from palmgrade.integrations.camera.frame_utils import _validate_frame_len


def test_exact_mono_length_is_valid():
    # Mono8 / Bayer = 1 byte per pixel.
    assert _validate_frame_len(frame_len=2448 * 2048, width=2448, height=2048, channels=1) is True


def test_exact_rgb_length_is_valid():
    assert _validate_frame_len(frame_len=2448 * 2048 * 3, width=2448, height=2048, channels=3) is True


def test_short_frame_is_invalid():
    # Partial frame from packet loss → fewer bytes than expected.
    assert _validate_frame_len(frame_len=1000, width=2448, height=2048, channels=1) is False


def test_long_frame_is_invalid():
    assert _validate_frame_len(frame_len=2448 * 2048 + 5, width=2448, height=2048, channels=1) is False


def test_rgb_length_with_mono_channels_is_invalid():
    # Same pixels but wrong channel assumption must not pass.
    assert _validate_frame_len(frame_len=2448 * 2048 * 3, width=2448, height=2048, channels=1) is False


def test_zero_dimensions_is_invalid():
    assert _validate_frame_len(frame_len=0, width=0, height=0, channels=3) is False
