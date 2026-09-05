"""Deterministic V2 trade intent contracts.

These objects describe a bounded plan and its protection intent.  They do not
create orders, fills, positions, or ledger effects.
"""

from __future__ import annotations

from dataclasses import dataclass
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
        for value, label in ((self.instrument, "instrument"), (self.strategy_ref, "strategy_ref"), (self.snapshot_ref, "snapshot_ref")):
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
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs or any(not _text(v, "evidence_ref") for v in self.evidence_refs):
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
        return canonical_sha256({
            "plan_id": str(self.plan_id), "account_id": str(self.account_id),
            "instrument": self.instrument, "strategy_ref": self.strategy_ref,
            "action": self.action.value, "direction": self.direction.value,
            "quantity": str(self.quantity), "entry_price": str(self.entry_price),
            "thesis": self.thesis, "invalidation": self.invalidation,
            "evidence_refs": self.evidence_refs, "snapshot_ref": self.snapshot_ref,
            "expires_at": self.expires_at.to_dict()["recorded_at"], "version": self.version,
        })
