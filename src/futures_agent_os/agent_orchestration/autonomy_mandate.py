from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class MandateStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class SimulationAutonomyMandate:
    mandate_id: str
    account_id: str
    scope: str
    expires_at: datetime
    status: MandateStatus = MandateStatus.DRAFT

    def __post_init__(self):
        if not self.mandate_id or not self.account_id or not self.scope or self.expires_at.tzinfo is None:
            raise ValueError("invalid mandate")

    @property
    def effective(self) -> bool:
        return self.status is MandateStatus.ACTIVE and self.expires_at > datetime.now(timezone.utc)


@dataclass(frozen=True)
class AutonomyModeBinding:
    mandate_id: str
    mode: str
    expires_at: datetime

    def effective(self, mandate: SimulationAutonomyMandate) -> bool:
        return (
            self.mode == "AUTONOMOUS_SIMULATION"
            and self.mandate_id == mandate.mandate_id
            and mandate.effective
            and self.expires_at > datetime.now(timezone.utc)
        )


def effective_autonomy(mandate: SimulationAutonomyMandate, binding: AutonomyModeBinding) -> bool:
    return mandate.effective and binding.effective(mandate)
