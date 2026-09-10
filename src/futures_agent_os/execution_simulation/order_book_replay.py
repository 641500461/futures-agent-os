"""Deterministic level-2 order-book consumption for paper research."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self):
        if not self.price.is_finite() or self.price <= 0 or not self.quantity.is_finite() or self.quantity < 0:
            raise ValueError("invalid book level")


@dataclass(frozen=True, slots=True)
class BookFill:
    quantity: Decimal
    notional: Decimal
    remaining: Decimal
    impact: Decimal


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
    return BookFill(filled, notional, remaining, average - reference_price)
