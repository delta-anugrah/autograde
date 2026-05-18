from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CameraSource(ABC):
    @abstractmethod
    def connect(self, index: int = 0) -> None:
        raise NotImplementedError

    @abstractmethod
    def grab_frame(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

