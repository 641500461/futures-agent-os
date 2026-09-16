"""Deterministic L3 quote/trade replay and canonical fill production.

L3 is a time ordered stream of quote snapshots and trade prints. Quote
snapshots supply displayed liquidity for aggressive orders; trade prints supply
executed volume against resting limits and the last-trade trigger for stops.
The resulting fills use the existing V2 Order/Fill contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast, overload

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

from .contracts import Fill
from .fill_model import FillOrderType


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _timestamp_text(value: datetime) -> str:
    return RecordedAt.from_datetime(value).to_dict()["recorded_at"]


class TickKind(StrEnum):
    QUOTE = "QUOTE"
    TRADE = "TRADE"


class ReplayAnomalyCode(StrEnum):
    OUT_OF_ORDER_SEQUENCE = "OUT_OF_ORDER_SEQUENCE"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    CLOCK_REGRESSION = "CLOCK_REGRESSION"
    CLOCK_GAP = "CLOCK_GAP"
    FIRST_SEQUENCE_GAP = "FIRST_SEQUENCE_GAP"


@dataclass(frozen=True, slots=True)
class ReplayAnomaly:
    code: ReplayAnomalyCode
    sequence: int
    previous_sequence: int | None = None


class TickReplayError(ValueError):
    """A deterministic data-quality failure with a machine-readable code."""

    def __init__(self, anomaly: ReplayAnomaly) -> None:
        self.anomaly = anomaly
        super().__init__(anomaly.code.value)


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
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("tick sequence must be a positive integer")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("tick timestamp must be timezone-aware")
        if not isinstance(self.kind, TickKind):
            raise TypeError("tick kind must be TickKind")
        if not isinstance(self.price, Decimal) or not self.price.is_finite() or self.price <= 0:
            raise ValueError("tick price must be positive finite Decimal")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity < 0:
            raise ValueError("tick quantity must be finite and non-negative")
        if self.kind is TickKind.QUOTE and (self.bid is None or self.ask is None):
            raise ValueError("QUOTE ticks require bid and ask")
        for value in (self.bid, self.ask):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value <= 0):
                raise ValueError("quote prices must be positive finite decimals")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")

    def payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "timestamp": _timestamp_text(self.timestamp),
            "kind": self.kind.value,
            "price": _decimal_text(self.price),
            "quantity": _decimal_text(self.quantity),
            "bid": None if self.bid is None else _decimal_text(self.bid),
            "ask": None if self.ask is None else _decimal_text(self.ask),
        }


@dataclass(frozen=True, slots=True)
class CalibratedSlippage:
    """Immutable calibration snapshot used by one replay configuration."""

    ticks: int
    mean_bps: Decimal
    p95_bps: Decimal
    scope: str

    def __post_init__(self) -> None:
        if isinstance(self.ticks, bool) or not isinstance(self.ticks, int) or self.ticks <= 0:
            raise ValueError("calibration ticks must be positive")
        if (
            any(not isinstance(x, Decimal) or not x.is_finite() or x < 0 for x in (self.mean_bps, self.p95_bps))
            or self.p95_bps < self.mean_bps
            or self.p95_bps >= Decimal("10000")
        ):
            raise ValueError("invalid calibration bps")
        if (
            not isinstance(self.scope, str)
            or not self.scope
            or self.scope != self.scope.strip()
            or any(char.isspace() for char in self.scope)
        ):
            raise ValueError("calibration scope must be canonical text")

    def payload(self) -> dict[str, object]:
        return {
            "ticks": self.ticks,
            "mean_bps": _decimal_text(self.mean_bps),
            "p95_bps": _decimal_text(self.p95_bps),
            "scope": self.scope,
        }


class SlippageStatistic(StrEnum):
    MEAN = "MEAN"
    P95 = "P95"


@dataclass(frozen=True, slots=True)
class TickReplayConfig:
    """All replay-affecting choices, frozen and content-addressable."""

    model_version: str = "l3-tick-replay-v1"
    latency_ms: Decimal = Decimal("0")
    slippage: CalibratedSlippage | None = None
    slippage_statistic: SlippageStatistic = SlippageStatistic.MEAN
    max_clock_step_seconds: Decimal | None = None
    expected_first_sequence: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_version, str)
            or not self.model_version
            or self.model_version != self.model_version.strip()
            or any(char.isspace() for char in self.model_version)
        ):
            raise ValueError("model_version must be canonical text")
        if not isinstance(self.latency_ms, Decimal) or not self.latency_ms.is_finite() or self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative finite Decimal")
        if self.latency_ms * Decimal("1000") != (self.latency_ms * Decimal("1000")).to_integral_value():
            raise ValueError("latency_ms must resolve to whole microseconds")
        if self.slippage is not None and not isinstance(self.slippage, CalibratedSlippage):
            raise TypeError("slippage must be CalibratedSlippage")
        if not isinstance(self.slippage_statistic, SlippageStatistic):
            raise TypeError("slippage_statistic must be SlippageStatistic")
        if self.max_clock_step_seconds is not None and (
            not isinstance(self.max_clock_step_seconds, Decimal)
            or not self.max_clock_step_seconds.is_finite()
            or self.max_clock_step_seconds <= 0
        ):
            raise ValueError("max_clock_step_seconds must be positive")
        if self.expected_first_sequence is not None and (
            isinstance(self.expected_first_sequence, bool)
            or not isinstance(self.expected_first_sequence, int)
            or self.expected_first_sequence < 1
        ):
            raise ValueError("expected_first_sequence must be positive")

    @property
    def digest(self) -> str:
        return canonical_sha256(cast(Any, self.payload()))

    def payload(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "latency_ms": _decimal_text(self.latency_ms),
            "slippage": None if self.slippage is None else self.slippage.payload(),
            "slippage_statistic": self.slippage_statistic.value,
            "max_clock_step_seconds": None
            if self.max_clock_step_seconds is None
            else _decimal_text(self.max_clock_step_seconds),
            "expected_first_sequence": self.expected_first_sequence,
        }

    @property
    def selected_slippage_bps(self) -> Decimal:
        if self.slippage is None:
            return Decimal("0")
        return self.slippage.p95_bps if self.slippage_statistic is SlippageStatistic.P95 else self.slippage.mean_bps


class ReplayStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    UNFILLED = "UNFILLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class TickReplayResult:
    order: Order
    fills: tuple[Fill, ...]
    status: ReplayStatus
    reason: str
    config_digest: str
    replay_digest: str
    triggered: bool = False
    trigger_sequence: int | None = None


class TickReplay:
    """Validate and replay one immutable tick stream."""

    def __init__(
        self,
        ticks: tuple[Tick, ...] | list[Tick],
        config: TickReplayConfig | None = None,
        *,
        max_clock_step_seconds: Decimal | None = None,
    ) -> None:
        if config is not None and not isinstance(config, TickReplayConfig):
            raise TypeError("config must be TickReplayConfig")
        if max_clock_step_seconds is not None:
            if config is not None:
                raise ValueError("max_clock_step_seconds must be supplied in config")
            config = TickReplayConfig(max_clock_step_seconds=max_clock_step_seconds)
        self.config = config or TickReplayConfig()
        self._ticks = tuple(ticks)
        self._validate()

    @property
    def ticks(self) -> tuple[Tick, ...]:
        return self._ticks

    def _validate(self) -> None:
        previous: Tick | None = None
        if self._ticks and self.config.expected_first_sequence is not None:
            if self._ticks[0].sequence != self.config.expected_first_sequence:
                raise TickReplayError(ReplayAnomaly(ReplayAnomalyCode.FIRST_SEQUENCE_GAP, self._ticks[0].sequence))
        for tick in self._ticks:
            if not isinstance(tick, Tick):
                raise TypeError("ticks must contain Tick values")
            if previous is not None:
                if tick.sequence <= previous.sequence:
                    raise TickReplayError(
                        ReplayAnomaly(ReplayAnomalyCode.OUT_OF_ORDER_SEQUENCE, tick.sequence, previous.sequence)
                    )
                if tick.sequence != previous.sequence + 1:
                    raise TickReplayError(
                        ReplayAnomaly(ReplayAnomalyCode.SEQUENCE_GAP, tick.sequence, previous.sequence)
                    )
                if tick.timestamp < previous.timestamp:
                    raise TickReplayError(
                        ReplayAnomaly(ReplayAnomalyCode.CLOCK_REGRESSION, tick.sequence, previous.sequence)
                    )
                if self.config.max_clock_step_seconds is not None:
                    delta = tick.timestamp - previous.timestamp
                    elapsed = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(
                        1_000_000
                    )
                    if elapsed > self.config.max_clock_step_seconds:
                        raise TickReplayError(
                            ReplayAnomaly(ReplayAnomalyCode.CLOCK_GAP, tick.sequence, previous.sequence)
                        )
            previous = tick

    @overload
    def run(self) -> tuple[Tick, ...]: ...

    @overload
    def run(self, order: Order, *, order_type: FillOrderType = FillOrderType.MARKET) -> TickReplayResult: ...

    def run(
        self, order: Order | None = None, *, order_type: FillOrderType = FillOrderType.MARKET
    ) -> tuple[Tick, ...] | TickReplayResult:
        """Return the validated stream, or replay an order when supplied."""
        if order is None:
            return self._ticks
        return self.replay(order, order_type=order_type)

    def _price(self, base: Decimal, direction: TradeDirection, *, limit: Decimal | None) -> Decimal:
        bps = self.config.selected_slippage_bps / Decimal("10000")
        adjusted = base * (Decimal("1") + bps if direction is TradeDirection.LONG else Decimal("1") - bps)
        if limit is not None:
            adjusted = min(adjusted, limit) if direction is TradeDirection.LONG else max(adjusted, limit)
        return adjusted

    @staticmethod
    def _order_payload(order: Order) -> dict[str, object]:
        return {
            "order_id": str(order.order_id),
            "execution_plan_id": str(order.execution_plan_id),
            "instrument": order.instrument,
            "direction": order.direction.value,
            "quantity": _decimal_text(order.quantity),
            "filled_quantity": _decimal_text(order.filled_quantity),
            "limit_price": None if order.limit_price is None else _decimal_text(order.limit_price),
            "stop_price": None if order.stop_price is None else _decimal_text(order.stop_price),
            "created_at": order.created_at.to_dict()["recorded_at"],
        }

    def replay(self, order: Order, *, order_type: FillOrderType = FillOrderType.MARKET) -> TickReplayResult:
        if not isinstance(order, Order):
            raise TypeError("order must be the canonical Decision Order")
        if order.status not in {OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("tick replay requires a working order")
        if not isinstance(order_type, FillOrderType):
            raise TypeError("order_type must be FillOrderType")
        if order_type is FillOrderType.LIMIT and order.limit_price is None:
            return self._result(order, (), ReplayStatus.REJECTED, "INVALID_LIMIT")
        if order_type is FillOrderType.STOP and order.stop_price is None:
            return self._result(order, (), ReplayStatus.REJECTED, "INVALID_STOP")
        if self.config.slippage is not None and self.config.slippage.scope != order.instrument:
            return self._result(order, (), ReplayStatus.REJECTED, "CALIBRATION_SCOPE_MISMATCH")
        limit_price = order.limit_price
        stop_price = order.stop_price

        activation = order.created_at.value + timedelta(microseconds=int(self.config.latency_ms * Decimal("1000")))
        remaining = order.quantity - order.filled_quantity
        working = order
        fills: list[Fill] = []
        triggered = order_type is FillOrderType.MARKET
        trigger_sequence: int | None = None
        saw_eligible = False
        saw_zero_liquidity = False
        for tick in self._ticks:
            if tick.timestamp.astimezone(UTC) < activation:
                continue
            saw_eligible = True
            base_price: Decimal | None = None
            available = Decimal("0")
            if order_type is FillOrderType.STOP and not triggered:
                assert stop_price is not None
                crossed_stop = (
                    tick.price >= stop_price if order.direction is TradeDirection.LONG else tick.price <= stop_price
                )
                if tick.kind is TickKind.TRADE and crossed_stop:
                    triggered = True
                    trigger_sequence = tick.sequence
                continue
            if tick.kind is TickKind.QUOTE:
                if order.direction is TradeDirection.LONG:
                    assert tick.ask is not None
                    crossed = (
                        order_type is FillOrderType.MARKET or (order_type is FillOrderType.STOP and triggered)
                    ) or (limit_price is not None and tick.ask <= limit_price)
                    base_price, available = tick.ask, tick.quantity
                else:
                    assert tick.bid is not None
                    crossed = (
                        order_type is FillOrderType.MARKET or (order_type is FillOrderType.STOP and triggered)
                    ) or (limit_price is not None and tick.bid >= limit_price)
                    base_price, available = tick.bid, tick.quantity
                if not crossed:
                    continue
                if order_type is FillOrderType.LIMIT:
                    triggered = True
            elif tick.kind is TickKind.TRADE and order_type is FillOrderType.LIMIT:
                assert limit_price is not None
                crossed = (
                    tick.price <= limit_price if order.direction is TradeDirection.LONG else tick.price >= limit_price
                )
                if not crossed:
                    continue
                triggered = True
                base_price, available = tick.price, tick.quantity
            else:
                continue
            if available <= 0:
                saw_zero_liquidity = True
                continue
            assert base_price is not None
            quantity = min(remaining, available)
            price = self._price(
                base_price, order.direction, limit=limit_price if order_type is FillOrderType.LIMIT else None
            )
            filled_at = RecordedAt.from_datetime(tick.timestamp)
            fill_seed = canonical_sha256(
                cast(
                    Any,
                    {
                        "order": self._order_payload(order),
                        "config": self.config.digest,
                        "tick": tick.payload(),
                        "fill_index": len(fills),
                        "quantity": _decimal_text(quantity),
                        "price": _decimal_text(price),
                    },
                )
            )
            fill = Fill(
                EntityId.deterministic("fill", fill_seed),
                order.order_id,
                order.instrument,
                order.direction,
                quantity,
                price,
                Decimal("0"),
                filled_at,
                schema_version=order.schema_version,
                source_ref=f"l3:{self.config.model_version}:{self.config.digest[:16]}",
            )
            fills.append(fill)
            working = working.apply_fill(quantity)
            remaining -= quantity
            if remaining == 0:
                break
        if fills:
            status = ReplayStatus.COMPLETED if remaining == 0 else ReplayStatus.PARTIAL
            reason = "FILLED" if remaining == 0 else "PARTIAL_FILL"
        elif order_type is FillOrderType.STOP and triggered:
            status, reason = (
                ReplayStatus.UNFILLED,
                "TRIGGERED_NO_LIQUIDITY" if saw_zero_liquidity else "TRIGGERED_NO_QUOTE",
            )
        elif saw_zero_liquidity:
            status, reason = ReplayStatus.UNFILLED, "NO_LIQUIDITY"
        else:
            status, reason = (
                ReplayStatus.UNFILLED,
                "NOT_TRIGGERED"
                if order_type is not FillOrderType.MARKET
                else ("NO_ELIGIBLE_QUOTE" if not saw_eligible else "NO_LIQUIDITY"),
            )
        return self._result(
            working,
            tuple(fills),
            status,
            reason,
            triggered=triggered,
            trigger_sequence=trigger_sequence,
            original_order=order,
        )

    def _result(
        self,
        order: Order,
        fills: tuple[Fill, ...],
        status: ReplayStatus,
        reason: str,
        *,
        triggered: bool = False,
        trigger_sequence: int | None = None,
        original_order: Order | None = None,
    ) -> TickReplayResult:
        source_order = original_order or order
        digest = canonical_sha256(
            cast(
                Any,
                {
                    "order": self._order_payload(source_order),
                    "result_order": self._order_payload(order),
                    "ticks": tuple(tick.payload() for tick in self._ticks),
                    "config": self.config.payload(),
                    "fills": tuple(str(fill.fill_id) for fill in fills),
                    "status": status.value,
                    "reason": reason,
                    "triggered": triggered,
                    "trigger_sequence": trigger_sequence,
                },
            )
        )
        return TickReplayResult(order, fills, status, reason, self.config.digest, digest, triggered, trigger_sequence)


__all__ = [
    "CalibratedSlippage",
    "ReplayAnomaly",
    "ReplayAnomalyCode",
    "ReplayStatus",
    "SlippageStatistic",
    "Tick",
    "TickKind",
    "TickReplay",
    "TickReplayConfig",
    "TickReplayError",
    "TickReplayResult",
]
