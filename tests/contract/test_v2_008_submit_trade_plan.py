from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import inspect

import pytest

from futures_agent_os.decision import (
    ApprovalAction,
    ApprovalScope,
    AutonomyMode,
    AutonomyModeBinding,
    BindingStatus,
    ExecutionOrigin,
    EscalationMode,
    GateRequest,
    MandateScope,
    MandateStatus,
    PlanApproval,
    PlanApprovalStatus,
    ProtectionIntent,
    SimulationAutonomyMandate,
    SubmitTradePlanService,
    TradeAction,
    TradeDirection,
    TradePlan,
    StopPolicy,
    OrderStatus,
    RiskDecisionOutcome,
)
from futures_agent_os.portfolio_risk import RiskBudgetLedger, RiskConstitution, ReservationStatus
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.execution_simulation import L1Bar, SimulationEngine, run_manual_shadow_episode


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _hash(seed: str) -> str:
    return canonical_sha256({"seed": seed})


def test_durable_consume_bridge_delegates_typed_ids_and_leaves_transaction_owner() -> None:
    receipt = EntityId.new("autonomy_gate_receipt")
    reservation = EntityId.new("risk_reservation")
    nonce = EntityId.new("receipt_nonce")

    class FakeRepository:
        def consume_receipt_and_reservation(self, connection, **kwargs):
            assert connection == "tx"
            assert kwargs == {
                "receipt_id": receipt.value,
                "reservation_id": reservation.value,
                "nonce": nonce.value,
                "now": _at().value,
            }
            return True

    assert SubmitTradePlanService.consume_durable_receipt_and_reservation(
        FakeRepository(), "tx", receipt_id=receipt, reservation_id=reservation, nonce=nonce, now=_at()
    )


def _plan(account: EntityId, *, quantity: str = "2") -> TradePlan:
    return TradePlan(
        EntityId.deterministic("trade_plan", f"plan-{quantity}"),
        account,
        "SHFE_AG_2601",
        "strategy:test",
        TradeAction.OPEN,
        TradeDirection.LONG,
        Decimal(quantity),
        Decimal("100"),
        ProtectionIntent(Decimal("95"), Decimal("50"), created_at=_at()),
        "support holds",
        "support breaks",
        (_hash("evidence"),),
        "snapshot:v2",
        _at(30),
        created_at=_at(),
    )


def _constitution() -> RiskConstitution:
    return RiskConstitution(
        "risk://v2",
        1,
        _hash("constitution"),
        Decimal("50"),
        Decimal("1000"),
        Decimal("20"),
        Decimal("0.1"),
    )


def _service() -> tuple[SubmitTradePlanService, RiskBudgetLedger]:
    constitution = _constitution()
    ledger = RiskBudgetLedger(
        constitution.max_single_loss,
        constitution.ref,
        constitution.version,
        constitution.content_hash,
    )
    return SubmitTradePlanService(constitution=constitution, risk_ledger=ledger), ledger


