from dataclasses import dataclass


@dataclass(frozen=True)
class PreTradeCritique:
    concerns: tuple[str, ...]
    verdict: str

    def __post_init__(self):
        if not self.concerns or self.verdict not in ("ACCEPT", "REJECT", "DEFER"):
            raise ValueError("invalid pre-trade critique")


class PreTradeCritic:
    def review(self, *, concerns: tuple[str, ...], verdict: str) -> PreTradeCritique:
        return PreTradeCritique(concerns, verdict)
