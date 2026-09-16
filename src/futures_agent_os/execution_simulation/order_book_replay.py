"""Deterministic L4 order-book replay with explicit queue assumptions.

A resting simulated order joins behind displayed depth. Later additions join
behind it; depth reductions cancel from behind before queue-ahead. Trade events
consume queue-ahead, the simulated order, then queue-behind. Every transition
records a conservation equation, without claiming real exchange queue priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

from .contracts import Fill


def _decimal(value: Decimal, label: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be a {'positive' if positive else 'non-negative'} finite Decimal")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


class BookSide(StrEnum):
    BID = "BID"
    ASK = "ASK"


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        _decimal(self.price, "book price", positive=True)
        _decimal(self.quantity, "book quantity")


@dataclass(frozen=True, slots=True)
class DepthConsumption:
    price: Decimal
    available_before: Decimal
    quantity: Decimal
    available_after: Decimal

    def __post_init__(self) -> None:
        _decimal(self.price, "consumption price", positive=True)
        for value in (self.available_before, self.quantity, self.available_after):
            _decimal(value, "depth quantity")
        if self.available_before != self.quantity + self.available_after:
            raise ValueError("depth consumption must conserve quantity")


@dataclass(frozen=True, slots=True)
class BookFill:
    """Compatibility result for direct depth consumption."""

    quantity: Decimal
    notional: Decimal
    remaining: Decimal
    impact: Decimal
    consumed_depth: Decimal = Decimal("0")
    levels: tuple[DepthConsumption, ...] = ()


def consume(levels: tuple[BookLevel, ...], requested: Decimal, reference_price: Decimal) -> BookFill:
    """Consume caller-ordered levels without inventing depth."""

    if not levels:
        raise ValueError("consumption requires book depth")
    if any(not isinstance(level, BookLevel) for level in levels):
        raise TypeError("levels must contain BookLevel values")
    if len({level.price for level in levels}) != len(levels):
        raise ValueError("book levels must have unique prices")
    _decimal(requested, "requested", positive=True)
    _decimal(reference_price, "reference_price", positive=True)
    remaining = requested
    notional = Decimal("0")
    transitions: list[DepthConsumption] = []
    for level in levels:
        if remaining == 0:
            break
        take = min(remaining, level.quantity)
        if take == 0:
            continue
        transitions.append(DepthConsumption(level.price, level.quantity, take, level.quantity - take))
        notional += take * level.price
        remaining -= take
    filled = requested - remaining
    average = notional / filled if filled else reference_price
    return BookFill(filled, notional, remaining, average - reference_price, filled, tuple(transitions))


@dataclass(frozen=True, slots=True)
class BookUpdate:
    """Legacy compact depth row retained for the initial public surface."""

    sequence: int
    side: BookSide
    price: Decimal
    quantity: Decimal
    queue_ahead: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("book sequence must be a positive integer")
        if not isinstance(self.side, BookSide):
            raise TypeError("book side must be BookSide")
        _decimal(self.price, "book price", positive=True)
        _decimal(self.quantity, "book quantity")
        _decimal(self.queue_ahead, "queue_ahead")
        if self.queue_ahead > self.quantity:
            raise ValueError("queue_ahead cannot exceed displayed quantity")


def replay(
    updates: tuple[BookUpdate, ...], requested: Decimal, reference_price: Decimal, *, side: BookSide
) -> BookFill:
    """Compatibility replay treating updates as independent depth levels."""

    if not updates:
        raise ValueError("book replay requires updates")
    if any(not isinstance(update, BookUpdate) for update in updates):
        raise TypeError("updates must contain BookUpdate values")
    if not isinstance(side, BookSide):
        raise TypeError("side must be BookSide")
    if any(updates[index].sequence >= updates[index + 1].sequence for index in range(len(updates) - 1)):
        raise ValueError("BOOK_SEQUENCE_ORDER")
    if any(updates[index + 1].sequence != updates[index].sequence + 1 for index in range(len(updates) - 1)):
        raise ValueError("BOOK_SEQUENCE_GAP")
    eligible = tuple(
        BookLevel(update.price, update.quantity - update.queue_ahead)
        for update in updates
        if update.side is side and update.quantity > update.queue_ahead
    )
    if not eligible:
        return BookFill(Decimal("0"), Decimal("0"), requested, Decimal("0"))
    return consume(eligible, requested, reference_price)


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    sequence: int
    recorded_at: RecordedAt
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    truth_sample_ref: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("snapshot sequence must be a non-negative integer")
        if not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("snapshot recorded_at must be RecordedAt")
        if not self.truth_sample_ref or self.truth_sample_ref != self.truth_sample_ref.strip():
            raise ValueError("snapshot requires a canonical truth_sample_ref")
        self._validate_side(self.bids, BookSide.BID)
        self._validate_side(self.asks, BookSide.ASK)
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError("snapshot book must not be crossed")

    @staticmethod
    def _validate_side(levels: tuple[BookLevel, ...], side: BookSide) -> None:
        if not isinstance(levels, tuple) or any(not isinstance(level, BookLevel) for level in levels):
            raise TypeError("snapshot depth must be immutable BookLevel tuples")
        prices = [level.price for level in levels]
        expected = sorted(prices, reverse=side is BookSide.BID)
        if prices != expected or len(prices) != len(set(prices)):
            raise ValueError(f"{side.value} depth must be unique and price-priority sorted")

    def payload(self) -> dict[str, object]:
        def render(levels: tuple[BookLevel, ...]) -> tuple[dict[str, str], ...]:
            return tuple(
                {"price": _decimal_text(level.price), "quantity": _decimal_text(level.quantity)} for level in levels
            )

        return {
            "sequence": self.sequence,
            "recorded_at": self.recorded_at.to_dict()["recorded_at"],
            "bids": render(self.bids),
            "asks": render(self.asks),
            "truth_sample_ref": self.truth_sample_ref,
        }


class BookEventKind(StrEnum):
    SET_DEPTH = "SET_DEPTH"
    TRADE = "TRADE"


@dataclass(frozen=True, slots=True)
class L4BookEvent:
    sequence: int
    recorded_at: RecordedAt
    kind: BookEventKind
    side: BookSide
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("event sequence must be a positive integer")
        if not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("event recorded_at must be RecordedAt")
        if not isinstance(self.kind, BookEventKind) or not isinstance(self.side, BookSide):
            raise TypeError("event kind and side must be typed enums")
        _decimal(self.price, "event price", positive=True)
        _decimal(self.quantity, "event quantity")

    def payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "recorded_at": self.recorded_at.to_dict()["recorded_at"],
            "kind": self.kind.value,
            "side": self.side.value,
            "price": _decimal_text(self.price),
            "quantity": _decimal_text(self.quantity),
        }


@dataclass(frozen=True, slots=True)
class QueueTransition:
    sequence: int
    trade_quantity: Decimal
    ahead_before: Decimal
    ahead_consumed: Decimal
    fill_quantity: Decimal
    behind_consumed: Decimal
    unmatched: Decimal
    ahead_after: Decimal
    behind_after: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.trade_quantity,
            self.ahead_before,
            self.ahead_consumed,
            self.fill_quantity,
            self.behind_consumed,
            self.unmatched,
            self.ahead_after,
            self.behind_after,
        ):
            _decimal(value, "queue transition quantity")
        if self.trade_quantity != self.ahead_consumed + self.fill_quantity + self.behind_consumed + self.unmatched:
            raise ValueError("trade quantity must be conserved")
        if self.ahead_before != self.ahead_consumed + self.ahead_after:
            raise ValueError("queue-ahead quantity must be conserved")


class L4ReplayStatus(StrEnum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    UNFILLED = "UNFILLED"


@dataclass(frozen=True, slots=True)
class L4ReplayConfig:
    model_version: str = "l4-price-time-v1"
    fidelity: str = "L4_ORDER_BOOK"

    def __post_init__(self) -> None:
        for value, label in ((self.model_version, "model_version"), (self.fidelity, "fidelity")):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or any(char.isspace() for char in value)
            ):
                raise ValueError(f"{label} must be canonical text")
        if self.fidelity != "L4_ORDER_BOOK":
            raise ValueError("L4 replay cannot claim another fidelity")

    @property
    def digest(self) -> str:
        return canonical_sha256(cast(Any, {"model_version": self.model_version, "fidelity": self.fidelity}))


@dataclass(frozen=True, slots=True)
class L4ReplayResult:
    order: Order
    fills: tuple[Fill, ...]
    status: L4ReplayStatus
    reason: str
    available_liquidity: Decimal
    consumed_liquidity: Decimal
    remaining_quantity: Decimal
    impact: Decimal
    impact_bps: Decimal
    depth_transitions: tuple[DepthConsumption, ...]
    queue_transitions: tuple[QueueTransition, ...]
    truth_sample_ref: str
    config_digest: str
    replay_digest: str


class OrderBookReplay:
    """Replay aggressive or resting canonical Orders against one frozen sample."""

    def __init__(
        self,
        snapshot: BookSnapshot,
        events: tuple[L4BookEvent, ...] = (),
        config: L4ReplayConfig | None = None,
    ) -> None:
        if not isinstance(snapshot, BookSnapshot):
            raise TypeError("snapshot must be BookSnapshot")
        if not isinstance(events, tuple) or any(not isinstance(event, L4BookEvent) for event in events):
            raise TypeError("events must be an immutable tuple of L4BookEvent values")
        if config is not None and not isinstance(config, L4ReplayConfig):
            raise TypeError("config must be L4ReplayConfig")
        self.snapshot = snapshot
        self.events = events
        self.config = config or L4ReplayConfig()
        self._validate_events()

    def _validate_events(self) -> None:
        previous_sequence = self.snapshot.sequence
        previous_time = self.snapshot.recorded_at.value
        for event in self.events:
            if event.sequence <= previous_sequence:
                raise ValueError("BOOK_SEQUENCE_ORDER")
            if event.sequence != previous_sequence + 1:
                raise ValueError("BOOK_SEQUENCE_GAP")
            if event.recorded_at.value < previous_time:
                raise ValueError("BOOK_CLOCK_REGRESSION")
            previous_sequence = event.sequence
            previous_time = event.recorded_at.value

    @staticmethod
    def _validate_order(order: Order) -> None:
        if not isinstance(order, Order):
            raise TypeError("order must be the canonical Decision Order")
        if order.status not in {OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("L4 replay requires a working order")

    @staticmethod
    def _levels(snapshot: BookSnapshot, side: BookSide) -> tuple[BookLevel, ...]:
        return snapshot.bids if side is BookSide.BID else snapshot.asks

    @staticmethod
    def _opposing_side(direction: TradeDirection) -> BookSide:
        return BookSide.ASK if direction is TradeDirection.LONG else BookSide.BID

    @staticmethod
    def _resting_side(direction: TradeDirection) -> BookSide:
        return BookSide.BID if direction is TradeDirection.LONG else BookSide.ASK

    @staticmethod
    def _order_payload(order: Order) -> dict[str, object]:
        return {
            "order_id": str(order.order_id),
            "instrument": order.instrument,
            "direction": order.direction.value,
            "quantity": _decimal_text(order.quantity),
            "filled_quantity": _decimal_text(order.filled_quantity),
            "limit_price": None if order.limit_price is None else _decimal_text(order.limit_price),
            "created_at": order.created_at.to_dict()["recorded_at"],
        }

    def _fill(self, order: Order, quantity: Decimal, price: Decimal, event: L4BookEvent | None, index: int) -> Fill:
        recorded_at = self.snapshot.recorded_at if event is None else event.recorded_at
        seed = canonical_sha256(
            cast(
                Any,
                {
                    "order": self._order_payload(order),
                    "sample": self.snapshot.payload(),
                    "events": tuple(item.payload() for item in self.events),
                    "config": self.config.digest,
                    "sequence": self.snapshot.sequence if event is None else event.sequence,
                    "index": index,
                    "quantity": _decimal_text(quantity),
                    "price": _decimal_text(price),
                },
            )
        )
        return Fill(
            EntityId.deterministic("fill", seed),
            order.order_id,
            order.instrument,
            order.direction,
            quantity,
            price,
            Decimal("0"),
            recorded_at,
            schema_version=order.schema_version,
            source_ref=f"l4:{self.config.model_version}:{self.snapshot.truth_sample_ref}",
        )

    def execute_aggressive(self, order: Order) -> L4ReplayResult:
        """Walk opposing snapshot depth in price priority; never use future events."""

        self._validate_order(order)
        side = self._opposing_side(order.direction)
        levels = self._levels(self.snapshot, side)
        remaining = order.quantity - order.filled_quantity
        eligible = tuple(
            level
            for level in levels
            if order.limit_price is None
            or (
                level.price <= order.limit_price
                if order.direction is TradeDirection.LONG
                else level.price >= order.limit_price
            )
        )
        available = sum((level.quantity for level in eligible), Decimal("0"))
        if not eligible or available == 0:
            return self._result(order, (), available, Decimal("0"), remaining, Decimal("0"), (), (), "NO_LIQUIDITY")
        consumed = consume(eligible, remaining, eligible[0].price)
        fills: list[Fill] = []
        working = order
        for index, transition in enumerate(consumed.levels):
            fills.append(self._fill(order, transition.quantity, transition.price, None, index))
            working = working.apply_fill(transition.quantity)
        vwap = consumed.notional / consumed.quantity
        impact = vwap - eligible[0].price if order.direction is TradeDirection.LONG else eligible[0].price - vwap
        impact_bps = impact / eligible[0].price * Decimal("10000")
        return self._result(
            working,
            tuple(fills),
            available,
            consumed.quantity,
            consumed.remaining,
            impact,
            consumed.levels,
            (),
            "FILLED" if consumed.remaining == 0 else "PARTIAL_FILL",
            impact_bps=impact_bps,
            original_order=order,
        )

    def execute_resting(self, order: Order) -> L4ReplayResult:
        """Place a limit order behind displayed depth and replay later trades."""

        self._validate_order(order)
        if order.limit_price is None:
            raise ValueError("resting L4 replay requires limit_price")
        side = self._resting_side(order.direction)
        price = order.limit_price
        ahead = next(
            (level.quantity for level in self._levels(self.snapshot, side) if level.price == price), Decimal("0")
        )
        behind = Decimal("0")
        remaining = order.quantity - order.filled_quantity
        working = order
        fills: list[Fill] = []
        transitions: list[QueueTransition] = []
        trade_flow = Decimal("0")
        for event in self.events:
            if event.side is not side or event.price != price:
                continue
            if event.kind is BookEventKind.SET_DEPTH:
                current = ahead + behind
                if event.quantity >= current:
                    behind += event.quantity - current
                else:
                    reduction = current - event.quantity
                    cancelled_behind = min(behind, reduction)
                    behind -= cancelled_behind
                    ahead -= min(ahead, reduction - cancelled_behind)
                continue
            trade_flow += event.quantity
            ahead_before = ahead
            ahead_consumed = min(ahead, event.quantity)
            ahead -= ahead_consumed
            after_ahead = event.quantity - ahead_consumed
            fill_quantity = min(remaining, after_ahead)
            remaining -= fill_quantity
            if fill_quantity > 0:
                fills.append(self._fill(order, fill_quantity, price, event, len(fills)))
                working = working.apply_fill(fill_quantity)
            after_fill = after_ahead - fill_quantity
            behind_consumed = min(behind, after_fill)
            behind -= behind_consumed
            unmatched = after_fill - behind_consumed
            transitions.append(
                QueueTransition(
                    event.sequence,
                    event.quantity,
                    ahead_before,
                    ahead_consumed,
                    fill_quantity,
                    behind_consumed,
                    unmatched,
                    ahead,
                    behind,
                )
            )
            if remaining == 0:
                break
        return self._result(
            working,
            tuple(fills),
            trade_flow,
            sum((fill.quantity for fill in fills), Decimal("0")),
            remaining,
            Decimal("0"),
            (),
            tuple(transitions),
            "FILLED" if remaining == 0 else ("PARTIAL_FILL" if fills else "QUEUE_NOT_REACHED"),
            original_order=order,
        )

    def _result(
        self,
        order: Order,
        fills: tuple[Fill, ...],
        available: Decimal,
        consumed: Decimal,
        remaining: Decimal,
        impact: Decimal,
        depth_transitions: tuple[DepthConsumption, ...],
        queue_transitions: tuple[QueueTransition, ...],
        reason: str,
        *,
        impact_bps: Decimal = Decimal("0"),
        original_order: Order | None = None,
    ) -> L4ReplayResult:
        status = (
            L4ReplayStatus.FILLED if remaining == 0 else (L4ReplayStatus.PARTIAL if fills else L4ReplayStatus.UNFILLED)
        )
        source_order = original_order or order
        digest = canonical_sha256(
            cast(
                Any,
                {
                    "order": self._order_payload(source_order),
                    "result_order": self._order_payload(order),
                    "snapshot": self.snapshot.payload(),
                    "events": tuple(event.payload() for event in self.events),
                    "config": self.config.digest,
                    "fills": tuple(str(fill.fill_id) for fill in fills),
                    "available": _decimal_text(available),
                    "consumed": _decimal_text(consumed),
                    "remaining": _decimal_text(remaining),
                    "impact": _decimal_text(impact),
                    "impact_bps": _decimal_text(impact_bps),
                    "reason": reason,
                },
            )
        )
        return L4ReplayResult(
            order,
            fills,
            status,
            reason,
            available,
            consumed,
            remaining,
            impact,
            impact_bps,
            depth_transitions,
            queue_transitions,
            self.snapshot.truth_sample_ref,
            self.config.digest,
            digest,
        )


__all__ = [
    "BookEventKind",
    "BookFill",
    "BookLevel",
    "BookSide",
    "BookSnapshot",
    "BookUpdate",
    "DepthConsumption",
    "L4ReplayConfig",
    "L4BookEvent",
    "L4ReplayResult",
    "L4ReplayStatus",
    "OrderBookReplay",
    "QueueTransition",
    "consume",
    "replay",
]
