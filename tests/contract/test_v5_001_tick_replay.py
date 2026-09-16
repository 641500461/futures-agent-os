from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import Fill, FillOrderType, OrderCommandProcessor
from futures_agent_os.execution_simulation.l3_tick_replay import (
    CalibratedSlippage,
    ReplayAnomalyCode,
    ReplayStatus,
    SlippageStatistic,
    Tick,
    TickKind,
    TickReplay,
    TickReplayConfig,
    TickReplayError,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def _tick(sequence: int, seconds: int = 0) -> Tick:
    return Tick(
        sequence,
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds),
        TickKind.TRADE,
        Decimal("100"),
        Decimal("1"),
    )


def _order(
    *,
    direction: TradeDirection = TradeDirection.LONG,
    quantity: str = "1",
    created: str = "2026-01-01T00:00:00Z",
    limit: str | None = None,
    stop: str | None = None,
) -> Order:
    return Order(
        EntityId.deterministic("order", f"v5-001:{direction}:{quantity}:{created}:{limit}:{stop}"),
        EntityId.deterministic("execution_plan", "v5-001"),
        "SHFE:AG",
        direction,
        Decimal(quantity),
        OrderStatus.WORKING,
        limit_price=None if limit is None else Decimal(limit),
        stop_price=None if stop is None else Decimal(stop),
        created_at=RecordedAt.parse(created),
    )


def _quote(sequence: int, seconds: int, *, bid: str = "99", ask: str = "101", quantity: str = "1") -> Tick:
    return Tick(
        sequence,
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds),
        TickKind.QUOTE,
        Decimal(ask),
        Decimal(quantity),
        Decimal(bid),
        Decimal(ask),
    )


def test_replay_is_deterministic_and_preserves_sequence() -> None:
    ticks = (_tick(1), _tick(2, 1))
    assert TickReplay(ticks).run() == ticks
    assert TickReplay(ticks).run() == TickReplay(ticks).run()


@pytest.mark.parametrize(
    "ticks,error",
    [((_tick(2), _tick(1, 1)), "OUT_OF_ORDER_SEQUENCE"), ((_tick(1, 1), _tick(2, 0)), "CLOCK_REGRESSION")],
)
def test_replay_rejects_invalid_order(ticks, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        TickReplay(ticks)


def test_replay_rejects_clock_gap() -> None:
    with pytest.raises(ValueError, match="CLOCK_GAP"):
        TickReplay((_tick(1), _tick(2, 10)), max_clock_step_seconds=Decimal("5"))


def test_market_replay_emits_canonical_partial_fills_and_is_reproducible() -> None:
    ticks = (_quote(1, 1, quantity="1"), _quote(2, 2, ask="102", quantity="2"))
    config = TickReplayConfig(
        slippage=CalibratedSlippage(100, Decimal("10"), Decimal("15"), "SHFE:AG"),
        slippage_statistic=SlippageStatistic.MEAN,
    )
    first = TickReplay(ticks, config).replay(_order(quantity="3"))
    second = TickReplay(ticks, config).replay(_order(quantity="3"))
    assert first.status is ReplayStatus.COMPLETED
    assert first.order.status is OrderStatus.FILLED
    assert [fill.quantity for fill in first.fills] == [Decimal("1"), Decimal("2")]
    assert [fill.price for fill in first.fills] == [Decimal("101.101"), Decimal("102.102")]
    assert all(isinstance(fill, Fill) for fill in first.fills)
    assert all(fill.order_id == first.order.order_id for fill in first.fills)
    assert first.replay_digest == second.replay_digest
    assert tuple(fill.fill_id for fill in first.fills) == tuple(fill.fill_id for fill in second.fills)


def test_replay_fills_apply_through_existing_order_processor() -> None:
    order = _order(quantity="2")
    result = TickReplay((_quote(1, 1, quantity="1"), _quote(2, 2, quantity="1"))).replay(order)
    processor = OrderCommandProcessor()
    processor.register(order)
    for index, fill in enumerate(result.fills, start=1):
        applied = processor.apply_fill(f"l3-fill-{index}", str(order.order_id), fill.quantity, event_sequence=index)
        assert applied.accepted
    assert processor.get(str(order.order_id)) == result.order


def test_latency_skips_early_quote_and_limit_trade_uses_print_volume() -> None:
    config = TickReplayConfig(latency_ms=Decimal("1500"))
    ticks = (_quote(1, 1, quantity="9"), _tick(2, 2))
    result = TickReplay(ticks, config).replay(_order(quantity="2", limit="100"), order_type=FillOrderType.LIMIT)
    assert result.status is ReplayStatus.PARTIAL
    assert len(result.fills) == 1
    assert result.fills[0].quantity == Decimal("1")
    assert result.reason == "PARTIAL_FILL" and result.triggered is True


def test_stop_trigger_is_separate_from_quote_fill() -> None:
    ticks = (
        _tick(1, 1),
        Tick(2, datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc), TickKind.TRADE, Decimal("105"), Decimal("1")),
        _quote(3, 3, quantity="1"),
    )
    result = TickReplay(ticks).replay(_order(stop="104"), order_type=FillOrderType.STOP)
    assert result.triggered is True and result.trigger_sequence == 2
    assert result.status is ReplayStatus.COMPLETED and len(result.fills) == 1


