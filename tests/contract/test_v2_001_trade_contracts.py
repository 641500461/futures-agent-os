from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.decision import (
    ExecutionPlan,
    ContractReferenceGraph,
    Fill,
    LedgerEntry,
    Order,
    OrderStatus,
    PositionLot,
    ProtectionIntent,
    ProtectionMandate,
    RiskDecision,
    RiskDecisionOutcome,
    Settlement,
    StopPolicy,
    TradeAction,
    TradeDirection,
    TradePlan,
    TradePlanStatus,
    TradePlanSubmitter,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def _at(hours: int = 1) -> RecordedAt:
    return RecordedAt.from_datetime(datetime.now(UTC) + timedelta(hours=hours))


def _plan(**changes: object) -> TradePlan:
    values: dict[str, object] = {
        "plan_id": EntityId.new("trade_plan"),
        "account_id": EntityId.new("simulation_account"),
        "instrument": "SHFE_AG_2601",
        "strategy_ref": "strategy:test",
        "action": TradeAction.OPEN,
        "direction": TradeDirection.LONG,
        "quantity": Decimal("2"),
        "entry_price": Decimal("100"),
        "protection": ProtectionIntent(stop_price=Decimal("95"), max_loss=Decimal("10")),
        "thesis": "price rejects support",
        "invalidation": "support breaks",
        "evidence_refs": ("a" * 64,),
        "snapshot_ref": "snapshot:test",
        "expires_at": _at(),
    }
    values.update(changes)
    return TradePlan(**values)  # type: ignore[arg-type]


def test_trade_plan_is_hashed_and_requires_protection() -> None:
    plan = _plan()
    assert len(plan.plan_hash) == 64
    replayed = TradePlan.hydrate(plan.to_dict())
    assert replayed == plan
    assert replayed.plan_hash == plan.plan_hash
    with pytest.raises(TypeError):
        _plan(protection=None)


def test_trade_plan_rejects_empty_evidence() -> None:
    with pytest.raises(ValueError):
        _plan(evidence_refs=())


def test_submission_preflight_rejects_expired_plan() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    created_at = RecordedAt.from_datetime(now.value - timedelta(seconds=2))
    expires_at = RecordedAt.from_datetime(now.value - timedelta(seconds=1))
    plan = _plan(created_at=created_at, expires_at=expires_at)
    assert TradePlanSubmitter.validate_plan(plan, now=now) == "PLAN_EXPIRED"


def test_order_transitions_and_fill_cap() -> None:
    from futures_agent_os.decision import Order, OrderStatus

    order = Order(
        EntityId.new("order"), EntityId.new("execution_plan"), "SHFE_AG_2601", TradeDirection.LONG, Decimal("2")
    )
    order = order.transition(OrderStatus.ACCEPTED).transition(OrderStatus.WORKING)
    order = order.apply_fill(Decimal("1"))
    assert order.status is OrderStatus.PARTIALLY_FILLED
    with pytest.raises(ValueError):
        order.apply_fill(Decimal("2"))


def test_v2_contracts_have_schema_time_source_and_stable_identity() -> None:
    plan = _plan()
    assert plan.schema_version == SchemaVersion(1, 0)
    assert isinstance(plan.created_at, RecordedAt) and plan.source_ref
    assert isinstance(plan.protection.intent_id, EntityId)
    assert isinstance(plan.protection.created_at, RecordedAt)

    risk = RiskDecision(
        EntityId.new("risk_decision"),
        plan.plan_id,
        plan.version,
        RiskDecisionOutcome.APPROVE,
        Decimal("1"),
        Decimal("5"),
        Decimal("10"),
        ("risk-rule:v1",),
        "risk-constitution:v1",
        plan.created_at,
        plan.plan_hash,
    )
    protection = ProtectionMandate(
        EntityId.new("protection_mandate"),
        plan.plan_id,
        Decimal("95"),
        Decimal("5"),
        plan.created_at,
        1,
        risk.decision_id,
        plan.version,
    )
    execution = ExecutionPlan(
        EntityId.new("execution_plan"),
        plan.plan_id,
        "LIMIT",
        Decimal("1"),
        Decimal("100"),
        None,
        protection.mandate_id,
        plan.created_at,
        risk.decision_id,
        plan.version,
    )
    stop_policy = StopPolicy(
        EntityId.new("stop_policy"),
        EntityId.new("position_lot"),
        Decimal("95"),
        Decimal("5"),
        protection_mandate_id=protection.mandate_id,
        created_at=plan.created_at,
    )
    order = Order.from_execution_plan(execution, instrument=plan.instrument, direction=plan.direction)
    fill = Fill(
        EntityId.new("fill"),
        order.order_id,
        plan.instrument,
        plan.direction,
        Decimal("1"),
        Decimal("100"),
        Decimal("0"),
        plan.created_at,
    )
    lot = PositionLot(
        EntityId.new("position_lot"),
        plan.account_id,
        plan.instrument,
        plan.direction,
        Decimal("1"),
        Decimal("100"),
        plan.created_at,
        fill.fill_id,
    )
    entry = LedgerEntry(
        EntityId.new("ledger_entry"), plan.account_id, fill.fill_id, Decimal("1"), "CNY", "FILL", plan.created_at
    )
    settlement = Settlement(
        EntityId.new("settlement"),
        plan.account_id,
        "2026-09-05",
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        plan.created_at,
    )
    for value in (risk, protection, execution, stop_policy, order, fill, lot, entry, settlement):
        assert value.schema_version == SchemaVersion(1, 0)
        assert value.source_ref


def test_v2_contracts_reject_mismatched_references_and_illegal_states() -> None:
    plan = _plan()
    with pytest.raises(ValueError):
        _plan(plan_id=EntityId.new("order"))
    with pytest.raises(ValueError):
        _plan(evidence_refs=("x" * 63,))
    with pytest.raises(ValueError):
        _plan(protection=ProtectionIntent(Decimal("105"), Decimal("10")))

    with pytest.raises(ValueError):
        Order(
            EntityId.new("order"),
            EntityId.new("execution_plan"),
            plan.instrument,
            TradeDirection.LONG,
            Decimal("1"),
            OrderStatus.FILLED,
        )
    with pytest.raises(ValueError):
        ProtectionMandate(
            EntityId.new("protection_mandate"),
            plan.plan_id,
            Decimal("95"),
            Decimal("5"),
            plan.created_at,
            1,
            EntityId.new("risk_decision"),
            None,
        )
    validated = plan.transition(TradePlanStatus.VALIDATED)
    assert validated.status.value == "VALIDATED"
    with pytest.raises(ValueError):
        validated.transition(TradePlanStatus.DRAFT)


def test_trade_plan_rejects_expiry_at_or_before_creation() -> None:
    plan = _plan()
    with pytest.raises(ValueError, match="expiry must be after creation"):
        _plan(expires_at=plan.created_at)


def test_reference_graph_resolves_registered_fact_after_binding() -> None:
    plan = _plan()
    graph = ContractReferenceGraph((plan,))
    reference = graph.register(plan)
    assert graph.require(reference) is plan
    assert graph.require_fact(plan.plan_id, plan.version, plan.plan_hash, expected_namespace="trade_plan") is plan
    with pytest.raises(ValueError):
        graph.require(type(reference)(reference.entity_id, reference.version, "0" * 64))
    with pytest.raises(ValueError):
        graph.require_fact(plan.plan_id, plan.version + 1, plan.plan_hash)


def test_owner_contract_surfaces_define_canonical_types() -> None:
    from futures_agent_os.accounting_settlement.contracts import PositionLot as AccountingPositionLot
    from futures_agent_os.execution_simulation.contracts import Order as ExecutionOrder
    from futures_agent_os.portfolio_risk.contracts import RiskDecision as PortfolioRiskDecision

    assert AccountingPositionLot.__module__.endswith("accounting_settlement.contracts")
    assert ExecutionOrder.__module__.endswith("execution_simulation.contracts")
    assert PortfolioRiskDecision.__module__.endswith("portfolio_risk.contracts")
