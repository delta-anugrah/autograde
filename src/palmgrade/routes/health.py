from typing import Annotated

from fastapi import APIRouter, Depends

from ..controllers.health_controller import get_health_detail
from ..core.dependencies import get_health_service
from ..schemas.common_schema import HealthDetailSchema
from ..services.health_service import HealthService

# `GET /health` hidup di `routes/health_ringan.py` sejak batch 2.1: rute itu
# bisa menjawab 503 (AI mati) dan harus teruji tanpa torch.
router = APIRouter(tags=["health"])


@router.get("/health/detail", response_model=HealthDetailSchema)
async def health_detail(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthDetailSchema:
    return await get_health_detail(service)
