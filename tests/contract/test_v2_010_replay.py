from datetime import UTC, datetime
from decimal import Decimal
import pytest

from futures_agent_os.accounting_settlement import AccountingEvent, AccountingEventLog, SimulationAccount
from futures_agent_os.decision import Fill, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_accounting_event_log_replays_in_order() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account_id = EntityId.new("simulation_account")
    fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    log = AccountingEventLog()
    log.append(AccountingEvent(1, EntityId.new("accounting_event"), fill))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    log.replay(account, account_id=account_id)
    assert account.state.cash == Decimal("999")
    with pytest.raises(ValueError):
        log.append(AccountingEvent(3, EntityId.new("accounting_event"), fill))
