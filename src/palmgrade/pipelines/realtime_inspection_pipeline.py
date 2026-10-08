from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ..core.config import Settings
from ..core.constants import (
    COLOR_FAIL,
    COLOR_FPS_LATAR,
    COLOR_FPS_TEKS,
    COLOR_LABEL_TEKS,
    COLOR_PASS,
    COLOR_ROI,
    COLOR_TP,
    COLOR_TRIGGER,
    FONT,
    FPS_ALPHA,
    FPS_FONT_SCALE,
    FPS_FONT_THICKNESS,
    TRIGGER_THICKNESS,
)
from ..domain.garis_capture import MENDATAR, TEGAK
from ..domain.grade_class import TP, grade_class_or_none, verdict_for_class
from ..domain.skala_tampilan import (
    TANPA_SKALA,
    garis_berskala,
    gaya_berskala,
    gaya_label,
    jari_kotak,
    kotak_berskala,
    pil_fps,
    pil_label,
)
from .model_registry import ModelRegistry

# Jarak garis pemicu dari tepi kanan frame saat ROI memenuhi layar. Cukup untuk
# lepas dari bingkai video di browser dan tetap terbaca dari beberapa meter;
# lebih jauh dari ini garisnya mulai berbohong soal di mana pemicunya.
_TRIGGER_MARGIN = 6

#: Text size inside a label pill, as a share of the `.env` label size (see `draw_boxes`).
_TEKS_PIL = 0.75


def _kotak_bulat(img: np.ndarray, kotak: tuple[int, int, int, int], warna, tebal: int, r: int) -> None:
    """Box outline with rounded corners (console design 2026-10-08).

    The straight sides are drawn without anti-aliasing so their pixels are exactly `warna`;
    only the corner arcs are smoothed.
    """
    x1, y1, x2, y2 = kotak
    if r <= 0:
        cv2.rectangle(img, (x1, y1), (x2, y2), warna, tebal)
        return
    cv2.line(img, (x1 + r, y1), (x2 - r, y1), warna, tebal)
    cv2.line(img, (x1 + r, y2), (x2 - r, y2), warna, tebal)
    cv2.line(img, (x1, y1 + r), (x1, y2 - r), warna, tebal)
    cv2.line(img, (x2, y1 + r), (x2, y2 - r), warna, tebal)
    for pusat, sudut in (((x1 + r, y1 + r), 180), ((x2 - r, y1 + r), 270),
                         ((x2 - r, y2 - r), 0), ((x1 + r, y2 - r), 90)):
        cv2.ellipse(img, pusat, (r, r), sudut, 0, 90, warna, tebal, cv2.LINE_AA)


