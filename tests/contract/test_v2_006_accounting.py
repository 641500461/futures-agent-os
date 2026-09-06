from datetime import UTC, datetime
from decimal import Decimal
from dataclasses import replace
import pytest

from futures_agent_os.accounting_settlement import SimulationAccount
from futures_agent_os.decision import Fill, Settlement, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt
from futures_agent_os.accounting_settlement.replay import AccountingEvent, AccountingEventLog


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
    settlement = Settlement(
        EntityId.new("settlement"), account_id, "2026-09-05", Decimal("10"), Decimal("10"), Decimal("0"), now
    )
    state = account.settle(settlement)
    assert state.cash == Decimal("10009") and state.realized_pnl == Decimal("10")
    assert account.settle(settlement) == state


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
    assert state.cash == Decimal("1008")
    assert state.equity == Decimal("1008")
    assert account.equity == Decimal("1008")
    assert account.close(close_fill) == state
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


def test_settlement_resets_cost_basis_and_replay_uses_stable_lot_ids() -> None:
    account_id = EntityId.new("simulation_account")
    now = RecordedAt.from_datetime(datetime.now(UTC))
    fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("0"),
        now,
    )
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    account.apply_fill(fill, lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)), account_id=account_id)
    settlement = account.mark_to_market(EntityId.new("settlement"), "2026-09-05", Decimal("105"), now)
    account.settle(settlement)
    assert account.state.lots[0].average_price == Decimal("105")
    next_day = account.mark_to_market(EntityId.new("settlement"), "2026-09-06", Decimal("106"), now)
    assert next_day.realized_pnl == Decimal("1")
    log = AccountingEventLog()
    log.append(AccountingEvent(1, EntityId.new("accounting_event"), fill))
    first = SimulationAccount(Decimal("1000"), account_id=account_id)
    second = SimulationAccount(Decimal("1000"), account_id=account_id)
    log.replay(first, account_id=account_id)
    log.replay(second, account_id=account_id)
    assert first.state == second.state
    assert first.state.lots[0].lot_id == second.state.lots[0].lot_id


def test_account_snapshot_restores_idempotency_and_conservation() -> None:
    account_id = EntityId.new("simulation_account")
    now = RecordedAt.from_datetime(datetime.now(UTC))
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
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    account.apply_fill(fill, lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)), account_id=account_id)
    settlement = Settlement(
        EntityId.new("settlement"), account_id, "2026-09-05", Decimal("10"), Decimal("10"), Decimal("0"), now
    )
    account.settle(settlement)
    account.assert_conservation()
    restored = SimulationAccount.restore(account.snapshot())
    assert restored.state == account.state
    assert restored.apply_fill(fill, lot_id=EntityId.new("position_lot"), account_id=account_id) == account.state
    restored.assert_conservation()

    broken = replace(account.snapshot(), settlement_cash_adjustment=Decimal("99"))
    with pytest.raises(ValueError, match="conservation"):
        SimulationAccount.restore(broken)


def test_settlement_fee_is_included_in_cash_conservation() -> None:
    account_id = EntityId.new("simulation_account")
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account = SimulationAccount(Decimal("100"), account_id=account_id)
    settlement = Settlement(
        EntityId.new("settlement"), account_id, "2026-09-05", Decimal("8"), Decimal("10"), Decimal("2"), now
    )
    account.settle(settlement)
    assert account.state.cash == Decimal("108")
    account.assert_conservation()


def test_close_today_only_consumes_same_trading_day_lots() -> None:
    account_id = EntityId.new("simulation_account")
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    prior = RecordedAt.from_datetime(datetime(2026, 9, 5, tzinfo=UTC))
    today = RecordedAt.from_datetime(datetime(2026, 9, 6, tzinfo=UTC))
    for opened_at, lot in ((prior, "position_lot"), (today, "position_lot")):
        account.apply_fill(
            Fill(
                EntityId.new("fill"),
                EntityId.new("order"),
                "SHFE_AG_2601",
                TradeDirection.SHORT,
                Decimal("1"),
                Decimal("100"),
                Decimal("0"),
                opened_at,
            ),
            lot_id=EntityId.new(lot),
            account_id=account_id,
        )
    account.close(
        Fill(
            EntityId.new("fill"),
            EntityId.new("order"),
            "SHFE_AG_2601",
            TradeDirection.LONG,
            Decimal("1"),
            Decimal("99"),
            Decimal("0"),
            today,
        ),
        close_today=True,
    )
    assert len(account.state.lots) == 1 and account.state.lots[0].opened_at == prior
