"""Unit tests untuk gerbang lisensi thread grading.

Ini gerbang yang benar-benar menghentikan pabrik. Middleware HTTP saja tidak
cukup: grading jalan di thread background, tidak lewat login dan tidak lewat
HTTP — kalau cuma middleware yang menjaga, operator tidak bisa membuka
dashboard TAPI kamera tetap mendeteksi dan PLC tetap menyortir buah.
"""
from __future__ import annotations

import time

from palmgrade.license.gate import grading_blocked

NOW = 1_700_000_000.0


def test_disabled_feature_never_blocks():
    # PC dev / cloud / pabrik yang belum dilisensi: persis seperti sebelum
    # fitur ini ada, walau license_exp-nya 0.
    assert grading_blocked(False, 0, now=NOW) is False


def test_no_license_blocks():
    # Fail closed: token tidak ada atau tidak bisa diverifikasi.
    assert grading_blocked(True, 0, now=NOW) is True


def test_past_grace_end_blocks():
    assert grading_blocked(True, int(NOW) - 1, now=NOW) is True


def test_inside_grace_runs():
    assert grading_blocked(True, int(NOW) + 3600, now=NOW) is False


def test_defaults_to_wall_clock():
    assert grading_blocked(True, int(time.time()) + 3600) is False
    assert grading_blocked(True, int(time.time()) - 3600) is True
