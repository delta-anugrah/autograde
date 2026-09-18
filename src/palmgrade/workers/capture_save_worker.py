"""Menulis bukti satu janjang ke disk, di thread sendiri.

Kenapa ini ada sebagai thread terpisah, dan bukan sekadar beberapa baris di
dalam `FrameProcessingWorker`: menyimpan satu janjang memakan **~590 ms** pada
frame kamera 2448x2048 (diukur di PC Lampung 2026-09-17, dari selisih mikrodetik
antara nama file dan mtime tiap berkasnya). 570 ms dari angka itu adalah dua
encode WebP — single-thread di cv2, tanpa knob kecepatan.

Selama 590 ms itu, dulu, deteksi BERHENTI. Bukan melambat: loop-nya memang
memanggil encode secara lurus. Tiga akibatnya, dan tidak satu pun pernah muncul
sebagai error di log:

1. `frame_queue` (maxsize 5, drop-oldest, nol log — `frame_capture_worker`)
   membuang tiap frame yang datang selama itu. Di kamera pabrik 20 fps itu ~12
   frame per janjang, jadi janjang yang melintas ROI dalam setengah detik bisa
   tidak pernah dilihat model sama sekali.
2. ByteTrack kehilangan ~0,6 detik gerakan, lalu mengembalikan janjang yang sama
   dengan track id baru — dan track id baru artinya dihitung ulang, yaitu tonase
   dobel di angka yang dibayar ke petani.
3. Layar operator membeku: `DisplayWorker` memakai frame YOLO terakhir selama
   500 ms, lalu jatuh ke frame mentah tanpa kotak sampai deteksi hidup lagi.
   Ini yang dilaporkan sebagai "ngelag sedetik" dari tiga line sekaligus.

Yang TIDAK pindah ke sini, dan sengaja: pulse PLC, penandaan `processed`, dan
event WebSocket ke layar. Ketiganya harus terjadi pada detik janjang terdeteksi;
memindahkannya ke belakang antrean berarti piston menyortir buah dengan
keputusan basi.

Bebas torch/cv2 di level modul (storage disuntikkan), jadi tetap teruji di CI
ringan — CLAUDE.md § Tests.
"""
from __future__ import annotations

import datetime
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.config import Settings
from ..domain.vision_event import build_event_payload
from ..services.capture_writer import CaptureWriter

logger = logging.getLogger(__name__)

# Kedalaman antrean. Tiga janjang = ~1,8 detik kerja penulis pada frame sensor
# penuh; lebih dalam dari itu cuma menunda kabar buruk (dan menahan referensi ke
# frame 15 MB yang belum boleh dilepas GC). Penuh = grading memang lebih cepat
# dari disk, dan itu harus terdengar, bukan diserap diam-diam.
_QUEUE_MAX = 3

# Berapa lama penulis boleh menunggu pekerjaan sebelum melihat flag berhenti
# lagi. Hanya menentukan kecepatan shutdown, bukan throughput.
_POLL_TIMEOUT = 0.5

# Satu janjang selambat ini berarti disknya yang bermasalah, bukan ukuran frame.
# Diadukan supaya regresi seperti 2026-09-17 kelihatan dari log, bukan dari
# menghitung mikrodetik nama file di lapangan.
_SLOW_SAVE_S = 1.0


