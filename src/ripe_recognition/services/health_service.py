from dataclasses import dataclass

from ..core.config import Settings


@dataclass
class HealthService:
    settings: Settings

    def get_health(self) -> dict[str, str]:
        return {
            "message": "Ripe Recognition API is ready.",
            "detail": f"Environment: {self.settings.environment}",
        }

