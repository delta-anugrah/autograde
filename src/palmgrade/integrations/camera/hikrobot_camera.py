from __future__ import annotations

import logging
import os
from ctypes import POINTER, c_ubyte, c_void_p, cast, pointer, sizeof

import cv2
import numpy as np

from ...domain.kesehatan_kamera import StatistikAliran
from ...domain.setelan_kamera import NilaiSetelan
from .base import CameraSource
from .device_selector import extract_serial, find_index_by_serial
from .frame_utils import _validate_frame_len
from .mvs_error import format_mvs_ret
from .setelan_hikrobot import baca_setelan_hikrobot

logger = logging.getLogger(__name__)

# Rentang yang mungkin untuk badan kamera yang menyala. Di luar ini angkanya datang
# dari struct yang tidak cocok dengan versi SDK, bukan dari sensor.
_SUHU_MASUK_AKAL_C = (-40.0, 150.0)
# GenICam access mode "not implemented" (`AM_NI` in the SDK): the node is in the camera's
# feature list but the model has nothing behind it. MV-CS050-10GC answers this for
# `DeviceTemperature` (Lampung 2026-10-05). "Not available" (`AM_NA`) is not the same: it may
# become readable later, so it is still asked.
_AKSES_TIDAK_ADA = 0

try:
    from MvImport.MvCameraControl_class import (  # type: ignore
        MV_CC_DEVICE_INFO,
        MV_CC_DEVICE_INFO_LIST,
        MV_FRAME_OUT_INFO_EX,
        MV_GIGE_DEVICE,
        MV_USB_DEVICE,
        MV_ACCESS_Exclusive,
        MvCamera,
        PixelType_Gvsp_BayerRG8,
        PixelType_Gvsp_Mono8,
        PixelType_Gvsp_RGB8_Packed,
    )
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


