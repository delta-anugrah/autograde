from dataclasses import dataclass
from typing import Any

from ..repositories.result_repository import ResultRepository


@dataclass
class ResultService:
    result_repository: ResultRepository

    def list_today_results(self) -> list[dict[str, Any]]:
        return self.result_repository.list_today_results()

