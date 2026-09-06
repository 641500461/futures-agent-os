"""Deterministic V2 trade intent contracts.

These objects describe a bounded plan and its protection intent.  They do not
create orders, fills, positions, or ledger effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, date
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256


V2_CONTRACT_SCHEMA = SchemaVersion(1, 0)


def _now_recorded() -> RecordedAt:
    return RecordedAt.from_datetime(datetime.now(UTC))


def _schema(value: SchemaVersion, label: str) -> None:
    if not isinstance(value, SchemaVersion):
        raise TypeError(f"{label} must be a SchemaVersion")


def _optional_id(value: EntityId | None, label: str) -> None:
    if value is not None and not isinstance(value, EntityId):
        raise TypeError(f"{label} must be a typed identifier when present")


def _namespace(value: EntityId, expected: str, label: str) -> None:
    if value.namespace != expected:
        raise ValueError(f"{label} must use the {expected} identifier namespace")


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


_PLAN_TRANSITIONS: dict[TradePlanStatus, frozenset[TradePlanStatus]] = {
    TradePlanStatus.DRAFT: frozenset({TradePlanStatus.VALIDATED, TradePlanStatus.REJECTED, TradePlanStatus.STALE}),
    TradePlanStatus.VALIDATED: frozenset({TradePlanStatus.REJECTED, TradePlanStatus.STALE}),
    TradePlanStatus.REJECTED: frozenset(),
    TradePlanStatus.STALE: frozenset(),
}


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


def _canonical_value(value: object) -> Any:
    """Render a contract value into the JSON-safe form used by references."""
    if isinstance(value, EntityId):
        return str(value)
    if isinstance(value, RecordedAt):
        return value.to_dict()["recorded_at"]
    if isinstance(value, SchemaVersion):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (StrEnum,)):
        return value.value
    if isinstance(value, tuple):
        return tuple(_canonical_value(item) for item in value)
    if isinstance(value, frozenset):
        return tuple(sorted((_canonical_value(item) for item in value), key=str))
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {item.name: _canonical_value(getattr(value, item.name)) for item in fields(cast(Any, value))}
    return value


def _object_identity(value: object) -> EntityId:
    """Find the canonical identity field of a V2 fact."""
    for name in (
        "plan_id",
        "decision_id",
        "mandate_id",
        "execution_plan_id",
        "policy_id",
        "order_id",
        "fill_id",
        "lot_id",
        "entry_id",
        "settlement_id",
        "intent_id",
    ):
        candidate = getattr(value, name, None)
        if isinstance(candidate, EntityId):
            return candidate
    raise TypeError("V2 fact has no canonical identity")


def _object_version(value: object) -> int:
    version = getattr(value, "version", None)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("V2 fact requires a positive version")
    return version


def _object_hash(value: object) -> str:
    for name in ("plan_hash", "reservation_hash", "basis_hash", "authorization_hash", "receipt_hash"):
        digest = getattr(value, name, None)
        if isinstance(digest, str):
            return digest
    return canonical_sha256(_canonical_value(value))


@dataclass(frozen=True, slots=True)
class ContractReference:
    """A closed-world reference to an immutable V2 fact."""

    entity_id: EntityId
    version: int
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.entity_id, EntityId):
            raise TypeError("reference requires a typed entity id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("reference version must be positive")
        _hash(self.content_hash, "reference content_hash")

    @classmethod
    def for_fact(cls, fact: object) -> ContractReference:
        return cls(_object_identity(fact), _object_version(fact), _object_hash(fact))


class ContractReferenceGraph:
    """Closed-world resolver used by final gates and replay tests.

    A scalar ID is never considered sufficient: registration captures the
    target version and content digest, and every lookup compares all three.
    """

    def __init__(self, facts: tuple[object, ...] = ()) -> None:
        self._facts: dict[EntityId, ContractReference] = {}
        self._objects: dict[EntityId, object] = {}
        for fact in facts:
            self.register(fact)

    def register(self, fact: object) -> ContractReference:
        reference = ContractReference.for_fact(fact)
        existing = self._facts.get(reference.entity_id)
        if existing is not None and existing != reference:
            raise ValueError("reference identity already has a different version or hash")
        self._facts[reference.entity_id] = reference
        self._objects[reference.entity_id] = fact
        return reference

    def require(self, reference: ContractReference, *, expected_namespace: str | None = None) -> object:
        if not isinstance(reference, ContractReference):
            raise TypeError("reference resolver requires a ContractReference")
        if expected_namespace is not None and reference.entity_id.namespace != expected_namespace:
            raise ValueError("reference namespace mismatch")
        current = self._facts.get(reference.entity_id)
        if current != reference:
            raise ValueError("referenced fact is absent, stale, or hash-mismatched")
        return self._objects[reference.entity_id]

    def require_fact(
        self,
        entity_id: EntityId,
        version: int,
        content_hash: str,
        *,
        expected_namespace: str | None = None,
    ) -> object:
        """Resolve a fact from persisted scalar fields with full binding checks."""
        return self.require(
            ContractReference(entity_id, version, content_hash),
            expected_namespace=expected_namespace,
        )

    def contains(self, reference: ContractReference) -> bool:
        try:
            self.require(reference)
        except TypeError, ValueError:
            return False
        return True


def _parse_payload_value(value: object, annotation: object) -> object:
    """Parse the small scalar vocabulary used by deterministic hydrate methods."""
    if annotation is EntityId and isinstance(value, str):
        return EntityId.parse(value)
    if annotation is RecordedAt and isinstance(value, str):
        return RecordedAt.parse(value)
    if annotation is SchemaVersion and isinstance(value, str):
        return SchemaVersion.parse(value)
    if annotation is Decimal and isinstance(value, str):
        return Decimal(value)
    return value


@dataclass(frozen=True, slots=True)
class ProtectionIntent:
    """Agent supplied protection intent; Risk owns the enforceable mandate."""

    stop_price: Decimal
    max_loss: Decimal
    take_profit_price: Decimal | None = None
    time_limit_at: RecordedAt | None = None
    intent_id: EntityId = field(default_factory=lambda: EntityId.new("protection_intent"))
    created_at: RecordedAt = field(default_factory=_now_recorded)
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not isinstance(self.intent_id, EntityId):
            raise TypeError("protection intent requires a typed identifier")
        _namespace(self.intent_id, "protection_intent", "intent_id")
        if not isinstance(self.created_at, RecordedAt):
            raise TypeError("protection intent requires a timestamp")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("protection intent version must be positive")
        _schema(self.schema_version, "protection intent schema_version")
        _text(self.source_ref, "source_ref")
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
        if self.time_limit_at is not None and self.time_limit_at.value <= self.created_at.value:
            raise ValueError("time limit must follow protection intent creation")

    @property
    def source_refs(self) -> tuple[str, ...]:
        return (self.source_ref,)

    def to_dict(self) -> dict[str, object]:
        """Return the complete persisted fact, including identity and time."""
        return {
            "intent_id": str(self.intent_id),
            "stop_price": str(self.stop_price),
            "max_loss": str(self.max_loss),
            "take_profit_price": str(self.take_profit_price) if self.take_profit_price is not None else None,
            "time_limit_at": self.time_limit_at.to_dict()["recorded_at"] if self.time_limit_at else None,
            "created_at": self.created_at.to_dict()["recorded_at"],
            "version": self.version,
            "schema_version": str(self.schema_version),
            "source_ref": self.source_ref,
        }

    @classmethod
    def hydrate(cls, payload: dict[str, object]) -> ProtectionIntent:
        """Hydrate only from an explicit persisted identity and timestamp."""
        required = {
            "intent_id",
            "stop_price",
            "max_loss",
            "take_profit_price",
            "time_limit_at",
            "created_at",
            "version",
            "schema_version",
            "source_ref",
        }
        if set(payload) != required:
            raise ValueError("protection intent payload must contain the exact persisted fields")
        return cls(
            stop_price=Decimal(str(payload["stop_price"])),
            max_loss=Decimal(str(payload["max_loss"])),
            take_profit_price=(
                Decimal(str(payload["take_profit_price"])) if payload["take_profit_price"] is not None else None
            ),
            time_limit_at=(RecordedAt.parse(str(payload["time_limit_at"])) if payload["time_limit_at"] else None),
            intent_id=EntityId.parse(str(payload["intent_id"])),
            created_at=RecordedAt.parse(str(payload["created_at"])),
            version=int(str(payload["version"])),
            schema_version=SchemaVersion.parse(str(payload["schema_version"])),
            source_ref=str(payload["source_ref"]),
        )


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
    created_at: RecordedAt = field(default_factory=_now_recorded)
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.plan_id, self.account_id)):
            raise TypeError("trade plan requires typed identifiers")
        _namespace(self.plan_id, "trade_plan", "plan_id")
        _namespace(self.account_id, "simulation_account", "account_id")
        if not isinstance(self.created_at, RecordedAt):
            raise TypeError("trade plan requires a creation timestamp")
        _schema(self.schema_version, "trade plan schema_version")
        _text(self.source_ref, "source_ref")
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
        for value in self.evidence_refs:
            _hash(value, "evidence_ref")
        if not isinstance(self.expires_at, RecordedAt):
            raise TypeError("trade plan requires expiry")
        if self.expires_at.value <= self.created_at.value:
            raise ValueError("trade plan expiry must be after creation")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be positive")
        if not isinstance(self.status, TradePlanStatus):
            raise TypeError("status must be typed")
        if self.action is TradeAction.OPEN:
            if self.direction is TradeDirection.LONG and self.protection.stop_price >= self.entry_price:
                raise ValueError("long protection stop must be below entry")
            if self.direction is TradeDirection.SHORT and self.protection.stop_price <= self.entry_price:
                raise ValueError("short protection stop must be above entry")

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
                "protection": {
                    "stop_price": str(self.protection.stop_price),
                    "max_loss": str(self.protection.max_loss),
                    "take_profit_price": str(self.protection.take_profit_price)
                    if self.protection.take_profit_price is not None
                    else None,
                    "time_limit_at": self.protection.time_limit_at.to_dict()["recorded_at"]
                    if self.protection.time_limit_at is not None
                    else None,
                    "schema_version": str(self.protection.schema_version),
                    "source_ref": self.protection.source_ref,
                },
                "thesis": self.thesis,
                "invalidation": self.invalidation,
                "evidence_refs": self.evidence_refs,
                "snapshot_ref": self.snapshot_ref,
                "expires_at": self.expires_at.to_dict()["recorded_at"],
                "version": self.version,
                "schema_version": str(self.schema_version),
                "source_ref": self.source_ref,
            }
        )

    @property
    def source_refs(self) -> tuple[str, ...]:
        return (self.source_ref, *self.evidence_refs, self.snapshot_ref)

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": str(self.plan_id),
            "account_id": str(self.account_id),
            "instrument": self.instrument,
            "strategy_ref": self.strategy_ref,
            "action": self.action.value,
            "direction": self.direction.value,
            "quantity": str(self.quantity),
            "entry_price": str(self.entry_price),
            "protection": self.protection.to_dict(),
            "thesis": self.thesis,
            "invalidation": self.invalidation,
            "evidence_refs": self.evidence_refs,
            "snapshot_ref": self.snapshot_ref,
            "expires_at": self.expires_at.to_dict()["recorded_at"],
            "version": self.version,
            "status": self.status.value,
            "created_at": self.created_at.to_dict()["recorded_at"],
            "schema_version": str(self.schema_version),
            "source_ref": self.source_ref,
        }

    @classmethod
    def hydrate(cls, payload: dict[str, object]) -> TradePlan:
        """Hydrate a plan with all identity/time fields supplied by storage."""
        required = {
            "plan_id",
            "account_id",
            "instrument",
            "strategy_ref",
            "action",
            "direction",
            "quantity",
            "entry_price",
            "protection",
            "thesis",
            "invalidation",
            "evidence_refs",
            "snapshot_ref",
            "expires_at",
            "version",
            "status",
            "created_at",
            "schema_version",
            "source_ref",
        }
        if set(payload) != required or not isinstance(payload["protection"], dict):
            raise ValueError("trade plan payload must contain the exact persisted fields")
        refs = payload["evidence_refs"]
        if not isinstance(refs, (tuple, list)):
            raise TypeError("evidence_refs must be a persisted sequence")
        return cls(
            plan_id=EntityId.parse(str(payload["plan_id"])),
            account_id=EntityId.parse(str(payload["account_id"])),
            instrument=str(payload["instrument"]),
            strategy_ref=str(payload["strategy_ref"]),
            action=TradeAction(str(payload["action"])),
            direction=TradeDirection(str(payload["direction"])),
            quantity=Decimal(str(payload["quantity"])),
            entry_price=Decimal(str(payload["entry_price"])),
            protection=ProtectionIntent.hydrate(cast(dict[str, object], payload["protection"])),
            thesis=str(payload["thesis"]),
            invalidation=str(payload["invalidation"]),
            evidence_refs=tuple(str(item) for item in refs),
            snapshot_ref=str(payload["snapshot_ref"]),
            expires_at=RecordedAt.parse(str(payload["expires_at"])),
            version=int(str(payload["version"])),
            status=TradePlanStatus(str(payload["status"])),
            created_at=RecordedAt.parse(str(payload["created_at"])),
            schema_version=SchemaVersion.parse(str(payload["schema_version"])),
            source_ref=str(payload["source_ref"]),
        )

    def transition(self, target: TradePlanStatus) -> TradePlan:
        """Apply the closed plan lifecycle without mutating the original."""
        if not isinstance(target, TradePlanStatus):
            raise TypeError("plan transition target must be typed")
        if target not in _PLAN_TRANSITIONS[self.status]:
            raise ValueError(f"invalid trade plan transition {self.status} -> {target}")
        return replace(self, status=target)


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
    plan_hash: str | None = None
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"
    version: int = 1
    # Version of the Risk Constitution/rule set used for this decision.  It
    # is separate from the decision object's own optimistic version so a
    # replay can prove which immutable rules emitted every rule code.
    risk_constitution_version: int = 1
    risk_constitution_hash: str | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.decision_id, self.plan_id)):
            raise TypeError("risk decision requires typed identifiers")
        _namespace(self.decision_id, "risk_decision", "decision_id")
        _namespace(self.plan_id, "trade_plan", "plan_id")
        if self.plan_hash is None:
            raise ValueError("risk decisions must bind the immutable plan hash")
        _hash(self.plan_hash, "plan_hash")
        _schema(self.schema_version, "risk decision schema_version")
        _text(self.source_ref, "source_ref")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("risk decision version must be positive")
        if (
            isinstance(self.risk_constitution_version, bool)
            or not isinstance(self.risk_constitution_version, int)
            or self.risk_constitution_version < 1
        ):
            raise ValueError("risk constitution version must be positive")
        if self.risk_constitution_hash is not None:
            _hash(self.risk_constitution_hash, "risk_constitution_hash")
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
        if self.outcome in {RiskDecisionOutcome.APPROVE, RiskDecisionOutcome.MODIFY} and self.approved_quantity <= 0:
            raise ValueError("approved risk outcomes require positive quantity")
        if (
            self.outcome
            in {
                RiskDecisionOutcome.REJECT,
                RiskDecisionOutcome.PROTECT_ONLY,
                RiskDecisionOutcome.HALT,
            }
            and self.approved_quantity != 0
        ):
            raise ValueError("non-approved risk outcomes cannot authorize quantity")

    @property
    def rule_version(self) -> int:
        """Stable alias used by risk consumers and evidence serializers."""
        return self.risk_constitution_version


@dataclass(frozen=True, slots=True)
class ProtectionMandate:
    mandate_id: EntityId
    plan_id: EntityId
    stop_price: Decimal
    max_loss: Decimal
    issued_at: RecordedAt
    version: int = 1
    risk_decision_id: EntityId | None = None
    risk_decision_plan_version: int | None = None
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.mandate_id, self.plan_id)):
            raise TypeError("protection mandate requires typed identifiers")
        _namespace(self.mandate_id, "protection_mandate", "mandate_id")
        _namespace(self.plan_id, "trade_plan", "plan_id")
        _optional_id(self.risk_decision_id, "risk_decision_id")
        if self.risk_decision_id is not None:
            _namespace(self.risk_decision_id, "risk_decision", "risk_decision_id")
        if self.risk_decision_plan_version is not None and (
            isinstance(self.risk_decision_plan_version, bool)
            or not isinstance(self.risk_decision_plan_version, int)
            or self.risk_decision_plan_version < 1
        ):
            raise ValueError("risk decision plan version must be positive when present")
        _schema(self.schema_version, "protection mandate schema_version")
        _text(self.source_ref, "source_ref")
        for value, label in ((self.stop_price, "stop_price"), (self.max_loss, "max_loss")):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{label} must be positive")
        if (
            not isinstance(self.issued_at, RecordedAt)
            or isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
        ):
            raise ValueError("mandate requires timestamp and positive version")
        if (self.risk_decision_id is None) != (self.risk_decision_plan_version is None):
            raise ValueError("risk decision reference must include its plan version")
        if self.risk_decision_id is None and self.risk_decision_plan_version is not None:
            raise ValueError("risk decision plan version cannot be supplied without a decision")


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
    risk_decision_id: EntityId | None = None
    risk_decision_plan_version: int | None = None
    authorization_receipt_id: EntityId | None = None
    reservation_id: EntityId | None = None
    plan_hash: str | None = None
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"
    version: int = 1

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId) for value in (self.execution_plan_id, self.plan_id, self.protection_mandate_id)
        ):
            raise TypeError("execution plan requires typed identifiers")
        _namespace(self.execution_plan_id, "execution_plan", "execution_plan_id")
        _namespace(self.plan_id, "trade_plan", "plan_id")
        _namespace(self.protection_mandate_id, "protection_mandate", "protection_mandate_id")
        for value, label in (
            (self.risk_decision_id, "risk_decision_id"),
            (self.authorization_receipt_id, "authorization_receipt_id"),
            (self.reservation_id, "reservation_id"),
        ):
            _optional_id(value, label)
        if self.plan_hash is not None:
            _hash(self.plan_hash, "plan_hash")
        if self.risk_decision_plan_version is not None and (
            isinstance(self.risk_decision_plan_version, bool)
            or not isinstance(self.risk_decision_plan_version, int)
            or self.risk_decision_plan_version < 1
        ):
            raise ValueError("risk decision plan version must be positive when present")
        if (self.risk_decision_id is None) != (self.risk_decision_plan_version is None):
            raise ValueError("risk decision reference must include its plan version")
        _schema(self.schema_version, "execution plan schema_version")
        _text(self.source_ref, "source_ref")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("execution plan version must be positive")
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
    protection_mandate_id: EntityId | None = None
    created_at: RecordedAt = field(default_factory=_now_recorded)
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.policy_id, self.position_id)):
            raise TypeError("stop policy requires typed identifiers")
        _namespace(self.policy_id, "stop_policy", "policy_id")
        _namespace(self.position_id, "position_lot", "position_id")
        _optional_id(self.protection_mandate_id, "protection_mandate_id")
        if self.protection_mandate_id is not None:
            _namespace(self.protection_mandate_id, "protection_mandate", "protection_mandate_id")
        if not isinstance(self.created_at, RecordedAt):
            raise TypeError("stop policy requires a timestamp")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("stop policy version must be positive")
        _schema(self.schema_version, "stop policy schema_version")
        _text(self.source_ref, "source_ref")
        if not isinstance(self.active, bool):
            raise TypeError("stop policy active must be a bool")
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
    created_at: RecordedAt = field(default_factory=_now_recorded)
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.order_id, self.execution_plan_id)):
            raise TypeError("order requires typed identifiers")
        _namespace(self.order_id, "order", "order_id")
        _namespace(self.execution_plan_id, "execution_plan", "execution_plan_id")
        if not isinstance(self.created_at, RecordedAt):
            raise TypeError("order requires a timestamp")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("order version must be positive")
        _schema(self.schema_version, "order schema_version")
        _text(self.source_ref, "source_ref")
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
        if (
            self.status in {OrderStatus.CREATED, OrderStatus.ACCEPTED, OrderStatus.WORKING}
            and self.filled_quantity != 0
        ):
            raise ValueError("unfilled order states cannot carry filled quantity")
        if self.status is OrderStatus.PARTIALLY_FILLED and not 0 < self.filled_quantity < self.quantity:
            raise ValueError("partial order state requires a partial positive fill")
        if self.status is OrderStatus.FILLED and self.filled_quantity != self.quantity:
            raise ValueError("filled order state requires complete quantity")
        if self.limit_price is not None and (not self.limit_price.is_finite() or self.limit_price <= 0):
            raise ValueError("limit_price must be positive when provided")
        if self.stop_price is not None and (not self.stop_price.is_finite() or self.stop_price <= 0):
            raise ValueError("stop_price must be positive when provided")

    @classmethod
    def from_execution_plan(cls, execution_plan: ExecutionPlan, *, instrument: str, direction: TradeDirection) -> Order:
        order_seed = canonical_sha256(
            {
                "execution_plan": str(execution_plan.execution_plan_id),
                "instrument": instrument,
                "direction": direction.value,
                "quantity": str(execution_plan.quantity),
                "created_at": execution_plan.created_at.to_dict()["recorded_at"],
            }
        )
        return cls(
            EntityId.deterministic("order", order_seed),
            execution_plan.execution_plan_id,
            instrument,
            direction,
            execution_plan.quantity,
            limit_price=execution_plan.limit_price,
            stop_price=execution_plan.stop_price,
            created_at=execution_plan.created_at,
            schema_version=execution_plan.schema_version,
            source_ref=execution_plan.source_ref,
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
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.fill_id, self.order_id)):
            raise TypeError("fill requires typed identifiers")
        _namespace(self.fill_id, "fill", "fill_id")
        _namespace(self.order_id, "order", "order_id")
        _schema(self.schema_version, "fill schema_version")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("fill version must be positive")
        _text(self.source_ref, "source_ref")
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
    source_fill_id: EntityId | None = None
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.lot_id, self.account_id)):
            raise TypeError("position lot requires typed identifiers")
        _namespace(self.lot_id, "position_lot", "lot_id")
        _namespace(self.account_id, "simulation_account", "account_id")
        if self.source_fill_id is not None and not isinstance(self.source_fill_id, EntityId):
            raise TypeError("position lot source fill must be a typed identifier")
        if self.source_fill_id is not None:
            _namespace(self.source_fill_id, "fill", "source_fill_id")
        _schema(self.schema_version, "position lot schema_version")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("position lot version must be positive")
        _text(self.source_ref, "source_ref")
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
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.entry_id, self.account_id, self.event_ref)):
            raise TypeError("ledger entry requires typed identifiers")
        _namespace(self.entry_id, "ledger_entry", "entry_id")
        _namespace(self.account_id, "simulation_account", "account_id")
        _schema(self.schema_version, "ledger entry schema_version")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("ledger entry version must be positive")
        _text(self.source_ref, "source_ref")
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
    source_ref: str = "source:v2"
    version: int = 1
    schema_version: SchemaVersion = V2_CONTRACT_SCHEMA
    # Optional end-of-day mark used by the accounting projection to reset the
    # cost basis.  Keeping it optional preserves compatibility with legacy
    # settlement events that only carry a cash delta.
    settlement_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.settlement_id, self.account_id)):
            raise TypeError("settlement requires typed identifiers")
        _namespace(self.settlement_id, "settlement", "settlement_id")
        _namespace(self.account_id, "simulation_account", "account_id")
        _schema(self.schema_version, "settlement schema_version")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("settlement version must be positive")
        _text(self.source_ref, "source_ref")
        _text(self.trading_date, "trading_date")
        try:
            date.fromisoformat(self.trading_date)
        except ValueError as exc:
            raise ValueError("trading_date must be ISO-8601 YYYY-MM-DD") from exc
        for value, label in ((self.cash_delta, "cash_delta"), (self.realized_pnl, "realized_pnl"), (self.fees, "fees")):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{label} must be finite")
        if self.fees < 0:
            raise ValueError("fees must be non-negative")
        if self.settlement_price is not None and (
            not isinstance(self.settlement_price, Decimal)
            or not self.settlement_price.is_finite()
            or self.settlement_price <= 0
        ):
            raise ValueError("settlement_price must be positive when provided")
        if not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("recorded_at must be a RecordedAt")
