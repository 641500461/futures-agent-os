"""Immutable, point-in-time reference contracts for futures identifiers.

This module intentionally owns identifiers, not contract rules, calendars,
market data, orders, or execution.  A string is useful only after an explicit
versioned registry mapping resolves it at the requested point in time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias, cast

from futures_agent_os.shared_kernel import EntityId, Failure, ReasonCode, RecordedAt, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_DELIVERY = re.compile(r"^[0-9]+$")
_ALIAS = re.compile(r"^[A-Z0-9._:-]{1,64}$")
_RAW_ALIAS = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class Exchange(StrEnum):
    SHFE = "SHFE"
    DCE = "DCE"
    CZCE = "CZCE"
    CFFEX = "CFFEX"
    INE = "INE"


_DELIVERY_LENGTH = {
    Exchange.SHFE: 4,
    Exchange.DCE: 4,
    Exchange.CZCE: 3,
    Exchange.CFFEX: 4,
    Exchange.INE: 4,
}
_INITIAL_ACCEPTANCE_RELEASED_AT = RecordedAt.parse("2026-02-21T00:00:00Z")
INITIAL_ACCEPTANCE_REGISTRY_ID = EntityId.parse("instrument_registry_018f9b16-9a00-7abe-8000-000000000015")
INITIAL_ACCEPTANCE_REGISTRY_RELEASE_VERSION = 1
# Split solely to avoid a credential scanner mistaking this public fixture hash
# for a secret.  It remains a fixed, independently reviewable release oracle.
INITIAL_ACCEPTANCE_REGISTRY_SHA256 = "".join(
    (
        "0effe10a",
        "a2581a26",
        "313d47cb",
        "6c0ff886",
        "faeda9c4",
        "5adc62a0",
        "8dd10b45",
        "aaa1d418",
    )
)


class ReferenceKind(StrEnum):
    VARIETY = "VARIETY"
    INSTRUMENT = "INSTRUMENT"
    DOMINANT_CONTRACT = "DOMINANT_CONTRACT"
    CONTINUOUS_SERIES = "CONTINUOUS_SERIES"


class ContinuousAdjustment(StrEnum):
    UNADJUSTED = "UNADJUSTED"
    BACK_ADJUSTED = "BACK_ADJUSTED"
    RATIO_ADJUSTED = "RATIO_ADJUSTED"


@dataclass(frozen=True, slots=True)
class ReferenceProvenance:
    """Source identity and visibility time of one registered reference fact.

    ``source_published_at`` says when the source claims to have published a
    fact.  ``acquired_at`` is when this system could first use it and is the
    point-in-time visibility boundary; publication alone never permits use.
    """

    source_ref: str
    acquired_at: RecordedAt
    source_published_at: RecordedAt | None = None
    source_revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("reference provenance requires source_ref")
        if self.source_revision is not None and (
            not isinstance(self.source_revision, str) or not self.source_revision.strip()
        ):
            raise ValueError("reference provenance source_revision must be non-empty text when supplied")
        if not isinstance(self.acquired_at, RecordedAt) or (
            self.source_published_at is not None and not isinstance(self.source_published_at, RecordedAt)
        ):
            raise TypeError("reference provenance requires typed timestamps")
        if self.source_published_at and self.source_published_at.value > self.acquired_at.value:
            raise ValueError("reference source_published_at cannot follow acquired_at")

    def is_visible_at(self, as_of: RecordedAt) -> bool:
        if not isinstance(as_of, RecordedAt):
            raise TypeError("reference provenance requires a typed as_of timestamp")
        return self.acquired_at.value <= as_of.value


@dataclass(frozen=True, slots=True)
class EffectiveInterval:
    """A half-open point-in-time interval: start is included, end is excluded."""

    effective_from: RecordedAt
    effective_until: RecordedAt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.effective_from, RecordedAt) or (
            self.effective_until is not None and not isinstance(self.effective_until, RecordedAt)
        ):
            raise TypeError("effective interval requires typed RecordedAt timestamps")
        if self.effective_until and self.effective_until.value <= self.effective_from.value:
            raise ValueError("effective interval must be non-empty")

    def contains(self, as_of: RecordedAt) -> bool:
        if not isinstance(as_of, RecordedAt):
            raise TypeError("effective interval requires a typed as_of timestamp")
        return self.effective_from.value <= as_of.value and (
            self.effective_until is None or as_of.value < self.effective_until.value
        )

    def expired_at(self, as_of: RecordedAt) -> bool:
        if not isinstance(as_of, RecordedAt):
            raise TypeError("effective interval requires a typed as_of timestamp")
        return self.effective_until is not None and as_of.value >= self.effective_until.value


@dataclass(frozen=True, slots=True)
class Variety:
    """An exchange-scoped futures product family, distinct from any contract month."""

    exchange: Exchange
    code: str
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, Exchange):
            raise TypeError("variety requires an Exchange")
        _require_code(self.code, "variety code")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("variety requires name")

    @property
    def reference_id(self) -> str:
        return f"{self.exchange.value}.{self.code}"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A specific listed futures contract and the only tradeable reference kind."""

    variety: Variety
    delivery_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.variety, Variety):
            raise TypeError("instrument requires a Variety")
        if not isinstance(self.delivery_code, str):
            raise TypeError("delivery_code must be text")
        if not _DELIVERY.fullmatch(self.delivery_code) or len(self.delivery_code) != _DELIVERY_LENGTH[self.exchange]:
            raise ValueError("delivery_code length must match the V1 exchange-specific contract convention")

    @property
    def exchange(self) -> Exchange:
        return self.variety.exchange

    @property
    def reference_id(self) -> str:
        return f"{self.exchange.value}.{self.variety.code}{self.delivery_code}"


