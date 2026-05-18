from ..schemas.truck_schema import SetTruckRequest, SetTruckResponse
from ..services.truck_service import TruckService


async def set_truck(
    request: SetTruckRequest,
    service: TruckService,
) -> SetTruckResponse:
    payload = service.set_current_truck(request.truck_id)
    return SetTruckResponse.model_validate(payload)

