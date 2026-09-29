"""Tulis berkas utuh-atau-tidak-sama-sekali (batch 2.6).

Yang paling penting dibuktikan: listrik padam di tengah tulisan TIDAK
meninggalkan berkas 0 byte dengan nama akhir. Dulu itulah yang terjadi pada
foto dan sidecar, lalu `BatchUploadWorker` mengunggahnya ke R2 dan retensi
menghapus aslinya. Padamnya ditiru dengan `os._exit` di subprocess (pola
`test_batch_upload_crash.py`): tanpa cleanup, tanpa `finally`.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from palmgrade.domain.berkas_utuh import berkas_sementara
from palmgrade.integrations.storage.tulis_atomik import tulis_atomik

_REPO = Path(__file__).resolve().parents[2]

_PADAM_SAAT_GANTI_NAMA = """
import os, sys
from pathlib import Path
from palmgrade.integrations.storage.tulis_atomik import tulis_atomik

def padam(src, dst):
    os._exit(1)  # listrik padam: isi sudah di-fsync, nama akhir belum diganti

os.replace = padam
tulis_atomik(Path(sys.argv[1]), b"isi-foto-lengkap" * 1000)
"""


def _padamkan_saat_menulis(tujuan: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(_REPO / "src")}
    proc = subprocess.run(
        [sys.executable, "-c", _PADAM_SAAT_GANTI_NAMA, str(tujuan)],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr


def test_menulis_isi_dan_tidak_meninggalkan_sementara(tmp_path):
    tujuan = tmp_path / "a.json"
    tulis_atomik(tujuan, b'{"ok": true}')
    assert tujuan.read_bytes() == b'{"ok": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_menimpa_berkas_lama_utuh(tmp_path):
    tujuan = tmp_path / "a.json"
    tujuan.write_bytes(b"lama")
    tulis_atomik(tujuan, b"baru")
    assert tujuan.read_bytes() == b"baru"


def test_membuat_folder_bertingkat(tmp_path):
    tujuan = tmp_path / "results" / "2026-09-28" / "truk" / "bbox" / "Ripe" / "x.webp"
    tulis_atomik(tujuan, b"webp")
    assert tujuan.read_bytes() == b"webp"


def test_padam_di_tengah_tulis_tidak_meninggalkan_berkas_kosong(tmp_path):
    """Review Focus 5."""
    tujuan = tmp_path / "2026-09-28_091432_123456_auto.webp"
    _padamkan_saat_menulis(tujuan)

    assert not tujuan.exists(), "nama akhir muncul walau tulisannya tidak pernah selesai"
    sisa = list(tmp_path.iterdir())
    assert len(sisa) == 1 and berkas_sementara(sisa[0].name)
    assert sisa[0].stat().st_size == len(b"isi-foto-lengkap") * 1000


def test_padam_saat_menimpa_menyisakan_isi_lama(tmp_path):
    tujuan = tmp_path / "a_ripeness.json"
    tujuan.write_bytes(b'{"lama": true}')
    _padamkan_saat_menulis(tujuan)
    assert tujuan.read_bytes() == b'{"lama": true}'


def test_gagal_menulis_membuang_sementara_dan_nama_akhir_tidak_berubah(tmp_path, monkeypatch):
    tujuan = tmp_path / "a.json"
    tujuan.write_bytes(b"lama")

    def disk_penuh(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", disk_penuh)
    with pytest.raises(OSError):
        tulis_atomik(tujuan, b"baru")

    assert tujuan.read_bytes() == b"lama"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_izin_mengikuti_umask_bukan_0600(tmp_path):
    """Konsol (mount read-only) dan teknisi yang menyalin foto harus bisa membacanya."""
    umask = os.umask(0)
    os.umask(umask)
    tujuan = tmp_path / "x.webp"
    tulis_atomik(tujuan, b"webp")
    assert stat.S_IMODE(tujuan.stat().st_mode) == 0o666 & ~umask
