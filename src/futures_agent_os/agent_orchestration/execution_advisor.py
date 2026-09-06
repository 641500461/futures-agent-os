from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ExecutionRecommendation:
    algorithm: Literal["MARKET", "LIMIT", "STOP"]
    rationale: str

    def __post_init__(self):
        if self.algorithm not in ("MARKET", "LIMIT", "STOP") or not self.rationale:
            raise ValueError("unsupported execution algorithm")


class ExecutionAdvisor:
    def recommend(self, *, algorithm: str, rationale: str) -> ExecutionRecommendation:
        return ExecutionRecommendation(algorithm, rationale)  # type: ignore[arg-type]
