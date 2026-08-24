"""Artifact-only adapter for the read-only Research role.

This module validates and packages already-composed research artifacts.  It
does not run an experiment, persist a result, or interpret any trading domain
state.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .catalog import AgentRoleId, CATALOG_VERSION, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactClaim, ArtifactKind, ArtifactRef, StructuredArtifact


class _MarketStateRefPort(Protocol):
    assessment_id: EntityId
    schema_version: SchemaVersion
    as_of: RecordedAt
    valid_until: RecordedAt
    content_sha256: str


class _SpecPort(Protocol):
    spec_id: EntityId
    version: int
    schema_version: SchemaVersion


class _HypothesisPort(Protocol):
    hypothesis_id: EntityId
    spec: _SpecPort
    schema_version: SchemaVersion
    market_state_assessment: _MarketStateRefPort
    as_of: RecordedAt
    valid_until: RecordedAt
    lifecycle: object
    statement: str
    applicable_markets: tuple[str, ...]
    observable_outcome: str
    falsification_criterion: str
    required_data: tuple[str, ...]
    proposal_source: object
    content_sha256: str

    def payload(self) -> Mapping[str, JsonValue]: ...


class _EvidenceGapPort(Protocol):
    code: str
    description: str


class _EvidenceSynthesisPort(Protocol):
    synthesis_id: EntityId
    hypothesis: _HypothesisPort
    schema_version: SchemaVersion
    as_of: RecordedAt
    valid_until: RecordedAt
    knowns: tuple[str, ...]
    unknowns: tuple[str, ...]
    conflicts: tuple[str, ...]
    next_steps: tuple[str, ...]
    evidence_gaps: tuple[_EvidenceGapPort, ...]
    content_sha256: str

    def payload(self) -> Mapping[str, JsonValue]: ...


class _ExperimentRequestPort(Protocol):
    request_id: EntityId
    spec: _SpecPort
    hypothesis: _HypothesisPort
    schema_version: SchemaVersion
    as_of: RecordedAt
    valid_until: RecordedAt
    data_requirements: tuple[str, ...]
    control: str
    evaluation_window: str
    method: str
    metrics: tuple[str, ...]
    expected_diagnostics: tuple[str, ...]
    stop_condition: str
    potential_biases: tuple[str, ...]
    content_sha256: str

    def payload(self) -> Mapping[str, JsonValue]: ...


class ResearchSynthesisPort(Protocol):
    hypothesis: _HypothesisPort
    evidence_synthesis: _EvidenceSynthesisPort
    experiment_request: _ExperimentRequestPort
    content_sha256: str

    def payload(self) -> Mapping[str, JsonValue]: ...


@dataclass(frozen=True, slots=True)
class _EvidenceGapSnapshot:
    code: str
    description: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or not self.code
            or not isinstance(self.description, str)
            or not self.description
        ):
            raise ValueError("research evidence gap is invalid")


@dataclass(frozen=True, slots=True)
class _HypothesisSnapshot:
    hypothesis_id: EntityId
    spec_id: EntityId
    spec_version: int
    schema_version: SchemaVersion
    market_state: ArtifactRef
    market_state_valid_until: RecordedAt
    as_of: RecordedAt
    valid_until: RecordedAt
    lifecycle: str
    statement: str
    applicable_markets: tuple[str, ...]
    observable_outcome: str
    falsification_criterion: str
    required_data: tuple[str, ...]
    proposal_source: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _SynthesisSnapshot:
    hypothesis: _HypothesisSnapshot
    evidence_synthesis_id: EntityId
    evidence_synthesis_hash: str
    experiment_request_id: EntityId
    experiment_request_spec_id: EntityId
    experiment_request_spec_version: int
    experiment_request_hash: str
    data_requirements: tuple[str, ...]
    control: str
    evaluation_window: str
    method: str
    metrics: tuple[str, ...]
    expected_diagnostics: tuple[str, ...]
    stop_condition: str
    potential_biases: tuple[str, ...]
    knowns: tuple[str, ...]
    unknowns: tuple[str, ...]
    conflicts: tuple[str, ...]
    next_steps: tuple[str, ...]
    evidence_gaps: tuple[_EvidenceGapSnapshot, ...]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ResearchTaskSources:
    """One immutable market-state artifact, without mutable domain entities."""

    artifacts: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        artifacts = tuple(sorted(tuple(self.artifacts), key=_artifact_key))
        if len(artifacts) != 1 or not isinstance(artifacts[0], ArtifactRef):
            raise ValueError("research task sources require exactly one immutable market-state artifact")
        if artifacts[0].artifact_kind is not ArtifactKind.MARKET_STATE_ASSESSMENT:
            raise ValueError("research task sources require a market_state_assessment artifact")
        object.__setattr__(self, "artifacts", artifacts)


@dataclass(frozen=True, slots=True)
class ResearchAgentResult:
    """Bounded Research output with uncertainty preserved for deterministic fan-in."""

    artifacts: tuple[StructuredArtifact, ...]
    unknowns: tuple[str, ...]
    evidence_gaps: tuple[_EvidenceGapSnapshot, ...]
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        artifacts = tuple(self.artifacts)
        unknowns = tuple(self.unknowns)
        evidence_gaps = tuple(self.evidence_gaps)
        if tuple(item.ref.artifact_kind for item in artifacts) != (
            ArtifactKind.HYPOTHESIS,
            ArtifactKind.EVIDENCE_SYNTHESIS,
            ArtifactKind.EXPERIMENT_REQUEST,
        ):
            raise ValueError("research result requires one hypothesis, evidence synthesis, and experiment request")
        if not isinstance(self.expires_at, RecordedAt):
            raise TypeError("research result requires a typed expiry")
        if any(not isinstance(value, str) or not value.strip() for value in unknowns):
            raise ValueError("research result unknowns are invalid")
        if any(not isinstance(value, _EvidenceGapSnapshot) for value in evidence_gaps):
            raise TypeError("research result evidence gaps are invalid")
        if any(
            not isinstance(item, StructuredArtifact)
            or item.producer_role_id != AgentRoleId.RESEARCH.value
            or item.expires_at != self.expires_at
            or item.ref.as_of != item.ref.created_at
            for item in artifacts
        ):
            raise ValueError("research result artifacts must share immutable Research provenance and expiry")
        source_refs = artifacts[0].source_refs
        if not source_refs or any(item.source_refs != source_refs for item in artifacts):
            raise ValueError("research result artifacts must share exact immutable source references")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "unknowns", unknowns)
        object.__setattr__(self, "evidence_gaps", evidence_gaps)


class ResearchAgent:
    """Validate research artifacts against the exact PIT market-state input."""

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: ResearchTaskSources,
        synthesis: ResearchSynthesisPort,
        producer_run_id: EntityId,
    ) -> ResearchAgentResult:
        if not isinstance(task, AgentTaskEnvelope) or not isinstance(sources, ResearchTaskSources):
            raise TypeError("research packaging requires a task and immutable task sources")
        if task.assigned_role_id != AgentRoleId.RESEARCH.value or task.catalog_version != CATALOG_VERSION:
            raise ValueError("research task role or catalog version is invalid")
        expected_outputs = (ArtifactKind.HYPOTHESIS, ArtifactKind.EVIDENCE_SYNTHESIS, ArtifactKind.EXPERIMENT_REQUEST)
        if task.required_outputs != expected_outputs:
            raise ValueError(
                "research task required outputs must be hypothesis, evidence synthesis, and experiment request"
            )
        if task.policy_refs or task.may_delegate_research:
            raise ValueError("research task accepts no policy artifacts or delegated research")
        validate_task_envelope(task)
        if task.input_artifacts != sources.artifacts:
            raise ValueError("research task must name exact immutable source artifacts")
        source = sources.artifacts[0]
        if source.as_of != task.as_of:
            raise ValueError("research task source must share task as_of")
        frozen = _freeze_synthesis(synthesis)
        if (
            frozen.hypothesis.as_of != task.as_of
            or frozen.hypothesis.valid_until.value > task.expires_at.value
            or frozen.hypothesis.market_state != source
        ):
            raise ValueError("research artifacts must bind the exact immutable source lineage and task lifetime")
        source_refs = (source,)
        hypothesis_ref = ArtifactRef(
            frozen.hypothesis.hypothesis_id,
            ArtifactKind.HYPOTHESIS,
            frozen.hypothesis.schema_version,
            "sha256:" + frozen.hypothesis.content_sha256,
            frozen.hypothesis.as_of,
            frozen.hypothesis.as_of,
        )
        evidence_ref = ArtifactRef(
            frozen.evidence_synthesis_id,
            ArtifactKind.EVIDENCE_SYNTHESIS,
            frozen.hypothesis.schema_version,
            "sha256:" + frozen.evidence_synthesis_hash,
            frozen.hypothesis.as_of,
            frozen.hypothesis.as_of,
        )
        request_ref = ArtifactRef(
            frozen.experiment_request_id,
            ArtifactKind.EXPERIMENT_REQUEST,
            frozen.hypothesis.schema_version,
            "sha256:" + frozen.experiment_request_hash,
            frozen.hypothesis.as_of,
            frozen.hypothesis.as_of,
        )
        evidence_claim = ArtifactClaim(
            "research_evidence_gap",
            "unknowns: "
            + "; ".join(frozen.unknowns)
            + "; gaps: "
            + "; ".join(f"{item.code}: {item.description}" for item in frozen.evidence_gaps),
            source_refs,
            True,
        )
        artifacts = (
            StructuredArtifact(
                hypothesis_ref,
                AgentRoleId.RESEARCH.value,
                producer_run_id,
                source_refs,
                (
                    ArtifactClaim(
                        "falsifiable_hypothesis",
                        f"{frozen.hypothesis.statement} Falsifier: {frozen.hypothesis.falsification_criterion}",
                        source_refs,
                        True,
                    ),
                ),
                frozen.unknowns,
                frozen.hypothesis.valid_until,
            ),
            StructuredArtifact(
                evidence_ref,
                AgentRoleId.RESEARCH.value,
                producer_run_id,
                source_refs,
                (evidence_claim,),
                tuple((*frozen.unknowns, *(item.code for item in frozen.evidence_gaps))),
                frozen.hypothesis.valid_until,
            ),
            StructuredArtifact(
                request_ref,
                AgentRoleId.RESEARCH.value,
                producer_run_id,
                source_refs,
                (
                    ArtifactClaim(
                        "experiment_request",
                        "control: "
                        + frozen.control
                        + "; window: "
                        + frozen.evaluation_window
                        + "; method: "
                        + frozen.method
                        + "; metrics: "
                        + "; ".join(frozen.metrics)
                        + "; stop: "
                        + frozen.stop_condition,
                        source_refs,
                        True,
                    ),
                ),
                tuple(item.code for item in frozen.evidence_gaps),
                frozen.hypothesis.valid_until,
            ),
        )
        return ResearchAgentResult(artifacts, frozen.unknowns, frozen.evidence_gaps, frozen.hypothesis.valid_until)


def _artifact_key(value: ArtifactRef) -> tuple[str, str, str]:
    return (value.artifact_kind.value, value.content_hash, str(value.artifact_id))


def _freeze_synthesis(value: ResearchSynthesisPort) -> _SynthesisSnapshot:
    if not callable(getattr(value, "payload", None)):
        raise TypeError("research synthesis port requires payload integrity")
    payload_before = _freeze_json(value.payload())
    if canonical_sha256(payload_before) != value.content_sha256:
        raise ValueError("research synthesis payload hash is stale or forged")
    hypothesis = value.hypothesis
    evidence = value.evidence_synthesis
    request = value.experiment_request
    if any(not callable(getattr(item, "payload", None)) for item in (hypothesis, evidence, request)):
        raise TypeError("research artifacts require individual payload integrity")
    hypothesis_payload = _freeze_json(hypothesis.payload())
    evidence_payload = _freeze_json(evidence.payload())
    request_payload = _freeze_json(request.payload())
    if (
        canonical_sha256(hypothesis_payload) != hypothesis.content_sha256
        or canonical_sha256(evidence_payload) != evidence.content_sha256
        or canonical_sha256(request_payload) != request.content_sha256
    ):
        raise ValueError("research artifact payload hash is stale or forged")
    market_state = hypothesis.market_state_assessment
    hypothesis_spec = hypothesis.spec
    request_spec = request.spec
    if (
        not isinstance(hypothesis.hypothesis_id, EntityId)
        or hypothesis.hypothesis_id.namespace != "hypothesis"
        or not isinstance(hypothesis_spec.spec_id, EntityId)
        or hypothesis_spec.spec_id.namespace != "hypothesis_spec"
        or isinstance(hypothesis_spec.version, bool)
        or not isinstance(hypothesis_spec.version, int)
        or hypothesis_spec.version < 1
        or not isinstance(hypothesis.schema_version, SchemaVersion)
        or hypothesis_spec.schema_version != hypothesis.schema_version
        or not isinstance(hypothesis.as_of, RecordedAt)
        or not isinstance(hypothesis.valid_until, RecordedAt)
        or hypothesis.valid_until.value <= hypothesis.as_of.value
        or not isinstance(market_state.assessment_id, EntityId)
        or market_state.assessment_id.namespace != "market_state_assessment"
        or not isinstance(market_state.schema_version, SchemaVersion)
        or not isinstance(market_state.as_of, RecordedAt)
        or not isinstance(market_state.valid_until, RecordedAt)
        or not isinstance(market_state.content_sha256, str)
        or market_state.as_of != hypothesis.as_of
        or market_state.valid_until.value < hypothesis.valid_until.value
        or not isinstance(request_spec.spec_id, EntityId)
        or request_spec.spec_id.namespace != "experiment_request_spec"
        or isinstance(request_spec.version, bool)
        or not isinstance(request_spec.version, int)
        or request_spec.version < 1
        or request_spec.schema_version != hypothesis.schema_version
        or not isinstance(evidence.schema_version, SchemaVersion)
        or not isinstance(request.schema_version, SchemaVersion)
        or not isinstance(evidence.as_of, RecordedAt)
        or not isinstance(request.as_of, RecordedAt)
        or not isinstance(evidence.valid_until, RecordedAt)
        or not isinstance(request.valid_until, RecordedAt)
    ):
        raise ValueError("research hypothesis lineage or lifetime is invalid")
    market_ref = ArtifactRef(
        market_state.assessment_id,
        ArtifactKind.MARKET_STATE_ASSESSMENT,
        market_state.schema_version,
        "sha256:" + market_state.content_sha256,
        market_state.as_of,
        market_state.as_of,
    )
    collections = (
        hypothesis.applicable_markets,
        hypothesis.required_data,
        evidence.knowns,
        evidence.unknowns,
        evidence.conflicts,
        evidence.next_steps,
        evidence.evidence_gaps,
        request.data_requirements,
        request.metrics,
        request.expected_diagnostics,
        request.potential_biases,
    )
    if any(not isinstance(items, tuple) for items in collections):
        raise TypeError("research synthesis collections must be immutable tuples")
    gaps = tuple(
        _EvidenceGapSnapshot(getattr(item, "code", ""), getattr(item, "description", ""))
        for item in evidence.evidence_gaps
    )
    unknowns = evidence.unknowns
    lifecycle = getattr(hypothesis.lifecycle, "value", None)
    proposal_source = getattr(hypothesis.proposal_source, "value", None)
    if (
        lifecycle != "DRAFT"
        or proposal_source != "MARKET_STATE_ASSESSMENT"
        or any(
            not isinstance(item, str) or not item.strip()
            for item in (
                hypothesis.statement,
                hypothesis.observable_outcome,
                hypothesis.falsification_criterion,
            )
        )
        or any(
            not values or any(not isinstance(item, str) or not item.strip() for item in values)
            for values in (
                hypothesis.applicable_markets,
                hypothesis.required_data,
                evidence.next_steps,
                request.data_requirements,
                request.metrics,
                request.expected_diagnostics,
            )
        )
        or any(
            any(not isinstance(item, str) or not item.strip() for item in values)
            for values in (evidence.knowns, unknowns, evidence.conflicts, request.potential_biases)
        )
        or request.data_requirements != hypothesis.required_data
        or evidence.hypothesis is not hypothesis
        or request.hypothesis is not hypothesis
        or evidence.schema_version != hypothesis.schema_version
        or request.schema_version != hypothesis.schema_version
        or evidence.as_of != hypothesis.as_of
        or request.as_of != hypothesis.as_of
        or evidence.valid_until != hypothesis.valid_until
        or request.valid_until != hypothesis.valid_until
        or any(
            not isinstance(item, str) or not item.strip()
            for item in (request.control, request.evaluation_window, request.method, request.stop_condition)
        )
    ):
        raise ValueError("research synthesis fields are invalid or inconsistent")
    frozen = _SynthesisSnapshot(
        _HypothesisSnapshot(
            hypothesis.hypothesis_id,
            hypothesis_spec.spec_id,
            hypothesis_spec.version,
            hypothesis.schema_version,
            market_ref,
            market_state.valid_until,
            hypothesis.as_of,
            hypothesis.valid_until,
            lifecycle,
            hypothesis.statement,
            tuple(hypothesis.applicable_markets),
            hypothesis.observable_outcome,
            hypothesis.falsification_criterion,
            tuple(hypothesis.required_data),
            proposal_source,
            hypothesis.content_sha256,
        ),
        evidence.synthesis_id,
        evidence.content_sha256,
        request.request_id,
        request_spec.spec_id,
        request_spec.version,
        request.content_sha256,
        tuple(request.data_requirements),
        request.control,
        request.evaluation_window,
        request.method,
        tuple(request.metrics),
        tuple(request.expected_diagnostics),
        request.stop_condition,
        tuple(request.potential_biases),
        tuple(evidence.knowns),
        unknowns,
        tuple(evidence.conflicts),
        tuple(evidence.next_steps),
        gaps,
        value.content_sha256,
    )
    if (
        not isinstance(evidence.synthesis_id, EntityId)
        or evidence.synthesis_id.namespace != "evidence_synthesis"
        or not isinstance(request.request_id, EntityId)
        or request.request_id.namespace != "experiment_request"
    ):
        raise ValueError("research artifact identifiers are invalid")
    _verify_payloads(frozen, payload_before, hypothesis_payload, evidence_payload, request_payload)
    if (
        _freeze_json(value.payload()) != payload_before
        or _freeze_json(hypothesis.payload()) != hypothesis_payload
        or _freeze_json(evidence.payload()) != evidence_payload
        or _freeze_json(request.payload()) != request_payload
        or value.content_sha256 != frozen.content_sha256
        or hypothesis.content_sha256 != frozen.hypothesis.content_sha256
        or evidence.content_sha256 != frozen.evidence_synthesis_hash
        or request.content_sha256 != frozen.experiment_request_hash
    ):
        raise ValueError("research synthesis port mutated during extraction")
    return frozen


def _verify_payloads(
    frozen: _SynthesisSnapshot,
    synthesis_payload: JsonValue,
    hypothesis_payload: JsonValue,
    evidence_payload: JsonValue,
    request_payload: JsonValue,
) -> None:
    if not isinstance(synthesis_payload, Mapping):
        raise TypeError("research synthesis payload must be a mapping")
    if not isinstance(hypothesis_payload, Mapping):
        raise TypeError("research hypothesis payload must be a mapping")
    if not isinstance(evidence_payload, Mapping):
        raise TypeError("research evidence payload must be a mapping")
    if not isinstance(request_payload, Mapping):
        raise TypeError("experiment request payload must be a mapping")
    _require_exact_keys(
        synthesis_payload, {"hypothesis", "evidence_synthesis", "experiment_request"}, "research synthesis"
    )
    _require_exact_keys(
        hypothesis_payload,
        {
            "spec",
            "market_state_assessment",
            "as_of",
            "valid_until",
            "lifecycle",
            "statement",
            "applicable_markets",
            "observable_outcome",
            "falsification_criterion",
            "required_data",
            "proposal_source",
        },
        "hypothesis",
    )
    _require_exact_keys(
        evidence_payload,
        {
            "hypothesis_content_sha256",
            "as_of",
            "valid_until",
            "knowns",
            "unknowns",
            "conflicts",
            "next_steps",
            "evidence_gaps",
        },
        "evidence synthesis",
    )
    _require_exact_keys(
        request_payload,
        {
            "spec",
            "hypothesis_content_sha256",
            "as_of",
            "valid_until",
            "data_requirements",
            "control",
            "evaluation_window",
            "method",
            "metrics",
            "expected_diagnostics",
            "stop_condition",
            "potential_biases",
        },
        "experiment request",
    )
    source = hypothesis_payload.get("market_state_assessment")
    if not isinstance(source, Mapping):
        raise ValueError("research hypothesis payload source does not match lineage")
    _require_exact_keys(
        source, {"assessment_id", "content_sha256", "schema_version", "as_of", "valid_until"}, "market-state source"
    )
    if source != {
        "assessment_id": str(frozen.hypothesis.market_state.artifact_id),
        "content_sha256": frozen.hypothesis.market_state.content_hash.removeprefix("sha256:"),
        "schema_version": str(frozen.hypothesis.market_state.schema_version),
        "as_of": frozen.hypothesis.as_of.to_dict()["recorded_at"],
        "valid_until": frozen.hypothesis.market_state_valid_until.to_dict()["recorded_at"],
    }:
        raise ValueError("research hypothesis payload source does not match lineage")
    spec = hypothesis_payload.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("research hypothesis payload spec does not match port")
    _require_exact_keys(spec, {"spec_id", "version", "schema_version"}, "hypothesis spec")
    if (
        type(spec.get("version")) is not int
        or spec.get("spec_id") != str(frozen.hypothesis.spec_id)
        or spec.get("version") != frozen.hypothesis.spec_version
        or spec.get("schema_version") != str(frozen.hypothesis.schema_version)
        or hypothesis_payload.get("as_of") != frozen.hypothesis.as_of.to_dict()["recorded_at"]
        or hypothesis_payload.get("valid_until") != frozen.hypothesis.valid_until.to_dict()["recorded_at"]
        or hypothesis_payload.get("lifecycle") != frozen.hypothesis.lifecycle
        or hypothesis_payload.get("statement") != frozen.hypothesis.statement
        or hypothesis_payload.get("applicable_markets") != frozen.hypothesis.applicable_markets
        or hypothesis_payload.get("observable_outcome") != frozen.hypothesis.observable_outcome
        or hypothesis_payload.get("falsification_criterion") != frozen.hypothesis.falsification_criterion
        or hypothesis_payload.get("required_data") != frozen.hypothesis.required_data
        or hypothesis_payload.get("proposal_source") != frozen.hypothesis.proposal_source
    ):
        raise ValueError("research hypothesis payload does not match port")
    if (
        evidence_payload.get("hypothesis_content_sha256") != frozen.hypothesis.content_sha256
        or request_payload.get("hypothesis_content_sha256") != frozen.hypothesis.content_sha256
    ):
        raise ValueError("research artifacts must reference the exact hypothesis content")
    if (
        evidence_payload.get("as_of") != frozen.hypothesis.as_of.to_dict()["recorded_at"]
        or evidence_payload.get("valid_until") != frozen.hypothesis.valid_until.to_dict()["recorded_at"]
        or evidence_payload.get("knowns") != frozen.knowns
        or evidence_payload.get("unknowns") != frozen.unknowns
        or evidence_payload.get("conflicts") != frozen.conflicts
        or evidence_payload.get("next_steps") != frozen.next_steps
        or evidence_payload.get("evidence_gaps")
        != tuple({"code": item.code, "description": item.description} for item in frozen.evidence_gaps)
    ):
        raise ValueError("research evidence synthesis payload does not match port")
    request_spec = request_payload.get("spec")
    if not isinstance(request_spec, Mapping):
        raise ValueError("experiment request payload spec does not match port")
    _require_exact_keys(request_spec, {"spec_id", "version", "schema_version"}, "experiment request spec")
    if (
        type(request_spec.get("version")) is not int
        or request_spec.get("spec_id") != str(frozen.experiment_request_spec_id)
        or request_spec.get("version") != frozen.experiment_request_spec_version
        or request_spec.get("schema_version") != str(frozen.hypothesis.schema_version)
        or request_payload.get("as_of") != frozen.hypothesis.as_of.to_dict()["recorded_at"]
        or request_payload.get("valid_until") != frozen.hypothesis.valid_until.to_dict()["recorded_at"]
        or request_payload.get("data_requirements") != frozen.data_requirements
        or request_payload.get("control") != frozen.control
        or request_payload.get("evaluation_window") != frozen.evaluation_window
        or request_payload.get("method") != frozen.method
        or request_payload.get("metrics") != frozen.metrics
        or request_payload.get("expected_diagnostics") != frozen.expected_diagnostics
        or request_payload.get("stop_condition") != frozen.stop_condition
        or request_payload.get("potential_biases") != frozen.potential_biases
    ):
        raise ValueError("experiment request payload does not match port")
    expected = {
        "hypothesis": {"content_sha256": frozen.hypothesis.content_sha256},
        "evidence_synthesis": {"content_sha256": frozen.evidence_synthesis_hash},
        "experiment_request": {"content_sha256": frozen.experiment_request_hash},
    }
    if any(synthesis_payload.get(key) != value for key, value in expected.items()):
        raise ValueError("research synthesis payload does not match artifacts")


def _require_exact_keys(payload: Mapping[str, JsonValue], expected: set[str], name: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{name} payload keys are not exact")


def _freeze_json(value: JsonValue) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("research payload keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    raise TypeError("research payload must be canonical JSON")
