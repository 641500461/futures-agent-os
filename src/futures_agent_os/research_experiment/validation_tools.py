"""Replayable synchronous V1-010 research validation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from hashlib import sha256
import hmac
import json
from uuid import UUID
from typing import TYPE_CHECKING, Mapping, TypeVar, cast

from futures_agent_os.reference_market_data import BarStatus, MarketObservation, MarketSnapshot, ObservationKind
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .walk_forward import plan_walk_forward_fold_windows

if TYPE_CHECKING:
    from futures_agent_os.market_intelligence.feature_engine import FeatureObservation

TOOL_SCHEMA_VERSION = SchemaVersion(1, 5)
TOOLSET_VERSION = "research-validation.v1"
_SCALE = Decimal("0.00000001")
_MINIMUM_SAMPLES = 20
_VALIDATION_LIFETIME_SECONDS = 3600
_FEATURE_AUTHORITY = "market_intelligence.feature_observation_store.v1"
_MEMORY_AUTHORITY = "learning_review.validated_lesson_store.v1"
_EXPERIMENT_AUTHORITY = "research_experiment.result_store.v1"
_RESULT_AUTHORITY = "research_experiment.deterministic_tools.v1"
PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID = EntityId.parse("feature_spec_0198f4d0-0000-7000-8000-000000000010")
PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256 = canonical_sha256(
    {
        "feature_name": "prior_close_return",
        "algorithm": "SIMPLE_RETURN",
        "schema_version": "1.0",
        "signal_rule": "prior_close_return_threshold_direction.v1",
    }
)


class ResearchToolName(StrEnum):
    MARKET_QUERY = "market_query"
    HISTORICAL_QUERY = "historical_query"
    FEATURE_QUERY = "feature_query"
    CONTRACT_QUERY = "contract_query"
    MEMORY_SEARCH = "memory_search"
    EXPERIMENT_SEARCH = "experiment_search"
    L0_SIGNAL_TEST = "l0_signal_test"
    L1_BAR_BACKTEST = "l1_bar_backtest"
    WALK_FORWARD = "walk_forward_test"
    COST_STRESS = "cost_slippage_stress"
    COUNTERFACTUAL = "counterfactual_test"


REQUIRED_TOOLSET = tuple(ResearchToolName)


class ToolFailureCode(StrEnum):
    NONE = "NONE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    DATA_QUALITY = "DATA_QUALITY"
    NO_MATCH = "NO_MATCH"


class ExperimentOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class LessonValidationState(StrEnum):
    VALIDATED = "VALIDATED"


class LessonActivationState(StrEnum):
    ACTIVE = "ACTIVE"


@dataclass(frozen=True, slots=True)
class ResearchArtifactRef:
    artifact_id: EntityId
    artifact_kind: str
    schema_version: SchemaVersion
    content_sha256: str
    as_of: RecordedAt
    valid_until: RecordedAt

    def __post_init__(self) -> None:
        if (
            type(self.artifact_id) is not EntityId
            or type(self.artifact_kind) is not str
            or not self.artifact_kind.strip()
        ):
            raise ValueError("artifact ref requires exact identity and kind")
        if (
            type(self.schema_version) is not SchemaVersion
            or type(self.as_of) is not RecordedAt
            or type(self.valid_until) is not RecordedAt
            or self.valid_until.value <= self.as_of.value
        ):
            raise ValueError("artifact ref requires a valid typed lifetime")
        _digest(self.content_sha256)

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_id": str(self.artifact_id),
            "artifact_kind": self.artifact_kind,
            "schema_version": str(self.schema_version),
            "content_sha256": self.content_sha256,
            "as_of": _time(self.as_of),
            "valid_until": _time(self.valid_until),
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ResearchArtifactRef:
        _keys(
            value,
            {"artifact_id", "artifact_kind", "schema_version", "content_sha256", "as_of", "valid_until"},
            "artifact ref",
        )
        return cls(
            EntityId.parse(_str(value["artifact_id"])),
            _str(value["artifact_kind"]),
            SchemaVersion.parse(_str(value["schema_version"])),
            _str(value["content_sha256"]),
            RecordedAt.parse(_str(value["as_of"])),
            RecordedAt.parse(_str(value["valid_until"])),
        )


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    config_id: EntityId
    version: int
    train_bars: int
    test_bars: int
    step_bars: int
    minimum_samples: int
    signal_threshold: Decimal
    round_trip_cost_bps: Decimal
    slippage_bps: Decimal
    stress_multipliers: tuple[Decimal, ...]
    stop_after_failures: int
    maximum_contribution_ratio: Decimal = Decimal("0.80000000")
    minimum_fold_positive_ratio: Decimal = Decimal("0.50000000")
    minimum_signal_coverage: Decimal = Decimal("0.10000000")
    minimum_signal_accuracy: Decimal = Decimal("0.50000000")
    signal_rule: str = "prior_close_return_threshold_direction.v1"
    forward_label_rule: str = "next_close_direction.v1"
    single_strategy_rule: str = "fixed_directional_signal.v1"

    def __post_init__(self) -> None:
        ints = (
            self.version,
            self.train_bars,
            self.test_bars,
            self.step_bars,
            self.minimum_samples,
            self.stop_after_failures,
        )
        ratios = (
            self.maximum_contribution_ratio,
            self.minimum_fold_positive_ratio,
            self.minimum_signal_coverage,
            self.minimum_signal_accuracy,
        )
        decimals = (
            self.signal_threshold,
            self.round_trip_cost_bps,
            self.slippage_bps,
            *self.stress_multipliers,
            *ratios,
        )
        if (
            type(self.config_id) is not EntityId
            or self.config_id.namespace != "research_validation_config"
            or any(type(value) is not int or value < 1 for value in ints)
        ):
            raise ValueError("validation config requires identity and positive bounds")
        if any(type(value) is not Decimal or not value.is_finite() or value < 0 for value in decimals):
            raise ValueError("validation assumptions require finite non-negative Decimal values")
        if (
            type(self.stress_multipliers) is not tuple
            or tuple(sorted(set(self.stress_multipliers))) != self.stress_multipliers
            or not self.stress_multipliers
            or self.stress_multipliers[0] != Decimal(1)
        ):
            raise ValueError("stress scenarios require ordered unique baseline multiplier 1")
        if (
            self.minimum_samples < _MINIMUM_SAMPLES
            or self.train_bars < self.minimum_samples
            or self.test_bars < 5
            or self.step_bars < self.test_bars
        ):
            raise ValueError("validation requires >=20 samples and non-overlapping chronological tests")
        if any(value > 1 for value in ratios):
            raise ValueError("validation ratios must be from zero through one")
        if (self.signal_rule, self.forward_label_rule, self.single_strategy_rule) != (
            "prior_close_return_threshold_direction.v1",
            "next_close_direction.v1",
            "fixed_directional_signal.v1",
        ):
            raise ValueError("V1-010 signal/label/single-strategy rules are pinned")

    def payload(self) -> dict[str, JsonValue]:
        """Semantic config: config_id is registry identity, never content."""
        return {
            "version": self.version,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "step_bars": self.step_bars,
            "minimum_samples": self.minimum_samples,
            "signal_threshold": _dec(self.signal_threshold),
            "round_trip_cost_bps": _dec(self.round_trip_cost_bps),
            "slippage_bps": _dec(self.slippage_bps),
            "stress_multipliers": tuple(_dec(value) for value in self.stress_multipliers),
            "stop_after_failures": self.stop_after_failures,
            "maximum_contribution_ratio": _dec(self.maximum_contribution_ratio),
            "minimum_fold_positive_ratio": _dec(self.minimum_fold_positive_ratio),
            "minimum_signal_coverage": _dec(self.minimum_signal_coverage),
            "minimum_signal_accuracy": _dec(self.minimum_signal_accuracy),
            "signal_rule": self.signal_rule,
            "forward_label_rule": self.forward_label_rule,
            "single_strategy_rule": self.single_strategy_rule,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return {"config_id": str(self.config_id), **self.payload(), "content_sha256": self.content_sha256}

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ValidationConfig:
        _keys(
            value,
            {
                "config_id",
                "version",
                "train_bars",
                "test_bars",
                "step_bars",
                "minimum_samples",
                "signal_threshold",
                "round_trip_cost_bps",
                "slippage_bps",
                "stress_multipliers",
                "stop_after_failures",
                "maximum_contribution_ratio",
                "minimum_fold_positive_ratio",
                "minimum_signal_coverage",
                "minimum_signal_accuracy",
                "signal_rule",
                "forward_label_rule",
                "single_strategy_rule",
                "content_sha256",
            },
            "validation config",
        )
        content = _str(value["content_sha256"])
        copy = dict(value)
        copy.pop("content_sha256")
        config = cls(
            config_id=EntityId.parse(_str(copy.pop("config_id"))),
            version=_int(copy["version"]),
            train_bars=_int(copy["train_bars"]),
            test_bars=_int(copy["test_bars"]),
            step_bars=_int(copy["step_bars"]),
            minimum_samples=_int(copy["minimum_samples"]),
            signal_threshold=Decimal(_str(copy["signal_threshold"])),
            round_trip_cost_bps=Decimal(_str(copy["round_trip_cost_bps"])),
            slippage_bps=Decimal(_str(copy["slippage_bps"])),
            stress_multipliers=tuple(Decimal(_str(item)) for item in _seq(copy["stress_multipliers"])),
            stop_after_failures=_int(copy["stop_after_failures"]),
            maximum_contribution_ratio=Decimal(_str(copy["maximum_contribution_ratio"])),
            minimum_fold_positive_ratio=Decimal(_str(copy["minimum_fold_positive_ratio"])),
            minimum_signal_coverage=Decimal(_str(copy["minimum_signal_coverage"])),
            minimum_signal_accuracy=Decimal(_str(copy["minimum_signal_accuracy"])),
            signal_rule=_str(copy["signal_rule"]),
            forward_label_rule=_str(copy["forward_label_rule"]),
            single_strategy_rule=_str(copy["single_strategy_rule"]),
        )
        if config.content_sha256 != content:
            raise ValueError("validation config content hash mismatch")
        return config


@dataclass(frozen=True, slots=True)
class ResearchQueryScope:
    instrument_key: str
    market: str
    signal_rule: str
    config_sha256: str
    hypothesis_sha256: str
    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value.strip()
            for value in (self.instrument_key, self.market, self.signal_rule)
        ):
            raise ValueError("research query scope requires instrument, market, and signal rule")
        _digest(self.config_sha256)
        _digest(self.hypothesis_sha256)
        _tags(self.tags)
        if not self.tags:
            raise ValueError("research query scope tags cannot be empty")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "instrument_key": self.instrument_key,
            "market": self.market,
            "signal_rule": self.signal_rule,
            "config_sha256": self.config_sha256,
            "hypothesis_sha256": self.hypothesis_sha256,
            "tags": self.tags,
            "content_sha256": self.content_sha256,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "instrument_key": self.instrument_key,
                "market": self.market,
                "signal_rule": self.signal_rule,
                "config_sha256": self.config_sha256,
                "hypothesis_sha256": self.hypothesis_sha256,
                "tags": self.tags,
            }
        )

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ResearchQueryScope:
        _keys(
            value,
            {
                "instrument_key",
                "market",
                "signal_rule",
                "config_sha256",
                "hypothesis_sha256",
                "tags",
                "content_sha256",
            },
            "research query scope",
        )
        scope = cls(
            _str(value["instrument_key"]),
            _str(value["market"]),
            _str(value["signal_rule"]),
            _str(value["config_sha256"]),
            _str(value["hypothesis_sha256"]),
            tuple(_str(tag) for tag in _seq(value["tags"])),
        )
        if scope.content_sha256 != _str(value["content_sha256"]):
            raise ValueError("research query scope content hash mismatch")
        return scope


def _validate_authority_secret(secret: bytes) -> None:
    if type(secret) is not bytes or len(secret) < 32:
        raise ValueError("trusted authority secret requires at least 32 bytes")


def _authority_proof(authority_id: str, content_sha256: str, secret: bytes) -> str:
    return hmac.new(secret, f"{authority_id}:{content_sha256}".encode(), sha256).hexdigest()


def _verify_authority(authority_id: str, content_sha256: str, proof: str, secret: bytes) -> None:
    if not hmac.compare_digest(_authority_proof(authority_id, content_sha256, secret), proof):
        raise ValueError("owner-issued authority proof is invalid")


class TrustedFeatureEvidencePort:
    """In-memory Market Intelligence issuer; its signing secret is never serialized."""

    def __init__(self, secret: bytes) -> None:
        _validate_authority_secret(secret)
        self.__secret = secret

    def issue(
        self,
        observation: FeatureObservation,
        snapshot_ref: ResearchArtifactRef,
        valid_until: RecordedAt,
        scope: ResearchQueryScope,
    ) -> InjectedFeatureEvidenceRef:
        from futures_agent_os.market_intelligence.feature_engine import FeatureObservation as OwnerFeatureObservation

        if type(observation) is not OwnerFeatureObservation:
            raise TypeError("feature issuer accepts only the owner FeatureObservation type")
        observation.__post_init__()
        if (
            observation.target_reference_id != scope.instrument_key
            or observation.feature_spec_content_sha256 != PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256
            or observation.feature_spec_id != PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID
            or observation.market_snapshot_refs[-1].to_dict()
            != {
                "snapshot_id": str(snapshot_ref.artifact_id),
                "content_sha256": snapshot_ref.content_sha256,
                "as_of": _time(snapshot_ref.as_of),
                "schema_version": str(snapshot_ref.schema_version),
                "purpose": "RESEARCH",
            }
        ):
            raise ValueError("trusted feature issuer rejects target/spec/snapshot lineage mismatch")
        payload_json = canonical_json_text(observation.payload())
        ref = ResearchArtifactRef(
            observation.observation_id,
            "feature_observation",
            SchemaVersion(1, 0),
            observation.content_sha256,
            observation.as_of,
            valid_until,
        )
        unsigned = _feature_unsigned(ref, payload_json, scope.content_sha256)
        return InjectedFeatureEvidenceRef(
            ref,
            "prior_close_return",
            PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID,
            PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256,
            scope.content_sha256,
            payload_json,
            _FEATURE_AUTHORITY,
            _authority_proof(_FEATURE_AUTHORITY, canonical_sha256(unsigned), self.__secret),
            observation.content_sha256,
        )

    def verify(self, value: InjectedFeatureEvidenceRef) -> None:
        if type(value) is not InjectedFeatureEvidenceRef or value.authority_id != _FEATURE_AUTHORITY:
            raise ValueError("feature evidence issuer is not trusted")
        _hydrate_owner_feature_observation(value)
        unsigned = _feature_unsigned(value.ref, value.feature_observation_payload_json, value.scope_sha256)
        _verify_authority(value.authority_id, canonical_sha256(unsigned), value.authority_proof, self.__secret)


@dataclass(frozen=True, slots=True)
class InjectedFeatureEvidenceRef:
    ref: ResearchArtifactRef
    feature_name: str
    feature_spec_id: EntityId
    feature_spec_content_sha256: str
    scope_sha256: str
    feature_observation_payload_json: str
    authority_id: str
    authority_proof: str
    payload_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.ref) is not ResearchArtifactRef
            or self.ref.artifact_kind != "feature_observation"
            or self.ref.artifact_id.namespace != "feature_observation"
            or self.ref.schema_version != SchemaVersion(1, 0)
            or type(self.feature_name) is not str
            or self.feature_name != "prior_close_return"
            or self.feature_spec_id != PRIOR_CLOSE_RETURN_FEATURE_SPEC_ID
            or self.feature_spec_content_sha256 != PRIOR_CLOSE_RETURN_FEATURE_SPEC_SHA256
            or self.authority_id != _FEATURE_AUTHORITY
        ):
            raise ValueError("feature query accepts only the pinned V1-005 prior-close-return evidence")
        _digest(self.scope_sha256)
        _digest(self.payload_sha256)
        _digest(self.authority_proof)
        _hydrate_owner_feature_observation(self)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "ref": self.ref.to_dict(),
            "feature_name": self.feature_name,
            "feature_spec_id": str(self.feature_spec_id),
            "feature_spec_content_sha256": self.feature_spec_content_sha256,
            "scope_sha256": self.scope_sha256,
            "feature_observation_payload_json": self.feature_observation_payload_json,
            "authority_id": self.authority_id,
            "authority_proof": self.authority_proof,
            "payload_sha256": self.payload_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> InjectedFeatureEvidenceRef:
        _keys(
            value,
            {
                "ref",
                "feature_name",
                "feature_spec_id",
                "feature_spec_content_sha256",
                "scope_sha256",
                "feature_observation_payload_json",
                "authority_id",
                "authority_proof",
                "payload_sha256",
            },
            "injected feature evidence",
        )
        return cls(
            ResearchArtifactRef.hydrate(_map(value["ref"])),
            _str(value["feature_name"]),
            EntityId.parse(_str(value["feature_spec_id"])),
            _str(value["feature_spec_content_sha256"]),
            _str(value["scope_sha256"]),
            _str(value["feature_observation_payload_json"]),
            _str(value["authority_id"]),
            _str(value["authority_proof"]),
            _str(value["payload_sha256"]),
        )


def _hydrate_owner_feature_observation(value: InjectedFeatureEvidenceRef) -> FeatureObservation:
    from futures_agent_os.market_intelligence.feature_engine import FeatureObservation as OwnerFeatureObservation

    try:
        payload = json.loads(value.feature_observation_payload_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("feature observation payload must be canonical JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("feature observation payload must be an object")
    hydrated = OwnerFeatureObservation.hydrate(value.ref.artifact_id, _map(payload))
    if (
        canonical_json_text(hydrated.payload()) != value.feature_observation_payload_json
        or hydrated.feature_spec_id != value.feature_spec_id
        or hydrated.feature_spec_content_sha256 != value.feature_spec_content_sha256
        or hydrated.content_sha256 != value.payload_sha256
        or hydrated.content_sha256 != value.ref.content_sha256
        or hydrated.as_of != value.ref.as_of
    ):
        raise ValueError("feature evidence does not match the owner FeatureObservation")
    return hydrated


@dataclass(frozen=True, slots=True)
class MemorySearchRecord:
    ref: ResearchArtifactRef
    applicability_tags: tuple[str, ...]
    validation_state: LessonValidationState = LessonValidationState.VALIDATED
    activation_state: LessonActivationState = LessonActivationState.ACTIVE
    revoked_at: RecordedAt | None = None
    scope_sha256: str = ""

    def __post_init__(self) -> None:
        if type(self.ref) is not ResearchArtifactRef or self.ref.artifact_kind != "validated_lesson":
            raise ValueError("memory search accepts only ValidatedLesson")
        _tags(self.applicability_tags)
        _digest(self.scope_sha256)
        if (
            type(self.validation_state) is not LessonValidationState
            or self.validation_state is not LessonValidationState.VALIDATED
            or type(self.activation_state) is not LessonActivationState
            or self.activation_state is not LessonActivationState.ACTIVE
            or self.revoked_at is not None
        ):
            raise ValueError("memory search rejects revoked/inactive lessons")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "ref": self.ref.to_dict(),
            "applicability_tags": self.applicability_tags,
            "validation_state": self.validation_state.value,
            "activation_state": self.activation_state.value,
            "revoked_at": None,
            "scope_sha256": self.scope_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> MemorySearchRecord:
        _keys(
            value,
            {
                "ref",
                "applicability_tags",
                "validation_state",
                "activation_state",
                "revoked_at",
                "scope_sha256",
            },
            "memory search record",
        )
        if value["revoked_at"] is not None:
            raise ValueError("memory search rejects revoked lessons")
        return cls(
            ResearchArtifactRef.hydrate(_map(value["ref"])),
            tuple(_str(tag) for tag in _seq(value["applicability_tags"])),
            LessonValidationState(_str(value["validation_state"])),
            LessonActivationState(_str(value["activation_state"])),
            None,
            _str(value["scope_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ExperimentSearchRecord:
    ref: ResearchArtifactRef
    tags: tuple[str, ...]
    outcome: ExperimentOutcome
    completed_at: RecordedAt
    provenance_refs: tuple[ResearchArtifactRef, ...]
    scope_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.ref) is not ResearchArtifactRef
            or self.ref.artifact_kind != "experiment_result"
            or type(self.outcome) is not ExperimentOutcome
            or type(self.completed_at) is not RecordedAt
        ):
            raise ValueError("experiment search requires typed success/failed ExperimentResult")
        _tags(self.tags)
        _digest(self.scope_sha256)
        if (
            self.ref.as_of.value > self.completed_at.value
            or type(self.provenance_refs) is not tuple
            or not self.provenance_refs
            or tuple(sorted(set(self.provenance_refs), key=_ref_key)) != self.provenance_refs
            or any(
                type(ref) is not ResearchArtifactRef
                or ref.as_of.value > self.completed_at.value
                or ref.valid_until.value < self.ref.valid_until.value
                for ref in self.provenance_refs
            )
        ):
            raise ValueError("experiment result requires immutable PIT provenance")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "ref": self.ref.to_dict(),
            "tags": self.tags,
            "outcome": self.outcome.value,
            "completed_at": _time(self.completed_at),
            "provenance_refs": tuple(ref.to_dict() for ref in self.provenance_refs),
            "scope_sha256": self.scope_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ExperimentSearchRecord:
        _keys(
            value,
            {"ref", "tags", "outcome", "completed_at", "provenance_refs", "scope_sha256"},
            "experiment record",
        )
        return cls(
            ResearchArtifactRef.hydrate(_map(value["ref"])),
            tuple(_str(tag) for tag in _seq(value["tags"])),
            ExperimentOutcome(_str(value["outcome"])),
            RecordedAt.parse(_str(value["completed_at"])),
            tuple(ResearchArtifactRef.hydrate(_map(ref)) for ref in _seq(value["provenance_refs"])),
            _str(value["scope_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class MemorySearchBatch:
    batch_id: EntityId
    authority_id: str
    records: tuple[MemorySearchRecord, ...]
    authority_proof: str

    def __post_init__(self) -> None:
        if (
            type(self.batch_id) is not EntityId
            or self.batch_id.namespace != "memory_search_batch"
            or self.authority_id != _MEMORY_AUTHORITY
            or type(self.records) is not tuple
            or any(type(item) is not MemorySearchRecord for item in self.records)
            or tuple(sorted(set(self.records), key=lambda item: _ref_key(item.ref))) != self.records
        ):
            raise ValueError("memory search requires an owner-issued canonical sealed batch")
        if self.batch_id != semantic_entity_id("memory_search_batch", self.payload()):
            raise ValueError("memory search batch identity must bind authority content")
        _digest(self.authority_proof)

    def payload(self) -> dict[str, JsonValue]:
        return {"authority_id": self.authority_id, "records": tuple(item.to_dict() for item in self.records)}

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "batch_id": str(self.batch_id),
            **self.payload(),
            "content_sha256": self.content_sha256,
            "authority_proof": self.authority_proof,
        }

    @classmethod
    def seal(cls, records: tuple[MemorySearchRecord, ...]) -> MemorySearchBatch:
        raise PermissionError("memory batches can only be issued by TrustedMemorySearchPort")

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> MemorySearchBatch:
        _keys(
            value,
            {"batch_id", "authority_id", "records", "content_sha256", "authority_proof"},
            "memory search batch",
        )
        batch = cls(
            EntityId.parse(_str(value["batch_id"])),
            _str(value["authority_id"]),
            tuple(MemorySearchRecord.hydrate(_map(item)) for item in _seq(value["records"])),
            _str(value["authority_proof"]),
        )
        if batch.content_sha256 != _str(value["content_sha256"]):
            raise ValueError("memory batch content hash mismatch")
        return batch


@dataclass(frozen=True, slots=True)
class ExperimentSearchBatch:
    batch_id: EntityId
    authority_id: str
    records: tuple[ExperimentSearchRecord, ...]
    authority_proof: str

    def __post_init__(self) -> None:
        if (
            type(self.batch_id) is not EntityId
            or self.batch_id.namespace != "experiment_search_batch"
            or self.authority_id != _EXPERIMENT_AUTHORITY
            or type(self.records) is not tuple
            or any(type(item) is not ExperimentSearchRecord for item in self.records)
            or tuple(sorted(set(self.records), key=lambda item: _ref_key(item.ref))) != self.records
        ):
            raise ValueError("experiment search requires an owner-issued canonical sealed batch")
        if self.batch_id != semantic_entity_id("experiment_search_batch", self.payload()):
            raise ValueError("experiment search batch identity must bind authority content")
        _digest(self.authority_proof)

    def payload(self) -> dict[str, JsonValue]:
        return {"authority_id": self.authority_id, "records": tuple(item.to_dict() for item in self.records)}

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "batch_id": str(self.batch_id),
            **self.payload(),
            "content_sha256": self.content_sha256,
            "authority_proof": self.authority_proof,
        }

    @classmethod
    def seal(cls, records: tuple[ExperimentSearchRecord, ...]) -> ExperimentSearchBatch:
        raise PermissionError("experiment batches can only be issued by TrustedExperimentSearchPort")

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ExperimentSearchBatch:
        _keys(
            value,
            {"batch_id", "authority_id", "records", "content_sha256", "authority_proof"},
            "experiment search batch",
        )
        batch = cls(
            EntityId.parse(_str(value["batch_id"])),
            _str(value["authority_id"]),
            tuple(ExperimentSearchRecord.hydrate(_map(item)) for item in _seq(value["records"])),
            _str(value["authority_proof"]),
        )
        if batch.content_sha256 != _str(value["content_sha256"]):
            raise ValueError("experiment batch content hash mismatch")
        return batch


class TrustedMemorySearchPort:
    """Learning & Review-owned in-memory issuer for validated lesson results."""

    def __init__(self, secret: bytes) -> None:
        _validate_authority_secret(secret)
        self.__secret = secret

    def issue(self, records: tuple[MemorySearchRecord, ...]) -> MemorySearchBatch:
        ordered = _canonical_records(records, "memory")
        payload: dict[str, JsonValue] = {
            "authority_id": _MEMORY_AUTHORITY,
            "records": tuple(item.to_dict() for item in ordered),
        }
        content = canonical_sha256(payload)
        return MemorySearchBatch(
            semantic_entity_id("memory_search_batch", payload),
            _MEMORY_AUTHORITY,
            ordered,
            _authority_proof(_MEMORY_AUTHORITY, content, self.__secret),
        )

    def verify(self, value: MemorySearchBatch) -> None:
        if type(value) is not MemorySearchBatch or value.authority_id != _MEMORY_AUTHORITY:
            raise ValueError("memory batch issuer is not trusted")
        _verify_authority(value.authority_id, value.content_sha256, value.authority_proof, self.__secret)


class TrustedExperimentSearchPort:
    """Research-owned in-memory issuer that preserves success and failed facts."""

    def __init__(self, secret: bytes) -> None:
        _validate_authority_secret(secret)
        self.__secret = secret

    def issue(self, records: tuple[ExperimentSearchRecord, ...]) -> ExperimentSearchBatch:
        ordered = _canonical_records(records, "experiment")
        payload: dict[str, JsonValue] = {
            "authority_id": _EXPERIMENT_AUTHORITY,
            "records": tuple(item.to_dict() for item in ordered),
        }
        content = canonical_sha256(payload)
        return ExperimentSearchBatch(
            semantic_entity_id("experiment_search_batch", payload),
            _EXPERIMENT_AUTHORITY,
            ordered,
            _authority_proof(_EXPERIMENT_AUTHORITY, content, self.__secret),
        )

    def verify(self, value: ExperimentSearchBatch) -> None:
        if type(value) is not ExperimentSearchBatch or value.authority_id != _EXPERIMENT_AUTHORITY:
            raise ValueError("experiment batch issuer is not trusted")
        _verify_authority(value.authority_id, value.content_sha256, value.authority_proof, self.__secret)


class TrustedResearchToolsPort:
    """Composition-root capability for signing and verifying deterministic tool results."""

    def __init__(self, secret: bytes) -> None:
        _validate_authority_secret(secret)
        self.__secret = secret

    def sign(self, content_sha256: str) -> str:
        _digest(content_sha256)
        return _authority_proof(_RESULT_AUTHORITY, content_sha256, self.__secret)

    def verify(self, value: ResearchToolResult) -> None:
        if type(value) is not ResearchToolResult or value.authority_id != _RESULT_AUTHORITY:
            raise ValueError("research tool result issuer is not trusted")
        _verify_authority(value.authority_id, value.content_sha256, value.authority_proof, self.__secret)


@dataclass(frozen=True, slots=True)
class ValidationRunRequest:
    request_id: EntityId
    run_id: EntityId
    snapshot_ref: ResearchArtifactRef
    config: ValidationConfig
    query_scope: ResearchQueryScope
    feature_evidence: tuple[InjectedFeatureEvidenceRef, ...]
    memory_batch: MemorySearchBatch
    experiment_batch: ExperimentSearchBatch
    requested_tools: tuple[ResearchToolName, ...] = REQUIRED_TOOLSET

    def __post_init__(self) -> None:
        if (
            type(self.request_id) is not EntityId
            or self.request_id.namespace != "research_validation_request"
            or type(self.run_id) is not EntityId
            or self.run_id.namespace != "research_validation_run"
        ):
            raise ValueError("run request requires caller-persisted identities")
        if (
            type(self.snapshot_ref) is not ResearchArtifactRef
            or self.snapshot_ref.artifact_kind != "market_snapshot"
            or type(self.config) is not ValidationConfig
        ):
            raise ValueError("run request requires snapshot/config")
        if self.snapshot_ref.valid_until.value != self.snapshot_ref.as_of.value + timedelta(
            seconds=_VALIDATION_LIFETIME_SECONDS
        ):
            raise ValueError("snapshot ref lifetime must be fixed by V1-010 policy")
        if (
            type(self.query_scope) is not ResearchQueryScope
            or self.query_scope.config_sha256 != self.config.content_sha256
            or self.query_scope.signal_rule != self.config.signal_rule
            or type(self.feature_evidence) is not tuple
            or type(self.memory_batch) is not MemorySearchBatch
            or type(self.experiment_batch) is not ExperimentSearchBatch
            or any(type(item) is not InjectedFeatureEvidenceRef for item in self.feature_evidence)
        ):
            raise TypeError("run request accepts only typed authority-port records")
        scope_hash = self.query_scope.content_sha256
        if (
            any(item.scope_sha256 != scope_hash for item in self.feature_evidence)
            or any(item.scope_sha256 != scope_hash for item in self.memory_batch.records)
            or any(item.scope_sha256 != scope_hash for item in self.experiment_batch.records)
            or any(item.applicability_tags != self.query_scope.tags for item in self.memory_batch.records)
            or any(item.tags != self.query_scope.tags for item in self.experiment_batch.records)
        ):
            raise ValueError("run request evidence must bind the exact research query scope")
        if tuple(sorted(set(self.feature_evidence), key=lambda item: _ref_key(item.ref))) != self.feature_evidence:
            raise ValueError("run request collections must be unique and canonical by full identity")
        for item in self.feature_evidence:
            feature_payload = cast("dict[str, object]", json.loads(item.feature_observation_payload_json))
            snapshots = _seq(feature_payload["market_snapshot_refs"])
            if not snapshots:
                raise ValueError("feature evidence requires snapshot lineage")
            latest = _map(snapshots[-1])
            if (
                feature_payload["target_reference_id"] != self.query_scope.instrument_key
                or latest.get("snapshot_id") != str(self.snapshot_ref.artifact_id)
                or latest.get("content_sha256") != self.snapshot_ref.content_sha256
                or latest.get("as_of") != _time(self.snapshot_ref.as_of)
                or latest.get("schema_version") != str(self.snapshot_ref.schema_version)
            ):
                raise ValueError("feature evidence must bind the exact target and MarketSnapshot lineage")
        refs = (
            tuple(item.ref for item in self.feature_evidence)
            + tuple(item.ref for item in self.memory_batch.records)
            + tuple(item.ref for item in self.experiment_batch.records)
        )
        if any(
            ref.as_of.value > self.snapshot_ref.as_of.value
            or ref.valid_until.value < self.snapshot_ref.valid_until.value
            for ref in refs
        ) or any(item.completed_at.value > self.snapshot_ref.as_of.value for item in self.experiment_batch.records):
            raise ValueError("run request rejects future/expired evidence")
        if self.requested_tools != REQUIRED_TOOLSET:
            raise ValueError("run request must freeze the full ordered V1-010 toolset")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "run_id": str(self.run_id),
            "snapshot_ref": self.snapshot_ref.to_dict(),
            "config": self.config.payload(),
            "config_sha256": self.config.content_sha256,
            "query_scope": self.query_scope.to_dict(),
            "feature_evidence": tuple(item.to_dict() for item in self.feature_evidence),
            "memory_batch": self.memory_batch.to_dict(),
            "experiment_batch": self.experiment_batch.to_dict(),
            "requested_tools": tuple(item.value for item in self.requested_tools),
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "request_id": str(self.request_id),
            **self.payload(),
            "config": self.config.to_dict(),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ValidationRunRequest:
        _keys(
            value,
            {
                "request_id",
                "run_id",
                "snapshot_ref",
                "config",
                "config_sha256",
                "query_scope",
                "feature_evidence",
                "memory_batch",
                "experiment_batch",
                "requested_tools",
                "content_sha256",
            },
            "validation run request",
        )
        feature = tuple(InjectedFeatureEvidenceRef.hydrate(_map(item)) for item in _seq(value["feature_evidence"]))
        request = cls(
            EntityId.parse(_str(value["request_id"])),
            EntityId.parse(_str(value["run_id"])),
            ResearchArtifactRef.hydrate(_map(value["snapshot_ref"])),
            ValidationConfig.hydrate(_map(value["config"])),
            ResearchQueryScope.hydrate(_map(value["query_scope"])),
            feature,
            MemorySearchBatch.hydrate(_map(value["memory_batch"])),
            ExperimentSearchBatch.hydrate(_map(value["experiment_batch"])),
            tuple(ResearchToolName(_str(item)) for item in _seq(value["requested_tools"])),
        )
        if request.config.content_sha256 != _str(value["config_sha256"]):
            raise ValueError("run request config hash mismatch")
        if request.content_sha256 != _str(value["content_sha256"]):
            raise ValueError("run request content hash mismatch")
        return request


@dataclass(frozen=True, slots=True)
class ResearchToolResult:
    result_id: EntityId
    tool: ResearchToolName
    as_of: RecordedAt
    valid_until: RecordedAt
    source_refs: tuple[ResearchArtifactRef, ...]
    warnings: tuple[str, ...]
    failure_code: ToolFailureCode
    request_sha256: str
    config: ValidationConfig
    run_id: EntityId
    metrics: tuple[tuple[str, str], ...]
    content_sha256: str
    authority_id: str
    authority_proof: str
    tool_version: str = TOOLSET_VERSION
    schema_version: SchemaVersion = TOOL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.result_id) is not EntityId
            or self.result_id.namespace != "research_tool_result"
            or type(self.run_id) is not EntityId
            or self.run_id.namespace != "research_validation_run"
        ):
            raise ValueError("result requires exact identities")
        if (
            type(self.tool) is not ResearchToolName
            or type(self.failure_code) is not ToolFailureCode
            or type(self.config) is not ValidationConfig
        ):
            raise TypeError("result requires closed types")
        if (
            self.tool_version != TOOLSET_VERSION
            or self.schema_version != TOOL_SCHEMA_VERSION
            or self.valid_until.value <= self.as_of.value
            or self.authority_id != _RESULT_AUTHORITY
        ):
            raise ValueError("result requires pinned version and lifetime")
        if (
            type(self.source_refs) is not tuple
            or not self.source_refs
            or tuple(sorted(set(self.source_refs), key=_ref_key)) != self.source_refs
            or any(
                ref.as_of.value > self.as_of.value or ref.valid_until.value < self.valid_until.value
                for ref in self.source_refs
            )
        ):
            raise ValueError("result sources require canonical PIT lifetime")
        if (
            tuple(sorted(set(self.warnings))) != self.warnings
            or tuple(sorted(set(self.metrics))) != self.metrics
            or len({key for key, _ in self.metrics}) != len(self.metrics)
        ):
            raise ValueError("result warnings/metric keys must be canonical unique")
        _digest(self.request_sha256)
        _digest(self.content_sha256)
        _digest(self.authority_proof)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("result content hash mismatch")
        if self.result_id != semantic_entity_id(
            "research_tool_result", {"request_sha256": self.request_sha256, "tool": self.tool.value}
        ):
            raise ValueError("result logical identity must derive from request and tool")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "tool": self.tool.value,
            "tool_version": self.tool_version,
            "schema_version": str(self.schema_version),
            "as_of": _time(self.as_of),
            "valid_until": _time(self.valid_until),
            "source_refs": tuple(ref.to_dict() for ref in self.source_refs),
            "warnings": self.warnings,
            "failure_code": self.failure_code.value,
            "request_sha256": self.request_sha256,
            "config": self.config.payload(),
            "config_sha256": self.config.content_sha256,
            "run_id": str(self.run_id),
            "metrics": self.metrics,
        }

    @property
    def artifact_refs(self) -> tuple[ResearchArtifactRef, ...]:
        return (
            ResearchArtifactRef(
                self.result_id, self.tool.value, self.schema_version, self.content_sha256, self.as_of, self.valid_until
            ),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "result_id": str(self.result_id),
            **self.payload(),
            "config": self.config.to_dict(),
            "artifact_refs": tuple(ref.to_dict() for ref in self.artifact_refs),
            "content_sha256": self.content_sha256,
            "authority_id": self.authority_id,
            "authority_proof": self.authority_proof,
        }

    @classmethod
    def hydrate(cls, value: Mapping[str, object]) -> ResearchToolResult:
        _keys(
            value,
            {
                "result_id",
                "tool",
                "tool_version",
                "schema_version",
                "as_of",
                "valid_until",
                "source_refs",
                "warnings",
                "failure_code",
                "request_sha256",
                "config",
                "config_sha256",
                "run_id",
                "metrics",
                "artifact_refs",
                "content_sha256",
                "authority_id",
                "authority_proof",
            },
            "research tool result",
        )
        result = cls(
            EntityId.parse(_str(value["result_id"])),
            ResearchToolName(_str(value["tool"])),
            RecordedAt.parse(_str(value["as_of"])),
            RecordedAt.parse(_str(value["valid_until"])),
            tuple(ResearchArtifactRef.hydrate(_map(ref)) for ref in _seq(value["source_refs"])),
            tuple(_str(item) for item in _seq(value["warnings"])),
            ToolFailureCode(_str(value["failure_code"])),
            _str(value["request_sha256"]),
            ValidationConfig.hydrate(_map(value["config"])),
            EntityId.parse(_str(value["run_id"])),
            tuple((_str(_seq(item)[0]), _str(_seq(item)[1])) for item in _seq(value["metrics"])),
            _str(value["content_sha256"]),
            _str(value["authority_id"]),
            _str(value["authority_proof"]),
            _str(value["tool_version"]),
            SchemaVersion.parse(_str(value["schema_version"])),
        )
        if (
            tuple(ResearchArtifactRef.hydrate(_map(ref)) for ref in _seq(value["artifact_refs"]))
            != result.artifact_refs
        ):
            raise ValueError("result artifact ref does not bind full content")
        return result


@dataclass(frozen=True, slots=True)
class _Sample:
    signal_time: RecordedAt
    label_time: RecordedAt
    signal: int
    label: int
    proxy_return: Decimal


class DeterministicResearchTools:
    """Synchronous Research worker port; no order/fill/position dependencies."""

    def __init__(
        self,
        feature_authority: TrustedFeatureEvidencePort,
        memory_authority: TrustedMemorySearchPort,
        experiment_authority: TrustedExperimentSearchPort,
        result_authority: TrustedResearchToolsPort,
    ) -> None:
        if (
            type(feature_authority) is not TrustedFeatureEvidencePort
            or type(memory_authority) is not TrustedMemorySearchPort
            or type(experiment_authority) is not TrustedExperimentSearchPort
            or type(result_authority) is not TrustedResearchToolsPort
        ):
            raise TypeError("research tools require explicitly injected trusted owner ports")
        self._feature_authority = feature_authority
        self._memory_authority = memory_authority
        self._experiment_authority = experiment_authority
        self._result_authority = result_authority

    def verify_results(self, results: tuple[ResearchToolResult, ...]) -> None:
        if type(results) is not tuple or any(type(item) is not ResearchToolResult for item in results):
            raise TypeError("research tool result verification requires exact typed tuples")
        for result in results:
            result.__post_init__()
            self._result_authority.verify(result)

    def run_snapshot_suite(
        self, snapshot: MarketSnapshot, request: ValidationRunRequest
    ) -> tuple[ResearchToolResult, ...]:
        if type(snapshot) is not MarketSnapshot or type(request) is not ValidationRunRequest:
            raise TypeError("suite requires MarketSnapshot and ValidationRunRequest")
        snapshot.__post_init__()
        request.__post_init__()
        for feature in request.feature_evidence:
            self._feature_authority.verify(feature)
        self._memory_authority.verify(request.memory_batch)
        self._experiment_authority.verify(request.experiment_batch)
        if (
            request.snapshot_ref.artifact_id != snapshot.snapshot_id
            or request.snapshot_ref.content_sha256 != snapshot.expected_content_sha256
            or request.snapshot_ref.as_of != snapshot.as_of
            or request.snapshot_ref.schema_version != snapshot.schema_version
            or request.query_scope.instrument_key != snapshot.rule_resolution.rule.instrument.reference_id
            or request.query_scope.market != snapshot.rule_resolution.rule.instrument.variety.code
        ):
            raise ValueError("request does not bind exact snapshot and instrument scope")
        bars = tuple(
            item
            for item in snapshot.active_observations
            if item.kind is ObservationKind.BAR
            and item.bar_status is BarStatus.FINAL
            and item.open_price
            and item.close_price
        )
        samples = _samples(bars, request.config)
        quality = snapshot.eligible_for(snapshot.intended_purpose)
        base_failure = ToolFailureCode.DATA_QUALITY if quality else ToolFailureCode.NONE
        base_warnings = () if quality is None else (quality.reason_code.value,)
        enough = quality is None and len(samples) >= request.config.train_bars + request.config.test_bars + 1
        vf = ToolFailureCode.NONE if enough else (base_failure if quality else ToolFailureCode.INSUFFICIENT_SAMPLE)
        vw = base_warnings if quality else (() if enough else ("fixed minimum sample not met",))
        common = (request.snapshot_ref,)
        future = sum(
            item.available_time.value > snapshot.as_of.value or item.ingested_at.value > snapshot.as_of.value
            for item in snapshot.observations
        )
        l0 = _l0(samples)
        l1 = _l1(samples, request.config)
        results = (
            _result(
                ResearchToolName.MARKET_QUERY,
                request,
                common,
                base_warnings,
                base_failure,
                (
                    ("active_observation_count", str(len(snapshot.active_observations))),
                    ("future_observation_count", str(future)),
                ),
                self._result_authority,
            ),
            _result(
                ResearchToolName.HISTORICAL_QUERY,
                request,
                common,
                base_warnings,
                base_failure,
                (("final_bar_count", str(len(bars))), ("future_observation_count", str(future))),
                self._result_authority,
            ),
            _result(
                ResearchToolName.FEATURE_QUERY,
                request,
                tuple(item.ref for item in request.feature_evidence) or common,
                vw,
                vf if request.feature_evidence else ToolFailureCode.NO_MATCH,
                (("injected_feature_count", str(len(request.feature_evidence))),),
                self._result_authority,
            ),
            _result(
                ResearchToolName.CONTRACT_QUERY,
                request,
                common,
                base_warnings,
                base_failure,
                (("rule_version", str(snapshot.rule_resolution.rule.version)),),
                self._result_authority,
            ),
            _search(ResearchToolName.MEMORY_SEARCH, request, self._result_authority),
            _search(ResearchToolName.EXPERIMENT_SEARCH, request, self._result_authority),
            _result(ResearchToolName.L0_SIGNAL_TEST, request, common, vw, vf, l0, self._result_authority),
            _result(
                ResearchToolName.L1_BAR_BACKTEST,
                request,
                common,
                tuple(sorted((*vw, "close-to-next-open directional approximation; no fill semantics"))),
                vf,
                l1,
                self._result_authority,
            ),
            _result(
                ResearchToolName.WALK_FORWARD,
                request,
                common,
                vw,
                vf,
                _walk(samples, request.config),
                self._result_authority,
            ),
            _result(
                ResearchToolName.COST_STRESS,
                request,
                common,
                vw,
                vf,
                _stress(samples, request.config),
                self._result_authority,
            ),
            _result(
                ResearchToolName.COUNTERFACTUAL,
                request,
                common,
                vw,
                vf,
                _counterfactual(samples, request.config),
                self._result_authority,
            ),
        )
        return tuple(sorted(results, key=lambda item: item.tool.value))


def _result(
    tool: ResearchToolName,
    request: ValidationRunRequest,
    sources: tuple[ResearchArtifactRef, ...],
    warnings: tuple[str, ...],
    failure: ToolFailureCode,
    metrics: tuple[tuple[str, str], ...],
    authority: TrustedResearchToolsPort,
) -> ResearchToolResult:
    sources = tuple(sorted(set(sources), key=_ref_key))
    warnings = tuple(sorted(set(warnings)))
    metrics = tuple(sorted(metrics))
    result_id = semantic_entity_id(
        "research_tool_result",
        {"request_sha256": request.content_sha256, "tool": tool.value},
    )
    payload: dict[str, JsonValue] = {
        "tool": tool.value,
        "tool_version": TOOLSET_VERSION,
        "schema_version": str(TOOL_SCHEMA_VERSION),
        "as_of": _time(request.snapshot_ref.as_of),
        "valid_until": _time(request.snapshot_ref.valid_until),
        "source_refs": tuple(ref.to_dict() for ref in sources),
        "warnings": warnings,
        "failure_code": failure.value,
        "request_sha256": request.content_sha256,
        "config": request.config.payload(),
        "config_sha256": request.config.content_sha256,
        "run_id": str(request.run_id),
        "metrics": metrics,
    }
    content_sha256 = canonical_sha256(payload)
    return ResearchToolResult(
        result_id,
        tool,
        request.snapshot_ref.as_of,
        request.snapshot_ref.valid_until,
        sources,
        warnings,
        failure,
        request.content_sha256,
        request.config,
        request.run_id,
        metrics,
        content_sha256,
        _RESULT_AUTHORITY,
        authority.sign(content_sha256),
    )


def _search(
    tool: ResearchToolName, request: ValidationRunRequest, authority: TrustedResearchToolsPort
) -> ResearchToolResult:
    metrics: tuple[tuple[str, str], ...]
    if tool is ResearchToolName.MEMORY_SEARCH:
        memory_selected = tuple(
            item
            for item in request.memory_batch.records
            if set(request.query_scope.tags) <= set(item.applicability_tags)
        )
        sources = tuple(item.ref for item in memory_selected)
        metrics = (("active_lesson_count", str(len(memory_selected))),)
    else:
        experiment_selected = tuple(
            item for item in request.experiment_batch.records if set(request.query_scope.tags) <= set(item.tags)
        )
        sources = tuple(item.ref for item in experiment_selected)
        metrics = (
            ("failed_count", str(sum(item.outcome is ExperimentOutcome.FAILED for item in experiment_selected))),
            ("match_count", str(len(experiment_selected))),
            ("success_count", str(sum(item.outcome is ExperimentOutcome.SUCCESS for item in experiment_selected))),
        )
    return _result(
        tool,
        request,
        sources or (request.snapshot_ref,),
        () if sources else ("no PIT-visible match",),
        ToolFailureCode.NONE if sources else ToolFailureCode.NO_MATCH,
        metrics,
        authority,
    )


def _samples(bars: tuple[MarketObservation, ...], config: ValidationConfig) -> tuple[_Sample, ...]:
    ordered = tuple(sorted(bars, key=lambda item: item.event_time.value))
    output = []
    for prior, current, future in zip(ordered, ordered[1:], ordered[2:], strict=False):
        assert prior.close_price and current.close_price and future.close_price and future.open_price
        signal_return = _ratio(Decimal(current.close_price.amount), Decimal(prior.close_price.amount))
        signal = (
            1 if signal_return >= config.signal_threshold else (-1 if signal_return <= -config.signal_threshold else 0)
        )
        forward = _ratio(Decimal(future.close_price.amount), Decimal(current.close_price.amount))
        label = 1 if forward > 0 else (-1 if forward < 0 else 0)
        output.append(
            _Sample(
                current.event_time,
                future.event_time,
                signal,
                label,
                _ratio(Decimal(future.open_price.amount), Decimal(current.close_price.amount)),
            )
        )
    return tuple(output)


def _l0(samples: tuple[_Sample, ...]) -> tuple[tuple[str, str], ...]:
    signalled = tuple(item for item in samples if item.signal)
    hits = sum(item.signal == item.label for item in signalled)
    return (
        ("accuracy", _ratio_text(hits, len(signalled))),
        ("eligible_count", str(len(samples))),
        ("hit_count", str(hits)),
        ("label_rule", "next_close_direction.v1"),
        ("signal_count", str(len(signalled))),
        ("signal_coverage", _ratio_text(len(signalled), len(samples))),
    )


def _values(
    samples: tuple[_Sample, ...],
    config: ValidationConfig,
    cost_multiplier: Decimal = Decimal(1),
    slippage_multiplier: Decimal = Decimal(1),
    invert: bool = False,
) -> tuple[Decimal, ...]:
    cost = (config.round_trip_cost_bps * cost_multiplier + config.slippage_bps * slippage_multiplier) / Decimal(10_000)
    return tuple(
        Decimal(-item.signal if invert else item.signal) * item.proxy_return - cost for item in samples if item.signal
    )


def _l1(samples: tuple[_Sample, ...], config: ValidationConfig) -> tuple[tuple[str, str], ...]:
    gross = tuple(Decimal(item.signal) * item.proxy_return for item in samples if item.signal)
    total = sum((abs(value) for value in gross), Decimal(0))
    contribution = Decimal(0) if total == 0 else max(abs(value) for value in gross) / total
    return (
        ("gross_directional_mean", _dec(_mean(gross))),
        ("max_abs_contribution_ratio", _dec(contribution)),
        ("net_directional_mean", _dec(_mean(_values(samples, config)))),
        ("proxy_rule", "signal_at_close_to_next_open.v1"),
        ("signal_count", str(len(gross))),
    )


def _walk(samples: tuple[_Sample, ...], config: ValidationConfig) -> tuple[tuple[str, str], ...]:
    folds: list[dict[str, JsonValue]] = []
    failures = 0
    stopped = False
    embargo_bars = 1
    windows = plan_walk_forward_fold_windows(
        len(samples),
        train_bars=config.train_bars,
        test_bars=config.test_bars,
        step_bars=config.step_bars,
        embargo_bars=embargo_bars,
    )
    for window in windows:
        train = samples[window.train_start : window.train_end]
        test = samples[window.test_start : window.test_end]
        signalled = tuple(item for item in test if item.signal)
        accuracy = (
            Decimal(sum(item.signal == item.label for item in signalled)) / Decimal(len(signalled))
            if signalled
            else Decimal(0)
        )
        folds.append(
            {
                "train_start": _time(train[0].signal_time),
                "train_end": _time(train[-1].label_time),
                "test_start": _time(test[0].signal_time),
                "test_end": _time(test[-1].label_time),
                "test_accuracy": _dec(accuracy),
                "config_sha256": config.content_sha256,
            }
        )
        failures = failures + 1 if accuracy < config.minimum_signal_accuracy else 0
        if failures >= config.stop_after_failures:
            stopped = True
            break
    positive = sum(Decimal(_str(fold["test_accuracy"])) >= config.minimum_signal_accuracy for fold in folds)
    return (
        ("fold_count", str(len(folds))),
        ("fold_manifest", canonical_json_text(cast("JsonValue", tuple(folds)))),
        ("positive_fold_ratio", _ratio_text(positive, len(folds))),
        ("stopped_early", str(stopped).lower()),
        ("tuning_count", "0"),
    )


def _stress(samples: tuple[_Sample, ...], config: ValidationConfig) -> tuple[tuple[str, str], ...]:
    scenarios = (
        {"changed_variable": "none", "multiplier": _dec(Decimal(1)), "net_mean": _dec(_mean(_values(samples, config)))},
        *(
            {
                "changed_variable": "round_trip_cost_bps",
                "multiplier": _dec(multiplier),
                "net_mean": _dec(_mean(_values(samples, config, cost_multiplier=multiplier))),
            }
            for multiplier in config.stress_multipliers[1:]
        ),
        *(
            {
                "changed_variable": "slippage_bps",
                "multiplier": _dec(multiplier),
                "net_mean": _dec(_mean(_values(samples, config, slippage_multiplier=multiplier))),
            }
            for multiplier in config.stress_multipliers[1:]
        ),
    )
    return (
        (
            "baseline_gross_mean",
            _dec(_mean(tuple(Decimal(item.signal) * item.proxy_return for item in samples if item.signal))),
        ),
        ("scenario_count", str(len(scenarios))),
        ("scenarios", canonical_json_text(cast("JsonValue", scenarios))),
        (
            "worst_net_mean",
            _dec(min((Decimal(_str(item["net_mean"])) for item in scenarios), default=Decimal(0))),
        ),
    )


def _counterfactual(samples: tuple[_Sample, ...], config: ValidationConfig) -> tuple[tuple[str, str], ...]:
    return (
        ("baseline_net_mean", _dec(_mean(_values(samples, config)))),
        ("changed_variable", "signal_direction"),
        ("counterfactual_net_mean", _dec(_mean(_values(samples, config, invert=True)))),
        ("fixed_config_sha256", config.content_sha256),
    )


def _ratio(current: Decimal, prior: Decimal) -> Decimal:
    if prior == 0:
        return Decimal(0)
    with localcontext() as context:
        context.prec = 50
        return ((current / prior) - Decimal(1)).quantize(_SCALE, rounding=ROUND_HALF_EVEN)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return (
        Decimal(0)
        if not values
        else (sum(values, Decimal(0)) / Decimal(len(values))).quantize(_SCALE, rounding=ROUND_HALF_EVEN)
    )


def _dec(value: Decimal) -> str:
    return format(value.quantize(_SCALE, rounding=ROUND_HALF_EVEN), "f")


def _ratio_text(a: int, b: int) -> str:
    return _dec(Decimal(0) if not b else Decimal(a) / Decimal(b))


def _time(value: RecordedAt) -> str:
    return value.to_dict()["recorded_at"]


def _ref_key(ref: ResearchArtifactRef) -> tuple[str, str, str, str, str, str]:
    return (
        ref.artifact_kind,
        str(ref.artifact_id),
        str(ref.schema_version),
        ref.content_sha256,
        _time(ref.as_of),
        _time(ref.valid_until),
    )


def _feature_unsigned(ref: ResearchArtifactRef, payload_json: str, scope_sha256: str) -> dict[str, JsonValue]:
    return {"ref": ref.to_dict(), "payload_json": payload_json, "scope_sha256": scope_sha256}


def _freeze_json(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return cast("JsonValue", value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, Mapping) and all(type(key) is str for key in value):
        return {str(key): _freeze_json(item) for key, item in value.items()}
    raise ValueError("feature observation payload contains non-JSON values")


_RecordT = TypeVar("_RecordT", MemorySearchRecord, ExperimentSearchRecord)


def _canonical_records(records: tuple[_RecordT, ...], label: str) -> tuple[_RecordT, ...]:
    if type(records) is not tuple:
        raise TypeError(f"{label} authority store emits exact tuples")
    if len(set(records)) != len(records):
        raise ValueError(f"{label} authority store rejects duplicate records")
    return tuple(sorted(records, key=lambda item: _ref_key(item.ref)))


def _digest(value: str) -> None:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("requires lowercase SHA-256")


def _tags(value: tuple[str, ...]) -> None:
    if (
        type(value) is not tuple
        or tuple(sorted(set(value))) != value
        or any(type(tag) is not str or not tag.strip() for tag in value)
    ):
        raise ValueError("tags must be canonical")


def _keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields are not exact")


def _map(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("requires mapping")
    return cast("Mapping[str, object]", value)


def _seq(value: object) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("requires sequence")
    return tuple(value)


def _str(value: object) -> str:
    if type(value) is not str:
        raise TypeError("requires string")
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise TypeError("requires integer")
    return value


def semantic_entity_id(namespace: str, payload: JsonValue) -> EntityId:
    raw = bytearray(sha256(canonical_json_text(payload).encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return EntityId(namespace, UUID(bytes=bytes(raw)))
