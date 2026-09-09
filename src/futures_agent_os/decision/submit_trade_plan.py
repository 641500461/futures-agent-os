"""Deterministic two-phase ``submit_trade_plan`` orchestration.

This module is the small application service at the Decision boundary.  It
coordinates owner APIs but does not become an owner of account, risk, or
execution state.  In particular, authorization is resolved before a risk
reservation is constructed, and a reservation is held until the final gate
and one-time receipt consumption succeed.

The service is an in-memory reference transaction for the V2 contract.  A
database adapter can replace the registries while preserving the same
ordering and result semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from futures_agent_os.portfolio_risk.reservation_contracts import (
    ReservationAction,
    ReservationSourceKind,
    RiskBudgetLedger,
    RiskBudgetReservation,
    ReservationStatus,
)
from futures_agent_os.portfolio_risk.risk_constitution import RiskConstitution, RiskEngine
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

from .autonomy_contracts import (
    ApprovalAction,
    AutonomyGate,
    AutonomyGateReceipt,
    AutonomyModeBinding,
    BasisIssuanceRegistry,
    GateRequest,
    PlanApproval,
    PlanApprovalRegistry,
    PlanApprovalStatus,
    PreflightOutcome,
    PreflightResult,
    ReceiptIssuanceRegistry,
    ReceiptRegistry,
    SimulationAutonomyMandate,
    ExecutionOrigin,
)
from .submission import TradePlanSubmitter
from .trade_contracts import (
    Order,
    OrderStatus,
    ProtectionMandate,
    RiskDecision,
    RiskDecisionOutcome,
    TradePlan,
    TradeDirection,
    LedgerEntry,
)

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class SubmitTradePlanResult:
    """All facts produced by one submit attempt.

    ``reservation`` and ``receipt`` are only populated when their respective
    stages succeeded.  No caller receives an internal registry or database
    handle, and failure results never expose an execution Order.
    """

    outcome: str
    reason: str
    preflight: PreflightResult | None = None
    basis: object | None = None
    reservation: RiskBudgetReservation | None = None
    risk: RiskDecision | None = None
    protection: ProtectionMandate | None = None
    receipt: AutonomyGateReceipt | None = None
    execution_plan: object | None = None
    order: Order | None = None
    ledger: LedgerEntry | None = None


class SubmitTradePlanService:
    """Run the V2 minimum two-phase safety chain.

    ``submit`` is intentionally explicit about all mutable facts.  Callers
    must provide a snapshot hash and run-version hash; inventing either would
    make replay and stale-snapshot detection impossible.
    """

    def __init__(
        self,
        *,
        constitution: RiskConstitution,
        risk_ledger: RiskBudgetLedger,
        basis_registry: BasisIssuanceRegistry | None = None,
        approval_registry: PlanApprovalRegistry | None = None,
        receipt_issuance: ReceiptIssuanceRegistry | None = None,
        receipt_registry: ReceiptRegistry | None = None,
    ) -> None:
        if not isinstance(constitution, RiskConstitution):
            raise TypeError("submit service requires a typed RiskConstitution")
        if not isinstance(risk_ledger, RiskBudgetLedger):
            raise TypeError("submit service requires the owner RiskBudgetLedger")
        self.constitution = constitution
        self.risk_ledger = risk_ledger
        self.basis_registry = basis_registry or BasisIssuanceRegistry()
        self.approval_registry = approval_registry or PlanApprovalRegistry()
        self.receipt_issuance = receipt_issuance or ReceiptIssuanceRegistry()
        self.receipt_registry = receipt_registry or ReceiptRegistry(self.receipt_issuance)
        if not isinstance(self.basis_registry, BasisIssuanceRegistry):
            raise TypeError("basis_registry must be a BasisIssuanceRegistry")
        if not isinstance(self.approval_registry, PlanApprovalRegistry):
            raise TypeError("approval_registry must be a PlanApprovalRegistry")
        if not isinstance(self.receipt_issuance, ReceiptIssuanceRegistry):
            raise TypeError("receipt_issuance must be a ReceiptIssuanceRegistry")
        if not isinstance(self.receipt_registry, ReceiptRegistry):
            raise TypeError("receipt_registry must be a ReceiptRegistry")

    @staticmethod
    def consume_durable_receipt_and_reservation(
        repository: object,
        connection: object,
        *,
        receipt_id: EntityId,
        reservation_id: EntityId,
        nonce: EntityId,
        now: RecordedAt,
    ) -> bool:
        """Bridge the final gate to the caller-owned PostgreSQL transaction.

        This explicit adapter keeps the default in-memory reference path
        unchanged while preventing accidental mixing of memory and durable
        state. The caller owns commit/rollback.
        """
        if not isinstance(receipt_id, EntityId) or not isinstance(reservation_id, EntityId):
            raise TypeError("durable consumption requires typed identifiers")
        if not isinstance(nonce, EntityId) or not isinstance(now, RecordedAt):
            raise TypeError("durable consumption requires typed nonce and timestamp")
        consume = getattr(repository, "consume_receipt_and_reservation", None)
        if not callable(consume):
            raise TypeError("repository must provide consume_receipt_and_reservation")
        return bool(
            consume(
                connection,
                receipt_id=receipt_id.value,
                reservation_id=reservation_id.value,
                nonce=nonce.value,
                now=now.value,
            )
        )

    @staticmethod
    def _request(
        plan: TradePlan,
        *,
        execution_origin: ExecutionOrigin,
        snapshot_hash: str,
        snapshot_expires_at: RecordedAt,
        run_versions_hash: str,
        session: str = "default",
    ) -> GateRequest:
        """Build the typed gate request from one immutable plan."""
        return GateRequest(
            plan.plan_id,
            plan.version,
            plan.plan_hash,
            plan.account_id,
            plan.instrument,
            plan.strategy_ref,
            session,
            ApprovalAction(plan.action.value),
            plan.quantity,
            execution_origin,
            snapshot_hash,
            snapshot_expires_at,
            run_versions_hash,
        )

    @staticmethod
    def _reservation(
        plan: TradePlan,
        basis: object,
        risk: RiskDecision,
        constitution: RiskConstitution,
        *,
        expires_at: RecordedAt,
        session: str = "default",
    ) -> RiskBudgetReservation:
        """Create a replay-stable reservation from the sizing decision."""
        # Deliberately avoid UUIDv7 runtime entropy in this identity.  A retry
        # of the same immutable input gets the same reservation identity.
        basis_id = getattr(basis, "basis_id")
        basis_hash = getattr(basis, "basis_hash")
        seed = canonical_sha256(
            {
                "plan": plan.plan_hash,
                "basis": basis_hash,
                "quantity": str(risk.approved_quantity),
                "loss": str(risk.max_loss),
                "margin": str(risk.margin),
                "expiry": expires_at.to_dict()["recorded_at"],
            }
        )
        return RiskBudgetReservation(
            EntityId.deterministic("risk_budget_reservation", seed),
            plan.account_id,
            plan.plan_id,
            plan.version,
            plan.plan_hash,
            plan.instrument,
            plan.strategy_ref,
            session,
            basis_id,
            basis_hash,
            constitution.ref,
            constitution.version,
            constitution.content_hash,
            constitution.max_single_loss,
            risk.max_loss,
            risk.margin,
            expires_at,
            risk_dimensions=(
                ("action", plan.action.value),
                ("direction", plan.direction.value),
                ("instrument", plan.instrument),
                ("strategy", plan.strategy_ref),
            ),
            quantity=risk.approved_quantity,
            action=ReservationAction(plan.action.value),
            source_kind=(
                ReservationSourceKind.MANDATE
                if getattr(basis, "kind").value == "MANDATE"
                else ReservationSourceKind.PLAN_APPROVAL
            ),
            source_ref=getattr(basis, "source_id"),
            source_hash=getattr(basis, "source_hash"),
        )

    @staticmethod
    def _protection(plan: TradePlan, risk: RiskDecision, now: RecordedAt) -> ProtectionMandate:
        seed = canonical_sha256(
            {
                "plan": plan.plan_hash,
                "risk": str(risk.decision_id),
                "risk_version": risk.version,
            }
        )
        return ProtectionMandate(
            EntityId.deterministic("protection_mandate", seed),
            plan.plan_id,
            plan.protection.stop_price,
            risk.max_loss,
            now,
            1,
            risk.decision_id,
            risk.plan_version,
        )

    @staticmethod
    def _order_payload(order: Order, *, plan: TradePlan) -> dict[str, object]:
        return {
            "order_id": str(order.order_id),
            "execution_plan_id": str(order.execution_plan_id),
            "plan_id": str(plan.plan_id),
            "instrument": order.instrument,
            "direction": order.direction.value,
            "quantity": str(order.quantity),
            "status": order.status.value,
            "filled_quantity": str(order.filled_quantity),
            "limit_price": str(order.limit_price) if order.limit_price is not None else None,
            "stop_price": str(order.stop_price) if order.stop_price is not None else None,
            "created_at": order.created_at.to_dict()["recorded_at"],
            "version": order.version,
            "source_ref": order.source_ref,
        }

    @staticmethod
    def _ledger_entry(
        order: Order, *, plan: TradePlan, reservation: RiskBudgetReservation, now: RecordedAt
    ) -> LedgerEntry:
        return LedgerEntry(
            EntityId.deterministic("ledger_entry", str(order.order_id)),
            plan.account_id,
            order.order_id,
            reservation.margin,
            "CNY",
            "MARGIN_RESERVED",
            now,
        )

    @staticmethod
    def _ledger_payload(entry: LedgerEntry, *, plan: TradePlan) -> dict[str, object]:
        return {
            "entry_id": str(entry.entry_id),
            "account_id": str(entry.account_id),
            "event_ref": str(entry.event_ref),
            "plan_id": str(plan.plan_id),
            "amount": str(entry.amount),
            "currency": entry.currency,
            "entry_type": entry.entry_type,
            "recorded_at": entry.recorded_at.to_dict()["recorded_at"],
            "version": entry.version,
            "source_ref": entry.source_ref,
        }

    @staticmethod
    def _recovered_order(payload: dict[str, object]) -> Order:
        """Hydrate the durable Order projection after a process restart."""

        def required(name: str) -> object:
            value = payload.get(name)
            if value is None:
                raise ValueError(f"recovered order is missing {name}")
            return value

        return Order(
            EntityId.parse(str(required("order_id"))),
            EntityId.parse(str(required("execution_plan_id"))),
            str(required("instrument")),
            TradeDirection(str(required("direction"))),
            Decimal(str(required("quantity"))),
            OrderStatus(str(required("status"))),
            Decimal(str(required("filled_quantity"))),
            Decimal(str(payload["limit_price"])) if payload.get("limit_price") is not None else None,
            Decimal(str(payload["stop_price"])) if payload.get("stop_price") is not None else None,
            RecordedAt.parse(str(required("created_at"))),
            int(str(required("version"))),
            source_ref=str(required("source_ref")),
        )

    @staticmethod
    def _recovered_ledger(payload: dict[str, object]) -> LedgerEntry:
        def required(name: str) -> object:
            value = payload.get(name)
            if value is None:
                raise ValueError(f"recovered ledger is missing {name}")
            return value

        return LedgerEntry(
            EntityId.parse(str(required("entry_id"))),
            EntityId.parse(str(required("account_id"))),
            EntityId.parse(str(required("event_ref"))),
            Decimal(str(required("amount"))),
            str(required("currency")),
            str(required("entry_type")),
            RecordedAt.parse(str(required("recorded_at"))),
            int(str(required("version"))),
            source_ref=str(required("source_ref")),
        )

    def _submit_with_durable_handles(
        self,
        plan: TradePlan,
        *,
        now: RecordedAt,
        execution_origin: ExecutionOrigin,
        snapshot_hash: str,
        snapshot_expires_at: RecordedAt,
        run_versions_hash: str,
        session: str = "default",
        mandate: SimulationAutonomyMandate | None = None,
        binding: AutonomyModeBinding | None = None,
        approval: PlanApproval | None = None,
        qualified: bool = True,
        health_permits: bool = True,
        approval_allowed: bool = False,
        data_quality: Decimal | None = None,
        concentration: Decimal | None = None,
        days_to_delivery: int | None = None,
        order_type: str = "MARKET",
        issue_order: bool = True,
        durable_repository: object | None = None,
        durable_connection: object | None = None,
    ) -> SubmitTradePlanResult:
        """Internal submit implementation with optional durable plumbing.

        Database/repository handles are intentionally accepted only by this
        private helper.  Public callers must use :meth:`submit`, which keeps
        infrastructure handles out of the application API.
        """
        if not isinstance(plan, TradePlan):
            raise TypeError("submit_trade_plan requires a TradePlan")
        if not isinstance(now, RecordedAt):
            raise TypeError("submit_trade_plan requires a RecordedAt")
        if (durable_repository is None) != (durable_connection is None):
            raise ValueError("durable_repository and durable_connection must be provided together")
        durable = durable_repository is not None and durable_connection is not None
        if durable:
            recover = getattr(durable_repository, "load_completed_submission", None)
            if callable(recover):
                recovered = recover(
                    durable_connection,
                    plan_id=plan.plan_id.value,
                    plan_version=plan.version,
                    plan_sha256=plan.plan_hash,
                )
                if recovered is not None:
                    try:
                        order = self._recovered_order(recovered.order_payload)
                        ledger = self._recovered_ledger(recovered.ledger_payload)
                    except TypeError, ValueError:
                        return SubmitTradePlanResult("REJECTED", "DURABLE_RECOVERY_INVALID")
                    return SubmitTradePlanResult("SUBMITTED", "ORDER_ALREADY_CREATED", order=order, ledger=ledger)
            # Durable preparation uses per-attempt candidate registries.  They
            # are never allowed to become a second source of truth or retain a
            # HELD reservation when PostgreSQL rolls the transaction back.
            basis_registry = BasisIssuanceRegistry()
            approval_registry = PlanApprovalRegistry()
            receipt_issuance = ReceiptIssuanceRegistry()
            receipt_registry = ReceiptRegistry(receipt_issuance)
            risk_ledger = RiskBudgetLedger(
                self.constitution.max_single_loss,
                self.constitution.ref,
                self.constitution.version,
                self.constitution.content_hash,
            )
        else:
            basis_registry = self.basis_registry
            approval_registry = self.approval_registry
            receipt_issuance = self.receipt_issuance
            receipt_registry = self.receipt_registry
            risk_ledger = self.risk_ledger
        hard = TradePlanSubmitter.validate_plan(plan, now=now)
        if hard != "PLAN_VALID":
            return SubmitTradePlanResult("REJECTED", hard)
        if snapshot_expires_at.value <= now.value:
            return SubmitTradePlanResult("REJECTED", "SNAPSHOT_EXPIRED")
        base_request = self._request(
            plan,
            execution_origin=execution_origin,
            snapshot_hash=snapshot_hash,
            snapshot_expires_at=snapshot_expires_at,
            run_versions_hash=run_versions_hash,
            session=session,
        )

        # Authorization is resolved before sizing or reservation.  ESCALATE is
        # a durable wait state: until a human grants the supplied approval,
        # this method returns without invoking the risk engine or creating a
        # reservation.
        preflight = AutonomyGate.preflight(
            base_request,
            mandate,
            binding,
            qualified=qualified,
            health_permits=health_permits,
            now=now,
            approval_allowed=approval_allowed,
            basis_registry=basis_registry,
        )
        basis = preflight.basis
        if preflight.outcome is PreflightOutcome.ESCALATE:
            if approval is None:
                return SubmitTradePlanResult("DEFERRED", "PLAN_APPROVAL_REQUIRED", preflight=preflight)
            approval_consumed, basis = approval_registry.consume(
                approval,
                now,
                EntityId.deterministic("authorization_basis", plan.plan_hash),
                plan_id=plan.plan_id,
                plan_version=plan.version,
                plan_hash=plan.plan_hash,
                account_id=plan.account_id,
                instrument=plan.instrument,
                strategy=plan.strategy_ref,
                session=session,
                action=base_request.action,
                quantity=base_request.quantity,
            )
            if approval_consumed.status is not PlanApprovalStatus.CONSUMED or basis is None:
                return SubmitTradePlanResult("REJECTED", "AUTHORIZATION_CONSUMPTION_INVALID", preflight=preflight)
            approval = approval_consumed
        elif preflight.outcome is not PreflightOutcome.AUTHORIZED or basis is None:
            return SubmitTradePlanResult("REJECTED", preflight.reason or preflight.outcome.value, preflight=preflight)

        # Sizing is deterministic and side-effect free, and is reached only
        # after a valid Basis exists.  No reservation exists before this point.
        risk_engine = RiskEngine(self.constitution)
        risk = risk_engine.decide(
            plan,
            decision_id=EntityId.deterministic("risk_decision", plan.plan_hash),
            now=now,
            data_quality=data_quality,
            concentration=concentration,
            days_to_delivery=days_to_delivery,
        )
        if risk.outcome not in {RiskDecisionOutcome.APPROVE, RiskDecisionOutcome.MODIFY}:
            return SubmitTradePlanResult("REJECTED", "RISK_NOT_APPROVED", preflight=None, risk=risk)
        request = replace(base_request, quantity=risk.approved_quantity)
        expiry = min((plan.expires_at, basis.expires_at, snapshot_expires_at), key=lambda item: item.value)
        reservation = self._reservation(plan, basis, risk, self.constitution, expires_at=expiry, session=session)
        if not risk_ledger.reserve(reservation, now):
            return SubmitTradePlanResult("REJECTED", "RISK_RESERVATION_REJECTED", preflight, basis, reservation, risk)

        # Receipt issuance is deliberately after reservation and before order
        # creation.  Final gate revalidates every binding and cannot widen it.
        final = AutonomyGate.final_gate(
            request,
            basis,
            mandate=mandate,
            approval=approval,
            reservation=reservation,
            binding=binding,
            qualified=qualified,
            health_permits=health_permits,
            now=now,
            issuance_registry=receipt_issuance,
            risk_ledger=risk_ledger,
        )
        if final.receipt is None:
            risk_ledger.release(reservation.reservation_id)
            return SubmitTradePlanResult(
                "REJECTED", final.reason or final.outcome.value, preflight, basis, reservation, risk
            )
        receipt = final.receipt
        # The risk result used for sizing is a proposal until the final
        # submission boundary.  Re-issue it after the Receipt has been
        # produced and require an exact match; a changed rule set, plan hash,
        # or mutable risk input therefore cannot turn an old decision into an
        # execution authority.
        current_risk = risk_engine.decide(
            plan,
            decision_id=EntityId.deterministic("risk_decision", plan.plan_hash),
            now=now,
            data_quality=data_quality,
            concentration=concentration,
            days_to_delivery=days_to_delivery,
        )
        if current_risk != risk:
            receipt_issuance.invalidate_basis(basis.basis_id)
            risk_ledger.release(reservation.reservation_id)
            return SubmitTradePlanResult(
                "REJECTED",
                "RISK_DECISION_STALE",
                preflight,
                basis,
                reservation,
                current_risk,
                receipt=receipt,
            )
        risk = current_risk
        protection = self._protection(plan, risk, now)
        submission = TradePlanSubmitter().submit(
            plan,
            risk,
            protection,
            receipt,
            reservation,
            order_type=order_type,
            now=now,
        )
        if submission.execution_plan is None:
            risk_ledger.release(reservation.reservation_id)
            return SubmitTradePlanResult(
                "REJECTED", submission.reason, preflight, basis, reservation, risk, protection, receipt
            )
        order = Order.from_execution_plan(
            submission.execution_plan,
            instrument=plan.instrument,
            direction=plan.direction,
        )
        ledger = self._ledger_entry(order, plan=plan, reservation=reservation, now=now)
        if not issue_order:
            if durable:
                persist_authorization = getattr(durable_repository, "persist_authorization_chain", None)
                if not callable(persist_authorization) or not persist_authorization(
                    durable_connection,
                    basis=basis,
                    reservation=reservation,
                    receipt=receipt,
                    constitution_ref=self.constitution.ref,
                    constitution_version=self.constitution.version,
                    constitution_hash=self.constitution.content_hash,
                    mandate=mandate,
                    approval=approval,
                    now=now.value,
                ):
                    return SubmitTradePlanResult(
                        "REJECTED", "DURABLE_AUTHORIZATION_PERSISTENCE_REJECTED", preflight, basis, reservation, risk
                    )
            return SubmitTradePlanResult(
                "AUTHORIZED",
                "EXECUTION_PLAN_CREATED",
                preflight,
                basis,
                reservation,
                risk,
                protection,
                receipt,
                submission.execution_plan,
            )
        durable_reservation: RiskBudgetReservation | None = reservation
        if durable:
            persist_submission = getattr(durable_repository, "persist_submission_chain", None)
            if callable(persist_submission):
                persisted = persist_submission(
                    durable_connection,
                    basis=basis,
                    reservation=reservation,
                    receipt=receipt,
                    order_id=order.order_id.value,
                    order_payload=self._order_payload(order, plan=plan),
                    ledger_id=ledger.entry_id.value,
                    ledger_payload=self._ledger_payload(ledger, plan=plan),
                    constitution_ref=self.constitution.ref,
                    constitution_version=self.constitution.version,
                    constitution_hash=self.constitution.content_hash,
                    mandate=mandate,
                    approval=approval,
                    correlation_id=plan.plan_id.value,
                    now=now.value,
                )
                if not persisted:
                    return SubmitTradePlanResult(
                        "REJECTED",
                        "DURABLE_SUBMISSION_PERSISTENCE_REJECTED",
                        preflight,
                        basis,
                        reservation,
                        risk,
                        protection,
                        receipt,
                    )
                durable_reservation = replace(
                    reservation,
                    status=ReservationStatus.CONSUMED,
                    version=reservation.version + 1,
                    state_version=reservation.state_version + 1,
                )
            else:
                # Compatibility for narrow repository doubles; production
                # PostgresAutonomyRepository always takes the atomic path above.
                persist_chain = getattr(durable_repository, "persist_prepared_chain", None)
                if not callable(persist_chain) or not persist_chain(
                    durable_connection,
                    basis=basis,
                    reservation=reservation,
                    receipt=receipt,
                    constitution_ref=self.constitution.ref,
                    constitution_version=self.constitution.version,
                    constitution_hash=self.constitution.content_hash,
                    mandate=mandate,
                    approval=approval,
                    now=now.value,
                ):
                    return SubmitTradePlanResult(
                        "REJECTED", "DURABLE_AUTHORIZATION_PERSISTENCE_REJECTED", preflight, basis, reservation, risk
                    )
                receipt_consumed = self.consume_durable_receipt_and_reservation(
                    durable_repository,
                    durable_connection,
                    receipt_id=receipt.receipt_id,
                    reservation_id=receipt.reservation_id,
                    nonce=receipt.nonce,
                    now=now,
                )
                if not receipt_consumed:
                    return SubmitTradePlanResult(
                        "REJECTED", "RECEIPT_CONSUME_REJECTED", preflight, basis, reservation, risk, protection, receipt
                    )
                append_execution_facts = getattr(durable_repository, "append_execution_facts", None)
                if not callable(append_execution_facts) or not append_execution_facts(
                    durable_connection,
                    order_id=order.order_id.value,
                    order_payload=self._order_payload(order, plan=plan),
                    ledger_id=ledger.entry_id.value,
                    ledger_payload=self._ledger_payload(ledger, plan=plan),
                    correlation_id=plan.plan_id.value,
                    now=now.value,
                ):
                    return SubmitTradePlanResult(
                        "REJECTED",
                        "DURABLE_EXECUTION_PERSISTENCE_REJECTED",
                        preflight,
                        basis,
                        reservation,
                        risk,
                        protection,
                        receipt,
                    )
                durable_reservation = replace(
                    reservation,
                    status=ReservationStatus.CONSUMED,
                    version=reservation.version + 1,
                    state_version=reservation.state_version + 1,
                )
        else:
            receipt_consumed = TradePlanSubmitter.consume_authorized_receipt(
                receipt_registry,
                receipt,
                now=now,
                request=request,
                basis=basis,
                reservation=reservation,
                ledger=risk_ledger,
                mandate=mandate,
                approval=approval,
                binding=binding,
                qualified=qualified,
                health_permits=health_permits,
            )
        if not durable and not receipt_consumed:
            return SubmitTradePlanResult(
                "REJECTED", "RECEIPT_CONSUME_REJECTED", preflight, basis, reservation, risk, protection, receipt
            )
        if not durable:
            durable_reservation = risk_ledger.reservation(reservation.reservation_id)
        return SubmitTradePlanResult(
            "SUBMITTED",
            "ORDER_CREATED",
            preflight,
            basis,
            durable_reservation,
            risk,
            protection,
            receipt,
            submission.execution_plan,
            order,
            ledger,
        )

    def submit(
        self,
        plan: TradePlan,
        *,
        now: RecordedAt,
        execution_origin: ExecutionOrigin,
        snapshot_hash: str,
        snapshot_expires_at: RecordedAt,
        run_versions_hash: str,
        session: str = "default",
        mandate: SimulationAutonomyMandate | None = None,
        binding: AutonomyModeBinding | None = None,
        approval: PlanApproval | None = None,
        qualified: bool = True,
        health_permits: bool = True,
        approval_allowed: bool = False,
        data_quality: Decimal | None = None,
        concentration: Decimal | None = None,
        days_to_delivery: int | None = None,
        order_type: str = "MARKET",
        issue_order: bool = True,
    ) -> SubmitTradePlanResult:
        """Submit one plan through the public application boundary.

        This facade deliberately exposes only domain facts.  Durable database
        connections and repositories are owned by the application adapter and
        are unavailable to ordinary callers.
        """
        return self._submit_with_durable_handles(
            plan,
            now=now,
            execution_origin=execution_origin,
            snapshot_hash=snapshot_hash,
            snapshot_expires_at=snapshot_expires_at,
            run_versions_hash=run_versions_hash,
            session=session,
            mandate=mandate,
            binding=binding,
            approval=approval,
            qualified=qualified,
            health_permits=health_permits,
            approval_allowed=approval_allowed,
            data_quality=data_quality,
            concentration=concentration,
            days_to_delivery=days_to_delivery,
            order_type=order_type,
            issue_order=issue_order,
        )

    def _submit_durable(
        self,
        plan: TradePlan,
        *,
        durable_repository: object,
        durable_connection: object,
        now: RecordedAt,
        execution_origin: ExecutionOrigin,
        snapshot_hash: str,
        snapshot_expires_at: RecordedAt,
        run_versions_hash: str,
        session: str = "default",
        mandate: SimulationAutonomyMandate | None = None,
        binding: AutonomyModeBinding | None = None,
        approval: PlanApproval | None = None,
        qualified: bool = True,
        health_permits: bool = True,
        approval_allowed: bool = False,
        data_quality: Decimal | None = None,
        concentration: Decimal | None = None,
        days_to_delivery: int | None = None,
        order_type: str = "MARKET",
        issue_order: bool = True,
    ) -> SubmitTradePlanResult:
        """Internal adapter used by application code owning a DB transaction."""
        return self._submit_with_durable_handles(
            plan,
            now=now,
            execution_origin=execution_origin,
            snapshot_hash=snapshot_hash,
            snapshot_expires_at=snapshot_expires_at,
            run_versions_hash=run_versions_hash,
            session=session,
            mandate=mandate,
            binding=binding,
            approval=approval,
            qualified=qualified,
            health_permits=health_permits,
            approval_allowed=approval_allowed,
            data_quality=data_quality,
            concentration=concentration,
            days_to_delivery=days_to_delivery,
            order_type=order_type,
            issue_order=issue_order,
            durable_repository=durable_repository,
            durable_connection=durable_connection,
        )


def submit_trade_plan(
    plan: TradePlan,
    *,
    service: SubmitTradePlanService,
    **kwargs: object,
) -> SubmitTradePlanResult:
    """Functional facade for callers that prefer a named application command."""
    if not isinstance(service, SubmitTradePlanService):
        raise TypeError("submit_trade_plan requires a SubmitTradePlanService")
    return service.submit(plan, **kwargs)  # type: ignore[arg-type]


__all__ = ["SubmitTradePlanResult", "SubmitTradePlanService", "submit_trade_plan"]
