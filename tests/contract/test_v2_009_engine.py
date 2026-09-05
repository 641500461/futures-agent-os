from datetime import UTC, datetime
from decimal import Decimal

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import L1Bar, SimulationEngine
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_shared_engine_is_deterministic_for_same_l1_input() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account_id = EntityId.new("simulation_account")
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("2"))
    first = SimulationEngine().execute_l1(
        order, bar, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    second = SimulationEngine().execute_l1(
        order, bar, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    assert first.order.filled_quantity == second.order.filled_quantity == Decimal("2")
    assert first.account_cash == second.account_cash
