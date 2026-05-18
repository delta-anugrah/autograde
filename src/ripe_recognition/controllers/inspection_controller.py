from ..schemas.inspection_schema import InspectionResultResponse
from ..services.result_service import ResultService


async def get_results_today(
    service: ResultService,
) -> list[InspectionResultResponse]:
    results = service.list_today_results()
    return [InspectionResultResponse.model_validate(item) for item in results]

