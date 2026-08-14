"""Jalur realtime edge: hasil grading harus nyampe API lokal seketika.

Di PC pabrik, operator butuh lihat Grading History **saat itu juga** — bukan
nunggu batch R2 jam berikutnya. Jalurnya:

    capture → outbox (SQLite) → OutboxRetryWorker (poll 1 detik)
        → POST {BACKEND_URL}/internal/vision/events → broadcastEvent → SSE → FE

Batch upload ke R2 (UPLOAD_API_URL, cloud) jalan terpisah dan tidak disentuh.

Test ini murni-logic: CI vision sengaja tidak install numpy/torch/cv2, jadi
payload-nya dibangun di `domain/vision_event.py` yang bebas dependensi berat,
dan dua call site-nya dijaga lewat pembacaan teks.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from palmgrade.domain.vision_event import build_event_payload, event_id_for

MACHINE_ID = "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01"
FILE_TS = "2026-08-13_095949_366673"
IMAGE_PATH = f"captures/results/2026-08-13/{FILE_TS}_manual.webp"
SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"


def _payload(**overrides):
    base = dict(
        machine_id=MACHINE_ID,
        file_ts=FILE_TS,
        timestamp="2026-08-13T09:59:49.366673+00:00",
        ripeness_status="rej",
        ripeness_confidence=1.0,
        capture_type="manual",
        image_path=IMAGE_PATH,
        truck_id="truck-7",
        assignment_id="assign-1",
        bounding_box={"x_min": 0, "y_min": 0, "x_max": 4, "y_max": 4},
    )
    base.update(overrides)
    return build_event_payload(**base)


# --------------------------------------------------------------- idempotensi

def test_event_id_deterministik_dari_timestamp_file() -> None:
    """Rumus yang sama dengan batch upload → POST ulang dibalas
    `already_processed`, bukan bikin baris dobel. uuid4 (versi lama capture
    manual) tidak punya jaminan itu: crash lalu retry = tonase dobel."""
    assert _payload()["event_id"] == event_id_for(MACHINE_ID, FILE_TS)
    assert _payload()["event_id"] == _payload()["event_id"]
    assert _payload()["event_id"] == str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{MACHINE_ID}:{FILE_TS}")
    )


def test_line_lain_di_detik_yang_sama_tidak_bentrok() -> None:
    a = _payload(machine_id="line-1")["event_id"]
    b = _payload(machine_id="line-2")["event_id"]
    assert a != b


# ------------------------------------------------------------------- gambar

def test_image_path_tetap_relatif_supaya_bisa_di_serve_api_lokal() -> None:
    """palmgrade-api merakitnya jadi `{apiPrefix}/captures/{line_code}/...`
    lewat `resolveCaptureUrl`, dan meng-serve folder artifacts vision yang
    di-mount read-only. URL absolut melewati perakitan itu → gambar mati di
    pabrik yang lagi offline."""
    p = _payload()
    assert p["image_path"] == IMAGE_PATH
    assert not p["image_path"].startswith("http")


# ------------------------------------------------------------------ kontrak

@pytest.mark.parametrize(
    "status,prediction,normalized",
    [("acc", "Acc", "ACC"), ("rej", "Rej", "REJ"), ("ACC", "Acc", "ACC")],
)
def test_prediction_dan_status_dinormalkan(status, prediction, normalized) -> None:
    p = _payload(ripeness_status=status)
    assert p["prediction"] == prediction
    assert p["ripeness_status"] == normalized


def test_payload_bawa_field_yang_diminta_api() -> None:
    p = _payload()
    assert set(p) == {
        "event_id",
        "machine_id",
        "assignment_id",
        "truck_id",
        "timestamp",
        "prediction",
        "ripeness_status",
        "ripeness_confidence",
        "tp_status",
        "tp_confidence",
        "capture_type",
        "image_path",
        "bounding_box",
    }
    assert p["capture_type"] == "manual"
    assert p["truck_id"] == "truck-7"
    assert p["assignment_id"] == "assign-1"


def test_confidence_dibulatkan_dua_desimal() -> None:
    p = _payload(ripeness_confidence=0.876543, tp_confidence=0.123456)
    assert p["ripeness_confidence"] == 0.88
    assert p["tp_confidence"] == 0.12


def test_tanpa_tp_snapshot_confidence_nol_bukan_none() -> None:
    """API mem-validasi `tp_confidence` sebagai angka."""
    p = _payload()
    assert p["tp_status"] is None
    assert p["tp_confidence"] == 0


def test_tanpa_truck_tetap_dibangun() -> None:
    """Capture reject sering ditekan sebelum truk di-assign. API punya
    `TruckResolver.resolveOrStub`, jadi event tanpa truck tetap tercatat.
    Membuangnya = operator menekan tombol dan tidak terjadi apa-apa."""
    assert _payload(truck_id=None)["truck_id"] is None


# ------------------------------------------------- guard: jalurnya masih hidup
# Dibaca sebagai teks supaya test tidak menarik torch/cv2/numpy.

def _live_lines(path: Path, needle: str) -> list[str]:
    return [
        ln
        for ln in path.read_text().splitlines()
        if needle in ln and not ln.strip().startswith("#")
    ]


@pytest.mark.parametrize(
    "relpath",
    ["services/capture_service.py", "workers/frame_processing_worker.py"],
)
def test_kedua_call_site_menulis_ke_outbox(relpath: str) -> None:
    """Regresi 2026-07-10: blok ini pernah dikomentari untuk batch-upload-r2,
    akibatnya Capture Reject balas `{"accepted":true}` tapi Grading History
    tidak pernah bertambah."""
    assert _live_lines(SRC / relpath, "outbox_store.add_event")
    assert _live_lines(SRC / relpath, "build_event_payload(")
    # Import-nya ikut dijaga: memanggilnya tanpa mengimpor lolos test teks tapi
    # NameError saat runtime — persis yang kejadian waktu fitur ini dipasang.
    assert _live_lines(SRC / relpath, "import build_event_payload")


def test_outbox_retry_worker_dinyalakan_di_main() -> None:
    """Outbox terisi tapi tidak ada yang mengirim = diam-diam mati."""
    assert _live_lines(SRC / "main.py", '_start_worker("outbox_retry"')
