"""Layar Support Model Deteksi: daftar model, simpan, restart line yang berubah.

Pola yang sama persis dengan `test_console_sumber_kamera.py`. Folder model
berisi checkpoint palsu dari `model_palsu` — tanpa torch.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from model_palsu import EMPAT, LAMA, buat_pt

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.domain.pilihan_model import ModelTidakSah
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services import model_library
from palmgrade.services.console_service import ConsoleService

BAWAAN = {"line-1": "", "line-2": "", "line-3": ""}


class FakeLine:
    def __init__(self, *, down: bool = False) -> None:
        self.restarted: list[str] = []
        self.down = down

    async def restart(self, line):
        if self.down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        self.restarted.append(line.line_code)


@pytest.fixture(autouse=True)
def cache_bersih():
    model_library._CACHE.clear()
    yield
    model_library._CACHE.clear()


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    release = tmp_path / "models" / "release"
    release.mkdir(parents=True)
    (tmp_path / "engines").mkdir()
    buat_pt(release / "best.pt", EMPAT)
    buat_pt(release / "coba.pt", EMPAT)
    buat_pt(release / "lama.pt", LAMA)
    settings = replace(Settings(), factory_tz="Asia/Jakarta", repo_root=tmp_path)
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def _simpan(svc, **pilihan):
    payload = {**BAWAAN, **{k.replace("_", "-"): v for k, v in pilihan.items()}}
    return asyncio.run(svc.simpan_model_deteksi(payload, diubah_oleh="support@x"))


def test_baca_memberi_pilihan_dan_daftar_model(svc):
    hasil = svc.model_deteksi()
    assert hasil["lines"] == BAWAAN
    daftar = {m["berkas"]: m for m in hasil["model"]}
    assert list(daftar) == ["best.pt", "coba.pt", "lama.pt"]
    assert daftar["coba.pt"]["kelas"] == ["JK", "Ripe", "TP", "Unripe"]
    assert daftar["lama.pt"]["cocok"] is False


def test_simpan_menulis_dan_merestart_yang_berubah(svc):
    hasil = _simpan(svc, line_2="coba.pt")

    per_line = {b["line_code"]: b for b in hasil["lines"]}
    assert per_line["line-2"] == {"line_code": "line-2", "direstart": True, "berubah": True}
    assert per_line["line-1"]["berubah"] is False
    assert svc.line_client.restarted == ["line-2"]
    assert svc.model_deteksi()["lines"]["line-2"] == "coba.pt"


def test_tidak_berubah_tidak_merestart(svc):
    _simpan(svc, line_1="coba.pt")
    svc.line_client.restarted.clear()
    hasil = _simpan(svc, line_1="coba.pt")
    assert svc.line_client.restarted == []
    assert all(not b["direstart"] for b in hasil["lines"])


def test_kembali_ke_bawaan_juga_restart(svc):
    _simpan(svc, line_3="coba.pt")
    svc.line_client.restarted.clear()
    _simpan(svc)
    assert svc.line_client.restarted == ["line-3"]
    assert svc.model_deteksi()["lines"]["line-3"] == ""


def test_model_tidak_ada_ditolak_tanpa_menulis(svc, tmp_path):
    with pytest.raises(ModelTidakSah, match="hantu.pt"):
        _simpan(svc, line_1="hantu.pt")
    assert not (tmp_path / "media.env").exists()
    assert svc.line_client.restarted == []


def test_model_kelas_asing_ditolak_menyebut_kelasnya(svc, tmp_path):
    with pytest.raises(ModelTidakSah, match="ACC"):
        _simpan(svc, line_2="lama.pt")
    assert not (tmp_path / "media.env").exists()


def test_payload_cacat_ditolak(svc):
    with pytest.raises(ModelTidakSah, match="line belum diisi"):
        asyncio.run(svc.simpan_model_deteksi({"line-1": ""}, diubah_oleh="x"))


def test_line_diam_tidak_membatalkan_simpan(svc):
    svc.line_client.down = True
    hasil = _simpan(svc, line_2="coba.pt")
    per_line = {b["line_code"]: b for b in hasil["lines"]}
    assert per_line["line-2"]["berubah"] is True
    assert per_line["line-2"]["direstart"] is False
    assert "tidak menjawab" in per_line["line-2"]["alasan"]
    # Berkasnya tetap tersimpan: line membacanya sendiri saat hidup lagi.
    assert svc.model_deteksi()["lines"]["line-2"] == "coba.pt"


def test_simpan_model_tidak_menyentuh_sumber_kamera(svc):
    sebelum = svc.sumber_kamera()["lines"]
    _simpan(svc, line_1="coba.pt")
    assert svc.sumber_kamera()["lines"] == sebelum


def test_baca_menyebut_folder_dan_bahwa_ia_terbaca(svc, tmp_path):
    folder = svc.model_deteksi()["folder"]
    assert folder == {"path": str(tmp_path / "models" / "release"), "terbaca": True}


def test_folder_tak_termount_dibedakan_dari_folder_kosong(svc, tmp_path):
    """Compose PC pabrik hidup di host; lupa menambah mount = folder tidak ada.

    Tanpa pembeda, layar bilang "belum ada berkas .pt" — mengundang orang
    menyalin model lagi, padahal yang kurang mount-nya (review 2026-09-24).
    """
    import shutil

    shutil.rmtree(tmp_path / "models")
    hasil = svc.model_deteksi()
    assert hasil["model"] == []
    assert hasil["folder"]["terbaca"] is False
