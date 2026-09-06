"""Deterministic event-driven L2 liquidity model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from .fill_model import FillDecision, FillOrderType


@dataclass(frozen=True, slots=True)
class BookEvent:
    sequence: int
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("sequence must be positive")
        for value in (self.bid_price, self.ask_price):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("book prices must be positive finite decimals")
        for value in (self.bid_quantity, self.ask_quantity):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("book quantities must be non-negative finite decimals")
        if self.bid_price >= self.ask_price:
            raise ValueError("crossed book")


class L2EventFillModel:
    def simulate(
        self, order: Order, events: tuple[BookEvent, ...], *, order_type: FillOrderType = FillOrderType.MARKET
    ) -> FillDecision:
        if order.status not in {OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("fill simulation requires a working order")
        if not events:
            return FillDecision(False, Decimal("0"), None, "NO_BOOK_EVENTS")
        if any(events[i].sequence >= events[i + 1].sequence for i in range(len(events) - 1)):
            raise ValueError("book events must be strictly ordered")
        if any(events[i + 1].sequence != events[i].sequence + 1 for i in range(len(events) - 1)):
            raise ValueError("book events contain a sequence gap")
        if order_type is FillOrderType.LIMIT and order.limit_price is None:
            return FillDecision(False, Decimal("0"), None, "INVALID_LIMIT")
        remaining = order.quantity - order.filled_quantity
        total = Decimal("0")
        last_price: Decimal | None = None
        # ``triggered`` records the order condition, independent of whether
        # available depth can fill the requested quantity.  This distinction
        # is essential for stop orders: a stop may trigger and then partially
        # fill or find no liquidity.
        triggered = order_type is FillOrderType.MARKET
        for event in events:
            price = event.ask_price if order.direction is TradeDirection.LONG else event.bid_price
            available = event.ask_quantity if order.direction is TradeDirection.LONG else event.bid_quantity
            if order_type is FillOrderType.STOP:
                if order.stop_price is None:
                    return FillDecision(False, Decimal("0"), None, "INVALID_STOP")
                crossed = (
                    price >= order.stop_price if order.direction is TradeDirection.LONG else price <= order.stop_price
                )
                if not triggered:
                    if not crossed:
                        continue
                    triggered = True
            if order_type is FillOrderType.LIMIT:
                assert order.limit_price is not None
                crossed = (
                    price <= order.limit_price if order.direction is TradeDirection.LONG else price >= order.limit_price
                )
                if not crossed:
                    continue
                triggered = True
            taken = min(remaining - total, available)
            if taken > 0:
                total += taken
                last_price = price
            if total == remaining:
                break
        if total <= 0:
            return FillDecision(triggered, Decimal("0"), None, "NO_LIQUIDITY" if triggered else "NOT_TRIGGERED")
        return FillDecision(triggered, total, last_price, "FILLED" if total == remaining else "PARTIAL_FILL")
