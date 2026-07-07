from __future__ import annotations

import logging
import os
from ctypes import POINTER, cast, c_ubyte

import cv2
import numpy as np

from .base import CameraSource
from .device_selector import extract_serial, find_index_by_serial
from .frame_utils import _validate_frame_len
from .mvs_error import format_mvs_ret

logger = logging.getLogger(__name__)

try:
    from MvImport.MvCameraControl_class import (  # type: ignore
        MV_ACCESS_Exclusive,
        MV_CC_DEVICE_INFO,
        MV_CC_DEVICE_INFO_LIST,
        MV_FRAME_OUT_INFO_EX,
        MV_GIGE_DEVICE,
        MV_USB_DEVICE,
        MvCamera,
        PixelType_Gvsp_BayerRG8,
        PixelType_Gvsp_Mono8,
        PixelType_Gvsp_RGB8_Packed,
    )
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


class HikrobotCamera(CameraSource):
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
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0 or self.device_list.nDeviceNum == 0:
            raise RuntimeError(f"No camera found, return code: {format_mvs_ret(ret)}")
        logger.info("Found %d device(s)", self.device_list.nDeviceNum)

        device_infos = [
            cast(self.device_list.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
            for i in range(self.device_list.nDeviceNum)
        ]

        if serial:
            # Pilih kamera by serial (stabil) — hindari rebutan antar line karena
            # urutan enum GigE tidak deterministik. Raise kalau serial tak ada
            # (reconnect loop akan retry; kamera bisa belum online).
            target_index = find_index_by_serial(device_infos, serial)
            logger.info("Camera selected by serial %s (enum index %d)", serial, target_index)
        else:
            target_index = index
            logger.info(
                "Camera selected by index %d (serial %s) — set CAMERA_SERIAL untuk stabil",
                target_index,
                extract_serial(device_infos[target_index]) or "?",
            )

        device_info = device_infos[target_index]
        self.cam = MvCamera()

        ret = self.cam.MV_CC_CreateHandle(device_info)
        if ret != 0:
            raise RuntimeError(f"CreateHandle failed with code: {format_mvs_ret(ret)}")
        logger.info("Camera handle created")

        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"OpenDevice failed with code: {format_mvs_ret(ret)}")
        logger.info("Camera device opened")

        # Apply feature set (.mfs dari MVS Feature Save) sebelum grabbing. Non-fatal:
        # kalau file tak ada / SDK menolak → warning + lanjut pakai setting firmware
        # (kamera yang sudah pernah di-load MVS tetap aman; line tidak mati gara-gara .mfs).
        if feature_file:
            self._load_features(feature_file)

        ret = self.cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"StartGrabbing failed with code: {format_mvs_ret(ret)}")
        logger.info("Camera started grabbing")

        # O1: allocate frame buffer once (max 4096×3072 RGB) to avoid 36 MB alloc per frame
        self._buffer_size = 4096 * 3072 * 3
        self._data_buf = (c_ubyte * self._buffer_size)()
        logger.info("Frame buffer pre-allocated (%d bytes)", self._buffer_size)

        self.connected = True

    def _load_features(self, feature_file: str) -> None:
        """Load `.mfs` feature set ke kamera via MV_CC_FeatureLoad. Non-fatal.

        File `.mfs` = hasil Feature Save dari MVS (framerate/exposure/gain/dll).
        Kalau path tak ada atau SDK menolak → log warning dan lanjut; kamera tetap
        grabbing pakai setting firmware/EEPROM (production-safe).
        """
        if not os.path.exists(feature_file):
            logger.warning(
                "CAMERA_FEATURE_FILE %s tidak ditemukan — lanjut pakai setting firmware",
                feature_file,
            )
            return
        ret = self.cam.MV_CC_FeatureLoad(feature_file)
        if ret != 0:
            logger.warning(
                "MV_CC_FeatureLoad(%s) gagal: %s — lanjut pakai setting firmware",
                feature_file,
                format_mvs_ret(ret),
            )
            return
        logger.info("Loaded camera features from %s", feature_file)

    def grab_frame(self):
        if not self.connected:
            return None
        frame_info = MV_FRAME_OUT_INFO_EX()

        ret = self.cam.MV_CC_GetOneFrameTimeout(self._data_buf, self._buffer_size, frame_info, 100)
        if ret != 0:
            logger.warning("Failed to grab frame, return code: %s", format_mvs_ret(ret))
            return None

        img_bytes = np.frombuffer(self._data_buf, dtype=np.uint8, count=frame_info.nFrameLen)
        w, h = frame_info.nWidth, frame_info.nHeight

        if frame_info.enPixelType == PixelType_Gvsp_Mono8:
            if not _validate_frame_len(frame_info.nFrameLen, w, h, channels=1):
                logger.warning("Dropping partial Mono8 frame: expected=%d got=%d", w * h, frame_info.nFrameLen)
                return None
            img = img_bytes.reshape((h, w))
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        elif frame_info.enPixelType == PixelType_Gvsp_BayerRG8:
            if not _validate_frame_len(frame_info.nFrameLen, w, h, channels=1):
                logger.warning("Dropping partial Bayer frame: expected=%d got=%d", w * h, frame_info.nFrameLen)
                return None
            img = img_bytes.reshape((h, w))
            img = cv2.cvtColor(img, cv2.COLOR_BAYER_RGGB2BGR_EA)

        elif frame_info.enPixelType in (17301513, PixelType_Gvsp_RGB8_Packed):
            if not _validate_frame_len(frame_info.nFrameLen, w, h, channels=3):
                logger.warning("Dropping partial RGB frame: expected=%d got=%d", w * h * 3, frame_info.nFrameLen)
                return None
            img = img_bytes.reshape((h, w, 3))
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        else:
            logger.error("Unsupported pixel format: %s", frame_info.enPixelType)
            return None

        return img

    def disconnect(self) -> None:
        if self.connected:
            self.cam.MV_CC_StopGrabbing()
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.connected = False
            logger.info("Camera disconnected")
