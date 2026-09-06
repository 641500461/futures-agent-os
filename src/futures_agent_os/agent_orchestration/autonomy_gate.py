from enum import StrEnum


class GateOutcome(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"
    PROTECT_ONLY = "PROTECT_ONLY"


def preflight(*, effective: bool, evidence_complete: bool) -> GateOutcome:
    if not effective:
        return GateOutcome.REJECT
    return GateOutcome.AUTHORIZED if evidence_complete else GateOutcome.ESCALATE


def final_gate(*, preflight_result: GateOutcome, risk_approved: bool) -> GateOutcome:
    if preflight_result is GateOutcome.REJECT:
        return GateOutcome.REJECT
    if not risk_approved:
        return GateOutcome.PROTECT_ONLY
    return GateOutcome.AUTHORIZED
