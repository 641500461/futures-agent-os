from decimal import Decimal

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import FaultInjector, L1Bar
from futures_agent_os.shared_kernel import EntityId


def test_fault_injector_rejects_duplicate_and_no_liquidity() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    injector = FaultInjector()
    seen: set[str] = set()
    assert injector.duplicate_command("cmd-1", seen).accepted
    assert not injector.duplicate_command("cmd-1", seen).accepted
    decision = injector.no_liquidity(
        order, L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("0"))
    )
    assert decision.triggered and decision.reason == "NO_LIQUIDITY" and decision.filled_quantity == Decimal("0")
