"""`/health/detail` melaporkan model yang BENAR-BENAR dimuat line.

Layar Model Deteksi menyandingkan pilihan di `media.env` dengan yang sedang
jalan. Tanpa ini tidak ada yang bisa membedakan "sudah dipilih" dari "sudah
berlaku" — persis kebutaan yang membuat Lampung seminggu memakai model lama.

`get_health_detail()` mengimpor torch, jadi yang diuji di CI adalah
potongan murninya: ringkasan model dan skemanya.
"""
from __future__ import annotations

from palmgrade.core.config import Settings
from palmgrade.schemas.common_schema import HealthDetailSchema
from palmgrade.services.health_service import HealthService


class FakeModel:
    def ringkasan(self) -> dict:
        return {
            "model_file": "coba.pt",
            "model_backend": "tensorrt",
            "model_kelas": ["JK", "Ripe", "TP", "Unripe"],
            "model_kelas_cocok": True,
        }


def _service(model=None) -> HealthService:
    return HealthService(settings=Settings(), state=None, camera=None, outbox=None, model=model)


def test_ringkasan_model_dari_registry():
    assert _service(FakeModel()).ringkasan_model() == FakeModel().ringkasan()


def test_tanpa_registry_ringkasan_kosong():
    # Registry belum dimuat: jangan memuatnya dari jalur health.
    assert _service().ringkasan_model() == {
        "model_file": None,
        "model_backend": None,
        "model_kelas": [],
        "model_kelas_cocok": None,
    }


def test_skema_menerima_ringkasan_model():
    detail = HealthDetailSchema(
        status="ok",
        environment="test",
        camera_type="opencv",
        camera_connected=True,
        gpu_available=False,
        gpu_device=None,
        machine_id="m",
        workers=[],
        **FakeModel().ringkasan(),
    )
    assert detail.model_backend == "tensorrt"
    assert detail.model_dump()["model_kelas"] == ["JK", "Ripe", "TP", "Unripe"]


def test_skema_bawaan_tanpa_model():
    detail = HealthDetailSchema(
        status="ok",
        environment="test",
        camera_type="opencv",
        camera_connected=True,
        gpu_available=False,
        gpu_device=None,
        machine_id="m",
        workers=[],
    )
    assert detail.model_file is None
    assert detail.model_kelas == []
    # None = tidak diketahui (registry belum dimuat / line versi lama), BUKAN
    # "tidak cocok": layar tidak boleh menyalakan alarm kelas untuk itu.
    assert detail.model_kelas_cocok is None


def test_skema_membawa_alarm_kelas():
    detail = HealthDetailSchema(
        status="ok",
        environment="test",
        camera_type="opencv",
        camera_connected=True,
        gpu_available=False,
        gpu_device=None,
        machine_id="m",
        workers=[],
        model_file="best.pt",
        model_backend="tensorrt",
        model_kelas=["ACC", "Rej", "TP"],
        model_kelas_cocok=False,
    )
    assert detail.model_dump()["model_kelas_cocok"] is False
