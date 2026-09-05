from decimal import Decimal
import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import BookEvent, L2EventFillModel
from futures_agent_os.shared_kernel import EntityId


def test_l2_consumes_visible_liquidity_deterministically() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("5"),
        OrderStatus.WORKING,
    )
    event = BookEvent(1, Decimal("99"), Decimal("4"), Decimal("101"), Decimal("2"))
    result = L2EventFillModel().simulate(order, (event,))
    assert result.filled_quantity == Decimal("2") and result.reason == "PARTIAL_FILL"


def test_l2_rejects_out_of_order_events() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    events = (
        BookEvent(2, Decimal("99"), Decimal("1"), Decimal("101"), Decimal("1")),
        BookEvent(1, Decimal("99"), Decimal("1"), Decimal("101"), Decimal("1")),
    )
    with pytest.raises(ValueError):
        L2EventFillModel().simulate(order, events)
