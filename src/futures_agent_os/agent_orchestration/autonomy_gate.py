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
