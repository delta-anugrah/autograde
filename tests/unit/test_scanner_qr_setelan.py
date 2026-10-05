"""Scanner QR switch (2026-10-05): off until support turns it on, carried on the state poll.

The four QR fields on the Timbangan tab ship `hidden`; this setting is what shows them.
"""
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
    assert svc.scanner_qr() is False
    assert svc.state()["scanner_qr"] is False


def test_nyala_tersimpan_dan_ikut_polling(tmp_path):
    svc = _svc(tmp_path)
    assert svc.simpan_scanner_qr(True, diubah_oleh="sp@pks.test") == {"aktif": True}
    assert svc.scanner_qr() is True
    assert svc.state()["scanner_qr"] is True


def test_bisa_dimatikan_lagi(tmp_path):
    svc = _svc(tmp_path)
    svc.simpan_scanner_qr(True, diubah_oleh="sp@pks.test")
    assert svc.simpan_scanner_qr(False, diubah_oleh="sp@pks.test") == {"aktif": False}
    assert svc.scanner_qr() is False


def test_selamat_dari_restart_konsol(tmp_path):
    _svc(tmp_path).simpan_scanner_qr(True, diubah_oleh="sp@pks.test")
    assert _svc(tmp_path).scanner_qr() is True


def test_perubahan_dicatat_dengan_siapa(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        _svc(tmp_path).simpan_scanner_qr(True, diubah_oleh="sp@pks.test")
    assert "sp@pks.test" in caplog.text and "NYALA" in caplog.text
