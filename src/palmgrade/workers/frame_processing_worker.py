from __future__ import annotations

import asyncio
import datetime
import logging
import queue
import time

from ..core.config import Settings
from ..core.constants import JPEG_QUALITY_SAVE
from ..integrations.notifications.webhook_client import WebhookClient
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
    ) -> None:
        self.pipeline = pipeline
        self.state = state
        self.storage = storage
        self.webhook = webhook
        self.settings = settings

        # Internal worker state — tidak perlu di RuntimeState karena hanya diakses worker ini
        self._processed_objects: set[int] = set()
        self._inactive_counter: dict[int, int] = {}
        self._last_tp: dict | None = None
        self._frame_count: int = 0
        self._last_results = None  # cached YOLO result for skip frames

    # ------------------------------------------------------------------ zone helpers

    def _lead_coord(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """Leading-edge coordinate in the direction of conveyor motion."""
        d = self.settings.conveyor_direction
        if d == "ltr": return x2
        if d == "ttb": return y1
        if d == "btt": return y2
        return x1  # rtl

    def _entry_line(self, width: int, height: int) -> int:
        """Pixel coordinate of the entry boundary (blue line)."""
        d = self.settings.conveyor_direction
        off = self.settings.detection_entry_offset
        if d == "rtl": return max(0, width - off)
        if d == "ltr": return min(width, off)
        if d == "ttb": return min(height, off)
        return max(0, height - off)  # btt

    def _exit_line(self, width: int, height: int) -> int:
        """Pixel coordinate of the exit boundary (green line)."""
        d = self.settings.conveyor_direction
        off = self.settings.detection_exit_offset
        if d == "rtl": return min(width, off)
        if d == "ltr": return max(0, width - off)
        if d == "ttb": return max(0, height - off)
        return min(height, off)  # btt

    def _has_entered(self, lead: int, entry_line: int) -> bool:
        """True when leading edge has crossed into the detection zone."""
        d = self.settings.conveyor_direction
        if d in ("rtl", "btt"):
            return lead <= entry_line  # coord decreasing toward exit
        return lead >= entry_line  # coord increasing toward exit (ltr, ttb)

    def _has_exited(self, lead: int, exit_line: int) -> bool:
        """True when leading edge has passed the exit boundary (+ margin)."""
        d = self.settings.conveyor_direction
        margin = self.settings.entry_margin
        if d in ("rtl", "btt"):
            return lead < exit_line + margin
        return lead > exit_line - margin

    # ------------------------------------------------------------------ save

    def _save_ripeness(
        self,
        annotated_frame,
        ripeness_status: str,
        ripeness_conf: float,
        truck_id: str | None,
        bounding_box: dict,
    ) -> tuple[str, str, str]:
        date_folder = datetime.datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")

        results_dir = self.settings.results_dir / date_folder
        img_filename = f"{timestamp}_auto.jpg"
        image_url = f"captures/results/{date_folder}/{img_filename}"

        self.storage.write_image(results_dir / img_filename, annotated_frame, quality=JPEG_QUALITY_SAVE)

        meta = {
            "timestamp": datetime.datetime.now().isoformat(),
            "image_path": image_url,
            "ripeness_status": ripeness_status,
            "ripeness_confidence": round(ripeness_conf, 2),
            "tp_status": None,
            "tp_confidence": 0,
            "capture_type": "auto",
            "truck_id": truck_id,
            "bounding_box": bounding_box,
        }
        self.storage.write_json(results_dir / f"{timestamp}_auto_ripeness.json", meta)

        if ripeness_status == "rej":
            errors_dir = self.settings.errors_dir / date_folder
            self.storage.write_image(errors_dir / img_filename, annotated_frame, quality=JPEG_QUALITY_SAVE)
            self.storage.write_json(errors_dir / f"{timestamp}_auto_ripeness.json", meta)

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
        }
        self.storage.write_json(results_dir / f"{timestamp}_auto_tp.json", meta)

    def run_once(self) -> None:
        if self.state.frame_queue.empty():
            time.sleep(0.001)
            return

        frame = self.state.frame_queue.get()
        self._frame_count += 1
        skip = self.settings.yolo_skip_frames
        run_yolo = (skip <= 1) or (self._frame_count % skip == 0) or (self._last_results is None)

        if not run_yolo:
            return  # DisplayWorker handles rendering with cached results

        height, width, _ = frame.shape
        entry_line = self._entry_line(width, height)
        exit_line = self._exit_line(width, height)

        results = self.pipeline.track_ripeness(frame)
        self._last_results = results
        self.state.last_yolo_results = results  # DisplayWorker reads this

        current_active_tracks: set[int] = set()

        if results.boxes is not None and len(results.boxes) > 0:
            for box in results.boxes:
                cls_id = int(box.cls[0].cpu().numpy())
                track_id = int(box.id[0].cpu().numpy()) if box.id is not None else -1
                label = results.names[cls_id]
                score = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                area = (x2 - x1) * (y2 - y1) if cls_id in (0, 1) else 0

                if track_id == -1:
                    continue

                current_active_tracks.add(track_id)

                if track_id in self._processed_objects:
                    continue

                lead = self._lead_coord(x1, y1, x2, y2)

                # Objek sudah melewati exit boundary — finalize dan skip
                if self._has_exited(lead, exit_line):
                    if track_id in self.state.track_history and self.state.track_history[track_id].get("processed", False):
                        self._processed_objects.add(track_id)
                    continue

                # Objek belum masuk entry boundary — skip (kecuali TP boleh dari mana saja)
                if not self._has_entered(lead, entry_line) and label.lower() != "tp":
                    continue

                self._inactive_counter.pop(track_id, None)

                if track_id not in self.state.track_history:
                    self.state.track_history[track_id] = {
                        "label": label,
                        "score": score,
                        "processed": False,
                        "bbox": (x1, y1, x2, y2),
                    }

                self.state.track_history[track_id]["label"] = label
                self.state.track_history[track_id]["score"] = score
                self.state.track_history[track_id]["bbox"] = (x1, y1, x2, y2)

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
                    ripeness_status = "rej" if area < self.settings.minimum_size else label.lower()
                    ripeness_conf = score
                    self.state.track_history[track_id]["processed"] = True
                    self._processed_objects.add(track_id)

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

                    event = {
                        "id": timestamp,
                        "ripeness_status": ripeness_status,
                        "ripeness_confidence": round(ripeness_conf, 2),
                        "tp_status": tp_snapshot["tp_status"] if tp_snapshot else None,
                        "tp_confidence": round(tp_snapshot["tp_confidence"], 2) if tp_snapshot else 0,
                        "title": f"{ripeness_status} Detected",
                        "description": f"{ripeness_status} (conf={ripeness_conf:.2f}, truck_id={self.state.current_truck_id})",
                        "timestamp": datetime.datetime.now().isoformat(),
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

                    truck_id = self.state.current_truck_id
                    if self.settings.enable_webhook and self.state.main_loop and truck_id:
                        webhook_payload = {
                            "timestamp": datetime.datetime.now().isoformat(),
                            "image_path": image_url,
                            "prediction": "Acc" if ripeness_status == "acc" else "Rej",
                            "ripeness_status": ripeness_status.upper(),
                            "ripeness_confidence": round(ripeness_conf, 2),
                            "tp_status": tp_snapshot["tp_status"] if tp_snapshot else None,
                            "tp_confidence": round(tp_snapshot["tp_confidence"], 2) if tp_snapshot else 0,
                            "capture_type": "auto",
                            "truck_id": truck_id,
                            "machine_id": self.settings.machine_id,
                            "bounding_box": {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                        }
                    if self.settings.enable_webhook and self.state.main_loop and truck_id:
                        asyncio.run_coroutine_threadsafe(
                            self.webhook.send_quality_event(webhook_payload),  # type: ignore[arg-type]
                            self.state.main_loop,
                        )

        # H6: do NOT discard from _processed_objects on cleanup — prevents re-trigger
        # if ByteTrack reuses the ID or the object re-enters after being marked inactive.
        inactive_tracks = set(self.state.track_history.keys()) - current_active_tracks
        for tid in inactive_tracks:
            self._inactive_counter[tid] = self._inactive_counter.get(tid, 0) + 1
            if self._inactive_counter[tid] >= 10:
                self.state.track_history.pop(tid, None)
                self._inactive_counter.pop(tid, None)

        # DisplayWorker handles MJPEG rendering — processing worker only does detection.

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in FrameProcessingWorker.run_once")
                time.sleep(1)
