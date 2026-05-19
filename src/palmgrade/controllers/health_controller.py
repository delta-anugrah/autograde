from ..schemas.common_schema import ApiMessage, HealthDetailSchema
from ..services.health_service import HealthService


async def get_health(service: HealthService) -> ApiMessage:
    payload = service.get_health()
    return ApiMessage.model_validate(payload)


async def get_health_detail(service: HealthService) -> HealthDetailSchema:
    return service.get_health_detail()
