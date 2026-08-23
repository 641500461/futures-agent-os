"""Property checks for explicit, half-open calendar occurrence semantics."""

from datetime import timedelta

from hypothesis import given, strategies as st

from futures_agent_os.reference_market_data import (
    Exchange,
    SessionPhase,
    TradingDateService,
    Variety,
    initial_acceptance_trading_calendar,
)
from futures_agent_os.shared_kernel import Failure, RecordedAt, ShanghaiTimestamp, TradingDate


def _market_time(minutes_after_start: int) -> ShanghaiTimestamp:
    start = ShanghaiTimestamp.from_iso("2026-08-24T21:00:00+08:00")
    return ShanghaiTimestamp.from_datetime(start.value + timedelta(minutes=minutes_after_start))


def _shfe_ag() -> Variety:
    return Variety(Exchange.SHFE, "AG", "synthetic silver")


@given(minutes_after_start=st.integers(min_value=0, max_value=329))
def test_every_explicit_shfe_night_minute_maps_to_its_declared_next_trading_date(minutes_after_start: int) -> None:
    outcome = TradingDateService(initial_acceptance_trading_calendar()).resolve(
        _shfe_ag(), _market_time(minutes_after_start), RecordedAt.parse("2026-08-02T00:00:00Z")
    )
    assert not isinstance(outcome, Failure)
    assert outcome.trading_date == TradingDate.parse("2026-08-25")
    assert outcome.phase is SessionPhase.CONTINUOUS


@given(minutes_after_start=st.integers(min_value=330, max_value=714))
def test_after_explicit_night_end_never_silently_reuses_that_trading_date(minutes_after_start: int) -> None:
    outcome = TradingDateService(initial_acceptance_trading_calendar()).resolve(
        _shfe_ag(), _market_time(minutes_after_start), RecordedAt.parse("2026-08-02T00:00:00Z")
    )
    assert isinstance(outcome, Failure)
