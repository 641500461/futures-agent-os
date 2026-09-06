from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PortfolioProposal:
    target_exposure: Decimal
    rationale: str

    def __post_init__(self):
        if not isinstance(self.target_exposure, Decimal) or not self.rationale:
            raise ValueError("portfolio proposal requires exposure and rationale")


class PortfolioAgent:
    def propose(self, *, target_exposure: Decimal, rationale: str) -> PortfolioProposal:
        return PortfolioProposal(target_exposure, rationale)
