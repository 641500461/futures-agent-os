"""Final deterministic gate for converting an approved plan into execution intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from futures_agent_os.portfolio_risk import RiskBudgetReservation
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

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
        plan_status = self.validate_plan(plan, now=now)
        if plan_status != "PLAN_VALID":
            return SubmissionResult(None, plan_status)
        if risk.plan_id != plan.plan_id or risk.plan_version != plan.version:
            return SubmissionResult(None, "RISK_PLAN_MISMATCH")
        if risk.plan_hash != plan.plan_hash:
            return SubmissionResult(None, "RISK_PLAN_HASH_MISMATCH")
        if risk.outcome not in {RiskDecisionOutcome.APPROVE, RiskDecisionOutcome.MODIFY}:
            return SubmissionResult(None, "RISK_NOT_APPROVED")
        if protection.plan_id != plan.plan_id:
            return SubmissionResult(None, "PROTECTION_PLAN_MISMATCH")
        if (
            protection.risk_decision_plan_version is not None
            and protection.risk_decision_plan_version != risk.plan_version
        ):
            return SubmissionResult(None, "PROTECTION_RISK_VERSION_MISMATCH")
        if protection.risk_decision_id is not None and protection.risk_decision_id != risk.decision_id:
            return SubmissionResult(None, "PROTECTION_RISK_MISMATCH")
        if (
            receipt.plan_id != plan.plan_id
            or receipt.plan_version != plan.version
            or receipt.plan_hash != plan.plan_hash
        ):
            return SubmissionResult(None, "RECEIPT_PLAN_MISMATCH")
        if (
            receipt.account_id != plan.account_id
            or receipt.instrument != plan.instrument
            or receipt.strategy != plan.strategy_ref
        ):
            return SubmissionResult(None, "RECEIPT_SCOPE_MISMATCH")
        if receipt.action.value != plan.action.value or receipt.quantity != risk.approved_quantity:
            return SubmissionResult(None, "RECEIPT_ACTION_QUANTITY_MISMATCH")
        if reservation.plan_id != plan.plan_id or reservation.plan_version != plan.version:
            return SubmissionResult(None, "RESERVATION_PLAN_MISMATCH")
        if (
            reservation.authorization_basis_id != receipt.basis_id
            or reservation.reservation_id != receipt.reservation_id
        ):
            return SubmissionResult(None, "RECEIPT_RESERVATION_MISMATCH")
        if receipt.expires_at.value <= now.value or reservation.expires_at.value <= now.value:
            return SubmissionResult(None, "AUTHORIZATION_EXPIRED")
        if (
            risk.approved_quantity <= 0
            or risk.approved_quantity != reservation.quantity
            or reservation.action.value != plan.action.value
            or reservation.instrument != plan.instrument
            or reservation.strategy != plan.strategy_ref
        ):
            return SubmissionResult(None, "QUANTITY_OUT_OF_SCOPE")
        execution_seed = canonical_sha256(
            {
                "plan": plan.plan_hash,
                "plan_version": plan.version,
                "risk": str(risk.decision_id),
                "quantity": str(risk.approved_quantity),
                "order_type": order_type,
                "limit_price": str(plan.entry_price),
                "stop_price": None,
                "protection": str(protection.mandate_id),
                "receipt": str(receipt.receipt_id),
                "reservation": str(reservation.reservation_id),
            }
        )
        execution = ExecutionPlan(
            EntityId.deterministic("execution_plan", execution_seed),
            plan.plan_id,
            order_type,
            risk.approved_quantity,
            plan.entry_price,
            None,
            protection.mandate_id,
            now,
            risk.decision_id,
            risk.plan_version,
            receipt.receipt_id,
            reservation.reservation_id,
            plan.plan_hash,
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
        # RiskBudgetLedger owns the compare-and-swap.  It invokes the receipt
        # registry callback while its lock is held, so a failed receipt check
        # cannot consume the reservation and a retry remains possible.
        consume_with_commit = getattr(ledger, "consume_with_commit", None)
        if callable(consume_with_commit):
            consumed = consume_with_commit(
                reservation.reservation_id,
                now,
                lambda: receipt_registry.consume(
                    receipt, now, request=request, basis=basis, reservation=reservation, **gate_context
                ),
            )
            return consumed is not None
        return False