def _isi_bulat(img: np.ndarray, kotak: tuple[int, int, int, int], warna, r: int) -> None:
    """A filled rectangle with rounded corners: the label and FPS pills."""
    x1, y1, x2, y2 = kotak
    r = max(0, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), warna, -1)
    cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), warna, -1)
    if r > 0:
        for pusat in ((x1 + r, y1 + r), (x2 - r, y1 + r), (x2 - r, y2 - r), (x1 + r, y2 - r)):
            cv2.circle(img, pusat, r, warna, -1, cv2.LINE_AA)


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
        self, frame: np.ndarray, results: Any, *, tampilkan_confidence: bool = False,
        skala: tuple[float, float] = TANPA_SKALA, ukuran_label: int = 100,
    ) -> np.ndarray:
        """`tampilkan_confidence` = mode dev (setelan `mode_dev` dari konsol).

        Bawaannya MATI, dan itu keputusan operator (2026-09-18): angkanya
        keyakinan model, bukan mutu buah, dan dari beberapa meter "54%"
        terbaca seperti "54% matang". Support yang menyetel `CONF_THRESHOLD`
        justru butuh angka itu — makanya jadi saklar, bukan dihapus.

        `skala` (batch 6.3) = from the frame the model saw to `frame`. `DisplayWorker`
        shrinks the picture first and draws here on the small frame, so the boxes and the
        `.env` style (written for the sensor frame) shrink with it. Left at its default,
        as for the saved evidence photo, nothing is scaled and the drawing is unchanged.
        """
        if results.boxes is None:
            return frame
        # `ukuran_label` (percent, set by support from the console) grows or shrinks the
        # text only. The saved evidence photo leaves it at 100.
        bt, fs, ft, jarak = gaya_label(gaya_berskala(
            self.settings.border_thickness, self.settings.font_scale,
            self.settings.font_thickness, skala,
        ), ukuran_label)
        for box in results.boxes:
            x1, y1, x2, y2 = kotak_berskala(*map(int, box.xyxy[0].tolist()), skala)
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
            # Bounding box with rounded corners, as in the console design (2026-10-08).
            _kotak_bulat(frame, (x1, y1, x2, y2), color, bt, jari_kotak(bt, x2 - x1, y2 - y1))
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
            # Label = a pill filled in the box colour with near-black text on the box's top-left
            # corner (console design 2026-10-08). It replaced coloured text with a black outline:
            # dark on a solid colour reads from further away than colour on a busy conveyor.
            # The text inside is `_TEKS_PIL` of the `.env` size, so the whole pill takes about the
            # height the bare text took and `FONT_SCALE` keeps meaning "how big the label is".
            fs_pil = fs * _TEKS_PIL
            (tw, th), _ = cv2.getTextSize(text, FONT, fs_pil, ft)
            pil, asal = pil_label(x1, y1, tw, th, jarak=jarak, lebar_gambar=frame.shape[1])
            _isi_bulat(frame, pil, color, round((pil[3] - pil[1]) * 0.3))
            cv2.putText(frame, text, asal, FONT, fs_pil, COLOR_LABEL_TEKS, ft, cv2.LINE_AA)
        return frame

    def draw_fps(self, frame: np.ndarray, fps: float) -> np.ndarray:
        """Detection FPS as a dark see-through pill in the top-right corner (console design
        2026-10-08). Drawn on the stream frame only, always the same size; the saved evidence
        photo has none. Top-right because the console's line card covers the top-left with its
        name chip."""
        teks = f"{fps:.0f} fps"
        (tw, th), _ = cv2.getTextSize(teks, FONT, FPS_FONT_SCALE, FPS_FONT_THICKNESS)
        (x1, y1, x2, y2), asal = pil_fps(frame.shape[1], tw, th)
        x2, y2 = min(x2, frame.shape[1]), min(y2, frame.shape[0])
        if x2 <= x1 or y2 <= y1:
            return frame
        potong = frame[y1:y2, x1:x2]
        lapis = potong.copy()
        # Pixels outside the rounded pill stay equal in both, so blending leaves them untouched.
        _isi_bulat(lapis, (0, 0, x2 - x1 - 1, y2 - y1 - 1), COLOR_FPS_LATAR, (y2 - y1) // 2)
        cv2.addWeighted(lapis, FPS_ALPHA, potong, 1 - FPS_ALPHA, 0, dst=potong)
        cv2.putText(frame, teks, asal, FONT, FPS_FONT_SCALE, COLOR_FPS_TEKS, FPS_FONT_THICKNESS, cv2.LINE_AA)
        return frame

    def roi_in_stream_space(
        self, width: int, height: int, roi: tuple[int, int, int, int] | None = None
    ) -> tuple[int, int, int, int] | None:
        """Kotak ROI seperti yang terlihat di layar, atau `None` kalau tidak sah.

        `ROI_*` ditulis dalam ruang setelan `width` x `height` (operator mengalibrasinya dari
        gambar di browser) dan dikembalikan di ruang itu juga. `draw_roi` memetakannya ke
        gambar stream (rasio kamera sejak 2026-10-07); ke ruang sensor dipetakan oleh
        `FrameProcessingWorker._roi_box_for`, karena di sanalah deteksi benar-benar berjalan.
        """
        # `roi` = the box set from the console (`RuntimeState.roi_override`); None = `.env`.
        s = self.settings
        rx1, ry1, x2, y2 = roi or (s.roi_x1, s.roi_y1, s.roi_x2, s.roi_y2)
        rx2 = x2 if x2 > 0 else width
        ry2 = y2 if y2 > 0 else height
        if rx2 <= rx1 or ry2 <= ry1:
            return None
        return rx1, ry1, rx2, ry2

    def draw_roi(
        self, frame: np.ndarray, garis_capture: int = 0, sumbu: str = TEGAK,
        *, tampil_garis: bool = True, tampil_roi: bool = True,
        roi: tuple[int, int, int, int] | None = None,
        skala_setelan: tuple[float, float] = TANPA_SKALA,
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

        `tampil_garis` / `tampil_roi` (console switches, 2026-10-04) only decide
        whether each one is DRAWN. Detection never reads them: a hidden line still
        triggers the capture and a hidden box still filters the region.

        `skala_setelan` (2026-10-07): ruang setelan ke gambar ini, per sumbu. Gambar stream
        menjaga rasio kamera (861x720 untuk kamera 1224x1024), sementara ROI dan garis tetap
        disimpan di ruang setelan `STREAM_WIDTH` x `STREAM_HEIGHT`. Kotak `0,0,0,0` tetap
        seluruh gambar. `TANPA_SKALA` = gambar seukuran ruang setelan, persis seperti dulu.
        """
        h, w = frame.shape[:2]
        if skala_setelan == TANPA_SKALA:
            kotak = self.roi_in_stream_space(w, h, roi)
        else:
            kotak = self.roi_in_stream_space(self.settings.stream_width, self.settings.stream_height, roi)
            kotak = kotak_berskala(*kotak, skala_setelan) if kotak is not None else None
        garis_capture = garis_berskala(garis_capture, sumbu == MENDATAR, skala_setelan)
        # A console box of all zeros is the full frame: nothing to draw, as with `.env`.
        aktif = any(roi) if roi is not None else self._roi_enabled
        if tampil_roi and kotak is not None and aktif:
            rx1, ry1, rx2, ry2 = kotak
            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), COLOR_ROI, 2)

        if garis_capture <= 0 or not tampil_garis:
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
