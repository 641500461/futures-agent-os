"""Deterministic L3 quote/trade tick replay primitives."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class TickKind(StrEnum):
    QUOTE = "QUOTE"
    TRADE = "TRADE"


@dataclass(frozen=True, slots=True)
class Tick:
    sequence: int
    timestamp: datetime
    kind: TickKind
    price: Decimal
    quantity: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0 or not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("tick sequence and timezone-aware timestamp are required")
        if not isinstance(self.kind, TickKind) or not all(isinstance(x, Decimal) and x.is_finite() and x > 0 for x in (self.price, self.quantity)):
            raise ValueError("tick price and quantity must be positive finite decimals")
        for value in (self.bid, self.ask):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value <= 0):
                raise ValueError("quote prices must be positive finite decimals")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")


class TickReplay:
    """Replay ticks with explicit rejection of disorder, gaps, and clock faults."""
    def __init__(self, ticks: tuple[Tick, ...] | list[Tick], *, max_clock_step_seconds: Decimal | None = None) -> None:
        self.ticks = tuple(ticks)
        self.max_clock_step_seconds = max_clock_step_seconds
        if max_clock_step_seconds is not None and (not max_clock_step_seconds.is_finite() or max_clock_step_seconds <= 0):
            raise ValueError("max_clock_step_seconds must be positive")
        previous = None
        for tick in self.ticks:
            if previous is not None:
                if tick.sequence <= previous.sequence:
                    raise ValueError("OUT_OF_ORDER_SEQUENCE")
                if tick.timestamp < previous.timestamp:
                    raise ValueError("CLOCK_REGRESSION")
                if max_clock_step_seconds is not None and Decimal(str((tick.timestamp - previous.timestamp).total_seconds())) > max_clock_step_seconds:
                    raise ValueError("CLOCK_GAP")
            previous = tick

    def run(self):
        return tuple(self.ticks)


@dataclass(frozen=True, slots=True)
class CalibratedSlippage:
    ticks: int
    mean_bps: Decimal
    p95_bps: Decimal
    scope: str

    def __post_init__(self) -> None:
        if self.ticks <= 0 or not self.scope or any(not isinstance(x, Decimal) or not x.is_finite() or x < 0 for x in (self.mean_bps, self.p95_bps)):
            raise ValueError("invalid calibration")
