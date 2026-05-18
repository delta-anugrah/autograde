from typing import Annotated

from fastapi import APIRouter, Depends

from ..controllers.inspection_controller import get_results_today
from ..core.dependencies import get_result_service
from ..schemas.inspection_schema import InspectionResultResponse
from ..services.result_service import ResultService

router = APIRouter(prefix="/api", tags=["inspection"])


@router.get("/results_today", response_model=list[InspectionResultResponse])
async def results_today(
    service: Annotated[ResultService, Depends(get_result_service)],
) -> list[InspectionResultResponse]:
    return await get_results_today(service)

