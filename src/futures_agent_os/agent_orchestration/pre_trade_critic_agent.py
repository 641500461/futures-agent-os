"""Artifact-only adapter for the V1 research Pre-trade Critic role."""

from __future__ import annotations

from dataclasses import dataclass

from futures_agent_os.research_experiment.critique import (
    Critique,
    CritiqueStatus,
    FindingState,
    ResearchArtifactIdentity,
)
from futures_agent_os.shared_kernel import EntityId, SchemaVersion

from .catalog import AgentRoleId, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactClaim, ArtifactKind, ArtifactRef, StructuredArtifact


def _identity_matches_ref(identity: ResearchArtifactIdentity, reference: ArtifactRef) -> bool:
    return (
        str(identity.artifact_id) == str(reference.artifact_id)
        and identity.artifact_kind.value == reference.artifact_kind.value
        and identity.schema_version == reference.schema_version
        and "sha256:" + identity.content_sha256 == reference.content_hash
        and identity.as_of == reference.as_of
    )


@dataclass(frozen=True, slots=True)
class CriticTaskSources:
    artifacts: tuple[StructuredArtifact, ...]

    def __post_init__(self) -> None:
        expected = {
            ArtifactKind.HYPOTHESIS,
            ArtifactKind.EVIDENCE_SYNTHESIS,
            ArtifactKind.EXPERIMENT_REQUEST,
        }
        if (
            type(self.artifacts) is not tuple
            or len(self.artifacts) != 3
            or any(type(item) is not StructuredArtifact for item in self.artifacts)
            or {item.ref.artifact_kind for item in self.artifacts} != expected
        ):
            raise ValueError("critic sources require exact immutable V1 research artifacts")
        if len(set(self.artifacts)) != len(self.artifacts):
            raise ValueError("critic source artifacts must be unique")
        if any(
            item.producer_role_id != AgentRoleId.RESEARCH.value
            or item.producer_run_id.namespace != "agent_run"
            or item.expires_at.value <= item.ref.created_at.value
            or not item.source_refs
            for item in self.artifacts
        ):
            raise ValueError("critic sources require complete Research StructuredArtifact provenance and expiry")
        first = self.artifacts[0]
        if any(
            item.producer_run_id != first.producer_run_id
            or item.source_refs != first.source_refs
            or item.expires_at != first.expires_at
            for item in self.artifacts[1:]
        ):
            raise ValueError("critic sources require one shared Research run, lineage, and expiry")

    @property
    def refs(self) -> tuple[ArtifactRef, ...]:
        return tuple(item.ref for item in self.artifacts)


@dataclass(frozen=True, slots=True)
class PreTradeCriticResult:
    artifact: StructuredArtifact
    status: CritiqueStatus
    unresolved_categories: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.artifact) is not StructuredArtifact
            or self.artifact.producer_role_id != AgentRoleId.PRE_TRADE_CRITIC.value
            or self.artifact.producer_run_id.namespace != "agent_run"
            or self.artifact.ref.artifact_kind is not ArtifactKind.CRITIQUE
            or type(self.status) is not CritiqueStatus
            or type(self.unresolved_categories) is not tuple
            or any(type(value) is not str or not value for value in self.unresolved_categories)
        ):
            raise ValueError("critic result has invalid provenance or immutable summary")


class PreTradeCriticAgent:
    """Package an already-composed deterministic Critique without tool calls."""

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: CriticTaskSources,
        critique: Critique,
        run_id: EntityId,
    ) -> PreTradeCriticResult:
        if (
            type(task) is not AgentTaskEnvelope
            or type(sources) is not CriticTaskSources
            or type(critique) is not Critique
        ):
            raise TypeError("critic adapter requires exact typed task, sources, and critique")
        if type(run_id) is not EntityId or run_id.namespace != "agent_run":
            raise ValueError("critic adapter requires an agent_run identity")
        critique.validate_current()
        validate_task_envelope(task)
        if task.assigned_role_id != AgentRoleId.PRE_TRADE_CRITIC.value:
            raise ValueError("critic adapter requires the Pre-trade Critic role")
        if task.allowed_tools:
            raise ValueError("V1 critic adapter performs no tool calls")
        # This adapter is the historical Catalog 1.4 fixed-GAP path. Catalog
        # 1.5 is dispatched to the synchronous V1_010CriticWorker instead.
        if critique.policy.schema_version != SchemaVersion(1, 4) or task.catalog_version != SchemaVersion(1, 4):
            raise ValueError("legacy critic adapter requires its pinned 1.4 policy")
        if task.required_outputs != (ArtifactKind.CRITIQUE,):
            raise ValueError("critic task must require exactly one critique")
        if task.input_artifacts != sources.refs:
            raise ValueError("critic task inputs must exactly match supplied sources")
        by_kind = {item.ref.artifact_kind: item.ref for item in sources.artifacts}
        pairs = (
            (critique.hypothesis, by_kind[ArtifactKind.HYPOTHESIS], sources.artifacts),
            (critique.evidence_synthesis, by_kind[ArtifactKind.EVIDENCE_SYNTHESIS], sources.artifacts),
            (critique.experiment_request, by_kind[ArtifactKind.EXPERIMENT_REQUEST], sources.artifacts),
        )
        if any(
            not _identity_matches_ref(identity, reference)
            or identity.valid_until != next(item.expires_at for item in structured if item.ref == reference)
            for identity, reference, structured in pairs
        ):
            raise ValueError("critic source identity or lineage does not match the Critique")
        earliest_input_expiry = min(source.expires_at.value for source in sources.artifacts)
        if (
            task.as_of != critique.hypothesis.as_of
            or task.expires_at.value > critique.expires_at.value
            or task.expires_at.value > earliest_input_expiry
            or critique.expires_at.value > earliest_input_expiry
        ):
            raise ValueError("critic task lifetime does not match its Critique")

        ref_by_hash = {item.ref.content_hash.removeprefix("sha256:"): item.ref for item in sources.artifacts}
        diagnostic_by_category = {item.category: item for item in critique.diagnostics}
        claims = tuple(
            ArtifactClaim(
                finding.category.value.lower(),
                finding.summary,
                tuple(
                    ref_by_hash[source.content_sha256]
                    for source in diagnostic_by_category[finding.category].source_artifacts
                ),
                True,
            )
            for finding in critique.findings
            if finding.category in diagnostic_by_category
        )
        warnings = tuple(
            f"{finding.category.value}:{finding.state.value}:{finding.severity.name}"
            for finding in critique.findings
            if finding.state in {FindingState.GAP, FindingState.UNKNOWN} or finding.unresolved
        )
        artifact_ref = ArtifactRef(
            critique.critique_id,
            ArtifactKind.CRITIQUE,
            critique.policy.schema_version,
            "sha256:" + critique.content_sha256,
            critique.evaluated_at,
            critique.hypothesis.as_of,
        )
        artifact = StructuredArtifact(
            artifact_ref,
            AgentRoleId.PRE_TRADE_CRITIC.value,
            run_id,
            sources.refs,
            claims,
            warnings,
            critique.expires_at,
        )
        unresolved = tuple(finding.category.value for finding in critique.findings if finding.unresolved)
        return PreTradeCriticResult(artifact, critique.status, unresolved)
