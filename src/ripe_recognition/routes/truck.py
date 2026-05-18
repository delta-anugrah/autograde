from typing import Annotated

from fastapi import APIRouter, Depends

from ..controllers.truck_controller import set_truck
from ..core.dependencies import get_truck_service
from ..schemas.truck_schema import SetTruckRequest, SetTruckResponse
from ..services.truck_service import TruckService

router = APIRouter(prefix="/api", tags=["truck"])


@router.post("/set_truck", response_model=SetTruckResponse)
async def set_truck_route(
    request: SetTruckRequest,
    service: Annotated[TruckService, Depends(get_truck_service)],
) -> SetTruckResponse:
    return await set_truck(request, service)

