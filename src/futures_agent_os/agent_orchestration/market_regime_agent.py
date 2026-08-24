"""Task/artifact adapter for the Market Regime role.

This supporting context deliberately consumes only task and artifact ports. It
does not import, construct, or interpret Market Intelligence domain objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from futures_agent_os.shared_kernel import EntityId, ModelOutputAuthority, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .catalog import AgentRoleId, CATALOG_VERSION, validate_task_envelope
from .contracts import (
    AgentTaskEnvelope,
    ArtifactClaim,
    ArtifactKind,
    ArtifactRef,
    ResultStatus,
    SpecialistResult,
    StructuredArtifact,
)


class AssessmentEvidencePort(Protocol):
    source_id: EntityId
    source_content_sha256: str
    statement: str


class AssessmentCandidatePort(Protocol):
    state: object
    support: tuple[AssessmentEvidencePort, ...]
    counter_evidence: tuple[AssessmentEvidencePort, ...]
    unknowns: tuple[str, ...]


class MarketStateAssessmentPort(Protocol):
    assessment_id: EntityId
    schema_version: SchemaVersion
    as_of: RecordedAt
    valid_until: RecordedAt
    market_snapshot: MarketSnapshotLineagePort
    feature_lineage: tuple[FeatureLineagePort, ...]
    regime_assessment_id: EntityId
    regime_assessment_content_sha256: str
    regime_assessment_schema_version: SchemaVersion
    authority: ModelOutputAuthority
    content_sha256: str
    candidates: tuple[AssessmentCandidatePort, ...]
    unknowns: tuple[str, ...]
    alternative_explanations: tuple[str, ...]

    def payload(self) -> Mapping[str, JsonValue]: ...


class MarketSnapshotLineagePort(Protocol):
    snapshot_id: EntityId
    content_sha256: str
    schema_version: SchemaVersion
    as_of: RecordedAt


class FeatureLineagePort(Protocol):
    observation_id: EntityId
    content_sha256: str
    schema_version: SchemaVersion
    as_of: RecordedAt


@dataclass(frozen=True, slots=True)
class _EvidenceSnapshot:
    source_id: EntityId
    source_content_sha256: str
    statement: str


@dataclass(frozen=True, slots=True)
class _CandidateSnapshot:
    state: str
    support: tuple[_EvidenceSnapshot, ...]
    counter_evidence: tuple[_EvidenceSnapshot, ...]
    unknowns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _AssessmentSnapshot:
    assessment_id: EntityId
    schema_version: SchemaVersion
    as_of: RecordedAt
    valid_until: RecordedAt
    market_snapshot: ArtifactRef
    features: tuple[ArtifactRef, ...]
    regime: ArtifactRef
    content_sha256: str
    candidates: tuple[_CandidateSnapshot, ...]
    unknowns: tuple[str, ...]
    alternatives: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketRegimeTaskSources:
    """The public artifact-only boundary presented to orchestration."""

    artifacts: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        artifacts = tuple(sorted(tuple(self.artifacts), key=_artifact_key))
        if not artifacts or any(not isinstance(item, ArtifactRef) for item in artifacts):
            raise ValueError("market regime task sources require immutable artifacts")
        if len({(item.artifact_id, item.content_hash) for item in artifacts}) != len(artifacts):
            raise ValueError("market regime task sources must be unique")
        kinds = {item.artifact_kind for item in artifacts}
        required = {
            ArtifactKind.MARKET_SNAPSHOT,
            ArtifactKind.FEATURE_OBSERVATION,
            ArtifactKind.REGIME_ASSESSMENT,
        }
        if kinds != required or sum(item.artifact_kind is ArtifactKind.MARKET_SNAPSHOT for item in artifacts) != 1:
            raise ValueError("market regime task sources require snapshot, feature, and deterministic regime artifacts")
        if sum(item.artifact_kind is ArtifactKind.REGIME_ASSESSMENT for item in artifacts) != 1:
            raise ValueError("market regime task sources require exactly one deterministic regime artifact")
        if any(item.as_of != artifacts[0].as_of for item in artifacts):
            raise ValueError("market regime task source artifacts must share one as_of")
        object.__setattr__(self, "artifacts", artifacts)


class MarketRegimeAgent:
    """Validate and package an already-composed Market Intelligence assessment."""

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: MarketRegimeTaskSources,
        assessment: MarketStateAssessmentPort,
        producer_run_id: EntityId,
    ) -> StructuredArtifact:
        if not isinstance(task, AgentTaskEnvelope) or not isinstance(sources, MarketRegimeTaskSources):
            raise TypeError("market regime packaging requires a task and immutable task sources")
        if task.assigned_role_id != AgentRoleId.MARKET_REGIME.value:
            raise ValueError("market regime agent task must be assigned to market_regime")
        if task.catalog_version != CATALOG_VERSION:
            raise ValueError("market regime agent task catalog version mismatch")
        if task.required_outputs != (ArtifactKind.MARKET_STATE_ASSESSMENT,):
            raise ValueError("market regime agent requires exactly one market_state_assessment required output")
        if task.may_delegate_research or task.policy_refs:
            raise ValueError("market regime agent accepts no delegated research or policy artifacts")
        validate_task_envelope(task)
        if tuple(sorted(task.input_artifacts, key=_artifact_key)) != sources.artifacts:
            raise ValueError("market regime agent task must name exact immutable source artifacts")
        if any(source.as_of != task.as_of for source in sources.artifacts):
            raise ValueError("market regime task sources must share task as_of")
        frozen = _freeze_assessment(assessment)
        if frozen.as_of != task.as_of or frozen.valid_until.value > task.expires_at.value:
            raise ValueError("market regime assessment port is invalid, stale, or authoritative")
        expected_sources = tuple(sorted((frozen.market_snapshot, *frozen.features, frozen.regime), key=_artifact_key))
        if sources.artifacts != expected_sources:
            raise ValueError("market regime task sources must exactly match assessment immutable lineage")
        source_by_identity = {(item.artifact_id, item.content_hash): item for item in sources.artifacts}
        claims = self._claims(frozen, source_by_identity)
        output_ref = ArtifactRef(
            frozen.assessment_id,
            ArtifactKind.MARKET_STATE_ASSESSMENT,
            frozen.schema_version,
            "sha256:" + frozen.content_sha256,
            frozen.as_of,
            frozen.as_of,
        )
        return StructuredArtifact(
            output_ref,
            AgentRoleId.MARKET_REGIME.value,
            producer_run_id,
            sources.artifacts,
            claims,
            tuple(sorted(set((*frozen.unknowns, *frozen.alternatives)))),
            frozen.valid_until,
        )

    @staticmethod
    def _claims(
        assessment: _AssessmentSnapshot,
        source_by_identity: dict[tuple[EntityId, str], ArtifactRef],
    ) -> tuple[ArtifactClaim, ...]:
        claims: list[ArtifactClaim] = []
        for candidate in assessment.candidates:
            evidence = tuple((*candidate.support, *candidate.counter_evidence))
            refs: list[ArtifactRef] = []
            for item in evidence:
                identity = (item.source_id, "sha256:" + item.source_content_sha256)
                try:
                    refs.append(source_by_identity[identity])
                except KeyError as error:
                    raise ValueError(
                        "market regime assessment claim evidence is outside task source lineage"
                    ) from error
            state = candidate.state
            if not evidence:
                if not candidate.unknowns:
                    raise ValueError("market regime assessment candidate has no evidence or explicit unknown")
                regime_refs = tuple(
                    item for item in source_by_identity.values() if item.artifact_kind is ArtifactKind.REGIME_ASSESSMENT
                )
                if len(regime_refs) != 1:
                    raise ValueError("unknown market regime candidate requires one deterministic regime provenance ref")
                refs = [regime_refs[0]]
                statement = f"candidate {state}: unknown: " + "; ".join(sorted(candidate.unknowns))
            else:
                statement = f"candidate {state}: " + "; ".join(item.statement for item in evidence)
            claims.append(
                ArtifactClaim(
                    "market_state_candidate",
                    statement,
                    tuple(sorted(set(refs), key=_artifact_key)),
                    is_inference=True,
                )
            )
        return tuple(sorted(claims, key=lambda item: item.statement))

    def deferred_result(self, task: AgentTaskEnvelope, warning: str) -> SpecialistResult:
        if not isinstance(task, AgentTaskEnvelope) or task.assigned_role_id != AgentRoleId.MARKET_REGIME.value:
            raise ValueError("market regime defer requires a market_regime task")
        if not isinstance(warning, str) or not warning.strip():
            raise ValueError("market regime defer requires a non-empty warning")
        return SpecialistResult(
            task.task_id,
            AgentRoleId.MARKET_REGIME.value,
            ResultStatus.DEFERRED,
            (),
            (),
            (),
            (warning,),
            task.expires_at,
        )


def _artifact_key(value: ArtifactRef) -> tuple[str, str, str]:
    return (value.artifact_kind.value, value.content_hash, str(value.artifact_id))


def _freeze_assessment(assessment: MarketStateAssessmentPort) -> _AssessmentSnapshot:
    if not callable(getattr(assessment, "payload", None)):
        raise TypeError("market regime assessment port requires payload integrity contract")
    if assessment.authority is not ModelOutputAuthority.NON_TRADING:
        raise ValueError("market regime assessment port must be NON_TRADING")
    payload_before = _freeze_json(assessment.payload())
    content_hash_before = assessment.content_sha256
    if canonical_sha256(payload_before) != content_hash_before:
        raise ValueError("market regime assessment payload hash is stale or forged")
    snapshot = assessment.market_snapshot
    if (
        not isinstance(snapshot.snapshot_id, EntityId)
        or snapshot.snapshot_id.namespace != "market_snapshot"
        or snapshot.as_of != assessment.as_of
    ):
        raise ValueError("market regime assessment snapshot lineage is invalid")
    features = tuple(assessment.feature_lineage)
    if not features or any(feature.as_of != assessment.as_of for feature in features):
        raise ValueError("market regime assessment feature lineage is invalid")
    candidates = tuple(_freeze_candidate(candidate) for candidate in assessment.candidates)
    if not candidates or not all(
        isinstance(item, str) and item for item in (*assessment.unknowns, *assessment.alternative_explanations)
    ):
        raise ValueError("market regime assessment candidate or warning fields are invalid")
    frozen = _AssessmentSnapshot(
        assessment.assessment_id,
        assessment.schema_version,
        assessment.as_of,
        assessment.valid_until,
        ArtifactRef(
            snapshot.snapshot_id,
            ArtifactKind.MARKET_SNAPSHOT,
            snapshot.schema_version,
            "sha256:" + snapshot.content_sha256,
            snapshot.as_of,
            snapshot.as_of,
        ),
        tuple(
            ArtifactRef(
                feature.observation_id,
                ArtifactKind.FEATURE_OBSERVATION,
                feature.schema_version,
                "sha256:" + feature.content_sha256,
                feature.as_of,
                feature.as_of,
            )
            for feature in features
        ),
        ArtifactRef(
            assessment.regime_assessment_id,
            ArtifactKind.REGIME_ASSESSMENT,
            assessment.regime_assessment_schema_version,
            "sha256:" + assessment.regime_assessment_content_sha256,
            assessment.as_of,
            assessment.as_of,
        ),
        content_hash_before,
        candidates,
        tuple(assessment.unknowns),
        tuple(assessment.alternative_explanations),
    )
    _verify_payload_matches_snapshot(payload_before, frozen)
    payload_after = _freeze_json(assessment.payload())
    if payload_after != payload_before or assessment.content_sha256 != content_hash_before:
        raise ValueError("market regime assessment port mutated during extraction")
    return frozen


def _freeze_candidate(value: AssessmentCandidatePort) -> _CandidateSnapshot:
    state = getattr(value.state, "value", None)
    if not isinstance(state, str) or not state:
        raise ValueError("market regime assessment candidate state must be a typed enum")

    def evidence(items: tuple[AssessmentEvidencePort, ...]) -> tuple[_EvidenceSnapshot, ...]:
        result = tuple(
            _EvidenceSnapshot(item.source_id, item.source_content_sha256, item.statement) for item in tuple(items)
        )
        if any(
            not isinstance(item.source_id, EntityId) or len(item.source_content_sha256) != 64 or not item.statement
            for item in result
        ):
            raise ValueError("market regime assessment evidence is invalid")
        return result

    unknowns = tuple(value.unknowns)
    if any(not isinstance(item, str) or not item for item in unknowns):
        raise ValueError("market regime assessment candidate unknowns are invalid")
    return _CandidateSnapshot(state, evidence(value.support), evidence(value.counter_evidence), unknowns)


def _verify_payload_matches_snapshot(payload: JsonValue, frozen: _AssessmentSnapshot) -> None:
    if not isinstance(payload, Mapping):
        raise TypeError("market regime assessment payload must be a mapping")
    if (
        payload.get("as_of") != frozen.as_of.to_dict()["recorded_at"]
        or payload.get("valid_until") != frozen.valid_until.to_dict()["recorded_at"]
    ):
        raise ValueError("market regime assessment payload time fields do not match port")
    snapshot = payload.get("market_snapshot")
    if not isinstance(snapshot, Mapping) or snapshot.get(
        "content_sha256"
    ) != frozen.market_snapshot.content_hash.removeprefix("sha256:"):
        raise ValueError("market regime assessment payload snapshot does not match port")
    if payload.get("regime_assessment_content_sha256") != frozen.regime.content_hash.removeprefix("sha256:"):
        raise ValueError("market regime assessment payload regime does not match port")
    spec = payload.get("spec")
    if (
        not isinstance(spec, Mapping)
        or spec.get("schema_version") != str(frozen.schema_version)
        or payload.get("regime_assessment_schema_version") != str(frozen.regime.schema_version)
        or payload.get("authority") != ModelOutputAuthority.NON_TRADING.value
    ):
        raise ValueError("market regime assessment payload authority or schema does not match port")
    expected_features = tuple(
        {"content_sha256": item.content_hash.removeprefix("sha256:"), "schema_version": str(item.schema_version)}
        for item in sorted(frozen.features, key=_artifact_key)
    )
    payload_features = payload.get("feature_lineage")
    if not isinstance(payload_features, tuple) or payload_features != expected_features:
        raise ValueError("market regime assessment payload feature lineage does not match port")
    expected_candidates = tuple(
        {
            "state": item.state,
            "support": tuple(
                {"source_content_sha256": evidence.source_content_sha256, "statement": evidence.statement}
                for evidence in item.support
            ),
            "counter_evidence": tuple(
                {"source_content_sha256": evidence.source_content_sha256, "statement": evidence.statement}
                for evidence in item.counter_evidence
            ),
            "unknowns": item.unknowns,
        }
        for item in sorted(frozen.candidates, key=lambda item: item.state)
    )
    payload_candidates = payload.get("candidates")
    if not isinstance(payload_candidates, tuple) or len(payload_candidates) != len(expected_candidates):
        raise ValueError("market regime assessment payload candidates do not match port")
    for actual, expected in zip(payload_candidates, expected_candidates, strict=True):
        if not isinstance(actual, Mapping) or any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("market regime assessment payload candidates do not match port")
    payload_unknowns = payload.get("unknowns")
    payload_alternatives = payload.get("alternative_explanations")
    if (
        not isinstance(payload_unknowns, tuple)
        or not isinstance(payload_alternatives, tuple)
        or payload_unknowns != frozen.unknowns
        or payload_alternatives != frozen.alternatives
    ):
        raise ValueError("market regime assessment payload warnings do not match port")


def _freeze_json(value: JsonValue) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("market regime assessment payload keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    raise TypeError("market regime assessment payload must be canonical JSON")
