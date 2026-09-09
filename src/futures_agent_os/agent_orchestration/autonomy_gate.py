from enum import StrEnum
from dataclasses import dataclass, replace
from datetime import datetime, timezone


class GateOutcome(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"
    PROTECT_ONLY = "PROTECT_ONLY"
    PERMIT = "PERMIT"


@dataclass(frozen=True, slots=True)
class AutonomyGateReceipt:
    receipt_id: str
    plan_id: str
    plan_hash: str
    basis_hash: str
    mode_hash: str
    issued_at: datetime
    expires_at: datetime
    outcome: GateOutcome = GateOutcome.PERMIT
    consumed: bool = False

    def __post_init__(self) -> None:
        if any(
            not isinstance(v, str) or not v.strip()
            for v in (self.receipt_id, self.plan_id, self.plan_hash, self.basis_hash, self.mode_hash)
        ):
            raise ValueError("receipt requires plan, basis and mode references")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None or self.expires_at <= self.issued_at:
            raise ValueError("receipt requires ordered timezone-aware expiry")
        if self.outcome is not GateOutcome.PERMIT:
            raise ValueError("only permitted gate results may issue a receipt")

    def consume(
        self, *, plan_id: str, plan_hash: str, basis_hash: str, mode_hash: str, now: datetime | None = None
    ) -> "AutonomyGateReceipt":
        now = now or datetime.now(timezone.utc)
        if (
            self.consumed
            or now >= self.expires_at
            or (plan_id, plan_hash, basis_hash, mode_hash)
            != (self.plan_id, self.plan_hash, self.basis_hash, self.mode_hash)
        ):
            raise ValueError("stale, mismatched or already consumed gate receipt")
        return replace(self, consumed=True)


def preflight(*, effective: bool, evidence_complete: bool) -> GateOutcome:
    if not effective:
        return GateOutcome.REJECT
    return GateOutcome.AUTHORIZED if evidence_complete else GateOutcome.ESCALATE


def final_gate(*, preflight_result: GateOutcome, risk_approved: bool) -> GateOutcome:
    if preflight_result is GateOutcome.REJECT:
        return GateOutcome.REJECT
    if not risk_approved:
        return GateOutcome.PROTECT_ONLY
    return GateOutcome.PERMIT
