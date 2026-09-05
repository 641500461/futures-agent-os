"""Deterministic sizing and Risk Constitution checks for simulation plans."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.decision import RiskDecision, RiskDecisionOutcome, TradePlan
from futures_agent_os.shared_kernel import EntityId, RecordedAt


@dataclass(frozen=True, slots=True)
class RiskConstitution:
    ref: str
    version: int
    content_hash: str
    max_single_loss: Decimal
    max_margin: Decimal
    max_quantity: Decimal
    margin_rate: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not self.ref.strip() or any(c.isspace() for c in self.ref):
            raise ValueError("constitution ref must be canonical")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("constitution version must be positive")
        if not isinstance(self.content_hash, str) or len(self.content_hash) != 64:
            raise ValueError("constitution hash must be SHA-256")
        for value in (self.max_single_loss, self.max_margin, self.max_quantity, self.margin_rate):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("constitution limits must be positive finite decimals")


class RiskEngine:
    def __init__(self, constitution: RiskConstitution) -> None:
        self.constitution = constitution

    def size(self, plan: TradePlan) -> Decimal:
        distance = abs(plan.entry_price - plan.protection.stop_price)
        if distance <= 0:
            raise ValueError("risk is not computable")
        quantity = min(plan.quantity, self.constitution.max_single_loss / distance)
        if quantity <= 0:
            raise ValueError("risk size is zero")
        return min(quantity, self.constitution.max_quantity)

    def decide(self, plan: TradePlan, *, decision_id: EntityId, now: RecordedAt) -> RiskDecision:
        try:
            quantity = self.size(plan)
        except ValueError:
            return RiskDecision(
                decision_id,
                plan.plan_id,
                plan.version,
                RiskDecisionOutcome.REJECT,
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                ("RISK_NOT_COMPUTABLE",),
                self.constitution.ref,
                now,
            )
        loss = abs(plan.entry_price - plan.protection.stop_price) * quantity
        margin = plan.entry_price * quantity * self.constitution.margin_rate
        if loss > self.constitution.max_single_loss:
            return RiskDecision(
                decision_id,
                plan.plan_id,
                plan.version,
                RiskDecisionOutcome.REJECT,
                Decimal("0"),
                loss,
                margin,
                ("MAX_SINGLE_LOSS",),
                self.constitution.ref,
                now,
            )
        if margin > self.constitution.max_margin:
            return RiskDecision(
                decision_id,
                plan.plan_id,
                plan.version,
                RiskDecisionOutcome.REJECT,
                Decimal("0"),
                loss,
                margin,
                ("MAX_MARGIN",),
                self.constitution.ref,
                now,
            )
        outcome = RiskDecisionOutcome.APPROVE if quantity == plan.quantity else RiskDecisionOutcome.MODIFY
        return RiskDecision(
            decision_id,
            plan.plan_id,
            plan.version,
            outcome,
            quantity,
            loss,
            margin,
            ("RISK_WITHIN_LIMITS",),
            self.constitution.ref,
            now,
        )
