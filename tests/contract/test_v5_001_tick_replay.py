from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from futures_agent_os.execution_simulation.l3_tick_replay import Tick, TickKind, TickReplay


def _tick(sequence: int, seconds: int = 0) -> Tick:
    return Tick(sequence, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds), TickKind.TRADE, Decimal("100"), Decimal("1"))


def test_replay_is_deterministic_and_preserves_sequence() -> None:
    ticks = (_tick(1), _tick(2, 1))
    assert TickReplay(ticks).run() == ticks
    assert TickReplay(ticks).run() == TickReplay(ticks).run()


@pytest.mark.parametrize("ticks,error", [((_tick(2), _tick(1, 1)), "OUT_OF_ORDER_SEQUENCE"), ((_tick(1, 1), _tick(2, 0)), "CLOCK_REGRESSION")])
def test_replay_rejects_invalid_order(ticks, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        TickReplay(ticks)


def test_replay_rejects_clock_gap() -> None:
    with pytest.raises(ValueError, match="CLOCK_GAP"):
        TickReplay((_tick(1), _tick(2, 10)), max_clock_step_seconds=Decimal("5"))
