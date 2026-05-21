from dataclasses import dataclass

from ..workers.runtime_state import RuntimeState


@dataclass
class TruckRepository:
    state: RuntimeState

    def get_current_truck_id(self) -> str | None:
        return self.state.current_truck_id

    def set_current_truck_id(self, truck_id: str) -> None:
        self.state.current_truck_id = truck_id