@dataclass
class SaveJob:
    """Satu janjang, lengkap, sebagaimana thread deteksi melihatnya.

    Semua identitas — `timestamp`, `date_folder`, `truck_folder`, `event_ts` —
    dihitung SAAT DETEKSI dan dibawa ke sini apa adanya. Penulis tidak pernah
    melihat jam. Itu bukan detail gaya: `event_id` adalah uuid5 dari `timestamp`,
    dan `BatchUploadWorker` menghitung ulang id yang sama dari NAMA FILE berjam-
    jam kemudian. Penulis yang menstempel jamnya sendiri akan membuat dua jalur
    itu menghasilkan id berbeda untuk satu janjang — API tidak lagi bisa membalas
    `already_processed`, dan janjangnya terhitung dua kali.

    `truck_id`, `assignment_id`, dan `ffb_source` ikut disalin karena truk bisa
    dilepas dari line antara deteksi dan penulisan; membaca `RuntimeState` dari
    sini akan menyimpan janjang ke truk yang salah.
    """

    timestamp: str
    date_folder: str
    truck_folder: str
    annotated_frame: Any
    clean_frame: Any
    ripeness_status: str
    ripeness_conf: float
    grade_class: str | None
    bounding_box: dict[str, int]
    truck_id: str | None
    assignment_id: str | None
    ffb_source: str | None
    event_ts: str
    tp: dict | None = None
    # Jam serah-terima, untuk mengukur berapa lama janjang menunggu di antrean.
    enqueued_at: float = field(default_factory=time.monotonic)

    @property
    def filename(self) -> str:
        """Nama berkas gambar. Diturunkan dari `timestamp`, satu tempat saja."""
        return f"{self.timestamp}_auto.webp"


