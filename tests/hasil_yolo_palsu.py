"""Fake YOLO results and a scripted line for `FrameProcessingWorker` tests, without torch.

`KotakPalsu` copies the part of `ultralytics.engine.results.Boxes` the worker reads: one
`data` array per frame (`x1, y1, x2, y2, track_id, conf, cls`), per-box views through
iteration, and `cpu()` / `numpy()`. It counts what costs time on a GPU: every column read on
a view that has not been moved to the CPU stands for one `.item()` or `.tolist()` call, which
on CUDA is one synchronisation with the GPU.

`LineBerskrip` runs the REAL worker over scripted frames and records what leaves it (PLC
signals, save jobs, screen events, worker state), so the same script can be compared between
two ways of reading the boxes. Imported as `hasil_yolo_palsu` (pattern of `ai_palsu`).
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from palmgrade.core.config import Settings
from palmgrade.workers import frame_processing_worker
from palmgrade.workers.frame_processing_worker import FrameProcessingWorker
from palmgrade.workers.runtime_state import RuntimeState

#: The real class order of `best.pt` (see `tests/unit/test_grade_class_detection.py`).
NAMA_KELAS = {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"}
ID_KELAS = {nama: nomor for nomor, nama in NAMA_KELAS.items()}

#: Sensor frame of the factory camera. Only the shape is used: ROI and the capture line are
#: scaled from stream space (1280x720) to this.
LEBAR_FRAME, TINGGI_FRAME = 2448, 2048


@dataclass
class Hitung:
    """What one frame cost. Shared by a boxes object and every view made from it."""

    pindah_cpu: int = 0       # `boxes.cpu()` calls: one whole-array transfer each
    baca_di_device: int = 0   # column reads before `cpu()`: one GPU sync each in the real thing


class KotakPalsu:
    def __init__(
        self, data: np.ndarray, *, berjejak: bool = True, hitung: Hitung | None = None,
        di_cpu: bool = False,
    ) -> None:
        self.data = data
        self._berjejak = berjejak
        self.hitung = hitung if hitung is not None else Hitung()
        self._di_cpu = di_cpu

    def _lihat(self, data: np.ndarray, *, di_cpu: bool) -> KotakPalsu:
        return KotakPalsu(data, berjejak=self._berjejak, hitung=self.hitung, di_cpu=di_cpu)

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self):
        for i in range(len(self.data)):
            yield self._lihat(self.data[i : i + 1], di_cpu=self._di_cpu)

    def _kolom(self, kolom: np.ndarray) -> np.ndarray:
        if not self._di_cpu:
            self.hitung.baca_di_device += 1
        return kolom

    @property
    def xyxy(self) -> np.ndarray:
        return self._kolom(self.data[:, :4])

    @property
    def conf(self) -> np.ndarray:
        return self._kolom(self.data[:, -2])

    @property
    def cls(self) -> np.ndarray:
        return self._kolom(self.data[:, -1])

    @property
    def id(self) -> np.ndarray | None:
        # Like ultralytics: `None` for the whole frame when the tracker gave no ids.
        return self._kolom(self.data[:, -3]) if self._berjejak else None

    def cpu(self) -> KotakPalsu:
        self.hitung.pindah_cpu += 1
        return self._lihat(self.data, di_cpu=True)

    def numpy(self) -> KotakPalsu:
        return self


class HasilPalsu:
    """One frame's `Results`: `boxes` (or None) and `names`."""

    def __init__(self, boxes: KotakPalsu | None, names: dict[int, str] | None = None) -> None:
        self.boxes = boxes
        self.names = NAMA_KELAS if names is None else names


def kotak(
    track_id: int, kelas: str, x1: float, y1: float, x2: float, y2: float, conf: float = 0.9
) -> tuple[float, ...]:
    """One row of `data`. Coordinates are in the sensor frame and may carry a fraction."""
    return (x1, y1, x2, y2, track_id, conf, ID_KELAS[kelas])


