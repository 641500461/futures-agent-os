import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation.order_book_replay import (
    BookEventKind,
    BookLevel,
    BookSide,
    BookSnapshot,
    BookUpdate,
    L4ReplayStatus,
    L4BookEvent,
    OrderBookReplay,
    consume,
    replay,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


TRUTH_SAMPLE = Path(__file__).parents[1] / "fixtures" / "v5_002_order_book_truth.json"


def _order(quantity: str, *, direction: TradeDirection = TradeDirection.LONG, limit: str | None = None) -> Order:
    return Order(
        EntityId.deterministic("order", f"v5-002:{quantity}:{direction}:{limit}"),
        EntityId.deterministic("execution_plan", "v5-002"),
        "SHFE:AG",
        direction,
        Decimal(quantity),
        OrderStatus.WORKING,
        limit_price=None if limit is None else Decimal(limit),
        created_at=RecordedAt.parse("2026-01-01T00:00:00Z"),
    )


def _truth_replay() -> tuple[OrderBookReplay, dict[str, object]]:
    payload = json.loads(TRUTH_SAMPLE.read_text())
    snapshot_payload = payload["snapshot"]
    snapshot = BookSnapshot(
        snapshot_payload["sequence"],
        RecordedAt.parse(snapshot_payload["recorded_at"]),
        tuple(BookLevel(Decimal(price), Decimal(quantity)) for price, quantity in snapshot_payload["bids"]),
        tuple(BookLevel(Decimal(price), Decimal(quantity)) for price, quantity in snapshot_payload["asks"]),
        payload["sample_ref"],
    )
    events = tuple(
        L4BookEvent(
            event["sequence"],
            RecordedAt.parse(event["recorded_at"]),
            BookEventKind(event["kind"]),
            BookSide(event["side"]),
            Decimal(event["price"]),
            Decimal(event["quantity"]),
        )
        for event in payload["events"]
    )
    return OrderBookReplay(snapshot, events), payload


def test_depth_consumption_partial_and_impact() -> None:
    result = consume(
        (BookLevel(Decimal("101"), Decimal("2")), BookLevel(Decimal("102"), Decimal("1"))),
        Decimal("4"),
        Decimal("100"),
    )
    assert result.quantity == result.consumed_depth == Decimal("3")
    assert result.remaining == Decimal("1") and result.notional == Decimal("304")
    assert all(item.available_before == item.quantity + item.available_after for item in result.levels)


def test_legacy_queue_ahead_and_sequence_gap_remain_fail_closed() -> None:
    result = replay(
        (
            BookUpdate(1, BookSide.ASK, Decimal("101"), Decimal("3"), Decimal("1")),
            BookUpdate(2, BookSide.ASK, Decimal("102"), Decimal("2")),
        ),
        Decimal("3"),
        Decimal("100"),
        side=BookSide.ASK,
    )
    assert result.quantity == result.consumed_depth == Decimal("3")
    with pytest.raises(ValueError, match="BOOK_SEQUENCE_GAP"):
        replay(
            (
                BookUpdate(1, BookSide.ASK, Decimal("101"), Decimal("1")),
                BookUpdate(3, BookSide.ASK, Decimal("102"), Decimal("1")),
            ),
            Decimal("1"),
            Decimal("100"),
            side=BookSide.ASK,
        )


def test_aggressive_order_walks_depth_with_partial_fill_and_market_impact() -> None:
    venue, _ = _truth_replay()
    first = venue.execute_aggressive(_order("4"))
    second = venue.execute_aggressive(_order("4"))
    assert first.status is L4ReplayStatus.PARTIAL and first.reason == "PARTIAL_FILL"
    assert first.order.status is OrderStatus.PARTIALLY_FILLED
    assert [fill.quantity for fill in first.fills] == [Decimal("1"), Decimal("2")]
    assert [fill.price for fill in first.fills] == [Decimal("101"), Decimal("102")]
    assert first.consumed_liquidity == first.available_liquidity == Decimal("3")
    assert first.remaining_quantity == Decimal("1") and first.impact > 0 and first.impact_bps > 0
    assert sum((item.quantity for item in first.depth_transitions), Decimal("0")) <= first.available_liquidity
    assert first.replay_digest == second.replay_digest
    assert tuple(fill.fill_id for fill in first.fills) == tuple(fill.fill_id for fill in second.fills)


def test_aggressive_sell_consumes_best_bids_first_with_adverse_impact() -> None:
    venue, _ = _truth_replay()
    result = venue.execute_aggressive(_order("4", direction=TradeDirection.SHORT))
    assert [fill.price for fill in result.fills] == [Decimal("99"), Decimal("98")]
    assert [fill.quantity for fill in result.fills] == [Decimal("2"), Decimal("2")]
    assert result.status is L4ReplayStatus.FILLED and result.impact > 0


def test_truth_sample_validates_queue_position_and_partial_fill() -> None:
    venue, sample = _truth_replay()
    expected = sample["expected_resting"]
    result = venue.execute_resting(_order(expected["order_quantity"], limit=expected["limit_price"]))
    assert result.truth_sample_ref == sample["sample_ref"]
    assert result.status.value == expected["status"] and result.reason == "PARTIAL_FILL"
    assert result.order.status is OrderStatus.PARTIALLY_FILLED
    assert [str(fill.quantity) for fill in result.fills] == expected["fill_quantities"]
    assert str(result.remaining_quantity) == expected["remaining_quantity"]
    assert [str(item.ahead_after) for item in result.queue_transitions] == expected["queue_ahead_after"]
    for item in result.queue_transitions:
        assert item.trade_quantity == (item.ahead_consumed + item.fill_quantity + item.behind_consumed + item.unmatched)
        assert item.ahead_before == item.ahead_consumed + item.ahead_after
    assert result.consumed_liquidity == sum((fill.quantity for fill in result.fills), Decimal("0"))
    assert result.consumed_liquidity <= result.available_liquidity


def test_depth_reduction_removes_queue_behind_before_queue_ahead() -> None:
    venue, _ = _truth_replay()
    result = venue.execute_resting(_order("4", limit="99"))
    # The first SET_DEPTH addition joins behind; later replay never promotes it ahead.
    assert result.queue_transitions[0].ahead_before == Decimal("2")
    assert result.queue_transitions[1].ahead_before == Decimal("1")


def test_sequence_clock_and_snapshot_shape_are_rejected_explicitly() -> None:
    venue, _ = _truth_replay()
    snapshot = venue.snapshot
    with pytest.raises(ValueError, match="BOOK_SEQUENCE_GAP"):
        OrderBookReplay(
            snapshot,
            (
                L4BookEvent(
                    snapshot.sequence + 2,
                    snapshot.recorded_at,
                    BookEventKind.TRADE,
                    BookSide.BID,
                    Decimal("99"),
                    Decimal("1"),
                ),
            ),
        )
    with pytest.raises(ValueError, match="BOOK_CLOCK_REGRESSION"):
        OrderBookReplay(
            snapshot,
            (
                L4BookEvent(
                    snapshot.sequence + 1,
                    RecordedAt.from_datetime(snapshot.recorded_at.value - timedelta(seconds=1)),
                    BookEventKind.TRADE,
                    BookSide.BID,
                    Decimal("99"),
                    Decimal("1"),
                ),
            ),
        )
    with pytest.raises(ValueError, match="price-priority"):
        BookSnapshot(
            1,
            snapshot.recorded_at,
            (BookLevel(Decimal("98"), Decimal("1")), BookLevel(Decimal("99"), Decimal("1"))),
            (),
            "truth:bad",
        )


def test_result_and_inputs_are_immutable_and_identify_l4_model() -> None:
    venue, _ = _truth_replay()
    result = venue.execute_aggressive(_order("1"))
    assert venue.config.fidelity == "L4_ORDER_BOOK"
    assert result.fills[0].source_ref.startswith("l4:l4-price-time-v1:truth:")
    with pytest.raises(AttributeError):
        result.remaining_quantity = Decimal("0")  # type: ignore[misc]