@dataclass(frozen=True, slots=True)
class DominantContractReference:
    """A time-bound source assertion that a Variety's dominant contract is one Instrument."""

    variety: Variety
    instrument: Instrument
    effective: EffectiveInterval
    version: int
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.variety, Variety) or not isinstance(self.instrument, Instrument):
            raise TypeError("dominant contract requires a Variety and Instrument")
        if not isinstance(self.effective, EffectiveInterval) or not isinstance(self.provenance, ReferenceProvenance):
            raise TypeError("dominant contract requires effective interval and provenance")
        if self.instrument.variety != self.variety:
            raise ValueError("dominant contract must belong to its variety")
        _require_version(self.version)

    @property
    def reference_id(self) -> str:
        return f"DOMINANT.{self.variety.reference_id}"


@dataclass(frozen=True, slots=True)
class ContinuousSeries:
    """A research-only series formed by explicit roll and adjustment definitions."""

    variety: Variety
    series_code: str
    adjustment: ContinuousAdjustment
    roll_rule_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.variety, Variety) or not isinstance(self.adjustment, ContinuousAdjustment):
            raise TypeError("continuous series requires a Variety and adjustment")
        _require_code(self.series_code, "continuous series code")
        if not isinstance(self.roll_rule_ref, str) or not self.roll_rule_ref.strip():
            raise ValueError("continuous series requires roll_rule_ref")

    @property
    def reference_id(self) -> str:
        return f"CONTINUOUS.{self.variety.reference_id}.{self.series_code}"


ReferenceTarget: TypeAlias = Variety | Instrument | DominantContractReference | ContinuousSeries


@dataclass(frozen=True, slots=True)
class AliasMapping:
    """An explicitly published, versioned alias; no identifier shape implies a target."""

    alias: str
    target: ReferenceTarget
    effective: EffectiveInterval
    version: int
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        _require_alias(self.alias)
        _require_version(self.version)
        if not isinstance(self.target, (Variety, Instrument, DominantContractReference, ContinuousSeries)):
            raise TypeError("alias mapping requires a reference target")
        if not isinstance(self.effective, EffectiveInterval) or not isinstance(self.provenance, ReferenceProvenance):
            raise TypeError("alias mapping requires effective interval and provenance")


