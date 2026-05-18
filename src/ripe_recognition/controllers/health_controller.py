from ..schemas.common_schema import ApiMessage
from ..services.health_service import HealthService


async def get_health(service: HealthService) -> ApiMessage:
    payload = service.get_health()
    return ApiMessage.model_validate(payload)

