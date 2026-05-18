from __future__ import annotations

import time
from ctypes import POINTER, cast, c_ubyte

import cv2
import numpy as np

from .base import CameraSource

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

    def connect(self, index: int = 0) -> None:
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0 or self.device_list.nDeviceNum == 0:
            raise RuntimeError(f"No camera found, return code: {ret}")
        print(f"[INFO] Found {self.device_list.nDeviceNum} device(s)")

        device_info = cast(
            self.device_list.pDeviceInfo[index], POINTER(MV_CC_DEVICE_INFO)
        ).contents
        self.cam = MvCamera()

        ret = self.cam.MV_CC_CreateHandle(device_info)
        if ret != 0:
            raise RuntimeError(f"CreateHandle failed with code: {ret}")
        print("[INFO] Camera handle created")

        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"OpenDevice failed with code: {ret}")
        print("[INFO] Camera device opened")

        ret = self.cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"StartGrabbing failed with code: {ret}")
        print("[INFO] Camera started grabbing")

        self.connected = True

    def grab_frame(self):
        frame_info = MV_FRAME_OUT_INFO_EX()
        buffer_size = 4096 * 3072 * 3
        data_buf = (c_ubyte * buffer_size)()

        ret = self.cam.MV_CC_GetOneFrameTimeout(data_buf, buffer_size, frame_info, 5000)
        if ret != 0:
            print(f"[WARN] Failed to grab frame, return code: {ret}")
            return None

        img_bytes = np.frombuffer(data_buf, dtype=np.uint8, count=frame_info.nFrameLen)

        if frame_info.enPixelType == PixelType_Gvsp_Mono8:
            img = img_bytes.reshape((frame_info.nHeight, frame_info.nWidth))
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        elif frame_info.enPixelType == PixelType_Gvsp_BayerRG8:
            img = img_bytes.reshape((frame_info.nHeight, frame_info.nWidth))
            img = cv2.cvtColor(img, cv2.COLOR_BAYER_RGGB2BGR_EA)

        elif frame_info.enPixelType in (17301513, PixelType_Gvsp_RGB8_Packed):
            expected = frame_info.nHeight * frame_info.nWidth * 3
            if frame_info.nFrameLen != expected:
                print(f"[WARN] Frame size mismatch: expected={expected}, got={frame_info.nFrameLen}")
            img = img_bytes.reshape((frame_info.nHeight, frame_info.nWidth, 3))
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        else:
            print(f"[ERROR] Unsupported pixel format: {frame_info.enPixelType}")
            return None

        return img

    def disconnect(self) -> None:
        if self.connected:
            self.cam.MV_CC_StopGrabbing()
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.connected = False
            print("[INFO] Camera disconnected")
