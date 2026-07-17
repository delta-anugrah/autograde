from __future__ import annotations

import datetime
import logging
import queue
import time
import uuid

from ..core.config import Settings
from ..core.constants import JPEG_QUALITY_SAVE
from ..integrations.notifications.webhook_client import WebhookClient
from ..integrations.outbox.outbox_store import OutboxStore
from ..integrations.storage.local_file_storage import LocalFileStorage
from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class FrameProcessingWorker:
    def __init__(
        self,
        pipeline: RealtimeInspectionPipeline,
        state: RuntimeState,
        storage: LocalFileStorage,
        webhook: WebhookClient,
        settings: Settings,
        outbox_store: OutboxStore,
    ) -> None:
        self.pipeline = pipeline
        self.state = state
        self.storage = storage
        self.webhook = webhook
        self.settings = settings
        self.outbox_store = outbox_store

        # Internal worker state — tidak perlu di RuntimeState karena hanya diakses worker ini
        self._processed_objects: set[int] = set()
        self._inactive_counter: dict[int, int] = {}
        self._last_tp: dict | None = None
        self._frame_count: int = 0
        self._last_results = None  # cached YOLO result for skip frames
        self._processed_times: dict[int, float] = {}
        self._cleanup_counter: int = 0
        self._fps_counter: int = 0
        self._fps_timer: float = 0.0

    # ------------------------------------------------------------------ zone helpers

    def _roi_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Effective ROI (x1,y1,x2,y2). Falls back to full frame when all coords are 0."""
        x1, y1 = self.settings.roi_x1, self.settings.roi_y1
        x2 = self.settings.roi_x2 if self.settings.roi_x2 > 0 else width
        y2 = self.settings.roi_y2 if self.settings.roi_y2 > 0 else height
        return x1, y1, x2, y2

    def _is_in_roi(self, cx: int, cy: int, roi: tuple[int, int, int, int]) -> bool:
        """True when object center (cx, cy) falls inside the ROI rectangle."""
        rx1, ry1, rx2, ry2 = roi
        return rx1 <= cx <= rx2 and ry1 <= cy <= ry2

    # ------------------------------------------------------------------ save

    def _save_ripeness(
        self,
        annotated_frame,
        ripeness_status: str,
        ripeness_conf: float,
        truck_id: str | None,
        bounding_box: dict,
    ) -> tuple[str, str, str]:
        now = datetime.datetime.now()
        date_folder = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%d_%H%M%S_%f")

        results_dir = self.settings.results_dir / date_folder
        img_filename = f"{timestamp}_auto.webp"
        image_url = f"captures/results/{date_folder}/{img_filename}"

        self.storage.write_image(results_dir / img_filename, annotated_frame, quality=JPEG_QUALITY_SAVE)

        meta = {
            "timestamp": now.isoformat(),
            "image_path": image_url,
            "ripeness_status": ripeness_status,
            "ripeness_confidence": round(ripeness_conf, 2),
            "tp_status": None,
            "tp_confidence": 0,
            "capture_type": "auto",
            "truck_id": truck_id,
            "bounding_box": bounding_box,
            "assignment_id": self.state.current_assignment_id,
        }
        self.storage.write_json(results_dir / f"{timestamp}_auto_ripeness.json", meta)

        # results/ adalah satu-satunya sumber kebenaran; foto REJ ditemukan lewat
        # metadata (ripeness_status == "REJ"), bukan folder errors/ terpisah.
        return date_folder, timestamp, image_url

    def _save_tp(
        self,
        last_tp: dict,
        truck_id: str | None,
        bounding_box: dict,
        timestamp: str,
    ) -> None:
        # H5: parse date_folder from timestamp param so midnight-split never mismatches
        date_folder = timestamp[:10]  # "YYYY-MM-DD_HHmmss_ffffff" → "YYYY-MM-DD"
        results_dir = self.settings.results_dir / date_folder

        meta = {
            "timestamp": datetime.datetime.now().isoformat(),
            "image_path": None,
            "ripeness_status": None,
            "ripeness_confidence": 0,
            "tp_status": last_tp["tp_status"],
            "tp_confidence": round(last_tp["tp_confidence"], 2),
            "capture_type": "auto",
            "truck_id": truck_id,
            "bounding_box": bounding_box,
            "assignment_id": self.state.current_assignment_id,
        }
        self.storage.write_json(results_dir / f"{timestamp}_auto_tp.json", meta)

    def run_once(self) -> None:
        if self.state.rewind_signal:
            self.pipeline.reset_tracker()
            self._processed_objects.clear()
            self._inactive_counter.clear()
            self._last_results = None
            self._last_tp = None
            self.state.track_history.clear()
            self.state.rewind_signal = False
            logger.info("Video rewind — ByteTrack and tracking state reset")

        try:
            frame = self.state.frame_queue.get(timeout=0.1)
        except Exception:
            return

        self._frame_count += 1
        skip = self.settings.yolo_skip_frames
        run_yolo = (skip <= 1) or (self._frame_count % skip == 0) or (self._last_results is None)

        if not run_yolo:
            return  # DisplayWorker handles rendering with cached results

        height, width, _ = frame.shape
        roi = self._roi_box(width, height)

        results = self.pipeline.track_ripeness(frame)
        self._last_results = results
        self.state.last_yolo_frame = frame        # paired: DisplayWorker pakai frame ini untuk draw boxes
        self.state.last_yolo_results = results    # paired: box selalu aligned dengan last_yolo_frame
        self.state.last_yolo_frame_at = time.time()

        if logger.isEnabledFor(logging.DEBUG):
            if results.boxes is not None and len(results.boxes) > 0:
                detections = []
                for b in results.boxes:
                    cls_id = int(b.cls[0].item())
                    tid = int(b.id[0].item()) if b.id is not None else -1
                    lbl = results.names[cls_id]
                    conf = float(b.conf[0].item())
                    bx1, by1, bx2, by2 = map(int, b.xyxy[0].tolist())
                    area = (bx2 - bx1) * (by2 - by1)
                    bcx, bcy = (bx1 + bx2) // 2, (by1 + by2) // 2
                    detections.append(f"id={tid} {lbl} conf={conf:.2f} bbox=({bx1},{by1},{bx2},{by2}) area={area} center=({bcx},{bcy})")
                logger.debug("[MODEL] frame=%d n=%d roi=%s | %s",
                             self._frame_count, len(results.boxes),
                             roi,
                             " | ".join(detections))
            else:
                logger.debug("[MODEL] frame=%d n=0", self._frame_count)

        self._fps_counter += 1
        fps_now = time.time()
        if self._fps_timer == 0.0:
            self._fps_timer = fps_now
        elif fps_now - self._fps_timer >= 1.0:
            self.state.inference_fps = self._fps_counter / (fps_now - self._fps_timer)
            self._fps_counter = 0
            self._fps_timer = fps_now

        current_active_tracks: set[int] = set()

        # Pre-scan: hitung buah (ACC/REJ) yang belum diproses dan ada di dalam ROI.
        # Jika > 1 buah sekaligus dalam ROI, semua di-force jadi rej.
        roi_fruit_count = 0
        if results.boxes is not None:
            for _box in results.boxes:
                _tid = int(_box.id[0].item()) if _box.id is not None else -1
                _lbl = results.names[int(_box.cls[0].item())]
                if _tid == -1 or _tid in self._processed_objects or _lbl.lower() not in ("acc", "rej"):
                    continue
                _bx1, _by1, _bx2, _by2 = map(int, _box.xyxy[0].tolist())
                _cx, _cy = (_bx1 + _bx2) // 2, (_by1 + _by2) // 2
                if self._is_in_roi(_cx, _cy, roi):
                    roi_fruit_count += 1
        force_rej_multi = roi_fruit_count > 1

        if results.boxes is not None and len(results.boxes) > 0:
            for box in results.boxes:
                cls_id = int(box.cls[0].item())
                track_id = int(box.id[0].item()) if box.id is not None else -1
                label = results.names[cls_id]
                score = float(box.conf[0].item())
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                area = (x2 - x1) * (y2 - y1) if cls_id in (0, 1) else 0

                if track_id == -1:
                    continue

                current_active_tracks.add(track_id)

                if track_id in self._processed_objects:
                    continue

                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                # Objek di luar ROI — skip (kecuali TP boleh dari mana saja)
                if not self._is_in_roi(cx, cy, roi) and label.lower() != "tp":
                    continue

                self._inactive_counter.pop(track_id, None)

                if track_id not in self.state.track_history:
                    self.state.track_history[track_id] = {
                        "label": label,
                        "score": score,
                        "processed": False,
                        "bbox": (x1, y1, x2, y2),
                    }

                track = self.state.track_history[track_id]
                track["label"] = label
                track["score"] = score
                track["bbox"] = (x1, y1, x2, y2)

                # Tangkai panjang (TP) → simpan sebagai kandidat terakhir
                if label.lower() == "tp":
                    self._last_tp = {
                        "tp_status": "PASS",
                        "tp_confidence": score,
                        "bbox": (x1, y1, x2, y2),
                    }
                    continue

                # Buah (ACC/REJ) yang sudah masuk zona deteksi
                if (
                    label.lower() in ("acc", "rej")
                    and not self.state.track_history[track_id]["processed"]
                ):
                    # >1 buah dalam ROI sekaligus → force rej (buah bertumpuk)
                    if force_rej_multi or area < self.settings.minimum_size:
                        ripeness_status = "rej"
                    else:
                        ripeness_status = label.lower()
                    ripeness_conf = score

                    annotated = self.pipeline.draw_boxes(frame.copy(), results)

                    date_folder, timestamp, image_url = self._save_ripeness(
                        annotated, ripeness_status, ripeness_conf,
                        self.state.current_truck_id,
                        {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                    )

                    # H3: snapshot _last_tp before clearing so event + webhook carry TP data
                    tp_snapshot = self._last_tp
                    if tp_snapshot:
                        self._save_tp(
                            tp_snapshot,
                            self.state.current_truck_id,
                            {
                                "x_min": tp_snapshot["bbox"][0],
                                "y_min": tp_snapshot["bbox"][1],
                                "x_max": tp_snapshot["bbox"][2],
                                "y_max": tp_snapshot["bbox"][3],
                            },
                            timestamp,
                        )
                        self._last_tp = None

                    event_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    event = {
                        "id": timestamp,
                        "ripeness_status": ripeness_status,
                        "ripeness_confidence": round(ripeness_conf, 2),
                        "tp_status": tp_snapshot["tp_status"] if tp_snapshot else None,
                        "tp_confidence": round(tp_snapshot["tp_confidence"], 2) if tp_snapshot else 0,
                        "title": f"{ripeness_status} Detected",
                        "description": f"{ripeness_status} (conf={ripeness_conf:.2f}, truck_id={self.state.current_truck_id})",
                        "timestamp": event_ts,
                        "image_url": image_url,
                        "capture_type": "auto",
                        "truck_id": self.state.current_truck_id,
                        "machine_id": self.settings.machine_id,
                        "bounding_box": {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                    }
                    # H2: drop-old pattern — never block the processing thread on a slow WebSocket client
                    try:
                        self.state.event_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self.state.event_queue.put_nowait(event)

                    # [DISABLED: batch-upload-r2 — lihat spec 2026-07-10]
                    # truck_id = self.state.current_truck_id
                    # if truck_id:
                    #     # event_id deterministik (machine_id + timestamp file, unik per
                    #     # detik per line) → kalau frame ini diproses ulang setelah crash
                    #     # SEBELUM `processed` di-set, event_id tetap sama → API idempotent
                    #     # (already_processed) → tidak double count.
                    #     event_id = str(
                    #         uuid.uuid5(uuid.NAMESPACE_URL, f"{self.settings.machine_id}:{timestamp}")
                    #     )
                    #     outbox_payload = {
                    #         "event_id": event_id,
                    #         "machine_id": self.settings.machine_id,
                    #         "assignment_id": self.state.current_assignment_id,
                    #         "truck_id": truck_id,
                    #         "timestamp": event_ts,
                    #         "prediction": "Acc" if ripeness_status == "acc" else "Rej",
                    #         "ripeness_status": ripeness_status.upper(),
                    #         "ripeness_confidence": round(ripeness_conf, 2),
                    #         "tp_status": tp_snapshot["tp_status"] if tp_snapshot else None,
                    #         "tp_confidence": round(tp_snapshot["tp_confidence"], 2) if tp_snapshot else 0,
                    #         "capture_type": "auto",
                    #         "image_path": image_url,
                    #         "bounding_box": {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                    #     }
                    #     try:
                    #         self.outbox_store.add_event(event_id, self.settings.machine_id, outbox_payload)
                    #     except Exception as exc:
                    #         logger.error("Failed to write event %s to outbox: %s", event_id, exc)

                    # Tandai `processed` SETELAH event aman di outbox (Celah-1 fix):
                    # kalau crash di tengah blok di atas, track ini BELUM processed →
                    # diproses ulang next frame → event_id deterministik = idempotent.
                    # Tanpa truck (truck_id null) tetap ditandai supaya tidak re-trigger.
                    self.state.track_history[track_id]["processed"] = True
                    self._processed_objects.add(track_id)
                    self._processed_times[track_id] = time.time()

        # H6: do NOT discard from _processed_objects on cleanup — prevents re-trigger
        # if ByteTrack reuses the ID or the object re-enters after being marked inactive.
        inactive_tracks = set(self.state.track_history.keys()) - current_active_tracks
        for tid in inactive_tracks:
            self._inactive_counter[tid] = self._inactive_counter.get(tid, 0) + 1
            if self._inactive_counter[tid] >= 10:
                self.state.track_history.pop(tid, None)
                self._inactive_counter.pop(tid, None)

        # Trim _processed_objects: remove IDs stale >300s and no longer in track_history
        self._cleanup_counter += 1
        if self._cleanup_counter >= 500:
            self._cleanup_counter = 0
            now = time.time()
            stale = {
                tid for tid in self._processed_objects
                if tid not in self.state.track_history
                and now - self._processed_times.get(tid, now) > 300
            }
            self._processed_objects -= stale
            for tid in stale:
                self._processed_times.pop(tid, None)

        # DisplayWorker handles MJPEG rendering — processing worker only does detection.

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in FrameProcessingWorker.run_once")
                time.sleep(1)
