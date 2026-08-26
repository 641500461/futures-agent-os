"""Synchronous Catalog 1.5 worker boundary for the V1-010 Research Critic."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from futures_agent_os.reference_market_data import MarketSnapshot
from futures_agent_os.research_experiment.research_hypothesis import (
    EvidenceSynthesis,
    ExperimentRequest,
    FalsifiableHypothesis,
)
from futures_agent_os.research_experiment.validation_critic import (
    DiagnosticEvidenceV1_010,
    ResearchCritiqueV1_010,
    TypedDiagnostic,
    V1_010CritiqueComposer,
)
from futures_agent_os.research_experiment.validation_tools import (
    ResearchToolResult,
    ValidationRunRequest,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .catalog import AgentRoleId, validate_task_envelope
from .contracts import (
    AgentTaskEnvelope,
    ArtifactClaim,
    ArtifactKind,
    ArtifactRef,
    ResultStatus,
    SpecialistResult,
    StructuredArtifact,
)


_CATALOG_1_5 = SchemaVersion(1, 5)


@dataclass(frozen=True, slots=True)
class V1_010CriticTaskSources:
    snapshot: MarketSnapshot
    request: ValidationRunRequest
    results: tuple[ResearchToolResult, ...]
    hypothesis: FalsifiableHypothesis
    evidence_synthesis: EvidenceSynthesis
    experiment_request: ExperimentRequest
    diagnostics: tuple[TypedDiagnostic, ...]
    evaluated_at: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if (
            type(self.snapshot) is not MarketSnapshot
            or type(self.request) is not ValidationRunRequest
            or type(self.results) is not tuple
            or any(type(item) is not ResearchToolResult for item in self.results)
            or type(self.hypothesis) is not FalsifiableHypothesis
            or type(self.evidence_synthesis) is not EvidenceSynthesis
            or type(self.experiment_request) is not ExperimentRequest
            or type(self.diagnostics) is not tuple
            or len(self.diagnostics) != 8
            or type(self.evaluated_at) is not RecordedAt
            or type(self.expires_at) is not RecordedAt
        ):
            raise TypeError("V1-010 worker sources require exact frozen values")


@dataclass(frozen=True, slots=True)
class V1_010CriticAgentResult:
    artifact: StructuredArtifact
    completion: SpecialistResult
    critique: ResearchCritiqueV1_010

    def __post_init__(self) -> None:
        if (
            type(self.artifact) is not StructuredArtifact
            or type(self.completion) is not SpecialistResult
            or type(self.critique) is not ResearchCritiqueV1_010
            or self.artifact.ref.artifact_kind is not ArtifactKind.CRITIQUE
            or self.artifact.ref.artifact_id != self.critique.critique_id
            or self.artifact.ref.content_hash != "sha256:" + self.critique.content_sha256
            or self.completion.artifacts != (self.artifact.ref,)
            or self.completion.role_id != AgentRoleId.PRE_TRADE_CRITIC.value
        ):
            raise ValueError("V1-010 worker result lineage is inconsistent")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "artifact": _structured_to_dict(self.artifact),
            "completion": _completion_to_dict(self.completion),
            "critique": self.critique.to_dict(),
        }


class V1_010ResearchCriticAgent:
    """Validate one exact 1.5 task and package a replayable Critic artifact."""

    def expected_inputs(self, sources: V1_010CriticTaskSources) -> tuple[ArtifactRef, ...]:
        return _input_refs(sources)

    def run(
        self,
        task: AgentTaskEnvelope,
        sources: V1_010CriticTaskSources,
        producer_run_id: EntityId,
    ) -> V1_010CriticAgentResult:
        if type(task) is not AgentTaskEnvelope or type(sources) is not V1_010CriticTaskSources:
            raise TypeError("V1-010 Critic worker requires exact task and sources")
        if type(producer_run_id) is not EntityId or producer_run_id.namespace != "agent_run":
            raise ValueError("V1-010 Critic worker requires an agent_run identity")
        validate_task_envelope(task)
        if (
            task.catalog_version != _CATALOG_1_5
            or task.assigned_role_id != AgentRoleId.PRE_TRADE_CRITIC.value
            or task.allowed_tools
            or task.policy_refs
            or task.required_outputs != (ArtifactKind.CRITIQUE,)
            or task.may_delegate_research
            or task.as_of != sources.snapshot.as_of
            or task.expires_at != sources.expires_at
        ):
            raise ValueError("V1-010 Critic task boundary is not exact")
        critique = self._compose(sources)
        input_refs = _input_refs(sources)
        if task.input_artifacts != input_refs:
            raise ValueError("V1-010 Critic task must bind snapshot, research, and all eight diagnostics")
        output_ref = ArtifactRef(
            critique.critique_id,
            ArtifactKind.CRITIQUE,
            _CATALOG_1_5,
            "sha256:" + critique.content_sha256,
            critique.evaluated_at,
            critique.market_snapshot_ref.as_of,
        )
        diagnostic_refs = input_refs[4:]
        claims = tuple(
            ArtifactClaim(
                diagnostic.CATEGORY.value.lower(),
                diagnostic.evidence.measurement.value,
                (diagnostic_ref,),
                False,
            )
            for diagnostic, diagnostic_ref in zip(critique.diagnostics, diagnostic_refs, strict=True)
        )
        artifact = StructuredArtifact(
            output_ref,
            AgentRoleId.PRE_TRADE_CRITIC.value,
            producer_run_id,
            input_refs,
            claims,
            critique.required_validations,
            critique.expires_at,
        )
        completion = SpecialistResult(
            task.task_id,
            AgentRoleId.PRE_TRADE_CRITIC.value,
            ResultStatus.COMPLETED,
            (output_ref,),
            (),
            (),
            critique.required_validations,
            critique.expires_at,
        )
        return V1_010CriticAgentResult(artifact, completion, critique)

    def recover(
        self,
        value: Mapping[str, object],
        task: AgentTaskEnvelope,
        sources: V1_010CriticTaskSources,
        producer_run_id: EntityId,
    ) -> V1_010CriticAgentResult:
        expected = self.run(task, sources, producer_run_id)
        if set(value) != {"artifact", "completion", "critique"}:
            raise ValueError("V1-010 Critic recovery fields are not exact")
        hydrated_critique = ResearchCritiqueV1_010.hydrate(
            _mapping(value["critique"]),
            sources.hypothesis,
            sources.evidence_synthesis,
            sources.experiment_request,
            sources.results,
        )
        recovered = V1_010CriticAgentResult(
            _hydrate_structured(_mapping(value["artifact"])),
            _hydrate_completion(_mapping(value["completion"])),
            hydrated_critique,
        )
        if recovered != expected:
            raise ValueError("V1-010 Critic recovery payload does not match deterministic replay")
        return recovered

    def run_serialized_diagnostics(
        self,
        task: AgentTaskEnvelope,
        sources: V1_010CriticTaskSources,
        serialized_diagnostics: tuple[Mapping[str, object], ...],
        producer_run_id: EntityId,
    ) -> V1_010CriticAgentResult | SpecialistResult:
        """Auditable external boundary: invalid upstream artifacts never become PASS."""

        code = "DIAGNOSTIC_MISSING" if len(serialized_diagnostics) != 8 else "DIAGNOSTIC_INVALID"
        try:
            if type(serialized_diagnostics) is not tuple or len(serialized_diagnostics) != 8:
                raise ValueError(code)
            hydrated = tuple(
                type(template)(
                    DiagnosticEvidenceV1_010.hydrate(
                        raw,
                        template.evidence.research_sources,
                        template.evidence.tool_results,
                    )
                )
                for raw, template in zip(serialized_diagnostics, sources.diagnostics, strict=True)
            )
            return self.run(task, replace(sources, diagnostics=hydrated), producer_run_id)
        except TypeError, ValueError, KeyError:
            return SpecialistResult(
                task.task_id,
                AgentRoleId.PRE_TRADE_CRITIC.value,
                ResultStatus.FAILED,
                (),
                (),
                (code,),
                (code,),
                task.expires_at,
            )

    @staticmethod
    def _compose(sources: V1_010CriticTaskSources) -> ResearchCritiqueV1_010:
        return V1_010CritiqueComposer().compose(
            sources.snapshot,
            sources.request,
            sources.hypothesis,
            sources.evidence_synthesis,
            sources.experiment_request,
            sources.diagnostics,
            sources.evaluated_at,
            sources.expires_at,
        )


def _input_refs(sources: V1_010CriticTaskSources) -> tuple[ArtifactRef, ...]:
    snapshot = sources.request.snapshot_ref
    return (
        ArtifactRef(
            snapshot.artifact_id,
            ArtifactKind.MARKET_SNAPSHOT,
            snapshot.schema_version,
            "sha256:" + snapshot.content_sha256,
            snapshot.as_of,
            snapshot.as_of,
        ),
        _research_ref(sources.hypothesis, ArtifactKind.HYPOTHESIS),
        _research_ref(sources.evidence_synthesis, ArtifactKind.EVIDENCE_SYNTHESIS),
        _research_ref(sources.experiment_request, ArtifactKind.EXPERIMENT_REQUEST),
        *(
            ArtifactRef(
                item.evidence.diagnostic_id,
                ArtifactKind.RESEARCH_DIAGNOSTIC,
                item.evidence.schema_version,
                "sha256:" + item.evidence.content_sha256,
                item.evidence.evaluated_at,
                item.evidence.as_of,
            )
            for item in sources.diagnostics
        ),
    )


def _research_ref(
    value: FalsifiableHypothesis | EvidenceSynthesis | ExperimentRequest, kind: ArtifactKind
) -> ArtifactRef:
    if type(value) is FalsifiableHypothesis:
        artifact_id = value.hypothesis_id
    elif type(value) is EvidenceSynthesis:
        artifact_id = value.synthesis_id
    elif type(value) is ExperimentRequest:
        artifact_id = value.request_id
    else:
        raise TypeError("worker research refs require exact frozen artifacts")
    return ArtifactRef(
        artifact_id,
        kind,
        value.schema_version,
        "sha256:" + value.content_sha256,
        value.as_of,
        value.as_of,
    )


def _ref_to_dict(ref: ArtifactRef) -> dict[str, JsonValue]:
    return {
        "artifact_id": str(ref.artifact_id),
        "artifact_kind": ref.artifact_kind.value,
        "schema_version": str(ref.schema_version),
        "content_hash": ref.content_hash,
        "created_at": ref.created_at.to_dict()["recorded_at"],
        "as_of": ref.as_of.to_dict()["recorded_at"],
    }


def _structured_to_dict(value: StructuredArtifact) -> dict[str, JsonValue]:
    return {
        "ref": _ref_to_dict(value.ref),
        "producer_role_id": value.producer_role_id,
        "producer_run_id": str(value.producer_run_id),
        "source_refs": tuple(_ref_to_dict(ref) for ref in value.source_refs),
        "claims": tuple(
            {
                "claim_kind": claim.claim_kind,
                "statement": claim.statement,
                "evidence_refs": tuple(_ref_to_dict(ref) for ref in claim.evidence_refs),
                "is_inference": claim.is_inference,
            }
            for claim in value.claims
        ),
        "warnings": value.warnings,
        "expires_at": value.expires_at.to_dict()["recorded_at"],
        "content_sha256": canonical_sha256(
            {
                "critique_ref": _ref_to_dict(value.ref),
                "source_refs": tuple(_ref_to_dict(ref) for ref in value.source_refs),
            }
        ),
    }


def _completion_to_dict(value: SpecialistResult) -> dict[str, JsonValue]:
    return {
        "task_id": str(value.task_id),
        "role_id": value.role_id,
        "status": value.status.value,
        "artifacts": tuple(_ref_to_dict(ref) for ref in value.artifacts),
        "counter_evidence_refs": tuple(_ref_to_dict(ref) for ref in value.counter_evidence_refs),
        "unknowns": value.unknowns,
        "warnings": value.warnings,
        "expires_at": value.expires_at.to_dict()["recorded_at"],
    }


def _hydrate_ref(value: Mapping[str, object]) -> ArtifactRef:
    if set(value) != {"artifact_id", "artifact_kind", "schema_version", "content_hash", "created_at", "as_of"}:
        raise ValueError("worker artifact ref fields are not exact")
    return ArtifactRef(
        EntityId.parse(str(value["artifact_id"])),
        ArtifactKind(str(value["artifact_kind"])),
        SchemaVersion.parse(str(value["schema_version"])),
        str(value["content_hash"]),
        RecordedAt.parse(str(value["created_at"])),
        RecordedAt.parse(str(value["as_of"])),
    )


def _sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("worker recovery collections must be JSON sequences")
    return tuple(value)


def _hydrate_structured(value: Mapping[str, object]) -> StructuredArtifact:
    expected = {
        "ref",
        "producer_role_id",
        "producer_run_id",
        "source_refs",
        "claims",
        "warnings",
        "expires_at",
        "content_sha256",
    }
    if set(value) != expected:
        raise ValueError("worker structured artifact fields are not exact")
    claims = tuple(
        ArtifactClaim(
            str(_mapping(item)["claim_kind"]),
            str(_mapping(item)["statement"]),
            tuple(_hydrate_ref(_mapping(ref)) for ref in _sequence(_mapping(item)["evidence_refs"])),
            _bool(_mapping(item)["is_inference"]),
        )
        for item in _sequence(value["claims"])
    )
    artifact = StructuredArtifact(
        _hydrate_ref(_mapping(value["ref"])),
        str(value["producer_role_id"]),
        EntityId.parse(str(value["producer_run_id"])),
        tuple(_hydrate_ref(_mapping(ref)) for ref in _sequence(value["source_refs"])),
        claims,
        tuple(str(item) for item in _sequence(value["warnings"])),
        RecordedAt.parse(str(value["expires_at"])),
    )
    if _structured_to_dict(artifact)["content_sha256"] != value["content_sha256"]:
        raise ValueError("worker structured artifact content hash mismatch")
    return artifact


def _hydrate_completion(value: Mapping[str, object]) -> SpecialistResult:
    expected = {
        "task_id",
        "role_id",
        "status",
        "artifacts",
        "counter_evidence_refs",
        "unknowns",
        "warnings",
        "expires_at",
    }
    if set(value) != expected:
        raise ValueError("worker completion fields are not exact")
    return SpecialistResult(
        EntityId.parse(str(value["task_id"])),
        str(value["role_id"]),
        ResultStatus(str(value["status"])),
        tuple(_hydrate_ref(_mapping(ref)) for ref in _sequence(value["artifacts"])),
        tuple(_hydrate_ref(_mapping(ref)) for ref in _sequence(value["counter_evidence_refs"])),
        tuple(str(item) for item in _sequence(value["unknowns"])),
        tuple(str(item) for item in _sequence(value["warnings"])),
        RecordedAt.parse(str(value["expires_at"])),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("worker recovery requires mapping payloads")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("worker recovery booleans must be exact")
    return value
