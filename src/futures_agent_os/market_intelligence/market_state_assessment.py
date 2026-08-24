"""Market Intelligence owned, deterministic composition of market-state evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.market_intelligence.feature_engine import FeatureObservation, MarketSnapshotRef
from futures_agent_os.market_intelligence.regime_model_service import (
    FeatureArtifactRef,
    RegimeAssessment,
    RegimeCandidate,
    RegimeKind,
)
from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    ModelOutputAuthority,
    ReasonCode,
    RecordedAt,
    SchemaVersion,
    canonical_sha256,
)
from futures_agent_os.shared_kernel.observability import JsonValue


MARKET_STATE_COMPOSITION_VERSION = "fao.market-state-assessment.v1"


class TransitionRisk(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MarketStateAssessmentSpec:
    spec_id: EntityId
    version: int
    schema_version: SchemaVersion
    algorithm_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.spec_id, EntityId) or self.spec_id.namespace != "market_state_assessment_spec":
            raise ValueError("market state assessment spec requires a market_state_assessment_spec id")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("market state assessment spec version must be positive")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("market state assessment spec requires SchemaVersion")
        if self.algorithm_version != MARKET_STATE_COMPOSITION_VERSION:
            raise ValueError("unsupported market state assessment algorithm_version")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "spec_id": str(self.spec_id),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True, slots=True)
class MarketStateEvidence:
    source_id: EntityId
    source_content_sha256: str
    statement: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, EntityId):
            raise TypeError("market state evidence requires a typed source id")
        if len(self.source_content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_content_sha256
        ):
            raise ValueError("market state evidence requires a lowercase source hash")
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise ValueError("market state evidence requires a non-empty statement")

    def to_dict(self) -> dict[str, str]:
        return {
            "source_content_sha256": self.source_content_sha256,
            "statement": self.statement,
        }


@dataclass(frozen=True, slots=True)
class FeatureObservationLineage:
    observation_id: EntityId
    content_sha256: str
    schema_version: SchemaVersion
    as_of: RecordedAt

    @classmethod
    def from_observation(cls, value: FeatureObservation) -> FeatureObservationLineage:
        return cls(value.observation_id, value.content_sha256, value.schema_version, value.as_of)

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, EntityId) or self.observation_id.namespace != "feature_observation":
            raise ValueError("feature lineage requires a feature_observation id")
        if len(self.content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_sha256
        ):
            raise ValueError("feature lineage requires a lowercase content hash")
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.as_of, RecordedAt):
            raise TypeError("feature lineage requires schema version and as_of")


@dataclass(frozen=True, slots=True)
class MarketStateCandidate:
    state: RegimeKind
    confidence: Decimal
    support: tuple[MarketStateEvidence, ...]
    counter_evidence: tuple[MarketStateEvidence, ...]
    unknowns: tuple[str, ...]

    def __post_init__(self) -> None:
        support = tuple(self.support)
        counter = tuple(self.counter_evidence)
        unknowns = tuple(sorted(self.unknowns))
        if (
            not isinstance(self.state, RegimeKind)
            or not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
        ):
            raise TypeError("market state candidate requires RegimeKind and finite Decimal confidence")
        if not 0 <= self.confidence <= 1 or not (support or counter or unknowns):
            raise ValueError("market state candidate requires confidence and evidence or an explicit unknown")
        if any(not isinstance(item, MarketStateEvidence) for item in (*support, *counter)):
            raise TypeError("market state evidence must be source-bound")
        if any(not isinstance(item, str) or not item.strip() for item in unknowns):
            raise ValueError("market state candidate unknowns must be non-empty strings")
        object.__setattr__(self, "support", _dedupe_evidence(support))
        object.__setattr__(self, "counter_evidence", _dedupe_evidence(counter))
        object.__setattr__(self, "unknowns", unknowns)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "state": self.state.value,
            "confidence": str(self.confidence),
            "support": tuple(item.to_dict() for item in self.support),
            "counter_evidence": tuple(item.to_dict() for item in self.counter_evidence),
            "unknowns": self.unknowns,
        }


@dataclass(frozen=True, slots=True)
class MarketStateAssessmentInput:
    market_snapshot: MarketSnapshotRef
    features: tuple[FeatureObservation, ...]
    deterministic_regime: RegimeAssessment

    def __post_init__(self) -> None:
        features = tuple(self.features)
        if (
            not isinstance(self.market_snapshot, MarketSnapshotRef)
            or not isinstance(self.deterministic_regime, RegimeAssessment)
            or not features
            or any(not isinstance(item, FeatureObservation) for item in features)
        ):
            raise TypeError("market state input requires immutable snapshot, features, and deterministic regime")
        if self.deterministic_regime.authority is not ModelOutputAuthority.NON_TRADING:
            raise ValueError("market state input only accepts NON_TRADING regime output")
        if self.deterministic_regime.terminal_market_snapshot_ref != self.market_snapshot:
            raise ValueError("market state snapshot must exactly match deterministic regime terminal snapshot")
        if self.deterministic_regime.as_of != self.market_snapshot.as_of:
            raise ValueError("market state inputs must share as_of")
        if len({item.observation_id for item in features}) != len(features):
            raise ValueError("market state feature observations must be unique")
        if any(item.as_of != self.market_snapshot.as_of for item in features):
            raise ValueError("market state features must share snapshot as_of")
        if any(
            not item.market_snapshot_refs or item.market_snapshot_refs[-1] != self.market_snapshot for item in features
        ):
            raise ValueError("market state features must terminate at supplied immutable snapshot")
        if {FeatureArtifactRef.from_observation(item) for item in features} != set(
            self.deterministic_regime.feature_observation_refs
        ):
            raise ValueError("market state features must exactly match deterministic regime lineage")
        if len({item.kind for item in self.deterministic_regime.candidates}) != len(
            self.deterministic_regime.candidates
        ):
            raise ValueError("market state rejects ambiguous duplicate deterministic candidates")
        object.__setattr__(self, "features", tuple(sorted(features, key=lambda item: item.content_sha256)))


@dataclass(frozen=True, slots=True)
class MarketStateAssessment:
    assessment_id: EntityId
    spec: MarketStateAssessmentSpec
    as_of: RecordedAt
    valid_until: RecordedAt
    market_snapshot: MarketSnapshotRef
    feature_observation_refs: tuple[FeatureArtifactRef, ...]
    feature_lineage: tuple[FeatureObservationLineage, ...]
    regime_assessment_id: EntityId
    regime_assessment_content_sha256: str
    regime_assessment_schema_version: SchemaVersion
    primary_state: RegimeKind | None
    candidates: tuple[MarketStateCandidate, ...]
    conflicts: tuple[tuple[RegimeKind, RegimeKind], ...]
    alternative_explanations: tuple[str, ...]
    transition_risk: TransitionRisk
    unknowns: tuple[str, ...]
    authority: ModelOutputAuthority
    content_sha256: str

    @property
    def schema_version(self) -> SchemaVersion:
        return self.spec.schema_version

    def __post_init__(self) -> None:
        raw_refs = tuple(self.feature_observation_refs)
        if any(not isinstance(item, FeatureArtifactRef) for item in raw_refs):
            raise TypeError("market state feature references must use typed FeatureArtifactRef values")
        refs = tuple(sorted(raw_refs, key=lambda item: (item.content_sha256, str(item.observation_id))))
        raw_feature_lineage = tuple(self.feature_lineage)
        if any(not isinstance(item, FeatureObservationLineage) for item in raw_feature_lineage):
            raise TypeError("market state feature lineage must use typed FeatureObservationLineage values")
        feature_lineage = tuple(
            sorted(raw_feature_lineage, key=lambda item: (item.content_sha256, str(item.observation_id)))
        )
        raw_candidates = tuple(self.candidates)
        if any(not isinstance(item, MarketStateCandidate) for item in raw_candidates):
            raise TypeError("market state candidates must use typed MarketStateCandidate values")
        candidates = tuple(sorted(raw_candidates, key=lambda item: item.state.value))
        raw_conflicts = tuple(self.conflicts)
        if any(not isinstance(pair, tuple) or len(pair) != 2 for pair in raw_conflicts):
            raise TypeError("market state conflicts must use typed pairs")
        conflicts = tuple(sorted(raw_conflicts, key=lambda item: (item[0].value, item[1].value)))
        alternatives = tuple(sorted(tuple(self.alternative_explanations)))
        unknowns = tuple(sorted(tuple(self.unknowns)))
        if not isinstance(self.assessment_id, EntityId) or self.assessment_id.namespace != "market_state_assessment":
            raise ValueError("market state assessment requires a market_state_assessment id")
        if (
            not isinstance(self.spec, MarketStateAssessmentSpec)
            or not isinstance(self.as_of, RecordedAt)
            or not isinstance(self.valid_until, RecordedAt)
            or not isinstance(self.market_snapshot, MarketSnapshotRef)
            or not isinstance(self.regime_assessment_id, EntityId)
            or self.regime_assessment_id.namespace != "regime_assessment"
            or not isinstance(self.regime_assessment_schema_version, SchemaVersion)
            or not isinstance(self.transition_risk, TransitionRisk)
        ):
            raise TypeError("market state assessment requires typed sources and transition risk")
        if self.valid_until.value <= self.as_of.value or not refs or not candidates:
            raise ValueError("market state assessment requires a valid lifetime, lineage, and candidates")
        if len({(item.observation_id, item.content_sha256) for item in refs}) != len(refs):
            raise ValueError("market state feature lineage must be unique")
        if (
            len(feature_lineage) != len(refs)
            or len({(item.observation_id, item.content_sha256) for item in feature_lineage}) != len(feature_lineage)
            or any(item.as_of != self.as_of for item in feature_lineage)
            or {(item.observation_id, item.content_sha256) for item in feature_lineage}
            != {(item.observation_id, item.content_sha256) for item in refs}
        ):
            raise ValueError("market state feature artifact lineage must exactly match feature references")
        if len({item.state for item in candidates}) != len(candidates):
            raise ValueError("market state candidates must have unique states")
        eligible = tuple(item for item in candidates if item.support)
        leaders = {
            item.state for item in eligible if item.confidence == max(candidate.confidence for candidate in eligible)
        }
        if (self.primary_state is None) != (len(leaders) != 1) or (
            self.primary_state is not None and self.primary_state not in leaders
        ):
            raise ValueError("market state primary state must be the unique highest-confidence candidate")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(state, RegimeKind) for state in pair)
            or pair[0] == pair[1]
            for pair in conflicts
        ) or len(set(conflicts)) != len(conflicts):
            raise ValueError("market state conflicts must be unique pairs of distinct RegimeKind values")
        if any(not isinstance(item, str) or not item.strip() for item in (*alternatives, *unknowns)):
            raise ValueError("market state alternatives and unknowns must be non-empty strings")
        if len(self.regime_assessment_content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.regime_assessment_content_sha256
        ):
            raise ValueError("market state assessment requires deterministic regime hash")
        if self.authority is not ModelOutputAuthority.NON_TRADING:
            raise ValueError("market state assessment is never trading authority")
        known_sources = {(item.observation_id, item.content_sha256) for item in refs}
        known_sources.add((self.regime_assessment_id, self.regime_assessment_content_sha256))
        if any(
            (evidence.source_id, evidence.source_content_sha256) not in known_sources
            for candidate in candidates
            for evidence in (*candidate.support, *candidate.counter_evidence)
        ):
            raise ValueError("market state evidence must belong to declared immutable lineage")
        object.__setattr__(self, "feature_observation_refs", refs)
        object.__setattr__(self, "feature_lineage", feature_lineage)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "conflicts", conflicts)
        object.__setattr__(self, "alternative_explanations", alternatives)
        object.__setattr__(self, "unknowns", unknowns)
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("market state assessment content_sha256 does not match immutable content")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "spec": self.spec.to_dict(),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
            "market_snapshot": {"content_sha256": self.market_snapshot.content_sha256},
            "feature_observation_refs": tuple(item.to_content_dict() for item in self.feature_observation_refs),
            "feature_lineage": tuple(
                {"content_sha256": item.content_sha256, "schema_version": str(item.schema_version)}
                for item in self.feature_lineage
            ),
            "regime_assessment_content_sha256": self.regime_assessment_content_sha256,
            "regime_assessment_schema_version": str(self.regime_assessment_schema_version),
            "primary_state": self.primary_state.value if self.primary_state else None,
            "candidates": tuple(item.to_dict() for item in self.candidates),
            "conflicts": tuple((left.value, right.value) for left, right in self.conflicts),
            "alternative_explanations": self.alternative_explanations,
            "transition_risk": self.transition_risk.value,
            "unknowns": self.unknowns,
            "authority": self.authority.value,
        }

    def trading_authorization(self) -> Failure:
        return Failure(ReasonCode.MODEL_OUTPUT_NOT_AUTHORIZATION, "market state is never trading permission")


class MarketStateAssessmentComposer:
    """Pure MI composition over already-versioned deterministic inputs."""

    def compose(
        self, spec: MarketStateAssessmentSpec, inputs: MarketStateAssessmentInput, valid_until: RecordedAt
    ) -> MarketStateAssessment:
        if not isinstance(spec, MarketStateAssessmentSpec) or not isinstance(inputs, MarketStateAssessmentInput):
            raise TypeError("market state composer requires typed spec and immutable inputs")
        if not isinstance(valid_until, RecordedAt) or valid_until.value <= inputs.market_snapshot.as_of.value:
            raise ValueError("market state valid_until must follow source as_of")
        regime_source = (inputs.deterministic_regime.assessment_id, inputs.deterministic_regime.content_sha256)
        source_by_hash = {
            feature.content_sha256: (feature.observation_id, feature.content_sha256) for feature in inputs.features
        }
        candidates = tuple(
            _candidate(candidate, inputs.deterministic_regime, source_by_hash, regime_source)
            for candidate in inputs.deterministic_regime.candidates
        )
        eligible = tuple(item for item in candidates if item.support)
        highest = max((item.confidence for item in eligible), default=None)
        leaders = tuple(item for item in eligible if item.confidence == highest)
        primary = leaders[0].state if len(leaders) == 1 else None
        primary_explanation = (
            {"no support-backed primary state"}
            if not eligible
            else {"primary state is tied"}
            if len(leaders) > 1
            else set()
        )
        unknowns = tuple(sorted(inputs.deterministic_regime.unknowns))
        alternatives = tuple(
            sorted(
                (
                    {*(f"candidate:{item.state.value}" for item in candidates if item.state is not primary), *unknowns}
                    | {f"conflict:{left.value}/{right.value}" for left, right in inputs.deterministic_regime.conflicts}
                    | primary_explanation
                )
            )
        )
        payload: dict[str, JsonValue] = {
            "spec": spec.to_dict(),
            "as_of": inputs.market_snapshot.as_of.to_dict()["recorded_at"],
            "valid_until": valid_until.to_dict()["recorded_at"],
            "market_snapshot": {"content_sha256": inputs.market_snapshot.content_sha256},
            "feature_observation_refs": tuple(
                item.to_content_dict()
                for item in sorted(
                    (FeatureArtifactRef.from_observation(feature) for feature in inputs.features),
                    key=lambda item: (item.content_sha256, str(item.observation_id)),
                )
            ),
            "feature_lineage": tuple(
                {"content_sha256": feature.content_sha256, "schema_version": str(feature.schema_version)}
                for feature in sorted(inputs.features, key=lambda item: item.content_sha256)
            ),
            "regime_assessment_content_sha256": inputs.deterministic_regime.content_sha256,
            "regime_assessment_schema_version": str(inputs.deterministic_regime.model_spec.schema_version),
            "primary_state": primary.value if primary else None,
            "candidates": tuple(item.to_dict() for item in sorted(candidates, key=lambda item: item.state.value)),
            "conflicts": tuple((left.value, right.value) for left, right in inputs.deterministic_regime.conflicts),
            "alternative_explanations": alternatives,
            "transition_risk": _transition_risk(inputs.deterministic_regime, primary, unknowns).value,
            "unknowns": unknowns,
            "authority": ModelOutputAuthority.NON_TRADING.value,
        }
        return MarketStateAssessment(
            EntityId.new("market_state_assessment"),
            spec,
            inputs.market_snapshot.as_of,
            valid_until,
            inputs.market_snapshot,
            tuple(FeatureArtifactRef.from_observation(feature) for feature in inputs.features),
            tuple(FeatureObservationLineage.from_observation(feature) for feature in inputs.features),
            inputs.deterministic_regime.assessment_id,
            inputs.deterministic_regime.content_sha256,
            inputs.deterministic_regime.model_spec.schema_version,
            primary,
            candidates,
            inputs.deterministic_regime.conflicts,
            alternatives,
            _transition_risk(inputs.deterministic_regime, primary, unknowns),
            unknowns,
            ModelOutputAuthority.NON_TRADING,
            canonical_sha256(payload),
        )


def _candidate(
    candidate: RegimeCandidate,
    regime: RegimeAssessment,
    source_by_hash: dict[str, tuple[EntityId, str]],
    regime_source: tuple[EntityId, str],
) -> MarketStateCandidate:
    def evidence(values: tuple[str, ...], relation: str) -> tuple[MarketStateEvidence, ...]:
        return tuple(
            MarketStateEvidence(*(source_by_hash.get(value, regime_source)), f"{relation}: {value}") for value in values
        )

    support = evidence(candidate.support, "supports")
    counter = evidence(candidate.counter_evidence, "counters")
    for left, right in regime.conflicts:
        if candidate.kind in (left, right):
            other = right if candidate.kind is left else left
            counter += (MarketStateEvidence(*regime_source, f"deterministic conflict with {other.value}"),)
    return MarketStateCandidate(candidate.kind, candidate.score, support, counter, candidate.unknowns)


def _dedupe_evidence(values: tuple[MarketStateEvidence, ...]) -> tuple[MarketStateEvidence, ...]:
    return tuple(sorted(set(values), key=lambda item: (item.source_content_sha256, item.statement)))


def _transition_risk(regime: RegimeAssessment, primary: RegimeKind | None, unknowns: tuple[str, ...]) -> TransitionRisk:
    if primary is None:
        return TransitionRisk.UNKNOWN
    if any(primary in pair for pair in regime.conflicts):
        return TransitionRisk.HIGH
    if any(
        candidate.kind in {RegimeKind.HIGH_VOLATILITY, RegimeKind.LIQUIDITY_STRESS, RegimeKind.LIMIT_RISK}
        and candidate.score >= Decimal("0.5")
        for candidate in regime.candidates
    ):
        return TransitionRisk.HIGH
    return TransitionRisk.MODERATE if unknowns else TransitionRisk.LOW