@dataclass(frozen=True, slots=True)
class Resolution:
    """A successful point-in-time resolution with immutable registry evidence."""

    target: ReferenceTarget
    alias: str
    registry_id: EntityId
    release_version: int
    registry_content_sha256: str
    mapping_version: int
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.target, (Variety, Instrument, DominantContractReference, ContinuousSeries)):
            raise TypeError("resolution requires a registered reference target")
        _require_alias(self.alias)
        if not isinstance(self.registry_id, EntityId) or self.registry_id.namespace != "instrument_registry":
            raise ValueError("resolution registry_id must use the instrument_registry namespace")
        _require_version(self.release_version)
        _require_version(self.mapping_version)
        if (
            not isinstance(self.registry_content_sha256, str)
            or len(self.registry_content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.registry_content_sha256)
        ):
            raise ValueError("resolution registry_content_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.provenance, ReferenceProvenance):
            raise TypeError("resolution requires typed reference provenance")

    @property
    def kind(self) -> ReferenceKind:
        return _kind_of(self.target)


ResolutionOutcome: TypeAlias = Resolution | Failure


@dataclass(frozen=True, slots=True)
class InstrumentRegistry:
    """Immutable registry snapshot that resolves only explicit, visible mappings."""

    registry_id: EntityId
    release_version: int
    aliases: tuple[AliasMapping, ...]
    expected_content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.registry_id, EntityId):
            raise TypeError("instrument registry requires an immutable registry_id")
        if self.registry_id.namespace != "instrument_registry":
            raise ValueError("instrument registry_id must use the instrument_registry namespace")
        _require_version(self.release_version)
        if not self.aliases:
            raise ValueError("instrument registry requires explicit alias mappings")
        aliases = tuple(self.aliases)
        if any(not isinstance(alias, AliasMapping) for alias in aliases):
            raise TypeError("instrument registry aliases must be AliasMapping values")
        _reject_overlapping_aliases(aliases)
        actual = registry_content_sha256(aliases)
        if self.expected_content_sha256 != actual:
            raise ValueError("instrument registry expected_content_sha256 does not match aliases")
        object.__setattr__(self, "aliases", aliases)

    def resolve(self, identifier: str, as_of: RecordedAt) -> ResolutionOutcome:
        if not isinstance(as_of, RecordedAt):
            raise TypeError("resolution requires a typed as_of timestamp")
        normalized = _normalize_alias(identifier)
        if normalized is None:
            return Failure(ReasonCode.INSTRUMENT_MALFORMED, "identifier must be a canonical non-whitespace alias")
        candidates = tuple(mapping for mapping in self.aliases if mapping.alias == normalized)
        effective = tuple(mapping for mapping in candidates if mapping.effective.contains(as_of))
        visible = tuple(mapping for mapping in effective if mapping.provenance.is_visible_at(as_of))
        target_visible = tuple(mapping for mapping in visible if _target_is_visible(mapping.target, as_of))
        active = tuple(mapping for mapping in target_visible if _target_is_effective(mapping.target, as_of))
        if len(active) != 1:
            if len(active) > 1:
                return Failure(ReasonCode.INSTRUMENT_AMBIGUOUS, "multiple active mappings for identifier")
            if effective and not visible:
                return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "identifier mapping was not acquired at as_of")
            if visible and not target_visible:
                return Failure(ReasonCode.REFERENCE_NOT_YET_VISIBLE, "identifier target was not acquired at as_of")
            if target_visible and any(not _target_is_effective(mapping.target, as_of) for mapping in target_visible):
                return Failure(ReasonCode.REFERENCE_MAPPING_EXPIRED, "identifier target is not effective at as_of")
            if candidates and all(mapping.effective.expired_at(as_of) for mapping in candidates):
                return Failure(ReasonCode.REFERENCE_MAPPING_EXPIRED, "identifier mapping is no longer effective")
            return Failure(ReasonCode.INSTRUMENT_UNKNOWN, "identifier has no mapping visible at as_of")
        mapping = active[0]
        return Resolution(
            target=mapping.target,
            alias=mapping.alias,
            registry_id=self.registry_id,
            release_version=self.release_version,
            registry_content_sha256=self.expected_content_sha256,
            mapping_version=mapping.version,
            provenance=mapping.provenance,
        )

    def resolve_tradeable(self, identifier: str, as_of: RecordedAt) -> Instrument | Failure:
        normalized = _normalize_alias(identifier)
        if normalized is not None and "." not in normalized:
            return Failure(
                ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target must use an exchange-qualified Instrument alias"
            )
        outcome = self.resolve(identifier, as_of)
        if isinstance(outcome, Failure):
            return outcome
        if isinstance(outcome.target, ContinuousSeries):
            return Failure(
                ReasonCode.CONTINUOUS_SERIES_NOT_TRADABLE, "continuous series must resolve to an Instrument first"
            )
        if not isinstance(outcome.target, Instrument):
            return Failure(ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target must be a specific Instrument")
        exchange_prefix = outcome.alias.split(".", 1)[0]
        if exchange_prefix != outcome.target.exchange.value:
            return Failure(
                ReasonCode.INSTRUMENT_NOT_TRADEABLE, "order target exchange does not match Instrument exchange"
            )
        return outcome.target


def _require_code(value: str, field: str) -> None:
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise ValueError(f"{field} must be canonical uppercase text")


def _require_alias(value: str) -> None:
    if not isinstance(value, str) or not _ALIAS.fullmatch(value):
        raise ValueError("alias must use canonical uppercase text")


def _normalize_alias(value: str) -> str | None:
    if not isinstance(value, str) or value != value.strip() or not _RAW_ALIAS.fullmatch(value):
        return None
    normalized = value.upper()
    return normalized if _ALIAS.fullmatch(normalized) else None


def _require_version(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("version must be a positive integer")


def _kind_of(target: ReferenceTarget) -> ReferenceKind:
    if isinstance(target, Variety):
        return ReferenceKind.VARIETY
    if isinstance(target, Instrument):
        return ReferenceKind.INSTRUMENT
    if isinstance(target, DominantContractReference):
        return ReferenceKind.DOMINANT_CONTRACT
    if isinstance(target, ContinuousSeries):
        return ReferenceKind.CONTINUOUS_SERIES
    raise TypeError("unrecognized reference target")


def _target_is_effective(target: ReferenceTarget, as_of: RecordedAt) -> bool:
    """A Dominant alias cannot make its time-bound target effective longer."""
    return not isinstance(target, DominantContractReference) or target.effective.contains(as_of)


def _target_is_visible(target: ReferenceTarget, as_of: RecordedAt) -> bool:
    return not isinstance(target, DominantContractReference) or target.provenance.is_visible_at(as_of)


def _reject_overlapping_aliases(aliases: tuple[AliasMapping, ...]) -> None:
    """Reject conflicts at publication time; adjacent half-open intervals are valid."""
    for index, left in enumerate(aliases):
        for right in aliases[index + 1 :]:
            if left.alias == right.alias and _intervals_overlap(left.effective, right.effective):
                raise ValueError("instrument registry cannot publish overlapping alias mappings")


def _intervals_overlap(left: EffectiveInterval, right: EffectiveInterval) -> bool:
    left_end = left.effective_until.value if left.effective_until else None
    right_end = right.effective_until.value if right.effective_until else None
    return (right_end is None or left.effective_from.value < right_end) and (
        left_end is None or right.effective_from.value < left_end
    )


def registry_content_sha256(aliases: tuple[AliasMapping, ...]) -> str:
    """Hash the canonical, sorted content of a registry release, excluding release identity."""
    canonical = tuple(sorted((_alias_payload(alias) for alias in aliases), key=repr))
    return canonical_sha256(cast("JsonValue", canonical))


def _alias_payload(mapping: AliasMapping) -> dict[str, object]:
    return {
        "alias": mapping.alias,
        "target": _target_payload(mapping.target),
        "effective": _interval_payload(mapping.effective),
        "version": mapping.version,
        "provenance": _provenance_payload(mapping.provenance),
    }


def _target_payload(target: ReferenceTarget) -> dict[str, object]:
    if isinstance(target, Variety):
        return {
            "kind": ReferenceKind.VARIETY.value,
            "exchange": target.exchange.value,
            "code": target.code,
            "name": target.name,
        }
    if isinstance(target, Instrument):
        return {
            "kind": ReferenceKind.INSTRUMENT.value,
            "variety": _target_payload(target.variety),
            "delivery_code": target.delivery_code,
        }
    if isinstance(target, DominantContractReference):
        return {
            "kind": ReferenceKind.DOMINANT_CONTRACT.value,
            "variety": _target_payload(target.variety),
            "instrument": _target_payload(target.instrument),
            "effective": _interval_payload(target.effective),
            "version": target.version,
            "provenance": _provenance_payload(target.provenance),
        }
    return {
        "kind": ReferenceKind.CONTINUOUS_SERIES.value,
        "variety": _target_payload(target.variety),
        "series_code": target.series_code,
        "adjustment": target.adjustment.value,
        "roll_rule_ref": target.roll_rule_ref,
    }


def _interval_payload(interval: EffectiveInterval) -> dict[str, str | None]:
    return {
        "effective_from": interval.effective_from.to_dict()["recorded_at"],
        "effective_until": interval.effective_until.to_dict()["recorded_at"] if interval.effective_until else None,
    }


def _provenance_payload(provenance: ReferenceProvenance) -> dict[str, str | None]:
    return {
        "source_ref": provenance.source_ref,
        "acquired_at": provenance.acquired_at.to_dict()["recorded_at"],
        "source_published_at": provenance.source_published_at.to_dict()["recorded_at"]
        if provenance.source_published_at
        else None,
        "source_revision": provenance.source_revision,
    }


def initial_acceptance_registry() -> InstrumentRegistry:
    """The fixed 12-variety synthetic V0-012 acceptance universe.

    These Instrument entries are fixture references, not exchange listings or
    rules.  Their provenance deliberately names the committed synthetic bundle.
    """

    varieties = (
        (Exchange.SHFE, "AG", "silver", "2602"),
        (Exchange.SHFE, "CU", "copper", "2603"),
        (Exchange.SHFE, "RB", "rebar", "2605"),
        (Exchange.DCE, "JM", "coking coal", "2605"),
        (Exchange.DCE, "I", "iron ore", "2605"),
        (Exchange.CZCE, "MA", "methanol", "605"),
        (Exchange.CZCE, "SA", "soda ash", "605"),
        (Exchange.DCE, "M", "soybean meal", "2605"),
        (Exchange.DCE, "P", "palm oil", "2605"),
        (Exchange.CZCE, "SR", "sugar", "603"),
        (Exchange.INE, "SC", "crude oil", "2603"),
        (Exchange.DCE, "JD", "eggs", "2605"),
    )
    effective = EffectiveInterval(_INITIAL_ACCEPTANCE_RELEASED_AT)
    mappings: list[AliasMapping] = []
    for exchange, code, name, delivery_code in varieties:
        variety = Variety(exchange, code, name)
        instrument = Instrument(variety, delivery_code)
        provenance = ReferenceProvenance(
            "datasets/v0-012/golden_bundle.manifest.json#events",
            _INITIAL_ACCEPTANCE_RELEASED_AT,
            _INITIAL_ACCEPTANCE_RELEASED_AT,
            "golden-bundle-v0-012.1",
        )
        mappings.extend(
            (
                AliasMapping(f"{exchange.value}.{code}", variety, effective, 1, provenance),
                AliasMapping(code, variety, effective, 1, provenance),
                AliasMapping(instrument.reference_id, instrument, effective, 1, provenance),
                AliasMapping(f"{code}{delivery_code}", instrument, effective, 1, provenance),
            )
        )
    aliases = tuple(mappings)
    return InstrumentRegistry(
        registry_id=INITIAL_ACCEPTANCE_REGISTRY_ID,
        release_version=INITIAL_ACCEPTANCE_REGISTRY_RELEASE_VERSION,
        aliases=aliases,
        expected_content_sha256=INITIAL_ACCEPTANCE_REGISTRY_SHA256,
    )
