"""Immutable, point-in-time market observations and quality-gated snapshots.

This V1 boundary deliberately implements only quote and OHLCV-bar facts.  It
does not manufacture term structure, basis, volatility, liquidity, features,
or a market-state interpretation from incomplete observations.  Those are
separate, versioned derived products in later bounded contexts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from collections.abc import Callable
from typing import TypeAlias, cast

from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    Price,
    Quantity,
    ReasonCode,
    RecordedAt,
    SchemaVersion,
    ShanghaiTimestamp,
    TradingDate,
    canonical_sha256,
)
from futures_agent_os.shared_kernel.observability import JsonValue

from .contract_rules import (
    ContractRuleRegistry,
    ContractRuleResolver,
    PriceLimitRange,
    RuleResolution,
    RuleSetRef,
)
from .data_lake import DatasetManifest, dataset_manifest_sha256
from .instrument_registry import ContinuousSeries, Instrument, ReferenceProvenance, Resolution
from .trading_calendar import SessionPhase, TradingCalendar, TradingDateResolution


_DIGEST_LENGTH = 64
_MINUTE = timedelta(minutes=1)


class ObservationKind(StrEnum):
    """The only raw market facts V1-004 accepts."""

    QUOTE = "QUOTE"
    BAR = "BAR"
    TRADE = "TRADE"
    SETTLEMENT = "SETTLEMENT"
    OPEN_INTEREST = "OPEN_INTEREST"


class SnapshotPurpose(StrEnum):
    DISPLAY = "DISPLAY"
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    EXECUTION = "EXECUTION"


class SourceTrust(StrEnum):
    PRIMARY = "PRIMARY"
    FALLBACK = "FALLBACK"
    TIMESTAMP_UNTRUSTED = "TIMESTAMP_UNTRUSTED"


class BarStatus(StrEnum):
    """A bar is never silently promoted from in-progress to final."""

    FINAL = "FINAL"
    IN_PROGRESS = "IN_PROGRESS"
    INCOMPLETE = "INCOMPLETE"


class MarketQualityCode(StrEnum):
    """Stable quality annotations; wording is intentionally not the contract."""

    MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    OUT_OF_ORDER_OBSERVATION = "OUT_OF_ORDER_OBSERVATION"
    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    CONFLICTING_OBSERVATION = "CONFLICTING_OBSERVATION"
    FUTURE_AVAILABILITY = "FUTURE_AVAILABILITY"
    INCOMPLETE_BAR = "INCOMPLETE_BAR"
    GAP_DETECTED = "GAP_DETECTED"
    PRICE_JUMP = "PRICE_JUMP"
    PRICE_LIMIT_CONFIRMED = "PRICE_LIMIT_CONFIRMED"
    SOURCE_FALLBACK = "SOURCE_FALLBACK"
    TIMESTAMP_UNTRUSTED = "TIMESTAMP_UNTRUSTED"


@dataclass(frozen=True, slots=True)
class BarInterval:
    """An explicit bar cadence; calendar semantics are never inferred here."""

    label: str
    duration: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip() or len(self.label) > 32:
            raise ValueError("bar interval requires a stable non-empty label")
        if not isinstance(self.duration, timedelta) or self.duration < _MINUTE:
            raise ValueError("bar interval duration must be at least one minute")
        if self.duration.microseconds != 0:
            raise ValueError("bar interval duration must use whole seconds")

    def to_dict(self) -> dict[str, int | str]:
        return {"label": self.label, "duration_seconds": int(self.duration.total_seconds())}


@dataclass(frozen=True, slots=True)
class DatasetManifestRef:
    """The exact manifest metadata that makes a snapshot replayable.

    The dataset object hash alone is insufficient: a different schema or
    revision can give identical bytes a different meaning.
    """

    manifest_id: EntityId
    manifest_sha256: str
    content_sha256: str
    schema_name: str
    schema_version: SchemaVersion
    revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.manifest_id, EntityId) or self.manifest_id.namespace != "dataset":
            raise ValueError("dataset manifest ref requires a dataset id")
        _require_digest(self.manifest_sha256, "manifest_sha256")
        _require_digest(self.content_sha256, "content_sha256")
        if not isinstance(self.schema_name, str) or not self.schema_name.strip():
            raise ValueError("dataset manifest ref requires schema_name")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("dataset manifest ref requires SchemaVersion")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("dataset manifest ref revision must be positive")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "manifest_id": str(self.manifest_id),
            "manifest_sha256": self.manifest_sha256,
            "content_sha256": self.content_sha256,
            "schema_name": self.schema_name,
            "schema_version": str(self.schema_version),
            "revision": self.revision,
        }

    @classmethod
    def from_manifest(cls, manifest: DatasetManifest) -> DatasetManifestRef:
        if not isinstance(manifest, DatasetManifest):
            raise TypeError("DatasetManifestRef.from_manifest requires DatasetManifest")
        return cls(
            manifest.dataset_id,
            dataset_manifest_sha256(manifest),
            manifest.content_hash.removeprefix("sha256:"),
            manifest.schema_name,
            manifest.schema_version,
            manifest.revision.revision,
        )


@dataclass(frozen=True, slots=True)
class DatasetRecordRef:
    manifest_id: EntityId
    locator: str
    record_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest_id, EntityId) or self.manifest_id.namespace != "dataset":
            raise ValueError("dataset record ref requires dataset manifest id")
        if not isinstance(self.locator, str) or not self.locator.strip() or self.locator != self.locator.strip():
            raise ValueError("dataset record ref requires canonical locator")
        _require_digest(self.record_sha256, "record_sha256")


MarketReference: TypeAlias = Instrument | ContinuousSeries


@dataclass(frozen=True, slots=True)
class MarketObservation:
    """One source fact with event and system-availability time kept distinct."""

    observation_id: EntityId
    reference: MarketReference
    kind: ObservationKind
    event_time: RecordedAt
    available_time: RecordedAt
    ingested_at: RecordedAt
    source: ReferenceProvenance
    source_trust: SourceTrust
    schema_version: SchemaVersion
    source_sequence: int
    dataset_record_ref: DatasetRecordRef | None = None
    last_price: Price | None = None
    bid_price: Price | None = None
    ask_price: Price | None = None
    bid_size: Quantity | None = None
    ask_size: Quantity | None = None
    open_price: Price | None = None
    high_price: Price | None = None
    low_price: Price | None = None
    close_price: Price | None = None
    volume: Quantity | None = None
    open_interest: Quantity | None = None
    bar_interval: BarInterval | None = None
    bar_status: BarStatus | None = None
    component_instrument: Instrument | None = None
    revision: int = 1
    supersedes_observation_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, EntityId) or self.observation_id.namespace != "market_observation":
            raise ValueError("market observation requires a market_observation id")
        if not isinstance(self.reference, (Instrument, ContinuousSeries)):
            raise TypeError("market observation requires an Instrument or ContinuousSeries")
        if isinstance(self.reference, Instrument) and self.component_instrument is not None:
            raise ValueError("Instrument observation cannot declare a continuous component_instrument")
        if isinstance(self.reference, ContinuousSeries):
            if (
                not isinstance(self.component_instrument, Instrument)
                or self.component_instrument.variety != self.reference.variety
            ):
                raise ValueError("ContinuousSeries observation requires an explicit same-Variety component_instrument")
        if not isinstance(self.kind, ObservationKind):
            raise TypeError("market observation requires an ObservationKind")
        if not all(isinstance(value, RecordedAt) for value in (self.event_time, self.available_time, self.ingested_at)):
            raise TypeError("market observation requires typed event_time, available_time, and ingested_at")
        if self.available_time.value < self.event_time.value or self.ingested_at.value < self.available_time.value:
            raise ValueError("market observation requires event_time <= available_time <= ingested_at")
        if not isinstance(self.source, ReferenceProvenance) or not isinstance(self.source_trust, SourceTrust):
            raise TypeError("market observation requires provenance and source trust")
        if self.source.acquired_at.value > self.available_time.value:
            raise ValueError("market observation available_time cannot precede source acquisition")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("market observation requires a SchemaVersion")
        if (
            isinstance(self.source_sequence, bool)
            or not isinstance(self.source_sequence, int)
            or self.source_sequence < 0
        ):
            raise ValueError("market observation source_sequence must be a non-negative integer")
        if self.dataset_record_ref is not None and not isinstance(self.dataset_record_ref, DatasetRecordRef):
            raise TypeError("market observation dataset_record_ref must be DatasetRecordRef")
        _validate_prices(self)
        _validate_quantities(self)
        if self.kind is ObservationKind.BAR:
            if not isinstance(self.bar_interval, BarInterval) or not isinstance(self.bar_status, BarStatus):
                raise ValueError("bar observation requires bar_interval and bar_status")
        elif self.bar_interval is not None or self.bar_status is not None:
            raise ValueError("non-bar observation cannot declare bar fields")
        if self.kind is ObservationKind.TRADE and self.last_price is None:
            raise ValueError("trade observation requires last_price")
        if self.kind is ObservationKind.SETTLEMENT and self.last_price is None:
            raise ValueError("settlement observation requires last_price")
        if self.kind is ObservationKind.OPEN_INTEREST and self.open_interest is None:
            raise ValueError("open-interest observation requires open_interest")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("market observation revision must be positive")
        if self.revision == 1 and self.supersedes_observation_id is not None:
            raise ValueError("initial market observation revision cannot supersede another observation")
        if self.revision > 1:
            if (
                not isinstance(self.supersedes_observation_id, EntityId)
                or self.supersedes_observation_id.namespace != "market_observation"
            ):
                raise ValueError("revised market observation requires supersedes_observation_id")
            if self.supersedes_observation_id == self.observation_id:
                raise ValueError("market observation cannot supersede itself")

    @property
    def reference_id(self) -> str:
        return self.reference.reference_id

    @property
    def natural_key(self) -> tuple[str, str, str, str, str | None, str | None]:
        """Identity of one source fact across immutable corrections.

        The source revision is intentionally *not* part of the lineage: a
        correction may have a new source revision while still correcting the
        same published fact.  A source reference, instrument/series, kind,
        event time, bar cadence, and continuous component together are the
        governed natural key.
        """
        return (
            self.reference_id,
            self.kind.value,
            self.event_time.to_dict()["recorded_at"],
            self.source.source_ref,
            self.bar_interval.label if self.bar_interval else None,
            self.component_instrument.reference_id if self.component_instrument else None,
        )


@dataclass(frozen=True, slots=True)
class PurposeFreshnessPolicy:
    """Purpose-specific freshness bound, constrained by the attributed session."""

    purpose: SnapshotPurpose
    maximum_age: timedelta
    allowed_session_phases: tuple[SessionPhase, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, SnapshotPurpose):
            raise TypeError("freshness policy requires a SnapshotPurpose")
        if not isinstance(self.maximum_age, timedelta) or self.maximum_age < timedelta(0):
            raise ValueError("freshness maximum_age must be non-negative")
        if self.maximum_age.microseconds != 0:
            raise ValueError("freshness maximum_age must use whole seconds")
        phases = tuple(sorted(self.allowed_session_phases, key=lambda item: item.value))
        if not phases or any(not isinstance(phase, SessionPhase) for phase in phases):
            raise ValueError("freshness policy requires explicit SessionPhase values")
        object.__setattr__(self, "allowed_session_phases", phases)

    def to_dict(self) -> dict[str, object]:
        return {
            "purpose": self.purpose.value,
            "maximum_age_seconds": int(self.maximum_age.total_seconds()),
            "allowed_session_phases": tuple(phase.value for phase in self.allowed_session_phases),
        }


@dataclass(frozen=True, slots=True)
class MarketQualityPolicy:
    """Declared, versioned thresholds used to assess one frozen snapshot."""

    policy_id: EntityId
    version: int
    freshness_by_purpose: tuple[PurposeFreshnessPolicy, ...]
    gap_after: timedelta
    max_price_jump_ratio: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, EntityId) or self.policy_id.namespace != "market_quality_policy":
            raise ValueError("market quality policy requires a market_quality_policy id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("market quality policy version must be positive")
        freshness = tuple(sorted(self.freshness_by_purpose, key=lambda item: item.purpose.value))
        if set(item.purpose for item in freshness) != set(SnapshotPurpose) or len(freshness) != len(SnapshotPurpose):
            raise ValueError("market quality policy requires exactly one freshness policy for every purpose")
        object.__setattr__(self, "freshness_by_purpose", freshness)
        if not isinstance(self.gap_after, timedelta) or self.gap_after < _MINUTE:
            raise ValueError("market quality gap_after must be at least one minute")
        if self.gap_after.microseconds != 0:
            raise ValueError("market quality gap_after must use whole seconds")
        if not isinstance(self.max_price_jump_ratio, Decimal) or not self.max_price_jump_ratio.is_finite():
            raise TypeError("market quality max_price_jump_ratio must be a finite Decimal")
        if self.max_price_jump_ratio < Decimal("0"):
            raise ValueError("market quality max_price_jump_ratio must be non-negative")

    def for_purpose(self, purpose: SnapshotPurpose) -> PurposeFreshnessPolicy:
        return next(item for item in self.freshness_by_purpose if item.purpose is purpose)

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": str(self.policy_id),
            "version": self.version,
            "freshness_by_purpose": tuple(item.to_dict() for item in self.freshness_by_purpose),
            "gap_after_seconds": int(self.gap_after.total_seconds()),
            "max_price_jump_ratio": str(self.max_price_jump_ratio),
        }


@dataclass(frozen=True, slots=True)
class SnapshotFreshness:
    """The oldest usable source availability in a snapshot, measured at as_of."""

    oldest_available_time: RecordedAt
    age: timedelta
    age_by_purpose: tuple[tuple[SnapshotPurpose, bool], ...]

    def is_fresh_for(self, purpose: SnapshotPurpose) -> bool:
        return dict(self.age_by_purpose)[purpose]


@dataclass(frozen=True, slots=True)
class MarketDataQuality:
    """Deterministic quality result; consumers choose an explicit purpose gate."""

    issues: tuple[MarketQualityIssue, ...]
    freshness: SnapshotFreshness

    def has(self, *codes: MarketQualityCode) -> bool:
        return any(issue.code in codes for issue in self.issues)


@dataclass(frozen=True, slots=True)
class MarketQualityIssue:
    """A structured quality fact, intentionally separate from a request failure."""

    code: MarketQualityCode
    observation_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, MarketQualityCode):
            raise TypeError("market quality issue requires MarketQualityCode")
        observation_ids = tuple(self.observation_ids)
        if any(not isinstance(item, EntityId) or item.namespace != "market_observation" for item in observation_ids):
            raise ValueError("market quality issue observation_ids must be market observations")
        object.__setattr__(self, "observation_ids", observation_ids)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """A content-addressed, immutable point-in-time market input boundary."""

    snapshot_id: EntityId
    as_of: RecordedAt
    trading_date_resolution: TradingDateResolution
    trading_calendar: TradingCalendar
    observations: tuple[MarketObservation, ...]
    reference_resolutions: tuple[Resolution, ...]
    contract_rule_registry: ContractRuleRegistry
    rule_resolution: RuleResolution
    dataset_manifest: DatasetManifest
    schema_version: SchemaVersion
    quality_policy: MarketQualityPolicy
    intended_purpose: SnapshotPurpose
    expected_content_sha256: str
    active_observations: tuple[MarketObservation, ...] = field(init=False)
    quality: MarketDataQuality = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, EntityId) or self.snapshot_id.namespace != "market_snapshot":
            raise ValueError("market snapshot requires a market_snapshot id")
        if not isinstance(self.as_of, RecordedAt) or not isinstance(
            self.trading_date_resolution, TradingDateResolution
        ):
            raise TypeError("market snapshot requires typed as_of and TradingDateResolution")
        if self.trading_date_resolution.as_of != self.as_of:
            raise ValueError("market snapshot calendar resolution as_of must exactly match snapshot as_of")
        if not isinstance(self.trading_calendar, TradingCalendar):
            raise TypeError("market snapshot requires the immutable TradingCalendar behind its resolution")
        observations = tuple(sorted(self.observations, key=_observation_sort_key))
        if not observations or any(not isinstance(item, MarketObservation) for item in observations):
            raise ValueError("market snapshot requires one or more MarketObservation values")
        _validate_observation_revision_history(observations)
        if any(
            item.available_time.value > self.as_of.value or item.ingested_at.value > self.as_of.value
            for item in observations
        ):
            raise ValueError("market snapshot as_of cannot include observations unavailable at as_of or un-ingested")
        active_observations = select_active_observations(observations, self.as_of, _validated=True)
        resolutions = tuple(sorted(self.reference_resolutions, key=lambda item: item.target.reference_id))
        if any(not isinstance(item, Resolution) for item in resolutions):
            raise TypeError("market snapshot reference_resolutions must be registry Resolution values")
        _validate_reference_resolutions(observations, resolutions)
        if any(not item.provenance.is_visible_at(self.as_of) for item in resolutions):
            raise ValueError("market snapshot cannot bind a registry resolution unavailable at as_of")
        _validate_rule_resolution(
            self.contract_rule_registry,
            self.rule_resolution,
            observations,
            self.trading_date_resolution.trading_date,
            self.as_of,
        )
        _validate_calendar_resolution(
            self.trading_date_resolution, self.trading_calendar, observations, self.rule_resolution.rule.instrument
        )
        _validate_dataset_manifest(self.dataset_manifest, observations, self.as_of)
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(
            self.quality_policy, MarketQualityPolicy
        ):
            raise TypeError("market snapshot requires schema version and quality policy")
        if not isinstance(self.intended_purpose, SnapshotPurpose):
            raise TypeError("market snapshot requires an intended SnapshotPurpose")
        actual = market_snapshot_content_sha256(
            self.as_of,
            self.trading_date_resolution,
            self.trading_calendar,
            observations,
            resolutions,
            self.contract_rule_registry,
            self.rule_resolution,
            self.dataset_manifest,
            self.schema_version,
            self.quality_policy,
            self.intended_purpose,
        )
        if self.expected_content_sha256 != actual:
            raise ValueError("market snapshot expected_content_sha256 does not match immutable content")
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "active_observations", active_observations)
        object.__setattr__(self, "reference_resolutions", resolutions)
        object.__setattr__(
            self,
            "quality",
            assess_market_quality(
                active_observations,
                self.as_of,
                self.quality_policy,
                price_limits=self.rule_resolution.rule.price_limits,
                _validated=True,
            ),
        )

    @classmethod
    def freeze(
        cls,
        snapshot_id: EntityId,
        as_of: RecordedAt,
        trading_date_resolution: TradingDateResolution,
        trading_calendar: TradingCalendar,
        observations: tuple[MarketObservation, ...],
        reference_resolutions: tuple[Resolution, ...],
        contract_rule_registry: ContractRuleRegistry,
        rule_resolution: RuleResolution,
        dataset_manifest: DatasetManifest,
        schema_version: SchemaVersion,
        quality_policy: MarketQualityPolicy,
        intended_purpose: SnapshotPurpose,
    ) -> MarketSnapshot:
        """Create a snapshot only after calculating its complete content hash."""
        content_sha256 = market_snapshot_content_sha256(
            as_of,
            trading_date_resolution,
            trading_calendar,
            observations,
            reference_resolutions,
            contract_rule_registry,
            rule_resolution,
            dataset_manifest,
            schema_version,
            quality_policy,
            intended_purpose,
        )
        return cls(
            snapshot_id,
            as_of,
            trading_date_resolution,
            trading_calendar,
            observations,
            reference_resolutions,
            contract_rule_registry,
            rule_resolution,
            dataset_manifest,
            schema_version,
            quality_policy,
            intended_purpose,
            content_sha256,
        )

    def eligible_for(self, purpose: SnapshotPurpose) -> None | Failure:
        """Fail closed for a requested use, while retaining displayable evidence."""
        if not isinstance(purpose, SnapshotPurpose):
            raise TypeError("snapshot purpose must be a SnapshotPurpose")
        if purpose is not self.intended_purpose:
            return Failure(ReasonCode.DATA_PURPOSE_DENIED, "snapshot was frozen for a different purpose")
        issues = self.quality
        if issues.has(MarketQualityCode.FUTURE_AVAILABILITY):
            return Failure(ReasonCode.DATA_FUTURE, "snapshot contains observations unavailable at as_of")
        freshness_rule = self.quality_policy.for_purpose(purpose)
        if self.trading_date_resolution.phase not in freshness_rule.allowed_session_phases:
            return Failure(ReasonCode.DATA_STALE, "snapshot session phase is not permitted for requested purpose")
        if not issues.freshness.is_fresh_for(purpose):
            if purpose is SnapshotPurpose.DISPLAY:
                # Display remains possible but its stale status remains part of
                # the returned immutable quality evidence.
                return None
            return Failure(ReasonCode.DATA_STALE, "snapshot exceeds its purpose-specific freshness policy")
        if purpose is SnapshotPurpose.DISPLAY:
            return None
        if purpose is SnapshotPurpose.EXECUTION and any(
            not isinstance(item.reference, Instrument) for item in self.active_observations
        ):
            return Failure(ReasonCode.CONTINUOUS_SERIES_NOT_TRADABLE, "continuous series cannot be an execution input")
        if (
            purpose is SnapshotPurpose.EXECUTION
            and self.trading_date_resolution.trading_date.value > self.rule_resolution.rule.last_trading_date.value
        ):
            return Failure(ReasonCode.INSTRUMENT_NOT_TRADEABLE, "contract is beyond its last trading date")
        if issues.has(MarketQualityCode.CONFLICTING_OBSERVATION):
            return Failure(ReasonCode.DATA_CONFLICT, "snapshot contains conflicting observations")
        if issues.has(MarketQualityCode.MISSING_REQUIRED_FIELDS):
            return Failure(ReasonCode.DATA_MISSING, "snapshot omits required fields for its observation kind")
        if purpose is SnapshotPurpose.RESEARCH:
            return None
        if issues.has(
            MarketQualityCode.OUT_OF_ORDER_OBSERVATION,
            MarketQualityCode.DUPLICATE_OBSERVATION,
            MarketQualityCode.GAP_DETECTED,
            MarketQualityCode.PRICE_JUMP,
            MarketQualityCode.INCOMPLETE_BAR,
            MarketQualityCode.TIMESTAMP_UNTRUSTED,
        ):
            return Failure(ReasonCode.DATA_CONFLICT, "snapshot is not reliable enough for deterministic replay")
        if purpose is SnapshotPurpose.BACKTEST:
            return None
        if issues.has(MarketQualityCode.SOURCE_FALLBACK):
            return Failure(ReasonCode.DATA_SOURCE_FALLBACK, "snapshot uses a fallback source")
        if not any(
            item.kind is ObservationKind.QUOTE
            and item.bid_price is not None
            and item.ask_price is not None
            and item.bid_size is not None
            and item.ask_size is not None
            and _quantity_amount(item.bid_size) > 0
            and _quantity_amount(item.ask_size) > 0
            and item.source_trust is SourceTrust.PRIMARY
            for item in self.active_observations
        ):
            return Failure(ReasonCode.DATA_MISSING, "execution requires a primary positive-size two-sided quote")
        return None


def select_active_observations(
    observations: tuple[MarketObservation, ...], as_of: RecordedAt, *, _validated: bool = False
) -> tuple[MarketObservation, ...]:
    """Select visible revision leaves at ``as_of`` without using tuple order.

    A correction becomes active only when it has both become externally
    available and has been ingested by this system.  The complete immutable
    history remains in the snapshot; this projection is solely the usable
    market fact set at the requested point in time.
    """
    if not isinstance(as_of, RecordedAt):
        raise TypeError("active observation selection requires a RecordedAt as_of")
    history = tuple(observations)
    if not history or any(not isinstance(item, MarketObservation) for item in history):
        raise ValueError("active observation selection requires observations")
    if not _validated:
        _validate_observation_revision_history(history)
    visible = {
        item.observation_id: item
        for item in history
        if item.available_time.value <= as_of.value and item.ingested_at.value <= as_of.value
    }
    superseded_visible = {
        item.supersedes_observation_id for item in visible.values() if item.supersedes_observation_id is not None
    }
    return tuple(
        sorted(
            (item for identifier, item in visible.items() if identifier not in superseded_visible),
            key=_observation_sort_key,
        )
    )


def _validate_observation_revision_history(observations: tuple[MarketObservation, ...]) -> None:
    """Validate a single immutable, non-forking correction graph.

    The graph belongs to a source lineage, never to caller order.  We permit
    independent source facts with the same natural key so duplicate/conflict
    quality remains observable; once an observation claims to be a revision,
    however, its exact predecessor and every timing boundary are mandatory.
    """
    by_id: dict[EntityId, MarketObservation] = {}
    for item in observations:
        if item.observation_id in by_id:
            raise ValueError("DATA_CONFLICT: duplicate market observation id")
        by_id[item.observation_id] = item

    successors: dict[EntityId, list[MarketObservation]] = {}
    for item in observations:
        predecessor_id = item.supersedes_observation_id
        if item.revision == 1:
            continue
        assert predecessor_id is not None  # MarketObservation validates this local invariant.
        if predecessor_id not in by_id:
            raise ValueError("DATA_CONFLICT: revised market observation predecessor is absent from history")
        successors.setdefault(predecessor_id, []).append(item)

    if any(len(items) > 1 for items in successors.values()):
        raise ValueError("DATA_CONFLICT: market observation revision history forks")

    # Check before the semantic successor checks.  Strictly incrementing
    # revisions would also reject a cycle, but a structural failure should not
    # be disguised as a mere version-number failure.
    for start in by_id:
        seen: set[EntityId] = set()
        current = start
        while current in by_id:
            if current in seen:
                raise ValueError("DATA_CONFLICT: market observation revision history contains a cycle")
            seen.add(current)
            predecessor_id = by_id[current].supersedes_observation_id
            if predecessor_id is None:
                break
            current = predecessor_id

    for item in observations:
        if item.revision == 1:
            continue
        assert item.supersedes_observation_id is not None
        predecessor = by_id[item.supersedes_observation_id]
        if item.natural_key != predecessor.natural_key:
            raise ValueError(
                "DATA_CONFLICT: revised market observation must preserve its natural key and source lineage"
            )
        if item.revision != predecessor.revision + 1:
            raise ValueError("DATA_CONFLICT: market observation revision must increment its predecessor by one")
        if item.available_time.value <= predecessor.available_time.value:
            raise ValueError("DATA_CONFLICT: revised market observation must have a strictly later available_time")
        if item.ingested_at.value <= predecessor.ingested_at.value:
            raise ValueError("DATA_CONFLICT: revised market observation must have a strictly later ingested_at")


def assess_market_quality(
    observations: tuple[MarketObservation, ...],
    as_of: RecordedAt,
    policy: MarketQualityPolicy,
    *,
    price_limits: PriceLimitRange | None = None,
    _validated: bool = False,
) -> MarketDataQuality:
    """Assess active, visible revision leaves; retain raw history elsewhere."""
    if not isinstance(as_of, RecordedAt) or not isinstance(policy, MarketQualityPolicy):
        raise TypeError("market quality assessment requires RecordedAt and MarketQualityPolicy")
    if not observations or any(not isinstance(item, MarketObservation) for item in observations):
        raise ValueError("market quality assessment requires observations")
    if price_limits is not None and not isinstance(price_limits, PriceLimitRange):
        raise TypeError("market quality assessment price_limits must be a PriceLimitRange")
    active_observations = select_active_observations(observations, as_of, _validated=_validated)
    # Direct quality inspection is also used to diagnose a wholly future batch.
    # A frozen snapshot rejects that batch before it reaches this function, so
    # no purpose decision ever treats this fallback as usable data.
    assessed_observations = active_observations or tuple(observations)
    issue_observations: dict[MarketQualityCode, set[EntityId]] = {}

    def add(code: MarketQualityCode, *items: MarketObservation) -> None:
        issue_observations.setdefault(code, set()).update(item.observation_id for item in items)

    oldest = min((item.available_time for item in assessed_observations), key=lambda item: item.value)
    age = as_of.value - oldest.value
    streams: dict[tuple[str, ObservationKind, str | None], list[MarketObservation]] = {}
    fingerprints: dict[tuple[str, ObservationKind, str, str | None], set[str]] = {}
    last_event: dict[tuple[str, ObservationKind, str | None], RecordedAt] = {}
    for item in sorted(assessed_observations, key=_arrival_sort_key):
        if item.available_time.value > as_of.value or item.ingested_at.value > as_of.value:
            add(MarketQualityCode.FUTURE_AVAILABILITY, item)
        if _missing_required_fields(item):
            add(MarketQualityCode.MISSING_REQUIRED_FIELDS, item)
        if item.kind is ObservationKind.BAR and item.bar_status is not BarStatus.FINAL:
            add(MarketQualityCode.INCOMPLETE_BAR, item)
        if item.source_trust is SourceTrust.FALLBACK:
            add(MarketQualityCode.SOURCE_FALLBACK, item)
        if item.source_trust is SourceTrust.TIMESTAMP_UNTRUSTED:
            add(MarketQualityCode.TIMESTAMP_UNTRUSTED, item)
        stream_key = (item.reference_id, item.kind, item.bar_interval.label if item.bar_interval else None)
        previous = last_event.get(stream_key)
        if previous is not None and item.event_time.value < previous.value:
            add(MarketQualityCode.OUT_OF_ORDER_OBSERVATION, item)
        if previous is None or item.event_time.value > previous.value:
            last_event[stream_key] = item.event_time
        streams.setdefault(stream_key, []).append(item)
        event_key = (item.reference_id, item.kind, item.event_time.to_dict()["recorded_at"], stream_key[2])
        fingerprints.setdefault(event_key, set()).add(_observation_content_sha256(item))
    for values in fingerprints.values():
        if len(values) == 1:
            # A set loses count, therefore find keys with more than one record below.
            continue
        matching = tuple(
            item
            for item in assessed_observations
            if len(
                fingerprints[
                    (
                        item.reference_id,
                        item.kind,
                        item.event_time.to_dict()["recorded_at"],
                        item.bar_interval.label if item.bar_interval else None,
                    )
                ]
            )
            > 1
        )
        add(MarketQualityCode.CONFLICTING_OBSERVATION, *matching)
    for event_key, values in fingerprints.items():
        count = sum(
            1
            for item in assessed_observations
            if (
                item.reference_id,
                item.kind,
                item.event_time.to_dict()["recorded_at"],
                item.bar_interval.label if item.bar_interval else None,
            )
            == event_key
        )
        if count > 1 and len(values) == 1:
            matching = tuple(
                item
                for item in assessed_observations
                if (
                    item.reference_id,
                    item.kind,
                    item.event_time.to_dict()["recorded_at"],
                    item.bar_interval.label if item.bar_interval else None,
                )
                == event_key
            )
            add(MarketQualityCode.DUPLICATE_OBSERVATION, *matching)
    for stream in streams.values():
        _detect_gaps_and_jumps(stream, policy, add, price_limits=price_limits)
    freshness = tuple((item.purpose, age <= item.maximum_age) for item in policy.freshness_by_purpose)
    if not all(is_fresh for _, is_fresh in freshness):
        add(MarketQualityCode.STALE_OBSERVATION)
    return MarketDataQuality(
        tuple(
            MarketQualityIssue(code, tuple(sorted(ids, key=str)))
            for code, ids in sorted(issue_observations.items(), key=lambda item: item[0].value)
        ),
        SnapshotFreshness(oldest, age, freshness),
    )


def market_snapshot_content_sha256(
    as_of: RecordedAt,
    trading_date_resolution: TradingDateResolution,
    trading_calendar: TradingCalendar,
    observations: tuple[MarketObservation, ...],
    reference_resolutions: tuple[Resolution, ...],
    contract_rule_registry: ContractRuleRegistry,
    rule_resolution: RuleResolution,
    dataset_manifest: DatasetManifest,
    schema_version: SchemaVersion,
    quality_policy: MarketQualityPolicy,
    intended_purpose: SnapshotPurpose,
) -> str:
    """Canonical release digest; arrival order is represented by immutable evidence."""
    payload = {
        "as_of": as_of.to_dict()["recorded_at"],
        "trading_date_resolution": _calendar_resolution_payload(trading_date_resolution),
        "trading_calendar_release": {
            "calendar_id": str(trading_calendar.calendar_id),
            "release_version": trading_calendar.release_version,
            "content_sha256": trading_calendar.expected_content_sha256,
        },
        "observations": tuple(_observation_payload(item) for item in sorted(observations, key=_observation_sort_key)),
        "reference_resolutions": tuple(
            _resolution_payload(item)
            for item in sorted(reference_resolutions, key=lambda item: item.target.reference_id)
        ),
        "contract_rule_registry": {
            "registry_id": str(contract_rule_registry.registry_id),
            "release_version": contract_rule_registry.release_version,
            "content_sha256": contract_rule_registry.expected_content_sha256,
        },
        "rule_resolution": _rule_resolution_payload(rule_resolution),
        "dataset_manifest_ref": DatasetManifestRef.from_manifest(dataset_manifest).to_dict(),
        "schema_version": str(schema_version),
        "quality_policy": quality_policy.to_dict(),
        "intended_purpose": intended_purpose.value,
    }
    return canonical_sha256(cast("JsonValue", payload))


def _validate_prices(item: MarketObservation) -> None:
    prices = tuple(
        value
        for value in (
            item.last_price,
            item.bid_price,
            item.ask_price,
            item.open_price,
            item.high_price,
            item.low_price,
            item.close_price,
        )
        if value is not None
    )
    if any(not isinstance(value, Price) for value in prices):
        raise TypeError("market observation prices must be Price values")
    if prices and any(
        (value.currency, value.unit, value.scale) != (prices[0].currency, prices[0].unit, prices[0].scale)
        for value in prices
    ):
        raise ValueError("market observation prices must share currency, unit, and scale")
    if (
        item.bid_price is not None
        and item.ask_price is not None
        and _price_amount(item.bid_price) > _price_amount(item.ask_price)
    ):
        raise ValueError("market observation bid_price cannot exceed ask_price")
    if all(value is not None for value in (item.open_price, item.high_price, item.low_price, item.close_price)):
        assert (
            item.open_price is not None
            and item.high_price is not None
            and item.low_price is not None
            and item.close_price is not None
        )
        if _price_amount(item.low_price) > min(
            _price_amount(item.open_price), _price_amount(item.close_price)
        ) or _price_amount(item.high_price) < max(_price_amount(item.open_price), _price_amount(item.close_price)):
            raise ValueError("bar high/low must contain open and close")


def _validate_quantities(item: MarketObservation) -> None:
    quantities = tuple(
        value for value in (item.bid_size, item.ask_size, item.volume, item.open_interest) if value is not None
    )
    if any(not isinstance(value, Quantity) for value in quantities):
        raise TypeError("market observation quantities must be Quantity values")
    if any(_quantity_amount(value) < 0 for value in quantities):
        raise ValueError("market observation quantities must be non-negative")


def _missing_required_fields(item: MarketObservation) -> bool:
    if item.kind is ObservationKind.QUOTE:
        return item.last_price is None and (item.bid_price is None or item.ask_price is None)
    if item.kind is ObservationKind.BAR:
        return any(value is None for value in (item.open_price, item.high_price, item.low_price, item.close_price))
    if item.kind in {ObservationKind.TRADE, ObservationKind.SETTLEMENT}:
        return item.last_price is None
    return item.open_interest is None


def _detect_gaps_and_jumps(
    stream: list[MarketObservation],
    policy: MarketQualityPolicy,
    add: Callable[[MarketQualityCode, MarketObservation, MarketObservation], None],
    *,
    price_limits: PriceLimitRange | None,
) -> None:
    ordered = sorted(stream, key=lambda item: item.event_time.value)
    for previous, current in zip(ordered, ordered[1:]):
        if current.event_time.value - previous.event_time.value > policy.gap_after:
            add(MarketQualityCode.GAP_DETECTED, previous, current)
        old_price = _representative_price(previous)
        new_price = _representative_price(current)
        if old_price is None or new_price is None or _price_amount(old_price) == 0:
            continue
        if (old_price.currency, old_price.unit, old_price.scale) != (
            new_price.currency,
            new_price.unit,
            new_price.scale,
        ):
            add(MarketQualityCode.CONFLICTING_OBSERVATION, previous, current)
            continue
        if (
            abs(_price_amount(new_price) - _price_amount(old_price)) / _price_amount(old_price)
            > policy.max_price_jump_ratio
        ):
            if _is_exact_price_limit_hit(new_price, price_limits):
                add(MarketQualityCode.PRICE_LIMIT_CONFIRMED, previous, current)
            else:
                add(MarketQualityCode.PRICE_JUMP, previous, current)


def _is_exact_price_limit_hit(price: Price, price_limits: PriceLimitRange | None) -> bool:
    """A limit confirmation is an exact rule-bound comparison, never rounded."""
    if price_limits is None:
        return False
    lower, upper = price_limits.lower_limit, price_limits.upper_limit
    if (price.currency, price.unit, price.scale) != (lower.currency, lower.unit, lower.scale):
        return False
    amount = _price_amount(price)
    return amount == _price_amount(lower) or amount == _price_amount(upper)


def _representative_price(item: MarketObservation) -> Price | None:
    return item.close_price or item.last_price or item.bid_price or item.ask_price


def _price_amount(value: Price) -> Decimal:
    """Price validates exact Decimal storage in its value-object constructor."""
    return cast("Decimal", value.amount)


def _quantity_amount(value: Quantity) -> Decimal:
    """Quantity validates exact Decimal storage in its value-object constructor."""
    return cast("Decimal", value.amount)


def _observation_content_sha256(item: MarketObservation) -> str:
    return canonical_sha256(cast("JsonValue", _observation_payload(item, include_id=False)))


def _observation_sort_key(item: MarketObservation) -> tuple[str, str, str, str, str, int, str]:
    """Canonical storage order; quality never infers arrival order from this."""
    return (
        item.reference_id,
        item.kind.value,
        item.event_time.to_dict()["recorded_at"],
        item.available_time.to_dict()["recorded_at"],
        item.ingested_at.to_dict()["recorded_at"],
        item.source_sequence,
        str(item.observation_id),
    )


def _arrival_sort_key(item: MarketObservation) -> tuple[str, str, str, str, int, str]:
    """Explicit acquisition evidence, not caller tuple order, defines arrival."""
    return (
        item.reference_id,
        item.kind.value,
        item.available_time.to_dict()["recorded_at"],
        item.ingested_at.to_dict()["recorded_at"],
        item.source_sequence,
        str(item.observation_id),
    )


def _observation_payload(item: MarketObservation, *, include_id: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "reference": _reference_payload(item.reference),
        "kind": item.kind.value,
        "event_time": item.event_time.to_dict()["recorded_at"],
        "available_time": item.available_time.to_dict()["recorded_at"],
        "ingested_at": item.ingested_at.to_dict()["recorded_at"],
        "source": {
            "source_ref": item.source.source_ref,
            "acquired_at": item.source.acquired_at.to_dict()["recorded_at"],
            "source_published_at": item.source.source_published_at.to_dict()["recorded_at"]
            if item.source.source_published_at
            else None,
            "source_revision": item.source.source_revision,
        },
        "source_trust": item.source_trust.value,
        "schema_version": str(item.schema_version),
        "source_sequence": item.source_sequence,
        "dataset_record_ref": {
            "manifest_id": str(item.dataset_record_ref.manifest_id),
            "locator": item.dataset_record_ref.locator,
            "record_sha256": item.dataset_record_ref.record_sha256,
        }
        if item.dataset_record_ref
        else None,
        "last_price": _price_payload(item.last_price),
        "bid_price": _price_payload(item.bid_price),
        "ask_price": _price_payload(item.ask_price),
        "bid_size": _quantity_payload(item.bid_size),
        "ask_size": _quantity_payload(item.ask_size),
        "open_price": _price_payload(item.open_price),
        "high_price": _price_payload(item.high_price),
        "low_price": _price_payload(item.low_price),
        "close_price": _price_payload(item.close_price),
        "volume": _quantity_payload(item.volume),
        "open_interest": _quantity_payload(item.open_interest),
        "bar_interval": item.bar_interval.to_dict() if item.bar_interval else None,
        "bar_status": item.bar_status.value if item.bar_status else None,
        "component_instrument": item.component_instrument.reference_id if item.component_instrument else None,
        "revision": item.revision,
        "supersedes_observation_id": str(item.supersedes_observation_id) if item.supersedes_observation_id else None,
    }
    if include_id:
        payload["observation_id"] = str(item.observation_id)
    return payload


def _reference_payload(reference: MarketReference) -> dict[str, str]:
    return {
        "kind": "INSTRUMENT" if isinstance(reference, Instrument) else "CONTINUOUS_SERIES",
        "reference_id": reference.reference_id,
    }


def _price_payload(value: Price | None) -> dict[str, str | int] | None:
    return value.to_dict() if value else None


def _quantity_payload(value: Quantity | None) -> dict[str, str | int] | None:
    return value.to_dict() if value else None


def _rule_set_payload(reference: RuleSetRef) -> dict[str, str | int]:
    return {
        "registry_id": str(reference.registry_id),
        "registry_release_version": reference.registry_release_version,
        "registry_content_sha256": reference.registry_content_sha256,
        "rule_id": str(reference.rule_id),
        "rule_version": reference.rule_version,
        "rule_content_sha256": reference.rule_content_sha256,
    }


def _rule_resolution_payload(resolution: RuleResolution) -> dict[str, object]:
    return {
        "rule_set_ref": _rule_set_payload(resolution.rule_set_ref),
        "trading_date": str(resolution.trading_date),
        "as_of": resolution.as_of.to_dict()["recorded_at"],
        "rule_content_sha256": resolution.rule_content_sha256,
    }


def _resolution_payload(resolution: Resolution) -> dict[str, str | int]:
    return {
        "target_reference_id": resolution.target.reference_id,
        "target_kind": resolution.kind.value,
        "alias": resolution.alias,
        "registry_id": str(resolution.registry_id),
        "release_version": resolution.release_version,
        "registry_content_sha256": resolution.registry_content_sha256,
        "mapping_version": resolution.mapping_version,
        "provenance_source_ref": resolution.provenance.source_ref,
        "provenance_acquired_at": resolution.provenance.acquired_at.to_dict()["recorded_at"],
    }


def _calendar_resolution_payload(resolution: TradingDateResolution) -> dict[str, str | int]:
    return {
        "exchange": resolution.exchange.value,
        "trading_date": str(resolution.trading_date),
        "market_time": resolution.market_time.to_dict()["market_time"],
        "as_of": resolution.as_of.to_dict()["recorded_at"],
        "session_name": resolution.session_name,
        "phase": resolution.phase.value,
        "schedule_revision_id": str(resolution.schedule.revision_id),
        "schedule_version": resolution.schedule.version,
        "schedule_variety": resolution.schedule.variety.reference_id,
        "calendar_id": str(resolution.calendar_ref.calendar_id),
        "calendar_release_version": resolution.calendar_ref.release_version,
        "calendar_content_sha256": resolution.calendar_ref.content_sha256,
    }


def _validate_reference_resolutions(
    observations: tuple[MarketObservation, ...], resolutions: tuple[Resolution, ...]
) -> None:
    """Every observed reference needs exactly one visible immutable registry fact."""
    observed = {item.reference_id for item in observations}
    observed.update(
        item.component_instrument.reference_id for item in observations if item.component_instrument is not None
    )
    indexed: dict[str, list[Resolution]] = {}
    for resolution in resolutions:
        if not isinstance(resolution.target, (Instrument, ContinuousSeries)):
            raise ValueError("snapshot registry resolution must target an Instrument or ContinuousSeries")
        indexed.setdefault(resolution.target.reference_id, []).append(resolution)
    if set(indexed) != observed or any(len(entries) != 1 for entries in indexed.values()):
        raise ValueError("market snapshot requires exactly one registry resolution for every observed reference")


def _validate_calendar_resolution(
    resolution: TradingDateResolution,
    calendar: TradingCalendar,
    observations: tuple[MarketObservation, ...],
    instrument: Instrument,
) -> None:
    """Each fact belongs to the explicit calendar phase used to freeze this snapshot."""
    if resolution.exchange is not instrument.exchange or resolution.schedule.variety != instrument.variety:
        raise ValueError("market snapshot calendar resolution must exactly match the rule Instrument variety")
    if resolution.calendar_ref != calendar.ref or resolution.schedule not in calendar.schedules:
        raise ValueError("market snapshot calendar resolution must be backed by its immutable TradingCalendar release")
    for observation in observations:
        market_time = ShanghaiTimestamp.from_datetime(
            observation.event_time.value.astimezone(resolution.market_time.value.tzinfo)
        )
        matching = resolution.schedule.matching_phase(market_time)
        if matching is None or matching[0] != resolution.session_name or matching[1].phase is not resolution.phase:
            raise ValueError("market observation event_time is outside the frozen calendar session phase")


def _validate_dataset_manifest(
    manifest: DatasetManifest, observations: tuple[MarketObservation, ...], as_of: RecordedAt
) -> None:
    if not isinstance(manifest, DatasetManifest):
        raise TypeError("market snapshot requires an actual DatasetManifest")
    if manifest.ingested_at.value > as_of.value or manifest.as_of.value > as_of.value:
        raise ValueError("market snapshot DatasetManifest cannot be later than snapshot as_of")
    for observation in observations:
        if observation.dataset_record_ref is None or observation.dataset_record_ref.manifest_id != manifest.dataset_id:
            raise ValueError("market observation must bind a DatasetRecordRef from snapshot DatasetManifest")
        if observation.reference_id not in manifest.instrument_universe:
            raise ValueError("market observation reference is absent from DatasetManifest instrument universe")
        if not (manifest.coverage.start.value <= observation.event_time.value <= manifest.coverage.end.value):
            raise ValueError("market observation event_time falls outside DatasetManifest coverage")


def _validate_rule_resolution(
    registry: ContractRuleRegistry,
    resolution: RuleResolution,
    observations: tuple[MarketObservation, ...],
    trading_date: TradingDate,
    as_of: RecordedAt,
) -> None:
    """Resolution must be produced by the supplied immutable registry, never self-attested."""
    if not isinstance(registry, ContractRuleRegistry) or not isinstance(resolution, RuleResolution):
        raise TypeError("market snapshot requires ContractRuleRegistry and RuleResolution")
    if (
        resolution.registry_id != registry.registry_id
        or resolution.registry_release_version != registry.release_version
        or resolution.registry_content_sha256 != registry.expected_content_sha256
        or resolution.rule not in registry.rules
    ):
        raise ValueError("market snapshot RuleResolution is not backed by supplied ContractRuleRegistry")
    if resolution.trading_date != trading_date or resolution.as_of != as_of:
        raise ValueError("market snapshot RuleResolution point in time is incompatible with snapshot")
    replay = ContractRuleResolver(registry).resolve(resolution.rule.instrument, trading_date, resolution.as_of)
    if not isinstance(replay, RuleResolution) or replay.rule_set_ref != resolution.rule_set_ref:
        raise ValueError("market snapshot RuleResolution does not match registry resolver semantics")
    rule = resolution.rule
    for observation in observations:
        observed_instrument = (
            observation.reference if isinstance(observation.reference, Instrument) else observation.component_instrument
        )
        assert observed_instrument is not None  # validated by MarketObservation.
        if observed_instrument != rule.instrument:
            raise ValueError("market observation component must exactly match its attached contract rule Instrument")
        prices = tuple(
            value
            for value in (
                observation.last_price,
                observation.bid_price,
                observation.ask_price,
                observation.open_price,
                observation.high_price,
                observation.low_price,
                observation.close_price,
            )
            if value is not None
        )
        expected_quote = (rule.tick_size.currency, rule.tick_size.unit, rule.tick_size.scale)
        if any((item.currency, item.unit, item.scale) != expected_quote for item in prices):
            raise ValueError("market observation prices must use the attached contract rule quote unit")
        quantities = tuple(
            value
            for value in (observation.bid_size, observation.ask_size, observation.volume, observation.open_interest)
            if value is not None
        )
        if any(item.unit != "lot" for item in quantities):
            raise ValueError("market observation quantities must use lot units for this V1 contract")


def _require_digest(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
