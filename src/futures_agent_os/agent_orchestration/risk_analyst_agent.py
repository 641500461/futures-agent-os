from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskAssessment:
    scenarios: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    proposed_loss: Decimal

    def __post_init__(self):
        if not self.scenarios or not isinstance(self.proposed_loss, Decimal):
            raise ValueError("invalid risk assessment")


class RiskAnalystAgent:
    def assess(
        self, *, scenarios: tuple[str, ...], counter_evidence: tuple[str, ...], proposed_loss: Decimal
    ) -> RiskAssessment:
        return RiskAssessment(scenarios, counter_evidence, proposed_loss)