def _mandate(
    account: EntityId,
    *,
    escalation_mode: EscalationMode = EscalationMode.SKIP_AND_NOTIFY,
) -> tuple[SimulationAutonomyMandate, AutonomyModeBinding]:
    scope = MandateScope(
        account,
        ("SHFE_AG_2601",),
        ("strategy:test",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("20"),
        "risk://v2",
        "notify://v2",
        "escalate://v2",
        escalation_mode,
    )
    mandate = SimulationAutonomyMandate(
        EntityId.deterministic("mandate", "mandate-v2"),
        1,
        MandateStatus.ACTIVE,
        scope,
        _at(20),
        _at(),
        "user:owner",
    )
    binding = AutonomyModeBinding(
        EntityId.deterministic("mode_binding", "binding-v2"),
        1,
        AutonomyMode.AUTONOMOUS_SIMULATION,
        BindingStatus.ACTIVE,
        account,
        mandate.mandate_id,
        mandate.version,
        _hash("runs"),
        _at(15),
        _at(),
        scope.sha256,
        "scan://v2",
        "universe://v2",
        "qualified://v2",
        "INITIAL_BINDING",
        "user:owner",
        "evidence://binding",
    )
    return mandate, binding


def _submit_kwargs() -> dict[str, object]:
    return {
        "now": _at(1),
        "execution_origin": ExecutionOrigin.AUTONOMOUS_AGENT,
        "snapshot_hash": _hash("snapshot"),
        "snapshot_expires_at": _at(10),
        "run_versions_hash": _hash("runs"),
        "session": "DAY",
        "qualified": True,
        "health_permits": True,
    }


def test_submit_trade_plan_requires_authorization_before_reservation() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-no-auth")
    result = service.submit(_plan(account), **_submit_kwargs())
    assert result.outcome == "REJECTED" and result.reason == "MANDATE_INACTIVE"
    assert all(r.status is ReservationStatus.RELEASED for r in ledger.reservations)


def test_submit_trade_plan_public_api_hides_durable_configuration() -> None:
    service, _ = _service()
    account = EntityId.deterministic("simulation_account", "account-partial-durable")
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        service.submit(_plan(account), durable_repository=object(), **_submit_kwargs())


def test_submit_trade_plan_signature_contains_only_domain_inputs() -> None:
    parameters = inspect.signature(SubmitTradePlanService.submit).parameters
    assert "durable_repository" not in parameters
    assert "durable_connection" not in parameters


def test_submit_trade_plan_builds_protected_order_and_consumes_once() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-success")
    mandate, binding = _mandate(account, escalation_mode=EscalationMode.REQUEST_ONE_OFF)
    result = service.submit(_plan(account), mandate=mandate, binding=binding, **_submit_kwargs())
    assert result.outcome == "SUBMITTED" and result.order is not None
    assert result.receipt is not None and result.protection is not None
    assert result.reservation is not None and result.reservation.status is ReservationStatus.CONSUMED
    replay = service.submit(_plan(account), mandate=mandate, binding=binding, **_submit_kwargs())
    assert replay.outcome == "REJECTED"
    assert replay.order is None
    assert len(ledger.reservations) == 1


def test_submit_trade_plan_uses_durable_consumer_when_explicitly_configured() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-durable-submit")
    mandate, binding = _mandate(account, escalation_mode=EscalationMode.REQUEST_ONE_OFF)
    calls: list[tuple[object, object]] = []

    class FakeRepository:
        def consume_receipt_and_reservation(self, connection, **kwargs):
            calls.append((connection, kwargs))
            return True

        def append_execution_facts(self, connection, **kwargs):
            calls.append((connection, kwargs))
            return True

        def persist_prepared_chain(self, connection, **kwargs):
            calls.append((connection, kwargs))
            return True

    result = service._submit_durable(
        _plan(account),
        mandate=mandate,
        binding=binding,
        durable_repository=FakeRepository(),
        durable_connection="tx",
        **_submit_kwargs(),
    )
    assert result.outcome == "SUBMITTED" and len(calls) == 3
    assert calls[0][0] == "tx"
    # Durable attempts use an ephemeral candidate ledger.  PostgreSQL owns the
    # reservation, so a rolled-back or committed call cannot poison a retry in
    # the service's in-memory reference ledger.
    assert ledger.reservations == ()
    assert result.order.quantity == Decimal("2")


def test_durable_prepared_chain_rejection_fails_closed_before_consumption() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-durable-reject")
    mandate, binding = _mandate(account)

    class RejectingRepository:
        def persist_prepared_chain(self, connection, **kwargs):
            return False

    result = service._submit_durable(
        _plan(account),
        mandate=mandate,
        binding=binding,
        durable_repository=RejectingRepository(),
        durable_connection="tx",
        **_submit_kwargs(),
    )
    assert result.outcome == "REJECTED"
    assert result.reason == "DURABLE_AUTHORIZATION_PERSISTENCE_REJECTED"
    assert result.order is None and result.receipt is None
    assert ledger.reservations == ()


def test_expired_snapshot_rejects_before_sizing_or_reservation() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-expired-snapshot")
    mandate, binding = _mandate(account)
    result = service.submit(
        _plan(account),
        mandate=mandate,
        binding=binding,
        now=_at(11),
        execution_origin=ExecutionOrigin.AUTONOMOUS_AGENT,
        snapshot_hash=_hash("snapshot"),
        snapshot_expires_at=_at(10),
        run_versions_hash=_hash("runs"),
        session="DAY",
    )
    assert result.outcome == "REJECTED"
    assert result.order is None and result.reservation is None
    assert ledger.reservations == ()


def test_mode_binding_run_versions_drift_rejects_before_reservation() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-binding-drift")
    mandate, binding = _mandate(account)
    result = service.submit(
        _plan(account),
        mandate=mandate,
        binding=binding,
        now=_at(1),
        execution_origin=ExecutionOrigin.AUTONOMOUS_AGENT,
        snapshot_hash=_hash("snapshot"),
        snapshot_expires_at=_at(10),
        run_versions_hash=_hash("different-runs"),
        session="DAY",
    )
    assert result.outcome == "REJECTED"
    assert result.order is None
    assert all(r.status is ReservationStatus.RELEASED for r in ledger.reservations)


def test_submit_trade_plan_accepts_safe_risk_sizing_reduction() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-reduced")
    mandate, binding = _mandate(account)
    result = service.submit(
        _plan(account, quantity="20"),
        mandate=mandate,
        binding=binding,
        **_submit_kwargs(),
    )
    assert result.outcome == "SUBMITTED" and result.order is not None
    assert result.risk is not None and result.risk.approved_quantity == Decimal("10")
    assert result.order.quantity == Decimal("10")
    assert ledger.reservations[0].quantity == Decimal("10")


def test_autonomous_scope_escalation_waits_without_sizing_or_reservation() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-escalate")
    plan = _plan(account)
    scope = MandateScope(
        account,
        ("OTHER_INSTRUMENT",),
        ("strategy:test",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("20"),
        "risk://v2",
        "notify://v2",
        "escalate://v2",
        EscalationMode.REQUEST_ONE_OFF,
    )
    mandate = SimulationAutonomyMandate(
        EntityId.deterministic("mandate", "mandate-escalate"),
        1,
        MandateStatus.ACTIVE,
        scope,
        _at(20),
        _at(),
        "user:owner",
    )
    binding = AutonomyModeBinding(
        EntityId.deterministic("mode_binding", "binding-escalate"),
        1,
        AutonomyMode.AUTONOMOUS_SIMULATION,
        BindingStatus.ACTIVE,
        account,
        mandate.mandate_id,
        mandate.version,
        _hash("runs"),
        _at(15),
        _at(),
        scope.sha256,
        "scan://v2",
        "universe://v2",
        "qualification://v2",
        "INITIAL_BINDING",
        "user:owner",
        "evidence://binding",
    )
    result = service.submit(
        plan,
        mandate=mandate,
        binding=binding,
        approval_allowed=True,
        **_submit_kwargs(),
    )
    assert result.outcome == "DEFERRED"
    assert result.reason == "PLAN_APPROVAL_REQUIRED"
    assert result.preflight is not None and result.preflight.outcome.value == "ESCALATE"
    assert result.basis is None and result.reservation is None and ledger.reservations == ()


def test_submit_rejects_when_current_risk_decision_changes_after_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-risk-recheck")
    mandate, binding = _mandate(account)
    import importlib

    submit_module = importlib.import_module("futures_agent_os.decision.submit_trade_plan")

    original = submit_module.RiskEngine.decide
    calls = 0

    def drifting(self, plan, **kwargs):
        nonlocal calls
        calls += 1
        decision = original(self, plan, **kwargs)
        if calls == 2:
            return replace(
                decision,
                outcome=RiskDecisionOutcome.REJECT,
                approved_quantity=Decimal("0"),
            )
        return decision

    monkeypatch.setattr(submit_module.RiskEngine, "decide", drifting)
    result = service.submit(_plan(account), mandate=mandate, binding=binding, **_submit_kwargs())
    assert result.outcome == "REJECTED" and result.reason == "RISK_DECISION_STALE"
    assert result.receipt is not None
    assert ledger.reservations[0].status is ReservationStatus.RELEASED


def test_autonomous_one_off_approval_can_reach_final_gate_once() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-one-off")
    plan = _plan(account)
    scope = MandateScope(
        account,
        ("OTHER_INSTRUMENT",),
        ("strategy:test",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("20"),
        "risk://v2",
        "notify://v2",
        "escalate://v2",
        EscalationMode.REQUEST_ONE_OFF,
    )
    mandate = SimulationAutonomyMandate(
        EntityId.deterministic("mandate", "mandate-one-off"),
        1,
        MandateStatus.ACTIVE,
        scope,
        _at(20),
        _at(),
        "user:owner",
    )
    binding = AutonomyModeBinding(
        EntityId.deterministic("mode_binding", "binding-one-off"),
        1,
        AutonomyMode.AUTONOMOUS_SIMULATION,
        BindingStatus.ACTIVE,
        account,
        mandate.mandate_id,
        1,
        _hash("runs"),
        _at(15),
        _at(),
        scope.sha256,
        "scan://v2",
        "universe://v2",
        "qualification://v2",
        "INITIAL_BINDING",
        "user:owner",
        "evidence://binding",
    )
    request = GateRequest(
        plan.plan_id,
        plan.version,
        plan.plan_hash,
        account,
        plan.instrument,
        plan.strategy_ref,
        "DAY",
        ApprovalAction.OPEN,
        plan.quantity,
        ExecutionOrigin.AUTONOMOUS_AGENT,
        _hash("snapshot"),
        _at(10),
        _hash("runs"),
    )
    approval = PlanApproval.request_agent_exception(
        request=request,
        mandate=mandate,
        binding=binding,
        qualified=True,
        health_permits=True,
        approval_id=EntityId.new("plan_approval"),
        approval_token=EntityId.new("approval_token"),
        expires_at=_at(8),
        now=_at(),
    ).decide(PlanApprovalStatus.GRANTED, _at(1))
    result = service.submit(
        plan,
        mandate=mandate,
        binding=binding,
        approval=approval,
        approval_allowed=True,
        **_submit_kwargs(),
    )
    assert result.outcome == "SUBMITTED" and result.order is not None
    assert result.basis is not None and result.basis.kind.value == "PLAN_APPROVAL"
    assert result.receipt is not None and result.reservation is not None
    assert result.reservation.status is ReservationStatus.CONSUMED
    assert len(ledger.reservations) == 1
    replay = service.submit(
        plan,
        mandate=mandate,
        binding=binding,
        approval=approval,
        approval_allowed=True,
        **_submit_kwargs(),
    )
    assert replay.outcome == "REJECTED" and replay.order is None


def test_manual_test_requires_granted_plan_approval() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-manual")
    plan = _plan(account)
    result = service.submit(
        plan,
        now=_at(1),
        execution_origin=ExecutionOrigin.MANUAL_TEST,
        snapshot_hash=_hash("snapshot"),
        snapshot_expires_at=_at(10),
        run_versions_hash=_hash("runs"),
        session="DAY",
        approval_allowed=True,
    )
    assert result.outcome == "DEFERRED" and result.reason == "PLAN_APPROVAL_REQUIRED"
    assert ledger.reservations == ()

    scope = ApprovalScope(
        account,
        ("SHFE_AG_2601",),
        ("strategy:test",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("2"),
        _at(),
        _at(10),
    )
    requested = PlanApproval(
        EntityId.deterministic("plan_approval", "approval-v2"),
        1,
        PlanApprovalStatus.REQUESTED,
        plan.plan_id,
        plan.version,
        plan.plan_hash,
        account,
        scope,
        EntityId.deterministic("approval_token", "token-v2"),
        "user:owner",
        _at(10),
        _at(),
    )
    granted = requested.decide(PlanApprovalStatus.GRANTED, _at(1))
    result = service.submit(
        plan,
        now=_at(2),
        execution_origin=ExecutionOrigin.MANUAL_TEST,
        snapshot_hash=_hash("snapshot"),
        snapshot_expires_at=_at(9),
        run_versions_hash=_hash("runs"),
        session="DAY",
        approval=granted,
        approval_allowed=True,
    )
    assert result.outcome == "SUBMITTED" and result.order is not None
    assert result.basis is not None
    assert result.reservation is not None and result.reservation.status is ReservationStatus.CONSUMED


def test_requested_plan_approval_cannot_be_consumed_as_basis() -> None:
    service, ledger = _service()
    account = EntityId.deterministic("simulation_account", "account-requested")
    plan = _plan(account)
    scope = ApprovalScope(
        account,
        ("SHFE_AG_2601",),
        ("strategy:test",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("2"),
        _at(),
        _at(10),
    )
    approval = PlanApproval(
        EntityId.deterministic("plan_approval", "requested-only"),
        1,
        PlanApprovalStatus.REQUESTED,
        plan.plan_id,
        plan.version,
        plan.plan_hash,
        account,
        scope,
        EntityId.deterministic("approval_token", "requested-only"),
        "service:agent",
        _at(10),
        _at(),
    )
    result = service.submit(
        plan,
        now=_at(2),
        execution_origin=ExecutionOrigin.AUTONOMOUS_AGENT,
        snapshot_hash=_hash("snapshot"),
        snapshot_expires_at=_at(9),
        run_versions_hash=_hash("runs"),
        session="DAY",
        approval=approval,
        approval_allowed=True,
    )
    assert result.outcome == "REJECTED"
    assert ledger.reservations == ()


def test_consumed_manual_basis_enters_shadow_execution_and_settlement() -> None:
    service, _ = _service()
    account_id = EntityId.deterministic("simulation_account", "account-manual-e2e")
    plan = _plan(account_id, quantity="1")
    mandate_scope = ApprovalScope(
        account_id,
        ("SHFE_AG_2601",),
        ("strategy:test",),
        ("DAY",),
        frozenset({ApprovalAction.OPEN}),
        Decimal("1"),
        _at(),
        _at(10),
    )
    approval = PlanApproval(
        EntityId.deterministic("plan_approval", "manual-e2e"),
        1,
        PlanApprovalStatus.GRANTED,
        plan.plan_id,
        1,
        plan.plan_hash,
        account_id,
        mandate_scope,
        EntityId.deterministic("approval_token", "manual-e2e"),
        "user:owner",
        _at(10),
        _at(),
        decided_at=_at(1),
        decided_by="user:owner",
    )
    result = service.submit(
        plan,
        now=_at(2),
        execution_origin=ExecutionOrigin.MANUAL_TEST,
        snapshot_hash=_hash("snapshot"),
        snapshot_expires_at=_at(9),
        run_versions_hash=_hash("runs"),
        session="DAY",
        approval=approval,
        approval_allowed=True,
    )
    assert result.outcome == "SUBMITTED" and result.order is not None
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    working_order = result.order.transition(OrderStatus.ACCEPTED).transition(OrderStatus.WORKING)
    probe = SimulationAccount(Decimal("1000"), account_id=account_id)
    opened = SimulationEngine().execute_l1(
        working_order,
        L1Bar(Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1")),
        probe,
        now=_at(2),
    )
    assert opened.fill is not None
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "manual-e2e"),
        EntityId.deterministic("position_lot", str(opened.fill.fill_id)),
        Decimal("95"),
        Decimal("5"),
    )
    report = run_manual_shadow_episode(
        working_order,
        account,
        open_bar=L1Bar(Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1")),
        exit_bar=L1Bar(Decimal("94"), Decimal("94"), Decimal("94"), Decimal("94"), Decimal("1")),
        stop_policy=policy,
        now=_at(2),
    )
    assert report.open_result.fill is not None and account.state.lots == ()


def test_request_one_off_grant_basis_receipt_and_durable_consume_golden_chain() -> None:
    """An agent exception remains human-granted and is consumed exactly once."""
    service, _ = _service()
    account = EntityId.deterministic("simulation_account", "account-one-off-golden")
    mandate, binding = _mandate(account, escalation_mode=EscalationMode.REQUEST_ONE_OFF)
    plan = _plan(account)
    # Force an exception by changing the instrument outside the mandate scope.
    plan = replace(plan, instrument="SHFE_CU_2601")
    kwargs = _submit_kwargs()
    request = service._request(
        plan,
        execution_origin=kwargs["execution_origin"],
        snapshot_hash=kwargs["snapshot_hash"],
        snapshot_expires_at=kwargs["snapshot_expires_at"],
        run_versions_hash=kwargs["run_versions_hash"],
        session=kwargs["session"],
    )
    approval = PlanApproval.request_agent_exception(
        request=request,
        mandate=mandate,
        binding=binding,
        qualified=True,
        health_permits=True,
        approval_id=EntityId.new("plan_approval"),
        approval_token=EntityId.new("approval_token"),
        expires_at=_at(10),
        now=_at(1),
    ).decide(PlanApprovalStatus.GRANTED, _at(2), actor="user:owner")

    calls: list[str] = []

    class Durable:
        def persist_prepared_chain(self, connection, **kwargs):
            calls.append("persist")
            return True

        def consume_receipt_and_reservation(self, connection, **kwargs):
            calls.append("consume")
            return True

        def append_execution_facts(self, connection, **kwargs):
            calls.append("facts")
            return True

    result = service._submit_durable(
        plan,
        mandate=mandate,
        binding=binding,
        approval=approval,
        approval_allowed=True,
        durable_repository=Durable(),
        durable_connection="tx",
        **kwargs,
    )
    assert result.outcome == "SUBMITTED"
    assert result.basis is not None and result.receipt is not None
    assert calls == ["persist", "consume", "facts"]
