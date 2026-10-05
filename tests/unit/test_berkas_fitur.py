"""Which `.mfs` a line pushes to its camera at each connect (spec §3.1, changed after phase 0).

Lampung sets `LINE_n_FEATURE_FILE=models/01102026.mfs`; the first draft let that win, which would have ignored
every save from the console. Now the saved file wins, and the configured file is the baseline.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from ai_palsu import KameraPalsu

from palmgrade.core.config import Settings
from palmgrade.integrations.camera.berkas_fitur import berkas_tersimpan, pilih_berkas_fitur
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState

BAKU = "models/01102026.mfs"


def test_tanpa_folder_selalu_baku():
    assert pilih_berkas_fitur(None, "line-1", BAKU) == BAKU
    assert berkas_tersimpan(None, "line-1") is None


def test_folder_tanpa_berkas_line_ini_baku(tmp_path):
    (tmp_path / "line-2.mfs").write_text("x")
    assert pilih_berkas_fitur(tmp_path, "line-1", BAKU) == BAKU


def test_berkas_tersimpan_menang(tmp_path):
    (tmp_path / "line-1.mfs").write_text("x")
    assert pilih_berkas_fitur(tmp_path, "line-1", BAKU) == str(tmp_path / "line-1.mfs")


def test_tanpa_baku_dan_tanpa_simpanan_none(tmp_path):
    assert pilih_berkas_fitur(tmp_path, "line-1", None) is None


def test_env_kosong_berarti_mati(monkeypatch):
    monkeypatch.delenv("CAMERA_SETELAN_DIR", raising=False)
    assert Settings().camera_setelan_dir is None
    monkeypatch.setenv("CAMERA_SETELAN_DIR", "  ")
    assert Settings().camera_setelan_dir is None
    monkeypatch.setenv("CAMERA_SETELAN_DIR", "/config/camera")
    assert Settings().camera_setelan_dir == Path("/config/camera")


class _KameraCatat(KameraPalsu):
    def __init__(self) -> None:
        super().__init__()
        self.berkas: list[str | None] = []

    def connect(self, index=0, serial=None, feature_file=None) -> None:
        self.berkas.append(feature_file)
        super().connect(index, serial, feature_file)


def test_tiap_sambung_memilih_ulang_dan_mencatat_yang_dipakai(tmp_path):
    """Saved after the line started: the next reconnect picks it up, no restart needed."""
    kamera, state = _KameraCatat(), RuntimeState()
    worker = FrameCaptureWorker(camera=kamera, state=state, feature_file=BAKU, setelan_dir=tmp_path, line_code="line-1")
    worker._sambung_kamera()
    (tmp_path / "line-1.mfs").write_text("x")
    worker._sambung_kamera()
    assert kamera.berkas == [BAKU, str(tmp_path / "line-1.mfs")]
    assert state.berkas_fitur_aktif == str(tmp_path / "line-1.mfs")
    assert os.path.basename(state.berkas_fitur_aktif) == "line-1.mfs"


def test_worker_lama_tanpa_folder_tetap_baku():
    kamera = _KameraCatat()
    FrameCaptureWorker(camera=kamera, state=RuntimeState(), feature_file=BAKU)._sambung_kamera()
    assert kamera.berkas == [BAKU]


def test_settings_replace_tetap_jalan(tmp_path):
    assert replace(Settings(), camera_setelan_dir=tmp_path).camera_setelan_dir == tmp_path
