from __future__ import annotations

import logging
from ctypes import POINTER, cast, c_ubyte

import cv2
import numpy as np

from .base import CameraSource
from .frame_utils import _validate_frame_len

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

    def connect(self, index: int = 0) -> None:
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0 or self.device_list.nDeviceNum == 0:
            raise RuntimeError(f"No camera found, return code: {ret}")
        logger.info("Found %d device(s)", self.device_list.nDeviceNum)

        device_info = cast(
            self.device_list.pDeviceInfo[index], POINTER(MV_CC_DEVICE_INFO)
        ).contents
        self.cam = MvCamera()

        ret = self.cam.MV_CC_CreateHandle(device_info)
        if ret != 0:
            raise RuntimeError(f"CreateHandle failed with code: {ret}")
        logger.info("Camera handle created")

        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"OpenDevice failed with code: {ret}")
        logger.info("Camera device opened")

        ret = self.cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"StartGrabbing failed with code: {ret}")
        logger.info("Camera started grabbing")

        # O1: allocate frame buffer once (max 4096×3072 RGB) to avoid 36 MB alloc per frame
        self._buffer_size = 4096 * 3072 * 3
        self._data_buf = (c_ubyte * self._buffer_size)()
        logger.info("Frame buffer pre-allocated (%d bytes)", self._buffer_size)

        self.connected = True

    def grab_frame(self):
        if not self.connected:
            return None
        frame_info = MV_FRAME_OUT_INFO_EX()

        ret = self.cam.MV_CC_GetOneFrameTimeout(self._data_buf, self._buffer_size, frame_info, 100)
        if ret != 0:
            logger.warning("Failed to grab frame, return code: %d", ret)
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
