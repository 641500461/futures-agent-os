"""Deterministic V2 trade intent contracts.

These objects describe a bounded plan and its protection intent.  They do not
create orders, fills, positions, or ledger effects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


class TradeAction(StrEnum):
    OPEN = "OPEN"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


class TradeDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradePlanStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class RiskDecisionOutcome(StrEnum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    PROTECT_ONLY = "PROTECT_ONLY"
    HALT = "HALT"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value):
        raise ValueError(f"{label} must be canonical non-empty text")
    return value


def _hash(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ProtectionIntent:
    """Agent supplied protection intent; Risk owns the enforceable mandate."""

    stop_price: Decimal
    max_loss: Decimal
    take_profit_price: Decimal | None = None
    time_limit_at: RecordedAt | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.stop_price, "stop_price"), (self.max_loss, "max_loss")):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{label} must be a positive finite Decimal")
        if self.take_profit_price is not None and (
            not isinstance(self.take_profit_price, Decimal)
            or not self.take_profit_price.is_finite()
            or self.take_profit_price <= 0
        ):
            raise ValueError("take_profit_price must be a positive finite Decimal")
        if self.time_limit_at is not None and not isinstance(self.time_limit_at, RecordedAt):
            raise TypeError("time_limit_at must be a RecordedAt")


@dataclass(frozen=True, slots=True)
class TradePlan:
    """Immutable, versioned trade intent with no execution authority."""

    plan_id: EntityId
    account_id: EntityId
    instrument: str
    strategy_ref: str
    action: TradeAction
    direction: TradeDirection
    quantity: Decimal
    entry_price: Decimal
    protection: ProtectionIntent
    thesis: str
    invalidation: str
    evidence_refs: tuple[str, ...]
    snapshot_ref: str
    expires_at: RecordedAt
    version: int = 1
    status: TradePlanStatus = TradePlanStatus.DRAFT

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.plan_id, self.account_id)):
            raise TypeError("trade plan requires typed identifiers")
        for value, label in (
            (self.instrument, "instrument"),
            (self.strategy_ref, "strategy_ref"),
            (self.snapshot_ref, "snapshot_ref"),
        ):
            _text(value, label)
        if not isinstance(self.action, TradeAction) or not isinstance(self.direction, TradeDirection):
            raise TypeError("trade plan action and direction must be typed")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("quantity must be a positive finite Decimal")
        if not isinstance(self.entry_price, Decimal) or not self.entry_price.is_finite() or self.entry_price <= 0:
            raise ValueError("entry_price must be a positive finite Decimal")
        if not isinstance(self.protection, ProtectionIntent):
            raise TypeError("trade plan requires protection intent")
        for value, label in ((self.thesis, "thesis"), (self.invalidation, "invalidation")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be non-empty")
        if (
            not isinstance(self.evidence_refs, tuple)
            or not self.evidence_refs
            or any(not _text(v, "evidence_ref") for v in self.evidence_refs)
        ):
            raise ValueError("trade plan requires immutable evidence references")
        if any(not isinstance(v, str) or len(v) != 64 for v in self.evidence_refs):
            raise ValueError("evidence references must be digest identifiers")
        if not isinstance(self.expires_at, RecordedAt):
            raise TypeError("trade plan requires expiry")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be positive")
        if not isinstance(self.status, TradePlanStatus):
            raise TypeError("status must be typed")

    @property
    def plan_hash(self) -> str:
        return canonical_sha256(
            {
                "plan_id": str(self.plan_id),
                "account_id": str(self.account_id),
                "instrument": self.instrument,
                "strategy_ref": self.strategy_ref,
                "action": self.action.value,
                "direction": self.direction.value,
                "quantity": str(self.quantity),
                "entry_price": str(self.entry_price),
                "thesis": self.thesis,
                "invalidation": self.invalidation,
                "evidence_refs": self.evidence_refs,
                "snapshot_ref": self.snapshot_ref,
                "expires_at": self.expires_at.to_dict()["recorded_at"],
                "version": self.version,
            }
        )


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: EntityId
    plan_id: EntityId
    plan_version: int
    outcome: RiskDecisionOutcome
    approved_quantity: Decimal
    max_loss: Decimal
    margin: Decimal
    rule_refs: tuple[str, ...]
    risk_constitution_ref: str
    issued_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.decision_id, self.plan_id)):
            raise TypeError("risk decision requires typed identifiers")
        if isinstance(self.plan_version, bool) or not isinstance(self.plan_version, int) or self.plan_version < 1:
            raise ValueError("plan_version must be positive")
        if not isinstance(self.outcome, RiskDecisionOutcome):
            raise TypeError("outcome must be typed")
        for value, label in (
            (self.approved_quantity, "approved_quantity"),
            (self.max_loss, "max_loss"),
            (self.margin, "margin"),
        ):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{label} must be finite and non-negative")
        if not isinstance(self.rule_refs, tuple) or any(
            not isinstance(value, str) or not value for value in self.rule_refs
        ):
            raise ValueError("rule_refs must be immutable text references")
        _text(self.risk_constitution_ref, "risk_constitution_ref")
        if not isinstance(self.issued_at, RecordedAt):
            raise TypeError("issued_at must be a RecordedAt")
        if self.outcome is RiskDecisionOutcome.APPROVE and self.approved_quantity <= 0:
            raise ValueError("APPROVE requires positive quantity")


@dataclass(frozen=True, slots=True)
class ProtectionMandate:
    mandate_id: EntityId
    plan_id: EntityId
    stop_price: Decimal
    max_loss: Decimal
    issued_at: RecordedAt
    version: int = 1

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.mandate_id, self.plan_id)):
            raise TypeError("protection mandate requires typed identifiers")
        for value, label in ((self.stop_price, "stop_price"), (self.max_loss, "max_loss")):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{label} must be positive")
        if not isinstance(self.issued_at, RecordedAt) or self.version < 1:
            raise ValueError("mandate requires timestamp and positive version")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    execution_plan_id: EntityId
    plan_id: EntityId
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    protection_mandate_id: EntityId
    created_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId) for value in (self.execution_plan_id, self.plan_id, self.protection_mandate_id)
        ):
            raise TypeError("execution plan requires typed identifiers")
        _text(self.order_type, "order_type")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("execution quantity must be positive")
        for optional_value, label in ((self.limit_price, "limit_price"), (self.stop_price, "stop_price")):
            if optional_value is not None and (
                not isinstance(optional_value, Decimal) or not optional_value.is_finite() or optional_value <= 0
            ):
                raise ValueError(f"{label} must be positive when provided")
        if not isinstance(self.created_at, RecordedAt):
            raise TypeError("created_at must be a RecordedAt")


@dataclass(frozen=True, slots=True)
class StopPolicy:
    policy_id: EntityId
    position_id: EntityId
    stop_price: Decimal
    max_loss: Decimal
    active: bool = True

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.policy_id, self.position_id)):
            raise TypeError("stop policy requires typed identifiers")
        if not isinstance(self.stop_price, Decimal) or self.stop_price <= 0 or not self.stop_price.is_finite():
            raise ValueError("stop price must be positive")
        if not isinstance(self.max_loss, Decimal) or self.max_loss <= 0 or not self.max_loss.is_finite():
            raise ValueError("max loss must be positive")


@dataclass(frozen=True, slots=True)
class Order:
    order_id: EntityId
    execution_plan_id: EntityId
    instrument: str
    direction: TradeDirection
    quantity: Decimal
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: Decimal = Decimal("0")
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.order_id, self.execution_plan_id)):
            raise TypeError("order requires typed identifiers")
        _text(self.instrument, "instrument")
        if not isinstance(self.direction, TradeDirection):
            raise TypeError("direction must be typed")
        for value, label in ((self.quantity, "quantity"), (self.filled_quantity, "filled_quantity")):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{label} must be finite and non-negative")
        if self.quantity <= 0 or self.filled_quantity > self.quantity:
            raise ValueError("order quantity must be positive and fills cannot exceed it")
        if not isinstance(self.status, OrderStatus):
            raise TypeError("status must be typed")
        if self.limit_price is not None and (not self.limit_price.is_finite() or self.limit_price <= 0):
            raise ValueError("limit_price must be positive when provided")
        if self.stop_price is not None and (not self.stop_price.is_finite() or self.stop_price <= 0):
            raise ValueError("stop_price must be positive when provided")

    @classmethod
    def from_execution_plan(cls, execution_plan: ExecutionPlan, *, instrument: str, direction: TradeDirection) -> Order:
        return cls(
            EntityId.new("order"),
            execution_plan.execution_plan_id,
            instrument,
            direction,
            execution_plan.quantity,
            limit_price=execution_plan.limit_price,
            stop_price=execution_plan.stop_price,
        )

    def transition(self, target: OrderStatus) -> Order:
        allowed = {
            OrderStatus.CREATED: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
            OrderStatus.ACCEPTED: {OrderStatus.WORKING, OrderStatus.EXPIRED},
            OrderStatus.WORKING: {
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
            },
            OrderStatus.PARTIALLY_FILLED: {
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
            },
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(f"invalid order transition {self.status} -> {target}")
        return replace(self, status=target)

    def apply_fill(self, quantity: Decimal) -> Order:
        if self.status not in {OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError("fills require a working order")
        if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
            raise ValueError("fill quantity must be positive")
        new_filled = self.filled_quantity + quantity
        if new_filled > self.quantity:
            raise ValueError("fills cannot exceed order quantity")
        target = OrderStatus.FILLED if new_filled == self.quantity else OrderStatus.PARTIALLY_FILLED
        return replace(self, filled_quantity=new_filled, status=target)


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: EntityId
    order_id: EntityId
    instrument: str
    direction: TradeDirection
    quantity: Decimal
    price: Decimal
    fee: Decimal
    filled_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.fill_id, self.order_id)):
            raise TypeError("fill requires typed identifiers")
        _text(self.instrument, "instrument")
        if not isinstance(self.direction, TradeDirection):
            raise TypeError("direction must be typed")
        for value, label in ((self.quantity, "quantity"), (self.price, "price")):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{label} must be positive")
        if not isinstance(self.fee, Decimal) or not self.fee.is_finite() or self.fee < 0:
            raise ValueError("fee must be non-negative")
        if not isinstance(self.filled_at, RecordedAt):
            raise TypeError("filled_at must be a RecordedAt")


@dataclass(frozen=True, slots=True)
class PositionLot:
    lot_id: EntityId
    account_id: EntityId
    instrument: str
    direction: TradeDirection
    quantity: Decimal
    average_price: Decimal
    opened_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.lot_id, self.account_id)):
            raise TypeError("position lot requires typed identifiers")
        _text(self.instrument, "instrument")
        if not isinstance(self.direction, TradeDirection):
            raise TypeError("direction must be typed")
        for value, label in ((self.quantity, "quantity"), (self.average_price, "average_price")):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{label} must be positive")
        if not isinstance(self.opened_at, RecordedAt):
            raise TypeError("opened_at must be a RecordedAt")


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: EntityId
    account_id: EntityId
    event_ref: EntityId
    amount: Decimal
    currency: str
    entry_type: str
    recorded_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.entry_id, self.account_id, self.event_ref)):
            raise TypeError("ledger entry requires typed identifiers")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValueError("ledger amount must be finite")
        _text(self.currency, "currency")
        _text(self.entry_type, "entry_type")
        if not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("recorded_at must be a RecordedAt")


@dataclass(frozen=True, slots=True)
class Settlement:
    settlement_id: EntityId
    account_id: EntityId
    trading_date: str
    cash_delta: Decimal
    realized_pnl: Decimal
    fees: Decimal
    recorded_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.settlement_id, self.account_id)):
            raise TypeError("settlement requires typed identifiers")
        _text(self.trading_date, "trading_date")
        for value, label in ((self.cash_delta, "cash_delta"), (self.realized_pnl, "realized_pnl"), (self.fees, "fees")):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{label} must be finite")
        if self.fees < 0:
            raise ValueError("fees must be non-negative")
        if not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("recorded_at must be a RecordedAt")