def hasil(*baris: tuple[float, ...], berjejak: bool = True, names: dict[int, str] | None = None) -> HasilPalsu:
    """A frame with these boxes. `berjejak=False` = the tracker gave no ids (`boxes.id is None`)."""
    data = np.array(baris, dtype=np.float32).reshape(len(baris), 7)
    if not berjejak:
        data = np.delete(data, 4, axis=1)
    return HasilPalsu(KotakPalsu(data, berjejak=berjejak), names)


class _Frame:
    """Stands in for the camera frame: the worker only reads `shape` and copies it."""

    shape = (TINGGI_FRAME, LEBAR_FRAME, 3)

    def copy(self) -> _Frame:
        return self


class _PipelineBerskrip:
    def __init__(self) -> None:
        self.berikutnya: Any = None

    def track_ripeness(self, frame, conf=None):
        return self.berikutnya

    def reset_tracker(self) -> None:
        pass

    def draw_boxes(self, frame, results, **_):
        return frame


class _PenulisRekam:
    def __init__(self) -> None:
        self.jobs: list = []

    def submit(self, job) -> bool:
        self.jobs.append(job)
        return True


class LineBerskrip:
    """The real `FrameProcessingWorker` with a scripted pipeline, one frame per `proses()`."""

    def __init__(self, monkeypatch, **setelan) -> None:
        self.sinyal_plc: list[str] = []
        monkeypatch.setattr(frame_processing_worker, "submit_grading", self.sinyal_plc.append)
        self.state = RuntimeState()
        self.pipeline = _PipelineBerskrip()
        self.penulis = _PenulisRekam()
        self.settings = replace(
            Settings(), lic_enabled=False, machine_id="mesin-uji", yolo_skip_frames=1,
            minimum_size=460_000, garis_capture=300, sumbu_garis="tegak",
            stream_width=1280, stream_height=720,
            **{"roi_x1": 0, "roi_y1": 0, "roi_x2": 0, "roi_y2": 0, **setelan},
        )
        self.worker = FrameProcessingWorker(
            pipeline=self.pipeline, state=self.state, storage=object(), webhook=None,
            settings=self.settings, outbox_store=None, capture_saver=self.penulis,
            tidur=lambda _detik: None,
        )

    def proses(self, results: HasilPalsu) -> dict[str, Any]:
        """Run one frame and return what it produced, without anything that carries a clock."""
        self.pipeline.berikutnya = results
        mulai_job, mulai_plc = len(self.penulis.jobs), len(self.sinyal_plc)
        self.state.frame_queue.put(_Frame())
        self.worker.run_once()
        acara = []
        while not self.state.event_queue.empty():
            acara.append(self.state.event_queue.get_nowait())
        return {
            "plc": self.sinyal_plc[mulai_plc:],
            "simpan": [_ringkas_job(job) for job in self.penulis.jobs[mulai_job:]],
            "acara": [_ringkas_acara(a) for a in acara],
            "tp_telat": self.state.tp_telat,
            "sudah_diproses": sorted(self.worker._processed_objects),
            "tp_terhitung": sorted(self.worker._tp_terhitung),
            "janjang_difoto": [list(bbox) for bbox, _ in self.worker._janjang_difoto],
            "jejak": {
                str(tid): [t["label"], t["score"], list(t["bbox"]), t["processed"], bool(t.get("plc_signalled"))]
                for tid, t in sorted(self.state.track_history.items())
            },
        }


def _ringkas_tp(tp: dict | None) -> list | None:
    if tp is None:
        return None
    return [tp["track_id"], tp["tp_status"], tp["tp_confidence"], list(tp["bbox"])]


def _ringkas_job(job) -> dict[str, Any]:
    return {
        "status": job.ripeness_status,
        "kelas": job.grade_class,
        "conf": job.ripeness_conf,
        "kotak": job.bounding_box,
        "tp": _ringkas_tp(job.tp),
    }


def _ringkas_acara(acara: dict) -> dict[str, Any]:
    return {
        kunci: acara[kunci]
        for kunci in (
            "ripeness_status", "grade_class", "ripeness_confidence", "tp_status",
            "tp_confidence", "title", "description", "capture_type", "bounding_box",
        )
    }


