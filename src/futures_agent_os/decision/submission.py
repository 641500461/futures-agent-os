"""Final deterministic gate for converting an approved plan into execution intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from futures_agent_os.portfolio_risk import RiskBudgetReservation
from futures_agent_os.shared_kernel import EntityId, RecordedAt

from .autonomy_contracts import AutonomyGateReceipt
from .trade_contracts import (
    ExecutionPlan,
    ProtectionMandate,
    RiskDecision,
    RiskDecisionOutcome,
    TradePlan,
    TradePlanStatus,
)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    execution_plan: ExecutionPlan | None
    reason: str


class TradePlanSubmitter:
    """Fail-closed final binding check; execution remains a separate owner."""

    @staticmethod
    def validate_plan(plan: TradePlan, *, now: RecordedAt) -> str:
        """Validate the pre-authorization portion without creating side effects."""
        if plan.status not in {TradePlanStatus.DRAFT, TradePlanStatus.VALIDATED}:
            return "PLAN_NOT_SUBMITTABLE"
        if plan.expires_at.value <= now.value:
            return "PLAN_EXPIRED"
        if plan.protection.max_loss <= 0 or not plan.evidence_refs:
            return "PLAN_PROTECTION_OR_EVIDENCE_MISSING"
        return "PLAN_VALID"

    def submit(
        self,
        plan: TradePlan,
        risk: RiskDecision,
        protection: ProtectionMandate,
        receipt: AutonomyGateReceipt,
        reservation: "RiskBudgetReservation",
        *,
        order_type: str,
        now: RecordedAt,
    ) -> SubmissionResult:
        if risk.plan_id != plan.plan_id or risk.plan_version != plan.version:
            return SubmissionResult(None, "RISK_PLAN_MISMATCH")
        if risk.outcome not in {RiskDecisionOutcome.APPROVE, RiskDecisionOutcome.MODIFY}:
            return SubmissionResult(None, "RISK_NOT_APPROVED")
        if protection.plan_id != plan.plan_id:
            return SubmissionResult(None, "PROTECTION_PLAN_MISMATCH")
        if (
            receipt.plan_id != plan.plan_id
            or receipt.plan_version != plan.version
            or receipt.plan_hash != plan.plan_hash
        ):
            return SubmissionResult(None, "RECEIPT_PLAN_MISMATCH")
        if reservation.plan_id != plan.plan_id or reservation.plan_version != plan.version:
            return SubmissionResult(None, "RESERVATION_PLAN_MISMATCH")
        if (
            reservation.authorization_basis_id != receipt.basis_id
            or reservation.reservation_id != receipt.reservation_id
        ):
            return SubmissionResult(None, "RECEIPT_RESERVATION_MISMATCH")
        if receipt.expires_at.value <= now.value or reservation.expires_at.value <= now.value:
            return SubmissionResult(None, "AUTHORIZATION_EXPIRED")
        if risk.approved_quantity <= 0 or risk.approved_quantity > reservation.quantity:
            return SubmissionResult(None, "QUANTITY_OUT_OF_SCOPE")
        execution = ExecutionPlan(
            EntityId.new("execution_plan"),
            plan.plan_id,
            order_type,
            risk.approved_quantity,
            plan.entry_price,
            None,
            protection.mandate_id,
            now,
        )
        return SubmissionResult(execution, "EXECUTION_PLAN_CREATED")

    @staticmethod
    def consume_authorized_receipt(
        receipt_registry: Any,
        receipt: AutonomyGateReceipt,
        *,
        now: RecordedAt,
        request: Any,
        basis: Any,
        reservation: Any,
        ledger: Any,
        **gate_context: object,
    ) -> bool:
        """Atomically consume the single-use receipt and its risk reservation."""
        if not receipt_registry.consume(
            receipt, now, request=request, basis=basis, reservation=reservation, **gate_context
        ):
            return False
        consumed = ledger.consume(reservation.reservation_id, now)
        return consumed is not None
