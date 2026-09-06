"""Deterministic L1 fill simulation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.decision import Order, OrderStatus, TradeDirection


class FillOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class IntrabarAmbiguityPolicy(StrEnum):
    """Declared deterministic policy when one OHLC bar hits both exits."""

    STOP_FIRST = "STOP_FIRST"


@dataclass(frozen=True, slots=True)
class L1Bar:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    available_quantity: Decimal
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            for value in (self.open, self.high, self.low, self.close)
        ):
            raise ValueError("bar prices must be positive finite decimals")
        if (
            self.low > self.high
            or not (self.low <= self.open <= self.high)
            or not (self.low <= self.close <= self.high)
        ):
            raise ValueError("bar OHLC values are inconsistent")
        if (
            not isinstance(self.available_quantity, Decimal)
            or not self.available_quantity.is_finite()
            or self.available_quantity < 0
        ):
            raise ValueError("available quantity must be non-negative")
        for value in (self.limit_up, self.limit_down):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value <= 0):
                raise ValueError("price limits must be positive when provided")


@dataclass(frozen=True, slots=True)
class FillDecision:
    triggered: bool
    filled_quantity: Decimal
    price: Decimal | None
    reason: str


class L1FillModel:
    def __init__(self, slippage: Decimal = Decimal("0")) -> None:
        if not isinstance(slippage, Decimal) or not slippage.is_finite() or slippage < 0:
            raise ValueError("slippage must be a non-negative finite Decimal")
        self.slippage = slippage

    @staticmethod
    def _crossed(
        order: Order, order_type: FillOrderType, price: Decimal, trigger: Decimal | None, limit: Decimal | None
    ) -> bool:
        if order_type is FillOrderType.MARKET:
            return True
        if order_type is FillOrderType.STOP:
            return trigger is not None and (
                price >= trigger if order.direction is TradeDirection.LONG else price <= trigger
            )
        if limit is None:
            return False
        return price <= limit if order.direction is TradeDirection.LONG else price >= limit

    def simulate(
        self,
        order: Order,
        bar: L1Bar,
        *,
        order_type: FillOrderType,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> FillDecision:
        if order.status not in {OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("fill simulation requires a working order")
        if not isinstance(order_type, FillOrderType):
            raise TypeError("order_type must be typed")
        if order_type is FillOrderType.STOP:
            if stop_price is None:
                return FillDecision(False, Decimal("0"), None, "INVALID_STOP")
            # A stop is triggered by the intrabar extreme, then executes at
            # the stop (or the opening gap, whichever is worse), never at the
            # extreme itself.  This keeps trigger and fill as separate facts.
            triggered = bar.high >= stop_price if order.direction is TradeDirection.LONG else bar.low <= stop_price
            trigger_price = (
                max(bar.open, stop_price) if order.direction is TradeDirection.LONG else min(bar.open, stop_price)
            )
        elif order_type is FillOrderType.LIMIT:
            if limit_price is None:
                return FillDecision(False, Decimal("0"), None, "INVALID_LIMIT")
            triggered = bar.low <= limit_price if order.direction is TradeDirection.LONG else bar.high >= limit_price
            trigger_price = (
                min(bar.open, limit_price) if order.direction is TradeDirection.LONG else max(bar.open, limit_price)
            )
        else:
            triggered = True
            trigger_price = bar.open
        if not triggered or not self._crossed(order, order_type, trigger_price, stop_price, limit_price):
            return FillDecision(False, Decimal("0"), None, "NOT_TRIGGERED")
        if bar.available_quantity <= 0:
            return FillDecision(True, Decimal("0"), None, "NO_LIQUIDITY")
        remaining = order.quantity - order.filled_quantity
        quantity = min(remaining, bar.available_quantity)
        price = (
            trigger_price + self.slippage if order.direction is TradeDirection.LONG else trigger_price - self.slippage
        )
        if bar.limit_up is not None and price >= bar.limit_up and order.direction is TradeDirection.LONG:
            return FillDecision(True, Decimal("0"), None, "LIMIT_UP_NO_MATCH")
        if bar.limit_down is not None and price <= bar.limit_down and order.direction is TradeDirection.SHORT:
            return FillDecision(True, Decimal("0"), None, "LIMIT_DOWN_NO_MATCH")
        return FillDecision(True, quantity, price, "FILLED" if quantity == remaining else "PARTIAL_FILL")

    def simulate_bracket(
        self,
        order: Order,
        bar: L1Bar,
        *,
        take_profit_price: Decimal,
        stop_price: Decimal,
        policy: IntrabarAmbiguityPolicy = IntrabarAmbiguityPolicy.STOP_FIRST,
    ) -> FillDecision:
        """Resolve a bracket exit with an explicit conservative same-bar rule.

        If both levels are touched, STOP_FIRST assumes the adverse path.  This
        prevents optimistic backtest fills when OHLC data lacks intrabar order.
        """
        if not isinstance(policy, IntrabarAmbiguityPolicy):
            raise TypeError("policy must be an IntrabarAmbiguityPolicy")
        for value, label in ((take_profit_price, "take_profit_price"), (stop_price, "stop_price")):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{label} must be positive")
        if order.direction is TradeDirection.LONG:
            hit_stop, hit_target = bar.low <= stop_price, bar.high >= take_profit_price
        else:
            hit_stop, hit_target = bar.high >= stop_price, bar.low <= take_profit_price
        if not hit_stop and not hit_target:
            return FillDecision(False, Decimal("0"), None, "NOT_TRIGGERED")
        chosen = stop_price if hit_stop else take_profit_price
        return self.simulate(order, bar, order_type=FillOrderType.LIMIT, limit_price=chosen)
