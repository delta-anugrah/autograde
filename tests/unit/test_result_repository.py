"""`/api/results_today` membaca sidecar dari disk, bukan basis data.

Sejak 2026-09-20 satu janjang punya SATU sidecar: nilai TP menumpang di berkas
ripeness-nya, dan `_auto_tp.json` tidak pernah ditulis lagi. Pembaca ini dulu
mengambil TP **hanya** dari cabang `_tp`, jadi tanpa berkas kedua dia akan
melaporkan setiap janjang tanpa tangkai panjang — angka yang salah tanpa satu
pun error, di endpoint yang tidak punya test sama sekali sebelum ini.

Murni logic: storage di-stub, tidak menyentuh disk (CLAUDE.md § Tests).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.result_repository import ResultRepository

HARI_INI = datetime.now(UTC).strftime("%Y-%m-%d")
TS = f"{HARI_INI}_091432_123456"


class FakeStorage:
    """Berkas JSON in-memory, dikunci per path seperti `LocalFileStorage`."""

    def __init__(self, berkas: dict[str, dict[str, Any]]) -> None:
        self._berkas = {Path(k): v for k, v in berkas.items()}

    def list_json_files(self, directory: Path) -> list[Path]:
        return sorted(p for p in self._berkas if p.parent == directory)

    def read_json(self, path: Path) -> dict[str, Any]:
        return self._berkas[path]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path)


def _repo(settings: Settings, berkas: dict[str, dict]) -> ResultRepository:
    hari = settings.results_dir / HARI_INI
    return ResultRepository(
        settings=settings,
        storage=FakeStorage({str(hari / nama): isi for nama, isi in berkas.items()}),
    )


def _sidecar(**over) -> dict[str, Any]:
    return {
        "timestamp": f"{HARI_INI}T09:14:32+00:00",
        "image_path": f"captures/results/{HARI_INI}/t/bbox/Ripe/{TS}_auto.webp",
        "machine_id": "m-1",
        "ripeness_status": "ACC",
        "grade_class": "Ripe",
        "ripeness_confidence": 0.91,
        "tp_status": False,
        "tp_confidence": 0,
        "tp_bounding_box": None,
        "capture_type": "auto",
        "truck_id": "truck-1",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        "assignment_id": "a-1",
        "ffb_source": "External",
    } | over


def test_tp_dibaca_dari_sidecar_janjangnya(settings) -> None:
    """Ini yang dijaga: nilai TP ada di berkas ripeness, bukan berkas kedua."""
    repo = _repo(settings, {
        f"{TS}_auto_ripeness.json": _sidecar(tp_status=True, tp_confidence=0.88),
    })

    (hasil,) = repo.list_today_results()

    assert hasil["tp_status"] is True
    assert hasil["tp_confidence"] == 0.88


def test_janjang_tanpa_tangkai_panjang_tetap_terbaca(settings) -> None:
    repo = _repo(settings, {f"{TS}_auto_ripeness.json": _sidecar()})

    (hasil,) = repo.list_today_results()

    assert hasil["tp_status"] is False
    assert hasil["tp_confidence"] == 0
    assert hasil["ripeness_status"] == "ACC"


def test_sidecar_tp_lama_masih_terbaca(settings) -> None:
    """Berkas `_auto_tp.json` tidak ditulis lagi, tapi yang sudah telanjur ada di
    disk pabrik harus tetap terbaca sampai retensi membuangnya — kalau tidak,
    janjang kemarin kehilangan tangkainya pada hari upgrade."""
    repo = _repo(settings, {
        f"{TS}_auto_ripeness.json": _sidecar(),
        f"{TS}_auto_tp.json": {
            "timestamp": f"{HARI_INI}T09:14:32+00:00",
            "tp_status": "PASS",
            "tp_confidence": 0.77,
        },
    })

    (hasil,) = repo.list_today_results()

    assert hasil["tp_confidence"] == 0.77, "berkas TP lama menang atas nol"


def test_capture_manual_tetap_muncul(settings) -> None:
    """Jalur manual menulis `image_url`, bukan `image_path` — beda yang sudah
    ada sejak lama dan sengaja ditangani defensif di sini."""
    repo = _repo(settings, {
        f"{TS}_manual_ripeness.json": {
            "timestamp": f"{HARI_INI}T09:14:32+00:00",
            "image_url": f"captures/results/{HARI_INI}/t/bbox/unknown/{TS}_manual.webp",
            "ripeness_status": "rej",
            "ripeness_confidence": 1.0,
            "tp_status": False,
            "tp_confidence": 0,
            "tp_bounding_box": None,
            "capture_type": "manual",
            "truck_id": None,
            "bounding_box": {"x_min": 0, "y_min": 0, "x_max": 9, "y_max": 9},
        },
    })

    (hasil,) = repo.list_today_results()

    assert hasil["ripeness_status"] == "rej"
    assert hasil["image_url"].endswith("_manual.webp")
