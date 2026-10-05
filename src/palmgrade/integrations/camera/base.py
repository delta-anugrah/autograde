from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ...domain.kesehatan_kamera import StatistikAliran


class CameraSource(ABC):
    #: Alasan grab terakhir yang gagal, untuk dibaca manusia (batch 3.3). Sumber yang
    #: tahu alasannya (kode MVS Hikrobot) mengisinya dan mencatat tiap kegagalan cuma
    #: di DEBUG; `FrameCaptureWorker` yang menulis SATU WARNING per kejadian dengan
    #: alasan ini. Atribut kelas, supaya sumber yang tidak memanggil `super().__init__()`
    #: tetap punya nilainya.
    galat_terakhir: str | None = None

    #: `grab_frame` waits for the next frame (a real camera). False for a source that hands
    #: a frame over at once (a photo, a video file): `FrameCaptureWorker` must then pace the
    #: loop itself even with no rate at all, or it spins thousands of times a second.
    menunggu_frame: bool = True

    #: Does the camera have a temperature sensor? None = not known (not asked yet, or a
    #: source that never says), False = the camera reports none, so the Diagnostics card says
    #: "not supported" and the line stops asking, True = a reading came back.
    suhu_didukung: bool | None = None

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

    def get_statistik_aliran(self) -> StatistikAliran | None:
        """Frames received and lost since grabbing started, or None when the source cannot say.

        Only a network camera counts frames lost on the wire; the capture worker turns the
        running totals into a 10-minute window (`domain/kesehatan_kamera.py`).
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
