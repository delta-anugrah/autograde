"""`/health/detail` tidak boleh melapor antrean kosong kalau antrean lama belum terserap.

Sejak batch 1 `outbox.db` pindah dari `artifacts/` ke `state/`. Kalau penyerapan
gagal (berkas rusak, disk penuh, `MemoryError`), barisnya tetap di berkas lama
yang tidak dihitung `pending_count()`. Danger Zone dan `autograde reset-data` di
host sama-sama membaca `outbox_pending`: nol palsu di sini membuat keduanya
menganggap aman menghapus janjang yang belum pernah sampai ke konsol.

`get_health_detail()` mengimpor torch, jadi yang diuji di CI potongan murninya.
"""
from __future__ import annotations

from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.schemas.common_schema import HealthDetailSchema
from palmgrade.services.health_service import HealthService


class _Outbox:
    def pending_count(self) -> int:
        return 3

    def failed_count(self) -> int:
        return 1


def _service(tmp_path, folder_db) -> HealthService:
    settings = replace(Settings(), repo_root=tmp_path)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return HealthService(
        settings=settings, state=None, camera=None, outbox=_Outbox(), folder_db=folder_db
    )


def test_tanpa_sisa_angka_antrean_apa_adanya(tmp_path):
    svc = _service(tmp_path, tmp_path / "state")
    assert svc.ringkasan_outbox() == {
        "outbox_pending": 3, "outbox_failed": 1, "outbox_lama_tertinggal": False,
    }


def test_sisa_outbox_lama_membuat_pending_tidak_diketahui(tmp_path):
    """`None`, bukan angka: berapa baris di berkas lama tidak diketahui (bisa
    justru karena tidak terbaca). Host `autograde reset-data` mengenali angka
    saja, jadi `None` terbaca "tidak diketahui" dan menolak menghapus."""
    svc = _service(tmp_path, tmp_path / "state")
    (svc.settings.artifacts_dir / "outbox.db").write_bytes(b"sisa")

    assert svc.ringkasan_outbox() == {
        "outbox_pending": None, "outbox_failed": 1, "outbox_lama_tertinggal": True,
    }


def test_folder_db_di_artifacts_bukan_sisa(tmp_path):
    svc = _service(tmp_path, tmp_path / "artifacts")
    (svc.settings.artifacts_dir / "outbox.db").write_bytes(b"antrean hidup")

    assert svc.ringkasan_outbox()["outbox_lama_tertinggal"] is False
    assert svc.ringkasan_outbox()["outbox_pending"] == 3


def test_skema_membawa_sisa_dan_pending_kosong():
    detail = HealthDetailSchema(
        status="ok", environment="test", camera_type="opencv", camera_connected=True,
        gpu_available=False, gpu_device=None, machine_id="m", workers=[],
        outbox_pending=None, outbox_failed=0, outbox_lama_tertinggal=True,
    )
    dump = detail.model_dump()
    assert dump["outbox_pending"] is None
    assert dump["outbox_lama_tertinggal"] is True
    # Bawaan tetap nol dan False untuk line yang sehat.
    bawaan = HealthDetailSchema(
        status="ok", environment="test", camera_type="opencv", camera_connected=True,
        gpu_available=False, gpu_device=None, machine_id="m", workers=[],
    )
    assert bawaan.outbox_pending == 0
    assert bawaan.outbox_lama_tertinggal is False
