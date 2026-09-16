from __future__ import annotations

import datetime
import logging
import queue
import time
from typing import TYPE_CHECKING

from ..core.config import Settings
from ..domain.grade_class import TP, grade_class_of, is_fruit_class, verdict_for_class
from ..domain.plc_signal import plc_status_for
from ..domain.vision_event import build_event_payload
from ..integrations.outbox.outbox_store import OutboxStore
from ..license.gate import grading_blocked
from ..plc import submit_grading
from ..services.capture_writer import CaptureWriter
from .runtime_state import RuntimeState

if TYPE_CHECKING:  # annotations only — these pull in cv2/torch, and the unit
    # suite deliberately runs without either (CLAUDE.md § Tests). Importing them
    # at runtime would keep the save path out of CI for no benefit: every one of
    # them is injected, so nothing here constructs one.
    from ..integrations.notifications.webhook_client import WebhookClient
    from ..integrations.storage.local_file_storage import LocalFileStorage
    from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline

logger = logging.getLogger(__name__)

# Label asing yang sudah pernah diadukan. Loop ini jalan 10-16 fps per line, jadi
# satu kelas tak dikenal akan menulis puluhan ribu baris log per jam dan menutupi
# semua yang lain. Diadukan sekali per nama, lalu diam.
_unknown_labels_seen: set[str] = set()


