from typing import Annotated

from fastapi import APIRouter, Depends

from ..controllers.health_controller import get_health
from ..core.dependencies import get_health_service
from ..schemas.common_schema import ApiMessage
from ..services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiMessage)
async def healthcheck(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> ApiMessage:
    return await get_health(service)

