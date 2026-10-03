from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CameraSource(ABC):
    #: Alasan grab terakhir yang gagal, untuk dibaca manusia (batch 3.3). Sumber yang
    #: tahu alasannya (kode MVS Hikrobot) mengisinya dan mencatat tiap kegagalan cuma
    #: di DEBUG; `FrameCaptureWorker` yang menulis SATU WARNING per kejadian dengan
    #: alasan ini. Atribut kelas, supaya sumber yang tidak memanggil `super().__init__()`
    #: tetap punya nilainya.
    galat_terakhir: str | None = None

    def __init__(self) -> None:
        self.connected: bool = False

    @abstractmethod
    def connect(self, index: int = 0, serial: str | None = None, feature_file: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def grab_frame(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    def get_fps(self) -> float:
        return 0.0

    def get_temperature(self) -> float | None:
        """Camera body temperature in °C, or None when the source cannot say.

        Only a real camera has a sensor. A webcam, a video file and a photo
        folder answer None, and the Diagnostics card shows a dash for them.
        """
        return None

    @property
    def exhausted(self) -> bool:
        return False

    @property
    def rewound(self) -> bool:
        """True on the first frame of a new pass through a looping source."""
        return False

    @property
    def supports_reconnect(self) -> bool:
        return True