#: Mostly ripe, like the conveyor. Picked with `random()` only (no `choice`, no `shuffle`), so a
#: seed gives the same frames on every Python version.
_CAMPURAN = ("Ripe", "Ripe", "Ripe", "Unripe", "JK", "TP")


def skenario_acak(benih: int, jumlah_frame: int) -> list[HasilPalsu]:
    """A seeded stretch of conveyor: bunches and stalks moving right to left, some stacked,
    some too small, ids that vanish and return, a frame with no ids, and empty frames.

    Coordinates carry fractions on purpose: the worker truncates them, and both ways of
    reading must truncate alike.
    """
    acak = random.Random(benih)
    benda: list[dict[str, Any]] = []
    nomor = 0
    frames: list[HasilPalsu] = []
    for _ in range(jumlah_frame):
        if acak.random() < 0.22 and len(benda) < 5:
            nomor += 1
            kelas = _CAMPURAN[int(acak.random() * len(_CAMPURAN))]
            if kelas == "TP":
                lebar, tinggi = acak.uniform(80, 220), acak.uniform(80, 220)
            else:
                lebar, tinggi = acak.uniform(560, 1100), acak.uniform(560, 1100)
            baru = {
                "id": nomor, "kelas": kelas, "lebar": lebar, "tinggi": tinggi,
                "x": LEBAR_FRAME - acak.uniform(0, 600), "y": acak.uniform(0, TINGGI_FRAME - tinggi),
                "laju": acak.uniform(140, 320),
            }
            benda.append(baru)
            if kelas == "Ripe" and acak.random() < 0.5:
                # A long stalk travelling with its bunch, ahead of it or behind it.
                nomor += 1
                sisi = acak.uniform(90, 200)
                geser = -sisi * 0.6 if acak.random() < 0.5 else lebar - sisi * 0.4
                benda.append({
                    "id": nomor, "kelas": "TP", "lebar": sisi, "tinggi": sisi,
                    "x": baru["x"] + geser, "y": baru["y"] + acak.uniform(0, tinggi - sisi),
                    "laju": baru["laju"],
                })
        for b in benda:
            b["x"] -= b["laju"]
        benda = [b for b in benda if b["x"] + b["lebar"] > 0]

        pilihan = acak.random()
        if pilihan < 0.05:
            frames.append(HasilPalsu(None))
            continue
        terlihat = [b for b in benda if acak.random() > 0.1]
        terlihat.sort(key=lambda _b: acak.random())
        baris = [
            kotak(
                -1 if acak.random() < 0.05 else b["id"], b["kelas"],
                b["x"], b["y"], b["x"] + b["lebar"], b["y"] + b["tinggi"],
                conf=acak.uniform(0.3, 0.99),
            )
            for b in terlihat
        ]
        frames.append(hasil(*baris, berjejak=pilihan >= 0.1))
    return frames


def ringkasan_skenario(monkeypatch, benih: int, jumlah_frame: int = 60) -> dict[str, Any]:
    """Run one seeded scenario and reduce it to what a golden file can hold: the counts a
    person can read, and a digest of every frame's full trace."""
    # Odd seeds narrow the detection area to the left third of the stream, so fewer bunches
    # count as stacked and more of them are graded on their own class.
    sempit = {"roi_x1": 0, "roi_y1": 0, "roi_x2": 420, "roi_y2": 720} if benih % 2 else {}
    line = LineBerskrip(monkeypatch, **sempit)
    jejak = [line.proses(frame) for frame in skenario_acak(benih, jumlah_frame)]
    simpan = [job for frame in jejak for job in frame["simpan"]]
    return {
        "benih": benih,
        "pulse_plc": sum(len(frame["plc"]) for frame in jejak),
        "janjang_disimpan": len(simpan),
        "acc": sum(1 for job in simpan if job["status"] == "acc"),
        "rej": sum(1 for job in simpan if job["status"] == "rej"),
        "tp_terpasang": sum(1 for job in simpan if job["tp"] is not None),
        "tp_telat": jejak[-1]["tp_telat"],
        "sidik": hashlib.sha256(json.dumps(jejak, sort_keys=True).encode()).hexdigest(),
    }
