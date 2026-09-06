from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class StrategyCandidate:
    thesis: str
    invalidation: str
    evidence: Tuple[str, ...]
    target_risk: str
    exit_intent: str

    def __post_init__(self):
        if (
            not self.thesis
            or not self.invalidation
            or not self.evidence
            or not self.target_risk
            or not self.exit_intent
        ):
            raise ValueError("strategy candidate requires thesis, invalidation, evidence, risk and exit intent")


class StrategyAgent:
    def propose(
        self, *, thesis: str, invalidation: str, evidence: tuple[str, ...], target_risk: str, exit_intent: str
    ) -> StrategyCandidate:
        return StrategyCandidate(thesis, invalidation, evidence, target_risk, exit_intent)