class CaptureSaveWorker:
    """Antrean + satu thread penulis per line."""

    def __init__(
        self,
        settings: Settings,
        storage: Any,
        outbox_store: Any,
        queue_max: int = _QUEUE_MAX,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.outbox_store = outbox_store
        self.capture_writer = CaptureWriter(settings, storage)
        self._queue: queue.Queue[SaveJob] = queue.Queue(maxsize=queue_max)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._selesai = threading.Condition()
        # Per instance, BUKAN atribut kelas: tiga line dalam satu proses (tes,
        # dan `make line` yang menjalankan beberapa app) akan saling mengaku
        # sibuk, dan `tunggu_kosong` salah satu line akan menunggu pekerjaan
        # line lain.
        self._sedang_menulis = False

    # --------------------------------------------------------------- lifecycle

    @property
    def antrean(self) -> int:
        """Janjang yang menunggu ditulis. Naik terus = penulis kalah cepat."""
        return self._queue.qsize()

    def start(self) -> threading.Thread:
        self._stop.clear()
        thread = threading.Thread(target=self.run_loop, daemon=True, name="capture_save")
        thread.start()
        self._thread = thread
        return thread

    def stop(self, timeout: float = 5.0) -> None:
        """Minta penulis berhenti sesudah pekerjaan yang sedang dipegangnya.

        `run_loop` boleh dijalankan thread yang dibuat di luar (`main.py`
        memakai `_start_worker` supaya watchdog ikut mengawasinya), jadi
        `_thread` bisa kosong — flag-nya tetap yang menghentikan loop.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def tunggu_kosong(self, timeout: float = 5.0) -> bool:
        """Antrean kosong DAN tidak ada yang sedang ditulis. Untuk tes dan shutdown."""
        with self._selesai:
            return self._selesai.wait_for(
                lambda: self._queue.empty() and not self._sedang_menulis, timeout=timeout
            )

    # ------------------------------------------------------------------ submit

    def submit(self, job: SaveJob) -> bool:
        """Serahkan satu janjang. Balik seketika. `False` = antrean penuh, dibuang.

        Yang dibuang adalah janjang yang BARU datang, bukan yang sudah antre.
        Yang lama sudah menerima pulse PLC-nya dan urutannya adalah urutan buah
        di conveyor; membuang dari depan akan membuat bukti yang tersimpan tidak
        sejalan dengan yang disortir mesin.

        Memblokir di sini akan mengembalikan persis masalah yang thread ini
        dibuat untuk menghilangkannya, jadi ini sengaja `put_nowait`.
        """
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            logger.error(
                "Antrean simpan penuh (%d) — janjang %s TIDAK disimpan. "
                "Disk atau CPU tidak mengimbangi laju grading.",
                self._queue.maxsize,
                job.timestamp,
            )
            return False

    # ------------------------------------------------------------------- tulis

    def run_once(self, job: SaveJob) -> None:
        """Tulis satu janjang. Melempar kalau gambar bukti gagal ditulis.

        Urutannya load-bearing (Critical Rule #8): gambar dulu, baru sidecar,
        baru outbox. `write_pair` melempar OSError kalau salinan bbox gagal, dan
        berhenti di situ berarti tidak ada catatan yang menunjuk file hantu.
        """
        image_url = self.capture_writer.write_pair(
            date_folder=job.date_folder,
            truck_folder=job.truck_folder,
            ripeness_status=job.ripeness_status,
            filename=job.filename,
            annotated_frame=job.annotated_frame,
            clean_frame=job.clean_frame,
        )

        results_dir = self.settings.results_dir / job.date_folder
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        self.storage.write_json(
            results_dir / f"{job.timestamp}_auto_ripeness.json",
            {
                "timestamp": job.event_ts,
                "image_path": image_url,
                "ripeness_status": job.ripeness_status,
                "grade_class": job.grade_class,
                "ripeness_confidence": round(job.ripeness_conf, 2),
                "tp_status": None,
                "tp_confidence": 0,
                "capture_type": "auto",
                "truck_id": job.truck_id,
                "bounding_box": job.bounding_box,
                "assignment_id": job.assignment_id,
                "ffb_source": job.ffb_source,
            },
        )

        if job.tp:
            bbox = job.tp["bbox"]
            self.storage.write_json(
                results_dir / f"{job.timestamp}_auto_tp.json",
                {
                    "timestamp": now_iso,
                    "image_path": None,
                    "ripeness_status": None,
                    "ripeness_confidence": 0,
                    "tp_status": job.tp["tp_status"],
                    "tp_confidence": round(job.tp["tp_confidence"], 2),
                    "capture_type": "auto",
                    "truck_id": job.truck_id,
                    "bounding_box": {
                        "x_min": bbox[0], "y_min": bbox[1],
                        "x_max": bbox[2], "y_max": bbox[3],
                    },
                    "assignment_id": job.assignment_id,
                },
            )

        payload = build_event_payload(
            machine_id=self.settings.machine_id,
            file_ts=job.timestamp,
            timestamp=job.event_ts,
            ripeness_status=job.ripeness_status,
            ripeness_confidence=job.ripeness_conf,
            capture_type="auto",
            image_path=image_url,
            truck_id=job.truck_id,
            assignment_id=job.assignment_id,
            bounding_box=job.bounding_box,
            tp_status=job.tp["tp_status"] if job.tp else None,
            tp_confidence=job.tp["tp_confidence"] if job.tp else None,
            grade_class=job.grade_class,
        )
        try:
            self.outbox_store.add_event(
                payload["event_id"], self.settings.machine_id, payload
            )
        except Exception as exc:
            # Gambar dan sidecar sudah aman di disk, dan `BatchUploadWorker`
            # membaca sidecar itu sendiri — jadi janjangnya tidak hilang, cuma
            # terlambat sampai ke layar. Melempar di sini akan membuat penulis
            # mengulang encode yang sudah berhasil.
            logger.error("Gagal menulis event %s ke outbox: %s", payload["event_id"], exc)

    def run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=_POLL_TIMEOUT)
            except queue.Empty:
                continue

            self._sedang_menulis = True
            mulai = time.monotonic()
            try:
                self.run_once(job)
            except Exception:
                # Satu janjang gagal TIDAK boleh mematikan penulis: tanpa thread
                # ini tidak ada lagi yang menyimpan bukti, sementara deteksi,
                # PLC, dan layar tetap jalan seolah semuanya normal.
                logger.exception("Gagal menyimpan janjang %s", job.timestamp)
            finally:
                lama = time.monotonic() - mulai
                tunggu = mulai - job.enqueued_at
                if lama + tunggu >= _SLOW_SAVE_S:
                    logger.warning(
                        "Simpan janjang %s lambat: tulis %.0f ms, antre %.0f ms, antrean=%d",
                        job.timestamp, lama * 1000, tunggu * 1000, self._queue.qsize(),
                    )
                self._sedang_menulis = False
                self._queue.task_done()
                with self._selesai:
                    self._selesai.notify_all()
