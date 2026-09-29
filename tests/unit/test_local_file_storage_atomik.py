"""Foto bukti dan sidecar tidak pernah tertinggal 0 byte dengan nama sah (batch 2.6).

Butuh cv2 + numpy (encode WebP sungguhan). CI memasang `opencv-python-headless`
(`requirements-ci.txt`), jadi berkas ini jalan di sana.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from palmgrade.domain.berkas_utuh import berkas_sementara  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]

_PADAM_SAAT_MENULIS_FOTO = """
import os, sys
from pathlib import Path
import numpy as np
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage

def padam(src, dst):
    os._exit(1)

os.replace = padam
frame = np.full((64, 96, 3), 120, dtype=np.uint8)
LocalFileStorage().write_image(Path(sys.argv[1]), frame, quality=65)
"""


@pytest.fixture
def frame():
    return np.random.default_rng(0).integers(0, 255, (64, 96, 3), dtype=np.uint8)


def test_foto_webp_terbaca_ulang_dan_tanpa_sisa_sementara(tmp_path, frame):
    tujuan = tmp_path / "bbox" / "Ripe" / "2026-09-28_091432_123456_auto.webp"
    LocalFileStorage().write_image(tujuan, frame, quality=65)

    terbaca = cv2.imread(str(tujuan))
    assert terbaca is not None and terbaca.shape == frame.shape
    assert [p.name for p in tujuan.parent.iterdir()] == [tujuan.name]


def test_sidecar_ditulis_utuh(tmp_path):
    tujuan = tmp_path / "2026-09-28" / "2026-09-28_091432_123456_auto_ripeness.json"
    LocalFileStorage().write_json(tujuan, {"ripeness_status": "ACC"})
    assert json.loads(tujuan.read_text(encoding="utf-8")) == {"ripeness_status": "ACC"}
    assert [p.name for p in tujuan.parent.iterdir()] == [tujuan.name]


def test_encode_gagal_jadi_oserror_tanpa_berkas(tmp_path):
    """Critical Rule #8: gambar yang tidak tertulis = OSError, bukan cv2.error."""
    tujuan = tmp_path / "x.webp"
    with pytest.raises(OSError):
        LocalFileStorage().write_image(tujuan, np.zeros((0, 0, 3), dtype=np.uint8))
    assert list(tmp_path.iterdir()) == []


def test_disk_penuh_tidak_meninggalkan_berkas_kosong(tmp_path, frame, monkeypatch):
    tujuan = tmp_path / "x.webp"

    def disk_penuh(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", disk_penuh)
    with pytest.raises(OSError):
        LocalFileStorage().write_image(tujuan, frame)
    assert list(tmp_path.iterdir()) == []


def test_padam_saat_menulis_foto_tidak_meninggalkan_foto_kosong(tmp_path):
    """Review Focus 5 di tingkat `LocalFileStorage.write_image`, yang dipanggil
    `CaptureWriter`. `CaptureWriter` sendiri tidak dilewati di sini; jalur lengkapnya
    (penulis bukti sampai sidecar) di `tests/e2e/test_bukti_tahan_listrik_padam.py`."""
    tujuan = tmp_path / "2026-09-28_091432_123456_auto.webp"
    env = {**os.environ, "PYTHONPATH": str(_REPO / "src")}
    proc = subprocess.run(
        [sys.executable, "-c", _PADAM_SAAT_MENULIS_FOTO, str(tujuan)],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr

    assert not tujuan.exists()
    sisa = list(tmp_path.iterdir())
    assert len(sisa) == 1 and berkas_sementara(sisa[0].name)
