from decimal import Decimal

import pytest

from futures_agent_os.decision import ExecutionPlan, Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import FillOrderType, L1Bar, L1FillModel
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
