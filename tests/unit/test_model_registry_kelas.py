"""Kelas model diperiksa untuk KEDUA backend, bukan cuma `.pt`.

Dulu `_warn_on_unexpected_classes` hanya jalan di jalur `.pt`. Line yang
memakai engine TensorRT — yaitu setiap PC pabrik — tidak pernah memeriksa
kelas modelnya, jadi engine hasil model lama dimuat tanpa satu pun ERROR.
Layar Model Deteksi memperbesar peluang salah pasang, jadi lubang ini ditutup
bersamaan.

Butuh torch + ultralytics (diimpor `model_registry` di level modul), jadi
dilewati di CI dan jalan di mesin pengembang yang memasangnya.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import pytest

pytest.importorskip("torch")
pytest.importorskip("ultralytics")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.pipelines import model_registry  # noqa: E402


class FakeYolo:
    """Pengganti `ultralytics.YOLO`: mencatat apa yang dimuat, tanpa GPU."""

    dimuat: list[str] = []
    names: dict = {}

    def __init__(self, path, task=None) -> None:
        FakeYolo.dimuat.append(str(path))

    def predict(self, *_a, **_k):
        return []

    def to(self, *_a):
        return self

    def half(self):
        return self


@pytest.fixture
def registry_palsu(tmp_path, monkeypatch):
    engines = tmp_path / "engines"
    release = tmp_path / "models" / "release"
    engines.mkdir()
    release.mkdir(parents=True)
    (release / "coba.pt").write_bytes(b"pt")
    FakeYolo.dimuat = []
    monkeypatch.setattr(model_registry, "YOLO", FakeYolo)
    monkeypatch.setattr(model_registry.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(model_registry.torch.cuda, "get_device_capability", lambda _i=0: (8, 6))
    monkeypatch.delenv("MEDIA_ENV_PATH", raising=False)
    settings = replace(Settings(), repo_root=tmp_path, model_file="coba.pt")
    return settings, engines


def test_engine_berkelas_asing_diadukan_error(registry_palsu, monkeypatch, caplog):
    settings, engines = registry_palsu
    (engines / "coba.sm86.engine").write_bytes(b"engine")
    monkeypatch.setattr(FakeYolo, "names", {0: "ACC", 1: "Rej", 2: "TP"})

    with caplog.at_level(logging.INFO, logger=model_registry.__name__):
        reg = model_registry.ModelRegistry(settings)

    assert reg.backend == "tensorrt"
    assert FakeYolo.dimuat == [str(engines / "coba.sm86.engine")]
    assert "Kelas model tidak seperti yang diharapkan" in caplog.text


def test_ringkasan_menyebut_berkas_backend_dan_kelas(registry_palsu, monkeypatch):
    settings, engines = registry_palsu
    (engines / "coba.sm86.engine").write_bytes(b"engine")
    monkeypatch.setattr(FakeYolo, "names", {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"})

    reg = model_registry.ModelRegistry(settings)

    assert reg.ringkasan() == {
        "model_file": "coba.pt",
        "model_backend": "tensorrt",
        "model_kelas": ["JK", "Ripe", "TP", "Unripe"],
    }


def test_tanpa_engine_jalur_pt_tetap_diperiksa(registry_palsu, monkeypatch, caplog):
    settings, _engines = registry_palsu
    monkeypatch.setattr(FakeYolo, "names", {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"})

    with caplog.at_level(logging.INFO, logger=model_registry.__name__):
        reg = model_registry.ModelRegistry(settings)

    assert reg.backend == "pytorch"
    assert "Kelas model terverifikasi" in caplog.text
    assert reg.ringkasan()["model_backend"] == "pytorch"
