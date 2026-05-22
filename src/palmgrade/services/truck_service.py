from dataclasses import dataclass

from ..repositories.truck_repository import TruckRepository


@dataclass
class TruckService:
    truck_repository: TruckRepository

    def set_current_truck(self, truck_id: str) -> dict[str, str]:
        self.truck_repository.set_current_truck_id(truck_id)
        return {
            "message": "Truck ID updated.",
            "truck_id": truck_id,
        }

