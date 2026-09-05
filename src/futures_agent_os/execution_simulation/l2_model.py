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
        for value in (self.bid_price, self.ask_price, self.bid_quantity, self.ask_quantity):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("book values must be positive finite decimals")
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
        event = events[0]
        price = event.ask_price if order.direction is TradeDirection.LONG else event.bid_price
        if order_type is FillOrderType.LIMIT:
            limit = getattr(order, "limit_price", None)
            if limit is not None and (
                (order.direction is TradeDirection.LONG and price > limit)
                or (order.direction is TradeDirection.SHORT and price < limit)
            ):
                return FillDecision(False, Decimal("0"), None, "NOT_MARKETABLE")
        quantity = min(
            order.quantity - order.filled_quantity,
            event.ask_quantity if order.direction is TradeDirection.LONG else event.bid_quantity,
        )
        return FillDecision(
            True, quantity, price, "FILLED" if quantity == order.quantity - order.filled_quantity else "PARTIAL_FILL"
        )
