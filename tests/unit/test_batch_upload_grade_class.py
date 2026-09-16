"""Jalur batch (R2 + API cloud) untuk kolom kelas dan verdict yang cacat.

Jalur ini membaca sidecar JSON dari disk berjam-jam sesudah janjangnya lewat, jadi
dia tidak bisa bertanya apa-apa ke line — apa yang tertulis di berkas itu satu-
satunya sumbernya. Dua hal yang dijaga di sini:

- `grade_class` ikut terbaca dari sidecar, dan baris lama yang tidak punya kunci
  itu tetap sah (None), bukan gagal upload.
- verdict cacat jadi `_PoisonError`. Dulu barisnya
  `"Acc" if str(...).lower() == "acc" else "Rej"`, jadi apa pun yang bukan "acc"
  diam-diam terkirim ke cloud sebagai REJ — janjang bagus tercatat dibuang, tanpa
  satu pun peringatan. Poison, bukan ValueError telanjang, supaya satu berkas
  busuk tidak menyandera seluruh batch (CLAUDE.md § Critical Rule 1).
"""
from __future__ import annotations

import json

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker, _PoisonError

TS = "2026-07-10_083000_123456"
DATE = "2026-07-10"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", "palmgrade")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://img.palmgrade.ai")
    monkeypatch.setenv("UPLOAD_API_URL", "https://api.palmgrade.ai")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    worker = BatchUploadWorker(settings=settings, manifest=manifest, uploader=None)
    return settings, manifest, worker


def _sidecar(settings, **over):
    d = settings.results_dir / DATE
    d.mkdir(parents=True, exist_ok=True)
    img = f"{TS}_auto.webp"
    (d / img).write_bytes(b"webp")
    meta = {
        "timestamp": "2026-07-10T08:30:00.123456",
        "image_path": f"captures/results/{DATE}/{img}",
        "ripeness_status": "acc", "ripeness_confidence": 0.91,
        "tp_status": None, "tp_confidence": 0,
        "capture_type": "auto", "truck_id": "t-1",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        "assignment_id": "a-1",
    }
    meta.update(over)
    p = d / f"{TS}_auto_ripeness.json"
    p.write_text(json.dumps(meta))
    return p


def _item(settings, path):
    """`item_key` relatif terhadap artifacts_dir, persis seperti `_scan` menulisnya."""
    return {
        "item_key": str(path.relative_to(settings.artifacts_dir)),
        "event_id": "e-1",
        "r2_key": "k/1.webp",
    }


def test_grade_class_terbaca_dari_sidecar(env):
    settings, manifest, worker = env
    p = _sidecar(settings, grade_class="JK", ripeness_status="rej")
    meta = json.loads(p.read_text())
    assert meta["grade_class"] == "JK"
    # Verdict di berkas tetap biner — kelas tidak menggantikannya.
    assert meta["ripeness_status"] == "rej"


def test_sidecar_lama_tanpa_kelas_tetap_sah(env):
    """Berkas yang ditulis sebelum kolom ini ada masih menunggu di disk pabrik
    (retensi 180 hari). Upload-nya tidak boleh gagal gara-gara kunci yang hilang."""
    settings, _, _ = env
    p = _sidecar(settings)
    meta = json.loads(p.read_text())
    assert "grade_class" not in meta
    from palmgrade.domain.grade_class import grade_class_or_none
    assert grade_class_or_none(meta.get("grade_class")) is None


@pytest.mark.parametrize("busuk", ["JK", "Ripe", "matang", "banana", "ACCC"])
def test_verdict_cacat_jadi_poison_bukan_diam_diam_rej(env, busuk):
    """Termasuk nama KELAS yang keliru ditulis ke kolom verdict — persis salah
    ketik yang paling mungkin terjadi saat menukar model."""
    settings, _, worker = env
    p = _sidecar(settings, ripeness_status=busuk)
    with pytest.raises(_PoisonError):
        worker._build_payload(_item(settings, p))


@pytest.mark.parametrize(
    "verdict,prediction", [("acc", "Acc"), ("ACC", "Acc"), ("rej", "Rej"), ("REJ", "Rej")]
)
def test_verdict_sah_dinormalkan_seperti_jalur_realtime(env, verdict, prediction):
    """Satu kosakata untuk dua jalur: batch dan realtime tidak boleh berbeda
    pendapat soal janjang yang sama."""
    from palmgrade.domain.vision_event import prediction_for, verdict_of
    assert verdict_of(verdict) == verdict.upper()
    assert prediction_for(verdict_of(verdict)) == prediction


def test_payload_batch_membawa_grade_class(env):
    """Yang naik ke cloud harus sama isinya dengan yang dilihat konsol."""
    settings, _, worker = env
    p = _sidecar(settings, grade_class="JK", ripeness_status="rej")
    payload = worker._build_payload(_item(settings, p))
    assert payload["grade_class"] == "JK"
    assert payload["ripeness_status"] == "REJ"
    assert payload["prediction"] == "Rej"


def test_payload_batch_sidecar_lama_grade_class_none(env):
    settings, _, worker = env
    p = _sidecar(settings)
    payload = worker._build_payload(_item(settings, p))
    assert payload["grade_class"] is None
    assert payload["ripeness_status"] == "ACC"
