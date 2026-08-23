"""Immutable point-in-time contract-rule truth.

V1-002 deliberately supports *only* exact Instrument scope.  It does not
inherit exchange- or variety-level values and it never field-merges rules from
different publications.  A resolution therefore returns one complete rule set
or a stable failure; later versions can add explicitly governed scope rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import TypeAlias, cast

from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    Money,
    Price,
    Quantity,
    ReasonCode,
    RecordedAt,
    TradingDate,
    canonical_sha256,
)
from futures_agent_os.shared_kernel.observability import JsonValue

from .instrument_registry import Instrument, ReferenceProvenance


DecimalInput: TypeAlias = Decimal | int | str
_UNDERLYING_UNIT = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _exact_decimal(value: DecimalInput, scale: int, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{field} rejects binary float; use Decimal, int, or str")
    if not isinstance(value, (Decimal, int, str)):
        raise TypeError(f"{field} must be Decimal, int, or str")
    if isinstance(scale, bool) or not isinstance(scale, int) or not 0 <= scale <= 18:
        raise ValueError(f"{field} scale must be an integer from 0 through 18")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field} must be a decimal number") from error
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    try:
        quantized = result.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as error:
        raise ValueError(f"{field} cannot be represented at its declared fixed-point scale") from error
    if quantized != result:
        raise ValueError(f"{field} exceeds its declared fixed-point scale")
    return quantized


def _positive_quantity(value: Quantity, field: str, *, unit: str | None = None, allow_zero: bool = False) -> None:
    if not isinstance(value, Quantity):
        raise TypeError(f"{field} must be a Quantity")
    amount = _exact_decimal(value.amount, value.scale, field)
    if (amount < 0) or (not allow_zero and amount == 0):
        raise ValueError(f"{field} must be {'non-negative' if allow_zero else 'positive'}")
    if unit is not None and value.unit != unit:
        raise ValueError(f"{field} must use {unit} units")


def _positive_price(value: Price, field: str, *, allow_zero: bool = False) -> None:
    if not isinstance(value, Price):
        raise TypeError(f"{field} must be a Price")
    amount = _exact_decimal(value.amount, value.scale, field)
    if (amount < 0) or (not allow_zero and amount == 0):
        raise ValueError(f"{field} must be {'non-negative' if allow_zero else 'positive'}")


def _underlying_unit_from_multiplier(multiplier: Quantity) -> str:
    """Require an unambiguous physical multiplier such as ``tonne/lot``."""
    _positive_quantity(multiplier, "multiplier")
    parts = multiplier.unit.split("/")
    if len(parts) != 2 or parts[1] != "lot" or not _UNDERLYING_UNIT.fullmatch(parts[0]):
        raise ValueError("multiplier unit must use canonical <underlying>/lot form")
    return parts[0]


def _require_quote_unit(value: Price, field: str, *, currency: str, underlying: str) -> None:
    _positive_price(value, field, allow_zero=field == "lower_limit")
    expected = f"{currency}/{underlying}"
    if value.currency != currency or value.unit != expected:
        raise ValueError(f"{field} must use canonical {expected} quote units")


def _require_version(value: int, field: str = "version") -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class Rate:
    """An exact non-negative ratio, such as 0.12 for a 12% margin rate."""

    value: DecimalInput
    scale: int

    def __post_init__(self) -> None:
        exact = _exact_decimal(self.value, self.scale, "rate")
        if not Decimal("0") <= exact <= Decimal("1"):
            raise ValueError("rate must be between 0 and 1 inclusive")
        object.__setattr__(self, "value", exact)

    def to_dict(self) -> dict[str, str | int]:
        value = _exact_decimal(self.value, self.scale, "rate")
        return {"value": f"{value:.{self.scale}f}", "scale": self.scale}


@dataclass(frozen=True, slots=True)
class RuleEffectiveInterval:
    """A TradingDate interval whose beginning is inclusive and ending exclusive."""

    effective_from: TradingDate
    effective_until: TradingDate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.effective_from, TradingDate) or (
            self.effective_until is not None and not isinstance(self.effective_until, TradingDate)
        ):
            raise TypeError("rule effective interval requires TradingDate values")
        if self.effective_until is not None and self.effective_until.value <= self.effective_from.value:
            raise ValueError("rule effective interval must be non-empty")

    def contains(self, trading_date: TradingDate) -> bool:
        if not isinstance(trading_date, TradingDate):
            raise TypeError("rule effective interval requires a TradingDate")
        return self.effective_from.value <= trading_date.value and (
            self.effective_until is None or trading_date.value < self.effective_until.value
        )

    def expired_at(self, trading_date: TradingDate) -> bool:
        if not isinstance(trading_date, TradingDate):
            raise TypeError("rule effective interval requires a TradingDate")
        return self.effective_until is not None and trading_date.value >= self.effective_until.value


@dataclass(frozen=True, slots=True)
class MarginRequirements:
    """Exact margin ratios; maintenance cannot exceed initial requirement."""

    initial_ratio: Rate
    maintenance_ratio: Rate

    def __post_init__(self) -> None:
        if not isinstance(self.initial_ratio, Rate) or not isinstance(self.maintenance_ratio, Rate):
            raise TypeError("margin requirements require Rate values")
        initial = _exact_decimal(self.initial_ratio.value, self.initial_ratio.scale, "initial margin")
        maintenance = _exact_decimal(self.maintenance_ratio.value, self.maintenance_ratio.scale, "maintenance margin")
        if initial <= 0:
            raise ValueError("initial margin must be positive")
        if maintenance <= 0 or maintenance > initial:
            raise ValueError("maintenance margin must be positive and no greater than initial margin")


class FeeBasis(StrEnum):
    PER_LOT = "PER_LOT"
    NOTIONAL_RATE = "NOTIONAL_RATE"


@dataclass(frozen=True, slots=True)
class ContractFee:
    """One explicit fee, either cash per lot or a notional ratio, never both."""

    basis: FeeBasis
    per_lot: Money | None = None
    notional_rate: Rate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.basis, FeeBasis):
            raise TypeError("contract fee requires a FeeBasis")
        if self.basis is FeeBasis.PER_LOT:
            if not isinstance(self.per_lot, Money) or self.notional_rate is not None:
                raise ValueError("per-lot contract fee requires exactly one per_lot Money amount")
            amount = _exact_decimal(self.per_lot.amount, self.per_lot.scale, "per-lot contract fee")
            if amount < 0:
                raise ValueError("per-lot contract fee must be non-negative")
        elif self.basis is FeeBasis.NOTIONAL_RATE:
            if not isinstance(self.notional_rate, Rate) or self.per_lot is not None:
                raise ValueError("notional-rate contract fee requires exactly one notional_rate")
        else:  # pragma: no cover - StrEnum validation is still defensive here.
            raise TypeError("contract fee requires a recognized FeeBasis")


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """The complete, non-fallback open/close/close-today fee truth."""

    open_fee: ContractFee
    close_fee: ContractFee
    close_today_fee: ContractFee

    def __post_init__(self) -> None:
        if not all(isinstance(fee, ContractFee) for fee in (self.open_fee, self.close_fee, self.close_today_fee)):
            raise TypeError("fee schedule requires explicit open, close, and close_today ContractFee values")
        monetary_fees = tuple(
            fee.per_lot for fee in (self.open_fee, self.close_fee, self.close_today_fee) if fee.per_lot is not None
        )
        if len({fee.currency for fee in monetary_fees}) > 1:
            raise ValueError("per-lot contract fees must use one currency")


@dataclass(frozen=True, slots=True)
class PriceLimitRange:
    """Explicit lower and upper permitted prices, not a derived percentage default."""

    lower_limit: Price
    upper_limit: Price

    def __post_init__(self) -> None:
        _positive_price(self.lower_limit, "lower_limit", allow_zero=True)
        _positive_price(self.upper_limit, "upper_limit")
        if (
            self.lower_limit.currency != self.upper_limit.currency
            or self.lower_limit.unit != self.upper_limit.unit
            or self.lower_limit.scale != self.upper_limit.scale
        ):
            raise ValueError("price limits must use the same currency and unit with the same scale")
        lower = _exact_decimal(self.lower_limit.amount, self.lower_limit.scale, "lower_limit")
        upper = _exact_decimal(self.upper_limit.amount, self.upper_limit.scale, "upper_limit")
        if lower >= upper:
            raise ValueError("lower price limit must be below upper price limit")


@dataclass(frozen=True, slots=True)
class TradingSession:
    """A local exchange-clock session description; it assigns no TradingDate."""

    name: str
    opens_at: time
    closes_at: time

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or self.name != self.name.strip():
            raise ValueError("trading session requires a canonical non-whitespace name")
        if not isinstance(self.opens_at, time) or not isinstance(self.closes_at, time):
            raise TypeError("trading session requires time-of-day values")
        if self.opens_at.tzinfo is not None or self.closes_at.tzinfo is not None:
            raise ValueError("trading session times must be local exchange clock values without timezone offsets")
        if self.opens_at == self.closes_at:
            raise ValueError("trading session must be non-empty")

    @property
    def crosses_midnight(self) -> bool:
        return self.closes_at < self.opens_at


@dataclass(frozen=True, slots=True)
class PositionTradingLimits:
    """Exact per-rule lot limits; zero explicitly represents a prohibition."""

    max_open_position: Quantity
    max_daily_open_quantity: Quantity
    max_daily_close_quantity: Quantity

    def __post_init__(self) -> None:
        _positive_quantity(self.max_open_position, "max_open_position", unit="lot", allow_zero=True)
        _positive_quantity(self.max_daily_open_quantity, "max_daily_open_quantity", unit="lot", allow_zero=True)
        _positive_quantity(self.max_daily_close_quantity, "max_daily_close_quantity", unit="lot", allow_zero=True)


@dataclass(frozen=True, slots=True)
class OffsetRules:
    """Explicit eligibility for open, close, and close-today offsets."""

    open_allowed: bool
    close_allowed: bool
    close_today_allowed: bool

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bool) for value in (self.open_allowed, self.close_allowed, self.close_today_allowed)
        ):
            raise TypeError("offset rules require bool values")
        if not self.close_allowed and self.close_today_allowed:
            raise ValueError("close_today cannot be allowed while close is forbidden")


@dataclass(frozen=True, slots=True)
class DeliveryRestrictions:
    """Date-specific restrictions near delivery; no calendar inference is performed."""

    new_open_forbidden_from: TradingDate
    close_only_from: TradingDate

    def __post_init__(self) -> None:
        if not isinstance(self.new_open_forbidden_from, TradingDate) or not isinstance(
            self.close_only_from, TradingDate
        ):
            raise TypeError("delivery restrictions require TradingDate values")
        if self.new_open_forbidden_from.value > self.close_only_from.value:
            raise ValueError("delivery restriction new_open_forbidden_from cannot follow close_only_from")


@dataclass(frozen=True, slots=True)
class ContractRuleVersion:
    """One full Instrument-scoped rule set with its effective and PIT evidence.

    This object has no optional economic field.  A valid value is complete
    enough for later deterministic sizing/cost code, but this V1 task neither
    calculates money nor permits trading.
    """

    rule_id: EntityId
    instrument: Instrument
    effective: RuleEffectiveInterval
    version: int
    provenance: ReferenceProvenance
    multiplier: Quantity
    tick_size: Price
    minimum_order_quantity: Quantity
    margin: MarginRequirements
    fees: FeeSchedule
    price_limits: PriceLimitRange
    sessions: tuple[TradingSession, ...]
    last_trading_date: TradingDate
    delivery_restrictions: DeliveryRestrictions
    limits: PositionTradingLimits
    offset_rules: OffsetRules

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, EntityId) or self.rule_id.namespace != "contract_rule":
            raise ValueError("contract rule_id must use the contract_rule namespace")
        if not isinstance(self.instrument, Instrument):
            raise TypeError("contract rule version is scoped only to an exact Instrument")
        if not isinstance(self.effective, RuleEffectiveInterval) or not isinstance(
            self.provenance, ReferenceProvenance
        ):
            raise TypeError("contract rule version requires effective interval and provenance")
        _require_version(self.version)
        underlying = _underlying_unit_from_multiplier(self.multiplier)
        _require_quote_unit(self.tick_size, "tick_size", currency=self.tick_size.currency, underlying=underlying)
        _positive_quantity(self.minimum_order_quantity, "minimum_order_quantity", unit="lot")
        if not isinstance(self.margin, MarginRequirements) or not isinstance(self.fees, FeeSchedule):
            raise TypeError("contract rule version requires margin and complete fee schedule")
        if not isinstance(self.price_limits, PriceLimitRange):
            raise TypeError("contract rule version requires explicit price limits")
        sessions = tuple(self.sessions)
        if not sessions or any(not isinstance(session, TradingSession) for session in sessions):
            raise TypeError("contract rule version requires one or more trading sessions")
        if len({session.name for session in sessions}) != len(sessions):
            raise ValueError("contract rule sessions must have unique names")
        object.__setattr__(self, "sessions", sessions)
        if not isinstance(self.last_trading_date, TradingDate) or not isinstance(
            self.delivery_restrictions, DeliveryRestrictions
        ):
            raise TypeError("contract rule version requires last_trading_date and delivery restrictions")
        if self.last_trading_date.value < self.effective.effective_from.value:
            raise ValueError("last_trading_date cannot precede effective_from")
        if self.delivery_restrictions.close_only_from.value > self.last_trading_date.value:
            raise ValueError("delivery restriction close_only_from cannot follow last_trading_date")
        if not isinstance(self.limits, PositionTradingLimits) or not isinstance(self.offset_rules, OffsetRules):
            raise TypeError("contract rule version requires position/trading limits and offset rules")
        _require_quote_unit(
            self.price_limits.lower_limit,
            "lower_limit",
            currency=self.tick_size.currency,
            underlying=underlying,
        )
        _require_quote_unit(
            self.price_limits.upper_limit,
            "upper_limit",
            currency=self.tick_size.currency,
            underlying=underlying,
        )
        for fee in (self.fees.open_fee, self.fees.close_fee, self.fees.close_today_fee):
            if fee.per_lot is not None and fee.per_lot.currency != self.tick_size.currency:
                raise ValueError("per-lot fees must use the tick price currency")


@dataclass(frozen=True, slots=True)
class ContractRuleRegistry:
    """Immutable release of complete Instrument-scoped contract rule versions."""

    registry_id: EntityId
    release_version: int
    rules: tuple[ContractRuleVersion, ...]
    expected_content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.registry_id, EntityId) or self.registry_id.namespace != "contract_rule_registry":
            raise ValueError("contract rule registry_id must use the contract_rule_registry namespace")
        _require_version(self.release_version, "registry release_version")
        rules = tuple(self.rules)
        if any(not isinstance(rule, ContractRuleVersion) for rule in rules):
            raise TypeError("contract rule registry rules must be ContractRuleVersion values")
        if len({(rule.rule_id, rule.version) for rule in rules}) != len(rules):
            raise ValueError("contract rule registry cannot contain duplicate rule_id/version pairs")
        actual = contract_rule_registry_content_sha256(rules)
        if not isinstance(self.expected_content_sha256, str) or self.expected_content_sha256 != actual:
            raise ValueError("contract rule registry expected_content_sha256 does not match rules")
        object.__setattr__(self, "rules", rules)


@dataclass(frozen=True, slots=True)
class RuleSetRef:
    """The immutable identity required to replay a historical rule decision."""

    registry_id: EntityId
    registry_release_version: int
    registry_content_sha256: str
    rule_id: EntityId
    rule_version: int
    rule_content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.registry_id, EntityId) or self.registry_id.namespace != "contract_rule_registry":
            raise ValueError("rule set ref requires a contract_rule_registry id")
        if not isinstance(self.rule_id, EntityId) or self.rule_id.namespace != "contract_rule":
            raise ValueError("rule set ref requires a contract_rule id")
        _require_version(self.registry_release_version, "registry_release_version")
        _require_version(self.rule_version, "rule_version")
        for field, digest in (
            ("registry_content_sha256", self.registry_content_sha256),
            ("rule_content_sha256", self.rule_content_sha256),
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError(f"{field} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class RuleResolution:
    """A deterministic selection of exactly one full ContractRuleVersion."""

    rule: ContractRuleVersion
    provenance: ReferenceProvenance
    trading_date: TradingDate
    as_of: RecordedAt
    registry_id: EntityId
    registry_release_version: int
    registry_content_sha256: str
    rule_content_sha256: str
    rule_set_ref: RuleSetRef


RuleResolutionOutcome: TypeAlias = RuleResolution | Failure


@dataclass(frozen=True, slots=True)
class ContractRuleResolver:
    """Fail-closed resolver for immutable, complete Instrument rule sets."""

    registry: ContractRuleRegistry

    def __post_init__(self) -> None:
        if not isinstance(self.registry, ContractRuleRegistry):
            raise TypeError("contract rule resolver requires a ContractRuleRegistry")

    def resolve(self, instrument: Instrument, trading_date: TradingDate, as_of: RecordedAt) -> RuleResolutionOutcome:
        if not isinstance(instrument, Instrument):
            raise TypeError("contract rule resolution requires an Instrument")
        if not isinstance(trading_date, TradingDate):
            raise TypeError("contract rule resolution requires a TradingDate")
        if not isinstance(as_of, RecordedAt):
            raise TypeError("contract rule resolution requires a RecordedAt as_of")
        candidates = tuple(rule for rule in self.registry.rules if rule.instrument == instrument)
        effective = tuple(rule for rule in candidates if rule.effective.contains(trading_date))
        visible = tuple(rule for rule in effective if rule.provenance.is_visible_at(as_of))
        if len(visible) > 1:
            return Failure(
                ReasonCode.RULE_CONFLICT, "multiple visible contract rules apply to instrument and trading_date"
            )
        if len(visible) == 1:
            rule = visible[0]
            rule_hash = contract_rule_content_sha256(rule)
            rule_set_ref = RuleSetRef(
                self.registry.registry_id,
                self.registry.release_version,
                self.registry.expected_content_sha256,
                rule.rule_id,
                rule.version,
                rule_hash,
            )
            return RuleResolution(
                rule,
                rule.provenance,
                trading_date,
                as_of,
                self.registry.registry_id,
                self.registry.release_version,
                self.registry.expected_content_sha256,
                rule_hash,
                rule_set_ref,
            )
        if effective:
            return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "contract rule was not acquired at as_of")
        return Failure(ReasonCode.RULE_MISSING, "no contract rule applies to instrument and trading_date")


def contract_rule_content_sha256(rule: ContractRuleVersion) -> str:
    """Hash immutable rule facts, including source/effective data but not rule identity."""
    if not isinstance(rule, ContractRuleVersion):
        raise TypeError("contract_rule_content_sha256 requires a ContractRuleVersion")
    return canonical_sha256(cast("JsonValue", _rule_payload(rule)))


def contract_rule_registry_content_sha256(rules: tuple[ContractRuleVersion, ...]) -> str:
    """Hash a release independent of caller ordering and release identity."""
    typed_rules = tuple(rules)
    if any(not isinstance(rule, ContractRuleVersion) for rule in typed_rules):
        raise TypeError("contract rule registry content requires ContractRuleVersion values")
    payload = tuple(sorted((_registry_rule_payload(rule) for rule in typed_rules), key=repr))
    return canonical_sha256(cast("JsonValue", payload))


def _rule_payload(rule: ContractRuleVersion) -> dict[str, object]:
    return {
        "instrument": rule.instrument.reference_id,
        "effective": {
            "from": str(rule.effective.effective_from),
            "until": str(rule.effective.effective_until) if rule.effective.effective_until else None,
        },
        "version": rule.version,
        "provenance": {
            "source_ref": rule.provenance.source_ref,
            "acquired_at": rule.provenance.acquired_at.to_dict()["recorded_at"],
            "source_published_at": rule.provenance.source_published_at.to_dict()["recorded_at"]
            if rule.provenance.source_published_at
            else None,
            "source_revision": rule.provenance.source_revision,
        },
        "multiplier": rule.multiplier.to_dict(),
        "tick_size": rule.tick_size.to_dict(),
        "minimum_order_quantity": rule.minimum_order_quantity.to_dict(),
        "margin": {
            "initial": rule.margin.initial_ratio.to_dict(),
            "maintenance": rule.margin.maintenance_ratio.to_dict(),
        },
        "fees": {
            "open": _fee_payload(rule.fees.open_fee),
            "close": _fee_payload(rule.fees.close_fee),
            "close_today": _fee_payload(rule.fees.close_today_fee),
        },
        "price_limits": {
            "lower": rule.price_limits.lower_limit.to_dict(),
            "upper": rule.price_limits.upper_limit.to_dict(),
        },
        "sessions": tuple(
            {
                "name": session.name,
                "opens_at": session.opens_at.isoformat(),
                "closes_at": session.closes_at.isoformat(),
            }
            for session in rule.sessions
        ),
        "last_trading_date": str(rule.last_trading_date),
        "delivery_restrictions": {
            "new_open_forbidden_from": str(rule.delivery_restrictions.new_open_forbidden_from),
            "close_only_from": str(rule.delivery_restrictions.close_only_from),
        },
        "limits": {
            "max_open_position": rule.limits.max_open_position.to_dict(),
            "max_daily_open_quantity": rule.limits.max_daily_open_quantity.to_dict(),
            "max_daily_close_quantity": rule.limits.max_daily_close_quantity.to_dict(),
        },
        "offset_rules": {
            "open_allowed": rule.offset_rules.open_allowed,
            "close_allowed": rule.offset_rules.close_allowed,
            "close_today_allowed": rule.offset_rules.close_today_allowed,
        },
    }


def _registry_rule_payload(rule: ContractRuleVersion) -> dict[str, object]:
    payload = _rule_payload(rule)
    return {"rule_id": str(rule.rule_id), "content": payload}


def _fee_payload(fee: ContractFee) -> dict[str, object]:
    return {
        "basis": fee.basis.value,
        "per_lot": fee.per_lot.to_dict() if fee.per_lot else None,
        "notional_rate": fee.notional_rate.to_dict() if fee.notional_rate else None,
    }
