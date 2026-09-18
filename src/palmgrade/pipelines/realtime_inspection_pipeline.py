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

    def draw_boxes(self, frame: np.ndarray, results: Any) -> np.ndarray:
        if results.boxes is None:
            return frame
        bt = self.settings.border_thickness
        fs = self.settings.font_scale
        ft = self.settings.font_thickness
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            label = results.names[int(box.cls[0].item())]
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

    def draw_roi(self, frame: np.ndarray) -> np.ndarray:
        """Kotak ROI (hijau) + garis pemicu capture (biru).

        Garis birunya menjawab satu pertanyaan yang sebelumnya cuma bisa dijawab
        dengan membaca kode: **di titik mana janjang difoto?** Jawabannya, titik
        TENGAH kotak janjang masuk ke kotak ROI (`_is_in_roi`, dievaluasi tiap
        frame). Karena buah bergerak dari kanan ke kiri di conveyor, batas yang
        dilewati lebih dulu adalah **sisi kanan** ROI — itu yang digambar tebal.
        Salah menandai sisi kiri akan membuat operator menggeser ROI ke arah
        yang keliru saat menyetel.
        ⚠️ Yang menentukan itu titik tengah, bukan tepi janjang. Jadi foto diambil
        saat SETENGAH janjang sudah melewati garis, bukan saat ujungnya menyentuh.
        Itu sebabnya capture terasa "terlalu cepat" kalau garisnya tidak terlihat.

        Digambar **selalu**, termasuk saat `ROI_*` masih `0,0,0,0`. Justru itu
        keadaan yang paling perlu terlihat: ROI penuh layar berarti janjang
        difoto begitu terdeteksi di mana pun, termasuk di pinggir frame tempat
        janjangnya belum utuh — dan tanpa garis ini, layarnya kosong dan
        terbaca seolah tidak ada aturan sama sekali.
        """
        h, w = frame.shape[:2]
        kotak = self.roi_in_stream_space(w, h)
        if kotak is None:
            return frame
        rx1, ry1, rx2, ry2 = kotak

        # Kotak ROI: batas wilayah yang dihitung. Tipis, karena ini konteks.
        if self._roi_enabled:
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), COLOR_ROI, 2)

        # Garis pemicu: tebal, biru, dari atas ke bawah kotak ROI.
        #
        # Ditarik MASUK dari tepi frame, bukan sekadar dijepit ke kolom terakhir.
        # Garis di kolom paling kanan terpotong separuh lebarnya oleh cv2 dan
        # berhimpit dengan bingkai video di browser — pada ROI penuh layar
        # (keadaan bawaan, dan keadaan PC Lampung saat ini) hasilnya praktis
        # tidak terlihat, padahal justru itu keadaan yang paling perlu terbaca:
        # tanpa ROI, janjang difoto begitu terdeteksi di mana pun.
        x = min(rx2, w - 1 - _TRIGGER_MARGIN)
        cv2.line(frame, (x, ry1), (x, ry2), COLOR_TRIGGER, TRIGGER_THICKNESS)

        # Diberi nama, karena garis berwarna tanpa keterangan cuma memindahkan
        # pertanyaannya. Ditulis di sisi KIRI garis supaya tidak keluar layar
        # saat garisnya menempel tepi kanan.
        teks = "CAPTURE"
        skala, tebal = 0.6, 2
        (tw, th), _ = cv2.getTextSize(teks, FONT, skala, tebal)
        tx = max(4, x - tw - 8)
        ty = min(ry1 + th + 8, frame.shape[0] - 4)
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
