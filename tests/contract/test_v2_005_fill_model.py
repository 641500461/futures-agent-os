from decimal import Decimal

import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import FillOrderType, IntrabarAmbiguityPolicy, L1Bar, L1FillModel
from futures_agent_os.shared_kernel import EntityId


def test_l1_model_separates_trigger_and_fill() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("10"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("100"), Decimal("105"), Decimal("99"), Decimal("103"), Decimal("3"))
    decision = L1FillModel(Decimal("0.5")).simulate(
        order, bar, order_type=FillOrderType.STOP, stop_price=Decimal("104")
    )
    assert decision.triggered and decision.filled_quantity == Decimal("3") and decision.reason == "PARTIAL_FILL"


def test_l1_model_does_not_fill_untriggered_stop() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))
    decision = L1FillModel().simulate(order, bar, order_type=FillOrderType.STOP, stop_price=Decimal("105"))
    assert decision.triggered is False and decision.filled_quantity == Decimal("0")


def test_bar_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValueError):
        L1Bar(Decimal("100"), Decimal("99"), Decimal("101"), Decimal("100"), Decimal("1"))


def test_stop_trigger_uses_stop_or_gap_price_and_limit_uses_intrabar_cross() -> None:
    stop_order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    gap_bar = L1Bar(Decimal("110"), Decimal("112"), Decimal("109"), Decimal("111"), Decimal("1"))
    stop = L1FillModel().simulate(stop_order, gap_bar, order_type=FillOrderType.STOP, stop_price=Decimal("105"))
    assert stop.triggered and stop.price == Decimal("110")
    limit_order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("105"), Decimal("106"), Decimal("99"), Decimal("104"), Decimal("1"))
    limit = L1FillModel().simulate(limit_order, bar, order_type=FillOrderType.LIMIT, limit_price=Decimal("100"))
    assert limit.triggered and limit.price == Decimal("100")


def test_bracket_same_bar_uses_declared_conservative_stop_first_policy() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("100"), Decimal("110"), Decimal("90"), Decimal("100"), Decimal("1"))
    decision = L1FillModel().simulate_bracket(
        order,
        bar,
        take_profit_price=Decimal("105"),
        stop_price=Decimal("95"),
        policy=IntrabarAmbiguityPolicy.STOP_FIRST,
    )
    assert decision.triggered and decision.price == Decimal("95")
