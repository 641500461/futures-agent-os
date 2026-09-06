from __future__ import annotations

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


def _mandate(account: EntityId) -> tuple[SimulationAutonomyMandate, AutonomyModeBinding]:
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
    assert ledger.reservations == ()


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
    mandate, binding = _mandate(account)
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
    mandate, binding = _mandate(account)
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
