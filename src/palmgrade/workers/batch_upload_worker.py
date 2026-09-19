"""Batch upload worker — kirim hasil deteksi (gambar + teks) ke cloud tiap jam.

Alur per tick (spec 2026-07-10 §3.3): scan → proses per item (gambar dulu ke
R2, lalu POST teks ke API cloud) → retensi. State per item hidup di
UploadManifest; worker ini stateless antar tick.

Klasifikasi kegagalan (spec §5):
- _RequeueError  → kondisi eksternal rusak (jaringan/5xx/429/401/403):
  requeue item + BREAK batch (percuma lanjut; sisa antrean nunggu tick berikut).
  Kecuali HTTP 404 (truck belum sinkron) — itu kondisi PER-ITEM, bukan global:
  requeue item + CONTINUE batch (`batch_fatal=False`), supaya satu item yang
  terus-menerus 404 tidak menyandera item lain di belakangnya (head-of-line
  starvation, antrean di-ORDER BY discovered_at ASC).
- _PoisonError   → input cacat (JSON korup/field hilang/gambar hilang):
  poisoned + CONTINUE (satu item busuk tidak menyandera batch). File TIDAK dihapus.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from ..core.config import Settings
from ..domain.capture_layout import thumb_key_of, thumb_twin_of, twins_of
from ..domain.grade_class import grade_class_or_none
from ..domain.vision_event import event_id_for, prediction_for, verdict_of
from ..integrations.upload.r2_uploader import R2Uploader, build_r2_key
from ..integrations.upload.upload_manifest import UploadManifest

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # payload teks kecil; 30s aman utk link pabrik lambat

_RIPENESS_SUFFIXES = ("_auto_ripeness.json", "_manual_ripeness.json")
_TP_SUFFIX = "_auto_tp.json"

# Berapa item dihapus sebelum sisa disk diukur ulang. statvfs itu murah tapi
# bukan gratis; 200 item ~40 MB, cukup halus untuk tidak kebablasan jauh.
_DISK_SWEEP_CHUNK = 200


class _PoisonError(Exception):
    """Input cacat — retry tidak akan menolong; item di-skip permanen."""


class _RequeueError(Exception):
    """Kondisi eksternal rusak — item diantre ulang.

    `batch_fatal=True` (default) → batch juga berhenti (kondisi global, mis.
    jaringan/5xx/429/401/403 — percuma lanjut, semua item bakal gagal sama).
    `batch_fatal=False` → batch lanjut (kondisi per-item, mis. HTTP 404 truck
    belum sinkron — item lain di belakangnya tetap layak diproses tick ini).
    """

    def __init__(self, message: str, *, batch_fatal: bool = True) -> None:
        super().__init__(message)
        self.batch_fatal = batch_fatal


def file_timestamp(json_name: str) -> str:
    for suffix in (*_RIPENESS_SUFFIXES, _TP_SUFFIX):
        if json_name.endswith(suffix):
            return json_name.removesuffix(suffix)
    raise ValueError(f"Bukan nama file hasil deteksi: {json_name}")


# Rumus dipindah ke domain/vision_event.py karena jalur realtime (outbox) dan
# jalur batch harus memakai id yang sama persis. Di-re-export supaya import
# lama tetap jalan.
__all__ = ["BatchUploadWorker", "event_id_for", "file_timestamp"]


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
            return json.loads(json_path.read_text(encoding="utf-8"))
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
        # Divalidasi pakai kosakata yang sama dengan jalur realtime. Dulu baris
        # ini `"Acc" if ... == "acc" else "Rej"`: verdict asing diam-diam jadi
        # Rej, jadi satu sidecar cacat mengirim janjang bagus ke cloud sebagai
        # REJ tanpa sepatah pun peringatan. `_PoisonError`, bukan ValueError
        # telanjang — satu berkas busuk tidak boleh menyandera seluruh batch.
        try:
            verdict = verdict_of(ripeness_status)
        except ValueError as exc:
            raise _PoisonError(f"{exc}: {json_path}") from exc

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
            "prediction": prediction_for(verdict),
            "ripeness_status": verdict,
            # Sama dengan jalur realtime; dibaca dari sidecar. Baris lama tidak
            # punya kunci ini dan tetap sah — nilainya None.
            "grade_class": grade_class_or_none(meta.get("grade_class")),
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

    # ---------------------------------------------------------------- orchestration

    def run_batch_once(self) -> None:
        if not self.settings.r2_bucket:
            if not self._warned_noop:
                logger.warning("R2_BUCKET kosong — batch upload no-op (saklar off)")
                self._warned_noop = True
            return

        self._scan()
        items = self.manifest.get_uploadable(limit=self.settings.upload_max_items_per_tick)
        logger.info("Batch tick: %d item eligible (%s)", len(items), self.manifest.counts())

        for item in items:
            try:
                self._process_item(item)
            except _PoisonError as exc:
                logger.error("Item poisoned %s: %s", item["item_key"], exc)
                self.manifest.mark_poisoned(item["id"], str(exc))
                continue  # satu item busuk tidak menyandera batch
            except _RequeueError as exc:
                self.manifest.requeue(item["id"], str(exc))
                if exc.batch_fatal:
                    logger.warning("Item requeued %s: %s — batch break", item["item_key"], exc)
                    break  # kondisi eksternal rusak — sisa antrean nunggu tick berikut
                logger.warning("Item requeued %s: %s — batch continue", item["item_key"], exc)
                continue  # kondisi per-item — item lain di belakangnya tetap diproses

        self._retention()

    def _process_item(self, item: dict[str, Any]) -> None:
        if item["status"] == "pending" and item["image_path"]:
            local = self.settings.artifacts_dir / item["image_path"].lstrip("/").removeprefix("captures/")
            if not local.exists():
                raise _PoisonError(f"file gambar hilang: {local}")
            try:
                self.uploader.put(local, item["r2_key"])
            except FileNotFoundError as exc:
                raise _PoisonError(f"file gambar hilang: {local}") from exc
            except Exception as exc:
                raise _RequeueError(f"PUT R2 gagal: {exc}") from exc

            thumb_local = thumb_twin_of(local)
            thumb_key = thumb_key_of(item["r2_key"])
            if thumb_local is not None and thumb_local.exists() and thumb_key is not None:
                try:
                    self.uploader.put(thumb_local, thumb_key)
                except Exception as exc:  # noqa: BLE001 — a preview must not hold the queue
                    # Never fatal, and never a poison: the annotated image — the
                    # evidence — is already in R2, so a picture the viewer can do
                    # without must not hold back every image and event queued
                    # behind it (batch-fatal is reserved for global conditions,
                    # the docstring above). This item is not requeued for the
                    # thumbnail alone, and nothing else revisits this PUT, so a
                    # failure here is not a delay — the thumbnail is permanently
                    # missing for this bunch. The viewer falls back to the full
                    # image when the thumbnail is absent (static/viewer.html).
                    logger.warning("PUT thumb R2 gagal (%s): %s", thumb_key, exc)

            self.manifest.mark_image_uploaded(item["id"])
            item["status"] = "image_uploaded"

        if not self.settings.upload_events_url:
            # No text receiver: the image is the upload. An item with no image at
            # all (an orphan tp sidecar) has nothing to send — done, so retention
            # can clean it up rather than poison holding the file forever.
            self.manifest.mark_done(item["id"])
            return

        payload = self._build_payload(item)  # bisa raise _PoisonError
        headers = {
            "Content-Type": "application/json",
            "x-webhook-secret": self.settings.upload_api_secret,
        }
        try:
            res = self._client.post(self.settings.upload_events_url, json=payload, headers=headers)
        except Exception as exc:
            raise _RequeueError(f"POST gagal: {exc}") from exc

        if res.status_code in (200, 201) or "already_processed" in res.text:
            self.manifest.mark_done(item["id"])
            return
        if res.status_code in (400, 422):
            raise _PoisonError(f"HTTP {res.status_code}: {res.text[:200]}")
        if res.status_code in (401, 403):
            logger.error("Auth ke API cloud ditolak (HTTP %s) — cek UPLOAD_API_SECRET", res.status_code)
            raise _RequeueError(f"HTTP {res.status_code}: {res.text[:200]}")
        if res.status_code == 404:
            logger.error("Truck belum ada di DB cloud (HTTP 404) — item nunggu sinkronisasi truck")
            raise _RequeueError(f"HTTP {res.status_code}: {res.text[:200]}", batch_fatal=False)
        raise _RequeueError(f"HTTP {res.status_code}: {res.text[:200]}")

    # ---------------------------------------------------------------- retention

    def _delete_item_files(self, item: dict[str, Any]) -> None:
        """Hapus WebP + JSON milik satu item, lalu barisnya di manifest."""
        json_path = self.settings.artifacts_dir / item["item_key"]
        targets = [json_path]
        if json_path.name.endswith("_auto_ripeness.json"):
            targets.append(json_path.with_name(json_path.name.replace("_auto_ripeness.json", _TP_SUFFIX)))
        if item["image_path"]:
            annotated = (
                self.settings.artifacts_dir / item["image_path"].lstrip("/").removeprefix("captures/")
            )
            targets.append(annotated)
            # The clean and thumb twins are deleted here or by nothing at all: they
            # have no manifest row of their own, so both age-based retention and the
            # disk guard would sweep `done` items while freeing only part of the
            # bytes — until the disk fills and `write_image` stops grading (Rule #8/#9).
            targets.extend(twins_of(annotated))
        for t in targets:
            t.unlink(missing_ok=True)
        self.manifest.delete_item(item["id"])

    def _free_bytes(self) -> int | None:
        """Sisa disk pada partisi artifacts, atau None kalau tak terbaca."""
        try:
            return shutil.disk_usage(self.settings.artifacts_dir).free
        except OSError as exc:
            logger.warning("Sisa disk tak terbaca (%s) — penjaga disk dilewati", exc)
            return None

    def _retention(self) -> None:
        cutoff = time.time() - self.settings.upload_retention_days * 86400
        for item in self.manifest.get_expired_done(cutoff):
            self._delete_item_files(item)
        self._retention_by_disk()

    def _retention_by_disk(self) -> None:
        """Pagar terakhir: buang `done` tertua sampai sisa disk di atas lantai.

        Retensi umur saja bertaruh bahwa throughput tidak melebihi perkiraan
        saat UPLOAD_RETENTION_DAYS disetel. Taruhan itu boleh kalah — yang tidak
        boleh adalah disk penuh, karena `LocalFileStorage.write_image` lalu raise
        dan **deteksi berhenti tersimpan**. Arsip lokal cuma cadangan; R2 dan DB
        cloud yang jadi arsip sesungguhnya, jadi mengorbankan yang tertua di sini
        selalu lebih murah daripada kehilangan grading yang sedang berjalan.
        """
        floor = int(self.settings.upload_disk_min_free_gb * 1024**3)
        if floor <= 0:
            return

        free = self._free_bytes()
        if free is None or free >= floor:
            return

        logger.warning(
            "Sisa disk %.1f GB di bawah lantai %.1f GB — membuang item done tertua",
            free / 1024**3, floor / 1024**3,
        )
        removed = 0
        while free is not None and free < floor:
            batch = self.manifest.get_oldest_done(_DISK_SWEEP_CHUNK)
            if not batch:
                # Tidak ada lagi yang aman dihapus: sisa disk terpakai oleh item
                # yang BELUM sampai ke cloud. Menghapusnya = kehilangan permanen,
                # jadi berhenti dan berisik — ini butuh tangan operator.
                logger.error(
                    "Sisa disk %.1f GB masih di bawah lantai %.1f GB tapi tidak ada item "
                    "done tersisa — antrean upload macet atau disk dipakai hal lain. "
                    "Cek koneksi ke cloud; grading berhenti menulis kalau disk habis.",
                    free / 1024**3, floor / 1024**3,
                )
                break
            for item in batch:
                self._delete_item_files(item)
            removed += len(batch)
            free = self._free_bytes()

        if removed:
            logger.warning(
                "Penjaga disk menghapus %d item done lebih awal dari %d hari; sisa disk kini %s",
                removed,
                self.settings.upload_retention_days,
                f"{free / 1024**3:.1f} GB" if free is not None else "tak terbaca",
            )
