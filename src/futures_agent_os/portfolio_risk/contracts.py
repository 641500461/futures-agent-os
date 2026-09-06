"""Portfolio & Risk-owned V2 contract surface.

The initial V2 implementation exposed these classes from ``decision``.  Keep
that import path as a compatibility shim while making the bounded-context
ownership explicit for new callers.
"""

from dataclasses import dataclass

from futures_agent_os.decision.trade_contracts import (
    ProtectionMandate as _DecisionProtectionMandate,
    RiskDecision as _DecisionRiskDecision,
    RiskDecisionOutcome,
)


@dataclass(frozen=True, slots=True)
class RiskDecision(_DecisionRiskDecision):
    """Portfolio & Risk canonical owner type.

    The decision import remains a compatibility base while new code imports
    this owner type.  Inherited validation is deterministic and side-effect
    free; Risk still owns the decision semantics.
    """

    pass


@dataclass(frozen=True, slots=True)
class ProtectionMandate(_DecisionProtectionMandate):
    """Portfolio & Risk canonical owner type for enforceable protection."""

    pass


__all__ = ["RiskDecision", "RiskDecisionOutcome", "ProtectionMandate"]
