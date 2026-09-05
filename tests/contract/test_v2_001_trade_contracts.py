from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.decision import ProtectionIntent, TradeAction, TradeDirection, TradePlan, TradePlanSubmitter
from futures_agent_os.shared_kernel import EntityId, RecordedAt


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
    with pytest.raises(TypeError):
        _plan(protection=None)


def test_trade_plan_rejects_empty_evidence() -> None:
    with pytest.raises(ValueError):
        _plan(evidence_refs=())


def test_submission_preflight_rejects_expired_plan() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    plan = _plan(expires_at=RecordedAt.from_datetime(now.value - timedelta(seconds=1)))
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
