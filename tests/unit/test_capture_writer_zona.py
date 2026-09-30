"""`CaptureWriter._mill_zone`: zona pabrik yang tidak bisa dipakai jatuh ke UTC.

Nama folder zona (`FACTORY_TZ=Asia`) lewat paket `tzdata` melempar
IsADirectoryError, bukan ZoneInfoNotFoundError. Tanpa ditangkap, janjang yang
sudah digrading tidak tersimpan sama sekali.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

from palmgrade.services import capture_writer
from palmgrade.services.capture_writer import CaptureWriter


def _zona_berupa_folder(nama):
    raise IsADirectoryError(21, "Is a directory", nama)


def test_zona_berupa_folder_jatuh_ke_utc(monkeypatch):
    monkeypatch.setattr(capture_writer, "ZoneInfo", _zona_berupa_folder)
    penulis = CaptureWriter(SimpleNamespace(factory_tz="Asia"), storage=None)
    assert penulis._mill_zone() is datetime.UTC


def test_zona_sah_tetap_dipakai():
    penulis = CaptureWriter(SimpleNamespace(factory_tz="Asia/Jakarta"), storage=None)
    assert str(penulis._mill_zone()) == "Asia/Jakarta"
