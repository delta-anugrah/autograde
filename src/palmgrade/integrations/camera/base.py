from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CameraSource(ABC):
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

    @property
    def exhausted(self) -> bool:
        return False

    @property
    def supports_reconnect(self) -> bool:
        return True
