from datetime import UTC, datetime
from decimal import Decimal

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Fill, Settlement, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_account_fill_and_settlement_are_deterministic() -> None:
    account_id = EntityId.new("simulation_account")
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account = SimulationAccount(Decimal("10000"), account_id=account_id)
    fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    state = account.apply_fill(fill, lot_id=EntityId.new("position_lot"), account_id=account_id)
    assert state.cash == Decimal("9999") and len(state.lots) == 1
    assert account.apply_fill(fill, lot_id=EntityId.new("position_lot"), account_id=account_id) == state
    state = account.settle(
        Settlement(
            EntityId.new("settlement"), account_id, "2026-09-05", Decimal("10"), Decimal("10"), Decimal("0"), now
        )
    )
    assert state.cash == Decimal("10009") and state.realized_pnl == Decimal("10")
