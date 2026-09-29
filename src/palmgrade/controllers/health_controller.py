from ..schemas.common_schema import HealthDetailSchema
from ..services.health_service import HealthService


async def get_health_detail(service: HealthService) -> HealthDetailSchema:
    return service.get_health_detail()