class HikrobotCamera(CameraSource):
    punya_setelan = True
    #: `connect()` yang sudah dipanggil OBJEK kamera ini (nilai kelas cuma bawaan; tiap
    #: objek menghitung sendiri, dan satu line memakai satu objek seumur prosesnya).
    #: Rincian sambung (perangkat, handle, grabbing) INFO cuma untuk yang pertama: kamera
    #: yang diam disambung ulang tiap ~2 detik selama FRAME_BERHENTI, dan enam baris INFO
    #: tiap siklus menenggelamkan `docker logs`. Kejadiannya sendiri dicatat
    #: `FrameCaptureWorker` (putus dan pulih).
    _jumlah_sambung = 0
    #: Laju objek ini sudah pernah dilaporkan (atau tidak bisa dilaporkan) sekali.
    _laju_sudah_dilapor = False
    #: Suhu objek ini sudah pernah gagal dibaca (WARNING sekali, sesudahnya DEBUG).
    _suhu_gagal_dilapor = False
    #: Stream counters of this object already failed once (WARNING once, then DEBUG).
    _statistik_gagal_dilapor = False

    def _level_rinci(self) -> int:
        return logging.INFO if self._jumlah_sambung <= 1 else logging.DEBUG

    def __init__(self) -> None:
        if not _SDK_AVAILABLE:
            raise RuntimeError(
                "MvImport SDK tidak ditemukan. "
                "Gunakan OpenCVCamera untuk development tanpa hardware."
            )
        self.device_list = MV_CC_DEVICE_INFO_LIST()
        self.cam = MvCamera()
        self.connected = False
        # O1: pre-allocated buffer — initialized in connect() once resolution is confirmed
        self._buffer_size: int = 0
        self._data_buf = None

    def connect(self, index: int = 0, serial: str | None = None, feature_file: str | None = None) -> None:
        self._jumlah_sambung += 1
        # Asked again on every connect: the camera behind this serial may have been swapped.
        self.suhu_didukung = None
        rinci = self._level_rinci()
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0 or self.device_list.nDeviceNum == 0:
            raise RuntimeError(f"No camera found, return code: {format_mvs_ret(ret)}")
        logger.log(rinci, "Found %d device(s)", self.device_list.nDeviceNum)

        device_infos = [
            cast(self.device_list.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
            for i in range(self.device_list.nDeviceNum)
        ]

        if serial:
            # Pilih kamera by serial (stabil) — hindari rebutan antar line karena
            # urutan enum GigE tidak deterministik. Raise kalau serial tak ada
            # (reconnect loop akan retry; kamera bisa belum online).
            target_index = find_index_by_serial(device_infos, serial)
            logger.log(rinci, "Camera selected by serial %s (enum index %d)", serial, target_index)
        else:
            target_index = index
            logger.log(
                rinci,
                "Camera selected by index %d (serial %s), set CAMERA_SERIAL untuk stabil",
                target_index,
                extract_serial(device_infos[target_index]) or "?",
            )

        device_info = device_infos[target_index]
        self.cam = MvCamera()

        ret = self.cam.MV_CC_CreateHandle(device_info)
        if ret != 0:
            raise RuntimeError(f"CreateHandle failed with code: {format_mvs_ret(ret)}")
        logger.log(rinci, "Camera handle created")

        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"OpenDevice failed with code: {format_mvs_ret(ret)}")
        logger.log(rinci, "Camera device opened")

        # Apply feature set (.mfs dari MVS Feature Save) sebelum grabbing. Non-fatal:
        # kalau file tak ada / SDK menolak → warning + lanjut pakai setting firmware
        # (kamera yang sudah pernah di-load MVS tetap aman; line tidak mati gara-gara .mfs).
        if feature_file:
            self._load_features(feature_file)

        ret = self.cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"StartGrabbing failed with code: {format_mvs_ret(ret)}")
        logger.log(rinci, "Camera started grabbing")

        # O1: allocate frame buffer once (max 4096×3072 RGB) to avoid 36 MB alloc per frame
        self._buffer_size = 4096 * 3072 * 3
        self._data_buf = (c_ubyte * self._buffer_size)()
        logger.log(rinci, "Frame buffer pre-allocated (%d bytes)", self._buffer_size)

        self.connected = True

    def _load_features(self, feature_file: str) -> None:
        """Load `.mfs` feature set ke kamera via MV_CC_FeatureLoad. Non-fatal.

        File `.mfs` = hasil Feature Save dari MVS (framerate/exposure/gain/dll).
        Kalau path tak ada atau SDK menolak → log warning dan lanjut; kamera tetap
        grabbing pakai setting firmware/EEPROM (production-safe).
        """
        if not os.path.exists(feature_file):
            logger.warning(
                "CAMERA_FEATURE_FILE %s tidak ditemukan, lanjut pakai setting firmware",
                feature_file,
            )
            return
        ret = self.cam.MV_CC_FeatureLoad(feature_file)
        if ret != 0:
            logger.warning(
                "MV_CC_FeatureLoad(%s) gagal: %s, lanjut pakai setting firmware",
                feature_file,
                format_mvs_ret(ret),
            )
            return
        logger.log(self._level_rinci(), "Loaded camera features from %s", feature_file)

    def get_fps(self) -> float:
        """Frame rate the camera is actually running at, asked of the camera itself.

        This is what makes the `.mfs` the ONE place the rate is set: the file is
        pushed on every connect, and the capture worker paces itself by what the
        camera answers here rather than by `CAMERA_FPS`.

        `ResultingFrameRate` is what the camera will really deliver — the limiter
        from the `.mfs`, already capped by exposure and link bandwidth.
        `AcquisitionFrameRate` is only what was asked for, so it is the second
        choice. 0.0 means "cannot say", and the caller falls back to CAMERA_FPS.
        """
        if not self.connected:
            return 0.0
        # Imported here, not at module load: a firmware or SDK build without this
        # struct must cost the rate reading only, never the whole camera.
        try:
            from MvImport.MvCameraControl_class import MVCC_FLOATVALUE  # type: ignore
        except ImportError:  # pragma: no cover - depends on the vendored SDK
            return 0.0

        pertama = not self._laju_sudah_dilapor
        self._laju_sudah_dilapor = True
        hasil = []
        for node in ("ResultingFrameRate", "AcquisitionFrameRate"):
            value = MVCC_FLOATVALUE()
            ret = self.cam.MV_CC_GetFloatValue(node, value)
            if ret == 0 and value.fCurValue > 0:
                logger.log(logging.INFO if pertama else logging.DEBUG,
                           "Camera reports %s = %.2f fps", node, value.fCurValue)
                return float(value.fCurValue)
            hasil.append(f"{node}: {format_mvs_ret(ret)}, value {value.fCurValue:.2f}")
        # Sekali per proses: kamera yang memang tidak melaporkan lajunya (Lampung) akan
        # tetap begitu di tiap sambung ulang, dan WARNING ini ikut ke tab Log. Kode SDK
        # per node ikut tercatat supaya log berikutnya menjawab KENAPA.
        logger.log(
            logging.WARNING if pertama else logging.DEBUG,
            "Camera did not report a frame rate (%s); pacing falls back to CAMERA_FPS, "
            "so the rate in the feature file cannot be confirmed.",
            "; ".join(hasil),
        )
        return 0.0

    def get_temperature(self) -> float | None:
        """`DeviceTemperature` in °C, rounded to 0.1. None = cannot say.

        Called by `FrameCaptureWorker` every few seconds under `state.lock`, never
        from a request handler: the SDK is not safe across threads.
        """
        if not self.connected or self.suhu_didukung is False:
            return None
        try:
            from MvImport.MvCameraControl_class import MVCC_FLOATVALUE  # type: ignore
        except ImportError:  # pragma: no cover - depends on the vendored SDK
            return None
        if self.suhu_didukung is None and self._suhu_tidak_ada():
            self.suhu_didukung = False
            logger.log(
                self._level_rinci(),
                "Camera has no temperature sensor (DeviceTemperature not implemented); "
                "the Diagnostics card says so and the line stops asking",
            )
            return None
        nilai = MVCC_FLOATVALUE()
        ret = self.cam.MV_CC_GetFloatValue("DeviceTemperature", nilai)
        suhu = float(nilai.fCurValue)
        if ret == 0 and _SUHU_MASUK_AKAL_C[0] < suhu < _SUHU_MASUK_AKAL_C[1] and suhu != 0.0:
            self.suhu_didukung = True
            return round(suhu, 1)
        level = logging.DEBUG if self._suhu_gagal_dilapor else logging.WARNING
        self._suhu_gagal_dilapor = True
        logger.log(
            level,
            "Camera did not report DeviceTemperature (%s, value %.1f); the Diagnostics card shows a dash",
            format_mvs_ret(ret), suhu,
        )
        return None

    def _suhu_tidak_ada(self) -> bool:
        """True only when the camera says `DeviceTemperature` is not implemented.

        Any other answer, including an SDK too old to have the call, means "try reading it".
        """
        try:
            from MvImport.MvCameraControl_class import MV_XML_AccessMode  # type: ignore
        except ImportError:
            return False
        akses = MV_XML_AccessMode()
        ret = self.cam.MV_XML_GetNodeAccessMode("DeviceTemperature", akses)
        return ret == 0 and akses.value == _AKSES_TIDAK_ADA

    def get_statistik_aliran(self) -> StatistikAliran | None:
        """Frames received and lost since grabbing started (GigE `MV_MATCH_TYPE_NET_DETECT`).

        Called by `FrameCaptureWorker` every few seconds under `state.lock`, like the
        temperature. None = cannot say; the card shows a dash for that row.
        """
        if not self.connected:
            return None
        try:
            from MvImport.MvCameraControl_class import (  # type: ignore
                MV_ALL_MATCH_INFO,
                MV_MATCH_INFO_NET_DETECT,
                MV_MATCH_TYPE_NET_DETECT,
            )
        except ImportError:  # pragma: no cover - depends on the vendored SDK
            return None
        net = MV_MATCH_INFO_NET_DETECT()
        info = MV_ALL_MATCH_INFO()
        info.nType = MV_MATCH_TYPE_NET_DETECT
        info.pInfo = cast(pointer(net), c_void_p)
        info.nInfoSize = sizeof(net)
        ret = self.cam.MV_CC_GetAllMatchInfo(info)
        if ret == 0:
            return StatistikAliran(diterima=int(net.nNetRecvFrameCount), hilang=int(net.nLostFrameCount))
        level = logging.DEBUG if self._statistik_gagal_dilapor else logging.WARNING
        self._statistik_gagal_dilapor = True
        logger.log(
            level,
            "Camera did not report stream counters (%s); the Diagnostics card shows a dash for lost frames",
            format_mvs_ret(ret),
        )
        return None

    def baca_setelan(self) -> list[NilaiSetelan]:
        """Capture thread only, under `state.lock`, through `state.perintah_kamera` (rule 3)."""
        if not self.connected:
            raise RuntimeError("camera not connected")
        return baca_setelan_hikrobot(self.cam)

    def grab_frame(self):
        if not self.connected:
            return None
        frame_info = MV_FRAME_OUT_INFO_EX()

        ret = self.cam.MV_CC_GetOneFrameTimeout(self._data_buf, self._buffer_size, frame_info, 100)
        if ret != 0:
            return self._gagal(f"grab gagal, kode {format_mvs_ret(ret)}")

        img_bytes = np.frombuffer(self._data_buf, dtype=np.uint8, count=frame_info.nFrameLen)
        w, h = frame_info.nWidth, frame_info.nHeight

        if frame_info.enPixelType == PixelType_Gvsp_Mono8:
            if not _validate_frame_len(frame_info.nFrameLen, w, h, channels=1):
                return self._gagal(f"frame Mono8 terpotong: {frame_info.nFrameLen} dari {w * h} byte")
            img = img_bytes.reshape((h, w))
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        elif frame_info.enPixelType == PixelType_Gvsp_BayerRG8:
            if not _validate_frame_len(frame_info.nFrameLen, w, h, channels=1):
                return self._gagal(f"frame Bayer terpotong: {frame_info.nFrameLen} dari {w * h} byte")
            img = img_bytes.reshape((h, w))
            img = cv2.cvtColor(img, cv2.COLOR_BAYER_RGGB2BGR_EA)

        elif frame_info.enPixelType in (17301513, PixelType_Gvsp_RGB8_Packed):
            if not _validate_frame_len(frame_info.nFrameLen, w, h, channels=3):
                return self._gagal(f"frame RGB terpotong: {frame_info.nFrameLen} dari {w * h * 3} byte")
            img = img_bytes.reshape((h, w, 3))
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        else:
            return self._gagal(f"format piksel {frame_info.enPixelType} tidak didukung")

        self.galat_terakhir = None
        return img

    def _gagal(self, alasan: str) -> None:
        """Satu grab gagal: alasan disimpan untuk WARNING per kejadian di
        `FrameCaptureWorker`, dan cuma DEBUG di sini. Dulu tiap grab gagal satu WARNING,
        dan kamera yang putus menggrab tiap 100 ms: ±10 baris per detik."""
        self.galat_terakhir = alasan
        logger.debug("Grab kamera gagal: %s", alasan)
        return None

    def disconnect(self) -> None:
        if self.connected:
            self.cam.MV_CC_StopGrabbing()
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.connected = False
            # DEBUG: tiap sambung ulang dimulai dengan ini, dan kejadiannya sudah
            # ditulis `FrameCaptureWorker` sebagai WARNING "menyambung ulang".
            logger.debug("Camera disconnected")
