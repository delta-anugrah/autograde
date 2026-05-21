from typing import Literal

RipenessStatus = Literal["acc", "rej"]
CaptureType = Literal["auto", "manual"]


class BoundingBox:
    def __init__(self, x_min: int, y_min: int, x_max: int, y_max: int) -> None:
        self.x_min = x_min
        self.y_min = y_min
        self.x_max = x_max
        self.y_max = y_max

    def to_dict(self) -> dict:
        return {"x_min": self.x_min, "y_min": self.y_min, "x_max": self.x_max, "y_max": self.y_max}
