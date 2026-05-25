from typing import Annotated

from fastapi import APIRouter, Depends

from ..controllers.health_controller import get_health, get_health_detail
from ..core.dependencies import get_health_service
from ..schemas.common_schema import ApiMessage, HealthDetailSchema
from ..services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiMessage)
async def healthcheck(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> ApiMessage:
    return await get_health(service)


@router.get("/health/detail", response_model=HealthDetailSchema)
async def health_detail(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthDetailSchema:
    return await get_health_detail(service)
