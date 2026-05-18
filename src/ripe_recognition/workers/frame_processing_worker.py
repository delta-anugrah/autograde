from __future__ import annotations

import asyncio
import datetime
import time

import cv2

from ..core.config import Settings
from ..core.constants import (
    DETECTION_START_X_OFFSET,
    ENTRY_MARGIN,
    JPEG_QUALITY_SAVE,
    JPEG_QUALITY_STREAM,
    REF_LINE_LEFT_EXTRA,
    REF_LINE_OFFSET,
    REF_LINE_RIGHT_OFFSET,
    REF_LINE_THICKNESS,
)
from ..integrations.notifications.webhook_client import WebhookClient
from ..integrations.storage.local_file_storage import LocalFileStorage
from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline
from .runtime_state import RuntimeState


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
        date_folder = datetime.datetime.now().strftime("%Y-%m-%d")
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
        results = self.pipeline.track_ripeness(frame)

        height, width, _ = frame.shape
        center_x = width // 2
        line_right = center_x + REF_LINE_OFFSET - REF_LINE_RIGHT_OFFSET
        line_left = center_x - REF_LINE_OFFSET - REF_LINE_LEFT_EXTRA
        detection_start_x = width - DETECTION_START_X_OFFSET

        cv2.line(frame, (line_left, 0), (line_left, height), (0, 255, 0), REF_LINE_THICKNESS)
        cv2.line(frame, (line_right, 0), (line_right, height), (0, 255, 0), REF_LINE_THICKNESS)
        cv2.line(frame, (detection_start_x, 0), (detection_start_x, height), (255, 0, 0), REF_LINE_THICKNESS)

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

                # Box sudah lewat keluar zona kiri
                if x1 < (line_left + ENTRY_MARGIN):
                    if track_id in self.state.track_history and self.state.track_history[track_id].get("processed", False):
                        self._processed_objects.add(track_id)
                    continue

                # Terlalu jauh di kanan, hanya izinkan TP
                if x1 > detection_start_x and label.lower() != "tp":
                    continue

                # Sudah melewati garis kiri → reset TP
                if x1 < line_left:
                    self._last_tp = None
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
                        "tp_status": "TP",
                        "tp_confidence": score,
                        "bbox": (x1, y1, x2, y2),
                    }
                    continue

                # Buah (ACC/REJ) yang sudah masuk zona deteksi
                if (
                    label.lower() in ("acc", "rej")
                    and x1 <= detection_start_x
                    and not self.state.track_history[track_id]["processed"]
                ):
                    ripeness_status = "rej" if area < self.settings.minimum_size else label.lower()
                    ripeness_conf = score
                    self.state.track_history[track_id]["processed"] = True
                    self._processed_objects.add(track_id)

                    annotated = self.pipeline.draw_boxes(frame.copy(), results, self.state.classified_labels)

                    date_folder, timestamp, image_url = self._save_ripeness(
                        annotated, ripeness_status, ripeness_conf,
                        self.state.current_truck_id,
                        {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                    )

                    if self._last_tp:
                        self._save_tp(
                            self._last_tp,
                            self.state.current_truck_id,
                            {
                                "x_min": self._last_tp["bbox"][0],
                                "y_min": self._last_tp["bbox"][1],
                                "x_max": self._last_tp["bbox"][2],
                                "y_max": self._last_tp["bbox"][3],
                            },
                            timestamp,
                        )
                        self._last_tp = None

                    event = {
                        "id": timestamp,
                        "ripeness_status": ripeness_status,
                        "ripeness_confidence": round(ripeness_conf, 2),
                        "tp_status": None,
                        "tp_score": 0,
                        "title": f"{ripeness_status} Detected",
                        "description": f"{ripeness_status} (conf={ripeness_conf:.2f}, truck_id={self.state.current_truck_id})",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "image_url": image_url,
                        "capture_type": "auto",
                        "truck_id": self.state.current_truck_id,
                        "machine_id": self.settings.machine_id,
                        "bounding_box": {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                    }
                    self.state.event_queue.put(event)

                    webhook_payload = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "image_path": image_url,
                        "ripeness_status": ripeness_status,
                        "ripeness_confidence": round(ripeness_conf, 2),
                        "tp_status": None,
                        "tp_confidence": 0,
                        "capture_type": "auto",
                        "truck_id": self.state.current_truck_id,
                        "machine_id": self.settings.machine_id,
                        "bounding_box": {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                    }
                    if self.settings.enable_webhook and self.state.main_loop:
                        asyncio.run_coroutine_threadsafe(
                            self.webhook.send_quality_event(webhook_payload),
                            self.state.main_loop,
                        )

        # Cleanup track yang tidak aktif
        inactive_tracks = set(self.state.track_history.keys()) - current_active_tracks
        for tid in inactive_tracks:
            self._inactive_counter[tid] = self._inactive_counter.get(tid, 0) + 1
            if self._inactive_counter[tid] >= 10:
                self.state.track_history.pop(tid, None)
                self.state.classified_labels.pop(tid, None)
                self._processed_objects.discard(tid)
                self._inactive_counter.pop(tid, None)

        # Encode stream frame
        stream_frame = self.pipeline.draw_boxes(frame.copy(), results, self.state.classified_labels)
        _, buffer = cv2.imencode(".jpg", stream_frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY_STREAM])

        if self.state.result_queue.full():
            try:
                self.state.result_queue.get_nowait()
            except Exception:
                pass
        self.state.result_queue.put(buffer.tobytes())

    def run_loop(self) -> None:
        while True:
            self.run_once()
