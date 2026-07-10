"""Batch upload worker — kirim hasil deteksi (gambar + teks) ke cloud tiap jam.

Alur per tick (spec 2026-07-10 §3.3): scan → proses per item (gambar dulu ke
R2, lalu POST teks ke API cloud) → retensi. State per item hidup di
UploadManifest; worker ini stateless antar tick.

Klasifikasi kegagalan (spec §5):
- _RequeueError  → kondisi eksternal rusak (jaringan/5xx/429/401/403/404):
  requeue item + BREAK batch (percuma lanjut; sisa antrean nunggu tick berikut).
- _PoisonError   → input cacat (JSON korup/field hilang/gambar hilang):
  poisoned + CONTINUE (satu item busuk tidak menyandera batch). File TIDAK dihapus.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..core.config import Settings
from ..integrations.upload.r2_uploader import R2Uploader, build_r2_key
from ..integrations.upload.upload_manifest import UploadManifest

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # payload teks kecil; 30s aman utk link pabrik lambat

_RIPENESS_SUFFIXES = ("_auto_ripeness.json", "_manual_ripeness.json")
_TP_SUFFIX = "_auto_tp.json"


class _PoisonError(Exception):
    """Input cacat — retry tidak akan menolong; item di-skip permanen."""


class _RequeueError(Exception):
    """Kondisi eksternal rusak — item diantre ulang, batch berhenti dulu."""


def file_timestamp(json_name: str) -> str:
    for suffix in (*_RIPENESS_SUFFIXES, _TP_SUFFIX):
        if json_name.endswith(suffix):
            return json_name.removesuffix(suffix)
    raise ValueError(f"Bukan nama file hasil deteksi: {json_name}")


def event_id_for(machine_id: str, file_ts: str) -> str:
    # Rumus PERSIS sama dgn outbox lama (frame_processing_worker) → POST ulang
    # event yang pernah terkirim dibalas already_processed, bukan row baru.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{machine_id}:{file_ts}"))


class BatchUploadWorker:
    def __init__(
        self,
        settings: Settings,
        manifest: UploadManifest,
        uploader: R2Uploader | None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.manifest = manifest
        self.uploader = uploader
        self._client = http_client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        self._warned_noop = False

    # ---------------------------------------------------------------- discovery

    def _read_meta(self, json_path: Path) -> dict[str, Any]:
        try:
            return json.loads(json_path.read_text())
        except FileNotFoundError as exc:
            raise _PoisonError(f"JSON hilang: {json_path}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _PoisonError(f"JSON korup: {json_path}: {exc}") from exc

    def _image_ref(self, meta: dict[str, Any]) -> str | None:
        # auto pakai "image_path", manual pakai "image_url" (capture_repository)
        return meta.get("image_path") or meta.get("image_url")

    def _scan(self) -> None:
        artifacts = self.settings.artifacts_dir
        results = self.settings.results_dir
        if not results.exists():
            return
        for json_path in sorted(results.glob("*/*_ripeness.json")):
            item_key = str(json_path.relative_to(artifacts))
            if self.manifest.has_item(item_key):
                continue
            ts = file_timestamp(json_path.name)
            image_path = None
            r2_key = None
            try:
                image_path = self._image_ref(self._read_meta(json_path))
            except _PoisonError:
                pass  # item tetap dibuat; poison ketahuan saat build payload
            if image_path:
                r2_key = build_r2_key(self.settings.machine_id, image_path)
            self.manifest.upsert_item(
                item_key,
                event_id=event_id_for(self.settings.machine_id, ts),
                image_path=image_path,
                r2_key=r2_key,
            )
        for tp_path in sorted(results.glob(f"*/*{_TP_SUFFIX}")):
            sibling = tp_path.with_name(
                tp_path.name.replace(_TP_SUFFIX, "_auto_ripeness.json")
            )
            if sibling.exists():
                continue  # digabung ke item ripeness-nya (merge saat build)
            item_key = str(tp_path.relative_to(artifacts))
            if self.manifest.has_item(item_key):
                continue
            ts = file_timestamp(tp_path.name)
            self.manifest.upsert_item(
                item_key,
                event_id=event_id_for(self.settings.machine_id, ts),
                image_path=None,
                r2_key=None,
            )

    # ---------------------------------------------------------------- payload

    def _build_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        artifacts = self.settings.artifacts_dir
        json_path = artifacts / item["item_key"]

        if json_path.name.endswith(_TP_SUFFIX):
            # Item tp yatim: coba pasangan ripeness yang muncul belakangan.
            sibling = json_path.with_name(
                json_path.name.replace(_TP_SUFFIX, "_auto_ripeness.json")
            )
            if not sibling.exists():
                raise _PoisonError(
                    f"tp tanpa pasangan ripeness — payload tak bisa direkonstruksi: {json_path}"
                )
            json_path = sibling  # merge penuh; event_id sama → already_processed

        meta = self._read_meta(json_path)
        ripeness_status = meta.get("ripeness_status")
        if not ripeness_status:
            raise _PoisonError(f"ripeness_status hilang: {json_path}")

        image_ref = self._image_ref(meta)
        if not image_ref:
            raise _PoisonError(f"image_path hilang: {json_path}")
        r2_key = item["r2_key"] or build_r2_key(self.settings.machine_id, image_ref)

        tp_status = meta.get("tp_status")
        tp_confidence = meta.get("tp_confidence", 0)
        tp_path = json_path.with_name(
            json_path.name.replace("_auto_ripeness.json", _TP_SUFFIX)
        )
        if tp_path != json_path and tp_path.exists():
            tp_meta = self._read_meta(tp_path)
            tp_status = tp_meta.get("tp_status") or tp_status
            tp_confidence = tp_meta.get("tp_confidence", tp_confidence)

        payload: dict[str, Any] = {
            "event_id": item["event_id"],
            "machine_id": self.settings.machine_id,
            "timestamp": meta.get("timestamp"),
            "prediction": "Acc" if str(ripeness_status).lower() == "acc" else "Rej",
            "ripeness_status": str(ripeness_status).upper(),
            "ripeness_confidence": meta.get("ripeness_confidence", 0),
            "tp_status": tp_status,
            "tp_confidence": tp_confidence,
            "capture_type": meta.get("capture_type", "auto"),
            "truck_id": meta.get("truck_id"),
            "image_path": f"{self.settings.r2_public_url}/{r2_key}",
            "bounding_box": meta.get("bounding_box") or {},
        }
        if meta.get("assignment_id"):
            payload["assignment_id"] = meta["assignment_id"]
        if not payload["timestamp"]:
            raise _PoisonError(f"timestamp hilang: {json_path}")
        return payload