def _grade_class_or_none(label: str | None) -> str | None:
    """Kelas model yang sudah dinormalkan, atau `None` kalau di luar keempatnya.

    Jalur realtime sengaja TIDAK melempar seperti `grade_class_of`: melempar di
    tengah loop frame akan mematikan grading satu line gara-gara satu kotak yang
    aneh. Yang tak dikenal dilewati (tidak digrading, tidak dipulse ke PLC) dan
    dicatat sekali — cukup buat ketahuan kalau model salah pasang, tanpa membuat
    line berhenti.
    """
    try:
        return grade_class_of(label)
    except ValueError:
        name = str(label)
        if name not in _unknown_labels_seen:
            _unknown_labels_seen.add(name)
            logger.error(
                "Kelas model tidak dikenal: %r - dilewati, tidak digrading. "
                "Cek MODEL_FILE menunjuk ke model 4 kelas (Ripe/Unripe/JK/TP).",
                name,
            )
        return None


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
        self.capture_writer = CaptureWriter(settings, storage)

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
        self._license_stop_logged: bool = False

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
        clean_frame,
        ripeness_status: str,
        ripeness_conf: float,
        truck_id: str | None,
        bounding_box: dict,
        grade_class: str | None = None,
    ) -> tuple[str, str, str]:
        # Timezone-aware UTC: a naive isoformat() leaves the consumer guessing.
        # palmgrade-api runs TZ=Asia/Jakarta and resolved bare date-times as
        # local, storing every capture 7 hours early. Deriving the filename from
        # the same aware instant keeps names byte-identical (containers run UTC)
        # while making the emitted timestamp unambiguous.
        now = datetime.datetime.now(datetime.timezone.utc)
        date_folder = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%d_%H%M%S_%f")

        results_dir = self.settings.results_dir / date_folder
        img_filename = f"{timestamp}_auto.webp"

        # Images are filed per truck and per verdict; the sidecar below is NOT
        # (see `domain/capture_layout`). `image_url` names the annotated copy.
        truck_folder = self.capture_writer.truck_folder(
            assignment_id=self.state.current_assignment_id,
            plate=self.state.current_plate,
            assigned_at=self.state.current_assigned_at,
            now=now,
        )
        image_url = self.capture_writer.write_pair(
            date_folder=date_folder,
            truck_folder=truck_folder,
            ripeness_status=ripeness_status,
            filename=img_filename,
            annotated_frame=annotated_frame,
            clean_frame=clean_frame,
        )

        meta = {
            "timestamp": now.isoformat(),
            "image_path": image_url,
            "ripeness_status": ripeness_status,
            # Ikut ditulis ke sidecar supaya jalur batch (yang membacanya dari
            # disk berjam-jam kemudian, bukan dari memori) membawa kelas yang
            # sama dengan jalur realtime.
            "grade_class": grade_class,
            "ripeness_confidence": round(ripeness_conf, 2),
            "tp_status": None,
            "tp_confidence": 0,
            "capture_type": "auto",
            "truck_id": truck_id,
            "bounding_box": bounding_box,
            "assignment_id": self.state.current_assignment_id,
            # Bukti kenapa sebuah janjang REJ tidak dibuang piston. Sumbernya
            # potret saat truk dipasang, bukan hasil hitung ulang belakangan.
            "ffb_source": self.state.current_ffb_source,
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
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
        # Gerbang lisensi — paling atas, sebelum frame diambil. Berhenti di sini
        # berarti pipeline tidak jalan DAN submit_grading tidak pernah dipanggil,
        # jadi coil OK/NG berhenti berdenyut dengan sendirinya.
        if grading_blocked(self.settings.lic_enabled, self.state.license_exp):
            if not self._license_stop_logged:
                logger.error(
                    "Langganan habis atau lisensi tidak valid — deteksi dihentikan. "
                    "Pasang token baru dengan `palmgrade license <token>`."
                )
                self._license_stop_logged = True
            # Tidur sebentar: tanpa ini run_loop memutar ribuan kali per detik
            # untuk tidak melakukan apa-apa dan menghabiskan satu core.
            time.sleep(1.0)
            return
        if self._license_stop_logged:
            logger.info("Lisensi kembali valid — deteksi dilanjutkan")
            self._license_stop_logged = False

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

        results = self.pipeline.track_ripeness(
            frame, conf=self.state.conf_threshold_override
        )
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

        # Pre-scan: hitung buah (Ripe/Unripe/JK) yang belum diproses dan ada di
        # dalam ROI. Jika > 1 buah sekaligus dalam ROI, semua di-force jadi rej.
        roi_fruit_count = 0
        if results.boxes is not None:
            for _box in results.boxes:
                _tid = int(_box.id[0].item()) if _box.id is not None else -1
                _lbl = _grade_class_or_none(results.names[int(_box.cls[0].item())])
                if _tid == -1 or _tid in self._processed_objects or not (
                    _lbl is not None and is_fruit_class(_lbl)
                ):
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

                # Kelas dibaca dari NAMA, bukan urutan id. Model yang dilatih ulang
                # boleh menukar urutan kelasnya; dulu baris ini `cls_id in (0, 1)`
                # dan penukaran itu membuat `area` selalu 0 untuk buah — penjaga
                # `minimum_size` berhenti bekerja tanpa satu pun pesan error.
                grade_class = _grade_class_or_none(label)
                area = (x2 - x1) * (y2 - y1) if (
                    grade_class is not None and is_fruit_class(grade_class)
                ) else 0

                if track_id == -1:
                    continue

                current_active_tracks.add(track_id)

                if track_id in self._processed_objects:
                    continue

                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                # Objek di luar ROI — skip (kecuali TP boleh dari mana saja)
                if not self._is_in_roi(cx, cy, roi) and grade_class != TP:
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

                # Kelas di luar keempatnya: lewati, jangan tebak. Menganggapnya
                # buah akan memalsukan rekap; menganggapnya REJ akan membuang
                # janjang yang bagus.
                if grade_class is None:
                    continue

                # Tangkai panjang (TP) → simpan sebagai kandidat terakhir
                if grade_class == TP:
                    self._last_tp = {
                        "tp_status": "PASS",
                        "tp_confidence": score,
                        "bbox": (x1, y1, x2, y2),
                    }
                    continue

                # Buah (Ripe/Unripe/JK) yang sudah masuk zona deteksi
                if (
                    is_fruit_class(grade_class)
                    and not self.state.track_history[track_id]["processed"]
                    and not self.state.track_history[track_id].get("plc_signalled")
                ):
                    # >1 buah dalam ROI sekaligus → force rej (buah bertumpuk),
                    # begitu juga buah yang terlalu kecil. Keduanya menimpa
                    # verdict, TAPI tidak menimpa `grade_class`: kelasnya tetap
                    # apa yang dilihat model, supaya konsol tidak melaporkan
                    # janjang matang sebagai Unripe hanya karena bertumpuk.
                    # Setelan dari konsol menang atas `.env` kalau ada
                    # (`/internal/setelan`); dibaca tiap frame supaya berlaku
                    # tanpa restart line.
                    minimum_size = (
                        self.state.minimum_size_override
                        if self.state.minimum_size_override is not None
                        else self.settings.minimum_size
                    )
                    if force_rej_multi or area < minimum_size:
                        ripeness_status = "rej"
                    else:
                        ripeness_status = (verdict_for_class(grade_class) or "REJ").lower()
                    ripeness_conf = score
                    # Buah REJ milik truk Internal tetap masuk ramp: tidak ada
                    # pulse ke PLC, tapi `ripeness_status` di bawah tetap REJ.
                    sinyal = plc_status_for(ripeness_status, self.state.current_ffb_source)
                    if sinyal is not None:
                        submit_grading(sinyal)
                    # Single-trigger TERPISAH dari `processed` di bawah, sengaja.
                    # `processed` baru diset setelah file tersimpan, supaya crash
                    # di tengah blok ini memproses ulang track-nya — aman karena
                    # event_id uuid5-nya sama dan API idempotent. Pulse Modbus
                    # TIDAK punya idempotensi itu: `_save_ripeness` melempar
                    # IOError kalau cv2.imwrite gagal (Critical Rule #8), track
                    # tetap belum `processed`, dan frame berikutnya masuk lagi ke
                    # blok ini pada 10-16 fps. Satu buah nyangkut akan menjenuhkan
                    # coil-nya tanpa henti dan PLC menghitungnya berpuluh kali.
                    # Flag ini diset SEBELUM tulis disk supaya jalur PLC tidak
                    # ikut mewarisi semantik retry jalur disk. Diset juga saat
                    # sinyal ditahan (buah REJ truk Internal): flag ini berarti
                    # "keputusan PLC sudah diambil", bukan "pulse sudah dikirim".
                    self.state.track_history[track_id]["plc_signalled"] = True

                    # `draw_boxes` gets the copy, so `frame` is still the clean
                    # capture — the training copy costs no second inference.
                    annotated = self.pipeline.draw_boxes(frame.copy(), results)

                    date_folder, timestamp, image_url = self._save_ripeness(
                        annotated, frame, ripeness_status, ripeness_conf,
                        self.state.current_truck_id,
                        {"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                        grade_class,
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
                        "grade_class": grade_class,
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

                    # Realtime ke API lokal: OutboxRetryWorker mengirim ini dalam
                    # ~1 detik. Tetap ditulis walau truk belum di-assign — API
                    # punya TruckResolver.resolveOrStub, dan membuangnya bikin
                    # deteksi hilang permanen dari Grading History.
                    outbox_payload = build_event_payload(
                        machine_id=self.settings.machine_id,
                        file_ts=timestamp,
                        timestamp=event_ts,
                        ripeness_status=ripeness_status,
                        ripeness_confidence=ripeness_conf,
                        capture_type="auto",
                        image_path=image_url,
                        truck_id=self.state.current_truck_id,
                        assignment_id=self.state.current_assignment_id,
                        bounding_box={"x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2},
                        tp_status=tp_snapshot["tp_status"] if tp_snapshot else None,
                        tp_confidence=tp_snapshot["tp_confidence"] if tp_snapshot else None,
                        grade_class=grade_class,
                    )
                    try:
                        self.outbox_store.add_event(
                            outbox_payload["event_id"], self.settings.machine_id, outbox_payload
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to write event %s to outbox: %s",
                            outbox_payload["event_id"],
                            exc,
                        )

                    # Tandai `processed` SETELAH file tersimpan (Celah-1 fix): kalau
                    # crash di tengah blok di atas, track ini BELUM processed → diproses
                    # ulang next frame → nama file (dan event_id uuid5 yang dihitung
                    # BatchUploadWorker dari nama itu) sama → idempotent di sisi API.
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
