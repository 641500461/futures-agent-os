from datetime import UTC, datetime
from decimal import Decimal
import pytest

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


def test_account_close_realizes_pnl_and_rejects_overclose() -> None:
    account_id = EntityId.new("simulation_account")
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    open_fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    account.apply_fill(open_fill, lot_id=EntityId.new("position_lot"), account_id=account_id)
    close_fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.SHORT,
        Decimal("1"),
        Decimal("110"),
        Decimal("1"),
        now,
    )
    state = account.close(close_fill)
    assert state.realized_pnl == Decimal("10") and state.lots[0].quantity == Decimal("1")
    with pytest.raises(ValueError):
        account.close(
            Fill(
                EntityId.new("fill"),
                EntityId.new("order"),
                "SHFE_AG_2601",
                TradeDirection.SHORT,
                Decimal("2"),
                Decimal("110"),
                Decimal("0"),
                now,
            )
        )


def test_margin_is_frozen_and_released_without_notional_cash_debit() -> None:
    account = SimulationAccount(Decimal("1000"))
    assert account.reserve_margin(Decimal("200")).margin == Decimal("200")
    assert account.state.cash == Decimal("1000")
    assert account.release_margin(Decimal("200")).margin == Decimal("0")
    with pytest.raises(ValueError):
        account.release_margin(Decimal("1"))


def test_mark_to_market_generates_settlement_pnl() -> None:
    account_id = EntityId.new("simulation_account")
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        Decimal("100"),
        Decimal("0"),
        now,
    )
    account.apply_fill(fill, lot_id=EntityId.new("position_lot"), account_id=account_id)
    settlement = account.mark_to_market(EntityId.new("settlement"), "2026-09-05", Decimal("105"), now)
    assert settlement.realized_pnl == Decimal("10") and settlement.cash_delta == Decimal("10")
