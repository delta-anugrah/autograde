"""Payload event grading yang dikirim ke palmgrade-api.

Dipakai tiga jalur yang harus sepakat soal bentuk & identitas event:

- capture manual (`services/capture_service.py`)
- deteksi otomatis (`workers/frame_processing_worker.py`)
- batch upload R2 (`workers/batch_upload_worker.py`) — lewat `event_id_for`

Modul ini sengaja bebas numpy/torch/cv2 supaya bisa dites di CI yang ringan.
"""
from __future__ import annotations

import uuid
from typing import Any


def event_id_for(machine_id: str, file_ts: str) -> str:
    """Identitas event = machine + timestamp file (unik per detik per line).

    Deterministik, jadi frame yang diproses ulang setelah crash menghasilkan
    id yang sama → palmgrade-api membalas `already_processed` dan tonase tidak
    terhitung dua kali. Mengubah rumus ini memutus idempotensi terhadap semua
    baris yang sudah terkirim.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{machine_id}:{file_ts}"))


def build_event_payload(
    *,
    machine_id: str,
    file_ts: str,
    timestamp: str,
    ripeness_status: str,
    ripeness_confidence: float,
    capture_type: str,
    image_path: str,
    truck_id: str | None,
    assignment_id: str | None,
    bounding_box: dict[str, Any] | None = None,
    tp_status: str | None = None,
    tp_confidence: float | None = None,
) -> dict[str, Any]:
    """`image_path` HARUS relatif (`captures/results/<tgl>/<file>.webp`).

    palmgrade-api merakitnya jadi `{apiPrefix}/captures/{line_code}/...` dan
    meng-serve folder artifacts vision yang di-mount read-only — itu satu-satunya
    cara gambar tetap kelihatan di pabrik saat internet mati. URL absolut (R2)
    hanya dipakai jalur batch upload ke cloud.
    """
    status = ripeness_status.upper()
    return {
        "event_id": event_id_for(machine_id, file_ts),
        "machine_id": machine_id,
        "assignment_id": assignment_id,
        "truck_id": truck_id,
        "timestamp": timestamp,
        "prediction": "Acc" if status == "ACC" else "Rej",
        "ripeness_status": status,
        "ripeness_confidence": round(ripeness_confidence, 2),
        "tp_status": tp_status,
        "tp_confidence": round(tp_confidence, 2) if tp_confidence else 0,
        "capture_type": capture_type,
        "image_path": image_path,
        "bounding_box": bounding_box or {},
    }
