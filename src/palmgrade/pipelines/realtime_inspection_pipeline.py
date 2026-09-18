from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ..core.config import Settings
from ..core.constants import (
    COLOR_FAIL,
    COLOR_PASS,
    COLOR_ROI,
    COLOR_TP,
    COLOR_TRIGGER,
    FONT,
    TRIGGER_THICKNESS,
)
from ..domain.garis_capture import MENDATAR, TEGAK
from ..domain.grade_class import TP, grade_class_or_none, verdict_for_class
from .model_registry import ModelRegistry

# Jarak garis pemicu dari tepi kanan frame saat ROI memenuhi layar. Cukup untuk
# lepas dari bingkai video di browser dan tetap terbaca dari beberapa meter;
# lebih jauh dari ini garisnya mulai berbohong soal di mana pemicunya.
_TRIGGER_MARGIN = 6


class RealtimeInspectionPipeline:
    def __init__(self, model_registry: ModelRegistry, settings: Settings) -> None:
        self.model_registry = model_registry
        self.settings = settings
        self._roi_enabled = not (
            settings.roi_x1 == 0 and settings.roi_y1 == 0
            and settings.roi_x2 == 0 and settings.roi_y2 == 0
        )
        self._use_half = model_registry.device == "cuda"

    @property
    def model(self):
        return self.model_registry.model

    # ------------------------------------------------------------------ draw

    def draw_boxes(
        self, frame: np.ndarray, results: Any, *, tampilkan_confidence: bool = False
    ) -> np.ndarray:
        """`tampilkan_confidence` = mode dev (setelan `mode_dev` dari konsol).

        Bawaannya MATI, dan itu keputusan operator (2026-09-18): angkanya
        keyakinan model, bukan mutu buah, dan dari beberapa meter "54%"
        terbaca seperti "54% matang". Support yang menyetel `CONF_THRESHOLD`
        justru butuh angka itu — makanya jadi saklar, bukan dihapus.
        """
        if results.boxes is None:
            return frame
        bt = self.settings.border_thickness
        fs = self.settings.font_scale
        ft = self.settings.font_thickness
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            label = results.names[int(box.cls[0].item())]
            score = float(box.conf[0].item())
            # Warna ikut VERDICT, bukan substring nama kelas. Dulu barisnya
            # `"rej" in label.lower()`, dan itu benar selama model masih
            # ACC/Rej/TP. Untuk model 4 kelas SALAH TOTAL: `Unripe` dan `JK`
            # tidak mengandung "rej", jadi janjang yang justru dibuang piston
            # digambar HIJAU — operator melihat hijau untuk buah yang ditolak.
            kelas = grade_class_or_none(label)
            verdict = verdict_for_class(kelas) if kelas else None
            color = COLOR_FAIL if verdict == "REJ" else COLOR_PASS
            # TP bukan buah dan tidak punya verdict: dikuningkan supaya tidak
            # terbaca sebagai "lolos" padahal dia cuma penanda tangkai panjang.
            if kelas == TP:
                color = COLOR_TP
            # bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, bt)
            # Teks memakai nama kelas apa adanya (Ripe/Unripe/JK/TP), BUKAN
            # `.upper()`: operator menyebut kelasnya persis begini, dan JK yang
            # jadi "JK" sama saja sedangkan "UNRIPE" lebih sulit dipindai mata
            # dari jarak jauh daripada "Unripe".
            #
            # **Tanpa angka confidence** (2026-09-18, permintaan operator).
            # Angkanya keyakinan MODEL, bukan mutu buah, dan dua-duanya terbaca
            # seperti "54% matang" dari jarak beberapa meter. Ambangnya sudah
            # diputuskan `CONF_THRESHOLD`: apa pun yang tergambar di sini sudah
            # lolos ambang itu, jadi angkanya tidak mengubah satu keputusan pun
            # yang diambil operator. `viewer.html` membuangnya lebih dulu
            # (commit abd8f17) — ini menyamakan layar line dengan layar detail.
            # Nilainya TETAP disimpan di sidecar dan dikirim ke API: yang
            # dibuang tampilannya, bukan datanya.
            text = f"{kelas or label}"
            if tampilkan_confidence:
                text = f"{text} {score * 100:.0f}%"
            (tw, th), bl = cv2.getTextSize(text, FONT, fs, ft)
            ty = y1 - 10 if y1 - th - 10 >= 0 else y1 + th + 10
            cv2.putText(frame, text, (x1, ty), FONT, fs, (0, 0, 0), ft + 4, cv2.LINE_AA)  # outline tebal
            cv2.putText(frame, text, (x1, ty), FONT, fs, color, ft + 1, cv2.LINE_AA)      # teks warna, agak tebal
        return frame

    def roi_in_stream_space(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """Kotak ROI seperti yang terlihat di layar, atau `None` kalau tidak sah.

        `ROI_*` memang ditulis dalam ruang stream (operator mengalibrasinya dari
        gambar di browser), jadi di sini tidak ada penskalaan — yang menskalakan
        ke ruang sensor adalah `FrameProcessingWorker._roi_box_for`, karena di
        sanalah deteksi benar-benar berjalan.
        """
        rx1 = self.settings.roi_x1
        ry1 = self.settings.roi_y1
        rx2 = self.settings.roi_x2 if self.settings.roi_x2 > 0 else width
        ry2 = self.settings.roi_y2 if self.settings.roi_y2 > 0 else height
        if rx2 <= rx1 or ry2 <= ry1:
            return None
        return rx1, ry1, rx2, ry2

    def draw_roi(
        self, frame: np.ndarray, garis_capture: int = 0, sumbu: str = TEGAK
    ) -> np.ndarray:
        """Kotak ROI (hijau, tipis) + garis capture (biru, tebal, bertanda).

        Dua hal berbeda yang sengaja digambar berbeda, karena keduanya menjawab
        pertanyaan yang berbeda:

        * **ROI** = WILAYAH. Bagian frame yang dianggap conveyor; janjang di luar
          itu tidak dihitung sama sekali. Tipis, karena ini konteks.
        * **Garis capture** = WAKTU. Janjang difoto saat kotaknya MENYENTUH garis
          ini (`domain/garis_capture.menyentuh_garis`). Tebal dan bertanda,
          karena inilah yang ditunjuk operator saat menyetel.

        `garis_capture` datang dari pemanggil (`DisplayWorker`) dalam ruang
        stream, bukan dibaca dari `Settings` di sini: nilainya bisa diubah dari
        konsol tanpa restart, dan `Settings` `frozen=True` dengan sengaja.

        `0` = tidak ada garis, dan tidak ada yang digambar selain ROI. Itu
        perilaku sebelum fitur ini ada, dan tetap sah — tapi artinya janjang
        difoto begitu masuk ROI, yang pada ROI penuh layar berarti begitu
        terdeteksi di mana pun.
        """
        h, w = frame.shape[:2]
        kotak = self.roi_in_stream_space(w, h)
        if kotak is not None and self._roi_enabled:
            rx1, ry1, rx2, ry2 = kotak
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), COLOR_ROI, 2)

        if garis_capture <= 0:
            return frame

        teks = "CAPTURE"
        skala, tebal = 0.6, 2
        (tw, th), _ = cv2.getTextSize(teks, FONT, skala, tebal)

        # Dijepit ke dalam frame: garis di baris/kolom terakhir terpotong separuh
        # oleh cv2 dan berhimpit dengan bingkai video di browser, jadi praktis
        # tidak terlihat justru saat operator paling perlu melihatnya.
        #
        # Labelnya selalu ditaruh di sisi yang MASIH muat: teks yang keluar layar
        # sama saja dengan tidak ada label, dan garis berwarna tanpa keterangan
        # cuma memindahkan pertanyaannya.
        if sumbu == MENDATAR:
            y = max(_TRIGGER_MARGIN, min(garis_capture, h - 1 - _TRIGGER_MARGIN))
            cv2.line(frame, (0, y), (w, y), COLOR_TRIGGER, TRIGGER_THICKNESS)
            tx = 8
            ty = y - 8 if y - th - 8 >= 0 else y + th + 8
        else:
            x = max(_TRIGGER_MARGIN, min(garis_capture, w - 1 - _TRIGGER_MARGIN))
            cv2.line(frame, (x, 0), (x, h), COLOR_TRIGGER, TRIGGER_THICKNESS)
            tx = x - tw - 8 if x - tw - 8 >= 4 else min(x + 8, w - tw - 4)
            ty = th + 8

        cv2.putText(frame, teks, (tx, ty), FONT, skala, (0, 0, 0), tebal + 3, cv2.LINE_AA)
        cv2.putText(frame, teks, (tx, ty), FONT, skala, COLOR_TRIGGER, tebal, cv2.LINE_AA)
        return frame

    # ----------------------------------------------------------------- track

    def track_ripeness(self, frame: np.ndarray, conf: float | None = None) -> Any:
        """`conf` menimpa `CONF_THRESHOLD` dari `.env` kalau diisi.

        Dikirim sebagai argumen, bukan dibaca dari `RuntimeState` di sini:
        pipeline sengaja tidak tahu apa-apa soal state runtime — yang memegang
        state itu worker, dan itu yang membuat pipeline bisa dites tanpa merakit
        satu line pun.
        """
        return self.model.track(
            frame, persist=True,
            conf=self.settings.conf_threshold if conf is None else conf,
            tracker="bytetrack.yaml", verbose=False, half=self._use_half,
        )[0]

    def reset_tracker(self) -> None:
        try:
            if self.model.predictor is not None and hasattr(self.model.predictor, "trackers"):
                for tracker in self.model.predictor.trackers:
                    tracker.reset()
        except Exception:
            pass

    def get_status(self) -> dict:
        return {
            "device": self.model_registry.device,
            "model": str(self.settings.ripeness_model_path),
        }