def test_sequence_gap_reports_machine_readable_anomaly() -> None:
    with pytest.raises(TickReplayError) as error:
        TickReplay((_tick(1), _tick(3, 1)))
    assert error.value.anomaly.code is ReplayAnomalyCode.SEQUENCE_GAP


def test_first_gap_and_clock_regression_are_distinct_anomalies() -> None:
    with pytest.raises(TickReplayError) as first:
        TickReplay((_tick(2),), TickReplayConfig(expected_first_sequence=1))
    assert first.value.anomaly.code is ReplayAnomalyCode.FIRST_SEQUENCE_GAP
    with pytest.raises(TickReplayError) as clock:
        TickReplay((_tick(1, 2), _tick(2, 1)))
    assert clock.value.anomaly.code is ReplayAnomalyCode.CLOCK_REGRESSION


def test_limit_caps_adverse_slippage_and_calibration_scope_is_enforced() -> None:
    calibrated = CalibratedSlippage(50, Decimal("100"), Decimal("200"), "SHFE:AG")
    config = TickReplayConfig(slippage=calibrated, slippage_statistic=SlippageStatistic.P95)
    fill = TickReplay((_quote(1, 1, ask="100", quantity="1"),), config).replay(
        _order(limit="100"), order_type=FillOrderType.LIMIT
    )
    assert fill.status is ReplayStatus.COMPLETED and fill.fills[0].price == Decimal("100")
    mismatch = TickReplay(
        (_quote(1, 1),),
        TickReplayConfig(slippage=CalibratedSlippage(50, Decimal("1"), Decimal("2"), "DCE:I")),
    ).replay(_order())
    assert mismatch.status is ReplayStatus.REJECTED and mismatch.reason == "CALIBRATION_SCOPE_MISMATCH"


def test_config_and_input_sequence_are_immutable() -> None:
    ticks = [_quote(1, 1)]
    replay = TickReplay(ticks)
    ticks.append(_quote(2, 2))
    assert len(replay.ticks) == 1
    with pytest.raises(AttributeError):
        replay.config.latency_ms = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("order_type", "reason"),
    ((FillOrderType.LIMIT, "INVALID_LIMIT"), (FillOrderType.STOP, "INVALID_STOP")),
)
def test_price_constrained_orders_fail_closed_without_required_price(order_type: FillOrderType, reason: str) -> None:
    result = TickReplay((_quote(1, 1),)).replay(_order(), order_type=order_type)
    assert result.status is ReplayStatus.REJECTED and result.reason == reason
