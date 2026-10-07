"""Timbangan dummy switch (2026-10-07): off until support turns it on, carried on the state poll."""
from __future__ import annotations

import logging
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


class _TanpaLine:
    async def assign_truck(self, *args, **kwargs):
        return None


def _svc(tmp_path) -> ConsoleService:
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), _TanpaLine())


def test_mati_sampai_support_menyalakan(tmp_path):
    svc = _svc(tmp_path)
    assert svc.timbangan_dummy() is False
    assert svc.state()["timbangan_dummy"] is False


def test_nyala_tersimpan_ikut_polling_dan_selamat_restart(tmp_path):
    assert _svc(tmp_path).simpan_timbangan_dummy(True, diubah_oleh="sp@pks.test") == {"aktif": True}
    svc = _svc(tmp_path)
    assert svc.timbangan_dummy() is True
    assert svc.state()["timbangan_dummy"] is True


def test_bisa_dimatikan_lagi(tmp_path):
    svc = _svc(tmp_path)
    svc.simpan_timbangan_dummy(True, diubah_oleh="sp@pks.test")
    assert svc.simpan_timbangan_dummy(False, diubah_oleh="sp@pks.test") == {"aktif": False}
    assert svc.timbangan_dummy() is False


def test_perubahan_dicatat_warning_dengan_siapa(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        _svc(tmp_path).simpan_timbangan_dummy(True, diubah_oleh="sp@pks.test")
    assert "sp@pks.test" in caplog.text and "Timbangan dummy NYALA" in caplog.text
