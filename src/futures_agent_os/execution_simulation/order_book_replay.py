"""Deterministic level-2 order-book consumption for paper research."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self):
        if not self.price.is_finite() or self.price <= 0 or not self.quantity.is_finite() or self.quantity < 0:
            raise ValueError("invalid book level")

class BookSide(StrEnum):
    BID = "BID"
    ASK = "ASK"

@dataclass(frozen=True, slots=True)
class BookUpdate:
    sequence: int
    side: BookSide
    price: Decimal
    quantity: Decimal
    queue_ahead: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.sequence < 1 or not isinstance(self.side, BookSide) or not self.price.is_finite() or self.price <= 0 or not self.quantity.is_finite() or self.quantity < 0 or not self.queue_ahead.is_finite() or self.queue_ahead < 0:
            raise ValueError("invalid book update")


@dataclass(frozen=True, slots=True)
class BookFill:
    quantity: Decimal
    notional: Decimal
    remaining: Decimal
    impact: Decimal
    consumed_depth: Decimal = Decimal("0")


def consume(levels: tuple[BookLevel, ...], requested: Decimal, reference_price: Decimal) -> BookFill:
    if (
        not levels
        or not requested.is_finite()
        or requested <= 0
        or not reference_price.is_finite()
        or reference_price <= 0
    ):
        raise ValueError("invalid consumption request")
    remaining = requested
    notional = Decimal("0")
    for level in levels:
        take = min(remaining, level.quantity)
        notional += take * level.price
        remaining -= take
        if remaining == 0:
            break
    filled = requested - remaining
    average = notional / filled if filled else reference_price
    return BookFill(filled, notional, remaining, average - reference_price, filled)

def replay(updates: tuple[BookUpdate, ...], requested: Decimal, reference_price: Decimal, *, side: BookSide) -> BookFill:
    if not updates or any(updates[i].sequence >= updates[i + 1].sequence for i in range(len(updates) - 1)):
        raise ValueError("BOOK_SEQUENCE_ORDER")
    if any(updates[i + 1].sequence != updates[i].sequence + 1 for i in range(len(updates) - 1)):
        raise ValueError("BOOK_SEQUENCE_GAP")
    eligible = tuple(BookLevel(u.price, max(Decimal("0"), u.quantity - u.queue_ahead)) for u in updates if u.side is side)
    return consume(eligible, requested, reference_price)
