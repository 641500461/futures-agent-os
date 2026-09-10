from decimal import Decimal

from hypothesis import given, strategies as st

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation.order_book_replay import (
    BookEventKind,
    BookLevel,
    BookSide,
    BookSnapshot,
    L4BookEvent,
    OrderBookReplay,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


AT = RecordedAt.parse("2026-01-01T00:00:00Z")


def _order(quantity: int, *, limit: Decimal | None = None) -> Order:
    return Order(
        EntityId.deterministic("order", f"v5-002-property:{quantity}:{limit}"),
        EntityId.deterministic("execution_plan", "v5-002-property"),
        "SHFE:AG",
        TradeDirection.LONG,
        Decimal(quantity),
        OrderStatus.WORKING,
        limit_price=limit,
        created_at=AT,
    )


@given(first=st.integers(0, 20), second=st.integers(0, 20), requested=st.integers(1, 40))
def test_aggressive_fill_never_exceeds_depth(first: int, second: int, requested: int) -> None:
    venue = OrderBookReplay(
        BookSnapshot(
            0,
            AT,
            (BookLevel(Decimal("99"), Decimal("1")),),
            (
                BookLevel(Decimal("101"), Decimal(first)),
                BookLevel(Decimal("102"), Decimal(second)),
            ),
            "truth:v5-002:property-depth",
        )
    )
    result = venue.execute_aggressive(_order(requested))
    expected = min(Decimal(requested), Decimal(first + second))
    assert result.consumed_liquidity == expected
    assert result.consumed_liquidity <= result.available_liquidity
    assert result.remaining_quantity + result.consumed_liquidity == Decimal(requested)
    assert sum((fill.quantity for fill in result.fills), Decimal("0")) == result.consumed_liquidity
    assert all(item.available_before == item.quantity + item.available_after for item in result.depth_transitions)


@given(ahead=st.integers(0, 20), requested=st.integers(1, 20), traded=st.integers(0, 50))
def test_resting_fill_obeys_queue_and_trade_conservation(ahead: int, requested: int, traded: int) -> None:
    snapshot = BookSnapshot(
        0,
        AT,
        (BookLevel(Decimal("99"), Decimal(ahead)),),
        (BookLevel(Decimal("101"), Decimal("1")),),
        "truth:v5-002:property-queue",
    )
    event = L4BookEvent(1, AT, BookEventKind.TRADE, BookSide.BID, Decimal("99"), Decimal(traded))
    result = OrderBookReplay(snapshot, (event,)).execute_resting(_order(requested, limit=Decimal("99")))
    expected = min(Decimal(requested), max(Decimal("0"), Decimal(traded - ahead)))
    transition = result.queue_transitions[0]
    assert result.consumed_liquidity == expected
    assert transition.trade_quantity == (
        transition.ahead_consumed + transition.fill_quantity + transition.behind_consumed + transition.unmatched
    )
    assert transition.ahead_before == transition.ahead_consumed + transition.ahead_after
