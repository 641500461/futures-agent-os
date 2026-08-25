"""Deterministic V1 research critique contracts.

The Critique is a research gate over immutable V1-007 artifacts and explicit
diagnostics.  Missing diagnostics remain gaps/unknowns; this module never
executes an experiment, invents evidence, or creates trading authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from threading import RLock
from uuid import UUID

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .research_hypothesis import EvidenceSynthesis, ExperimentRequest, FalsifiableHypothesis


class CritiqueStatus(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    REJECT = "REJECT"
    DEFER = "DEFER"


class CritiqueCategory(StrEnum):
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    DATA_LEAKAGE = "DATA_LEAKAGE"
    COST_COVERAGE = "COST_COVERAGE"
    SAMPLE_APPLICABILITY = "SAMPLE_APPLICABILITY"
    CONCENTRATION = "CONCENTRATION"
    PARAMETER_STABILITY = "PARAMETER_STABILITY"
    HISTORICAL_FAILURE = "HISTORICAL_FAILURE"
    CONCLUSION_STRENGTH = "CONCLUSION_STRENGTH"


class FindingState(StrEnum):
    CLEAR = "CLEAR"
    ISSUE = "ISSUE"
    GAP = "GAP"
    UNKNOWN = "UNKNOWN"


class IssueSeverity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class IssueResolution(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CONCLUSIVE = "CONCLUSIVE"


class DiagnosticConclusion(StrEnum):
    """Closed factual conclusion emitted by a category-specific diagnostic."""

    CLEAR = "CLEAR"
    ISSUE = "ISSUE"


class DiagnosticSpec(StrEnum):
    """The only diagnostic specifications V1-009 can recognise.

    These names reserve the deterministic V1-010 producer contracts.  V1-009
    deliberately does not manufacture any of their artifacts.
    """

    COUNTER_EVIDENCE = "counter_evidence.v1"
    DATA_LEAKAGE = "data_leakage.v1"
    COST_COVERAGE = "cost_coverage.v1"
    SAMPLE_APPLICABILITY = "sample_applicability.v1"
    CONCENTRATION = "concentration.v1"
    PARAMETER_STABILITY = "parameter_stability.v1"
    HISTORICAL_FAILURE = "historical_failure.v1"
    CONCLUSION_STRENGTH = "conclusion_strength.v1"


class DiagnosticMeasurement(StrEnum):
    """Closed measured outcomes; narrative text is never a gate input."""

    WITHIN_THRESHOLD = "WITHIN_THRESHOLD"
    THRESHOLD_BREACH = "THRESHOLD_BREACH"
    CRITICAL_BREACH = "CRITICAL_BREACH"


class ResearchArtifactKind(StrEnum):
    HYPOTHESIS = "hypothesis"
    EVIDENCE_SYNTHESIS = "evidence_synthesis"
    EXPERIMENT_REQUEST = "experiment_request"


def _sha256(value: str, field: str) -> None:
    if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} requires a lowercase content_sha256")


@dataclass(frozen=True, slots=True)
class CritiquePolicy:
    policy_id: EntityId
    version: int
    schema_version: SchemaVersion
    max_iterations: int

    def __post_init__(self) -> None:
        if type(self.policy_id) is not EntityId or self.policy_id.namespace != "critique_policy":
            raise ValueError("critique policy requires a critique_policy id")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("critique policy version must be a positive integer")
        if type(self.schema_version) is not SchemaVersion:
            raise TypeError("critique policy requires an exact SchemaVersion")
        if type(self.max_iterations) is not int or not 1 <= self.max_iterations <= 20:
            raise ValueError("critique policy max_iterations must be between 1 and 20")
        if (
            self.policy_id != V1_009_POLICY_ID
            or self.version != V1_009_POLICY_VERSION
            or self.schema_version != V1_009_POLICY_SCHEMA
            or self.max_iterations != V1_009_POLICY_MAX_ITERATIONS
        ):
            raise ValueError("V1-009 Critique policy is a fixed pinned contract")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "policy_id": str(self.policy_id),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "max_iterations": self.max_iterations,
        }


V1_009_POLICY_ID = EntityId("critique_policy", UUID("019034dd-0000-7000-8000-000000000009"))
V1_009_POLICY_VERSION = 1
V1_009_POLICY_SCHEMA = SchemaVersion(1, 4)
V1_009_POLICY_MAX_ITERATIONS = 1


def v1_009_critique_policy() -> CritiquePolicy:
    return CritiquePolicy(
        V1_009_POLICY_ID,
        V1_009_POLICY_VERSION,
        V1_009_POLICY_SCHEMA,
        V1_009_POLICY_MAX_ITERATIONS,
    )


@dataclass(frozen=True, slots=True)
class CritiqueRevision:
    """One immutable evaluation revision for an episode/hypothesis/policy."""

    episode_id: EntityId
    hypothesis_content_sha256: str
    policy_id: EntityId
    policy_version: int
    policy_schema_version: SchemaVersion
    evaluation_sha256: str
    iteration: int

    def __post_init__(self) -> None:
        if (
            type(self.episode_id) is not EntityId
            or self.episode_id.namespace != "decision_episode"
            or type(self.policy_id) is not EntityId
            or self.policy_id.namespace != "critique_policy"
            or type(self.policy_version) is not int
            or self.policy_version < 1
            or type(self.policy_schema_version) is not SchemaVersion
            or type(self.iteration) is not int
            or self.iteration < 1
        ):
            raise ValueError("critique revision requires exact episode, policy, and positive iteration")
        _sha256(self.hypothesis_content_sha256, "critique revision hypothesis")
        _sha256(self.evaluation_sha256, "critique revision evaluation")


class CritiqueRevisionStore:
    """Reference aggregate with transaction-equivalent immutable revision semantics."""

    def __init__(self) -> None:
        self._by_scope: dict[tuple[EntityId, EntityId, int, SchemaVersion], list[CritiqueRevision]] = {}
        self._maximum_by_scope: dict[tuple[EntityId, EntityId, int, SchemaVersion], int] = {}
        self._lock = RLock()

    def reserve(
        self, episode_id: EntityId, hypothesis_content_sha256: str, policy: CritiquePolicy, evaluation_sha256: str
    ) -> CritiqueRevision:
        if type(policy) is not CritiquePolicy:
            raise TypeError("critique revision requires an exact policy")
        _sha256(hypothesis_content_sha256, "critique revision hypothesis")
        _sha256(evaluation_sha256, "critique revision evaluation")
        key = (episode_id, policy.policy_id, policy.version, policy.schema_version)
        with self._lock:
            prior = self._by_scope.setdefault(key, [])
            frozen_maximum = self._maximum_by_scope.setdefault(key, policy.max_iterations)
            if frozen_maximum != policy.max_iterations:
                raise ValueError("critique revision policy maximum is immutable for its scope")
            for revision in prior:
                if revision.evaluation_sha256 == evaluation_sha256:
                    if revision.hypothesis_content_sha256 != hypothesis_content_sha256:
                        raise ValueError("critique evaluation retry conflicts with its reserved hypothesis")
                    return revision
            if prior and prior[-1].iteration >= policy.max_iterations:
                raise ValueError("critique iteration limit is exhausted; final unresolved revision must DEFER")
            revision = CritiqueRevision(
                episode_id,
                hypothesis_content_sha256,
                policy.policy_id,
                policy.version,
                policy.schema_version,
                evaluation_sha256,
                len(prior) + 1,
            )
            prior.append(revision)
            return revision

    def require(
        self, episode_id: EntityId, hypothesis_content_sha256: str, policy: CritiquePolicy, evaluation_sha256: str
    ) -> CritiqueRevision:
        """Return the exact prior reservation; completion never allocates one."""
        key = (episode_id, policy.policy_id, policy.version, policy.schema_version)
        with self._lock:
            if self._maximum_by_scope.get(key) != policy.max_iterations:
                raise ValueError("critique revision policy maximum is not the pinned scope")
            for revision in self._by_scope.get(key, ()):
                if revision.evaluation_sha256 == evaluation_sha256:
                    if revision.hypothesis_content_sha256 != hypothesis_content_sha256:
                        raise ValueError("critic completion hypothesis conflicts with its reservation")
                    return revision
        raise ValueError("critic completion requires an exact reserved revision")


@dataclass(frozen=True, slots=True)
class ResearchArtifactIdentity:
    artifact_id: EntityId
    artifact_kind: ResearchArtifactKind
    schema_version: SchemaVersion
    content_sha256: str
    as_of: RecordedAt
    valid_until: RecordedAt

    def __post_init__(self) -> None:
        if (
            type(self.artifact_id) is not EntityId
            or type(self.artifact_kind) is not ResearchArtifactKind
            or type(self.schema_version) is not SchemaVersion
            or type(self.as_of) is not RecordedAt
            or type(self.valid_until) is not RecordedAt
        ):
            raise TypeError("research artifact identity requires exact immutable values")
        if self.artifact_id.namespace != self.artifact_kind.value:
            raise ValueError("research artifact identity namespace does not match its kind")
        if self.valid_until.value <= self.as_of.value:
            raise ValueError("research artifact identity requires a valid lifetime")
        _sha256(self.content_sha256, "research artifact identity")

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_id": str(self.artifact_id),
            "artifact_kind": self.artifact_kind.value,
            "schema_version": str(self.schema_version),
            "content_sha256": self.content_sha256,
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
        }


@dataclass(frozen=True, slots=True)
class DiagnosticRevision:
    """A verified predecessor/successor identity pair, never a text claim."""

    predecessor: ResearchArtifactIdentity
    successor: ResearchArtifactIdentity

    def __post_init__(self) -> None:
        if (
            type(self.predecessor) is not ResearchArtifactIdentity
            or type(self.successor) is not ResearchArtifactIdentity
        ):
            raise TypeError("diagnostic revision requires exact artifact identities")
        if self.predecessor.artifact_kind is not self.successor.artifact_kind:
            raise ValueError("diagnostic revision must retain artifact kind lineage")
        if self.predecessor == self.successor:
            raise ValueError("diagnostic revision requires a distinct successor artifact")

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {"predecessor": self.predecessor.to_dict(), "successor": self.successor.to_dict()}


_SPEC_FOR_CATEGORY = dict(zip(CritiqueCategory, DiagnosticSpec, strict=True))
V1_009_REQUIRED_VALIDATIONS = tuple(
    f"DIAGNOSTIC_REQUIRED:{category.value}" for category in sorted(CritiqueCategory, key=lambda value: value.value)
)


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    """Content-addressed, PIT-bound evidence for exactly one Critique check.

    The three research artifacts are *not* diagnostics.  A diagnostic must
    carry its own measured facts and source lineage, so callers cannot relabel
    ordinary hypothesis/synthesis/request hashes as a passing check.
    ``diagnostic_kind`` is deliberately closed to the eight CritiqueCategory
    values; V1-009 consumes these facts but does not execute a tool to create
    them.
    """

    category: CritiqueCategory
    artifact_id: EntityId
    producer_role_id: str
    spec: DiagnosticSpec
    spec_version: SchemaVersion
    measurements: tuple[DiagnosticMeasurement, ...]
    source_artifacts: tuple[ResearchArtifactIdentity, ...]
    as_of: RecordedAt
    valid_until: RecordedAt
    revision: DiagnosticRevision | None
    content_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.category) is not CritiqueCategory
            or type(self.artifact_id) is not EntityId
            or type(self.spec) is not DiagnosticSpec
            or type(self.spec_version) is not SchemaVersion
            or type(self.measurements) is not tuple
            or type(self.source_artifacts) is not tuple
            or type(self.as_of) is not RecordedAt
            or type(self.valid_until) is not RecordedAt
            or (self.revision is not None and type(self.revision) is not DiagnosticRevision)
        ):
            raise TypeError("diagnostic evidence requires exact immutable typed values")
        if (
            self.artifact_id.namespace != "critique_diagnostic"
            or self.producer_role_id != "deterministic_research_diagnostic"
            or self.spec is not _SPEC_FOR_CATEGORY[self.category]
            or not self.measurements
            or any(type(v) is not DiagnosticMeasurement for v in self.measurements)
            or len(set(self.measurements)) != len(self.measurements)
            or self.measurements != tuple(sorted(self.measurements))
            or not self.source_artifacts
            or any(type(v) is not ResearchArtifactIdentity for v in self.source_artifacts)
            or len(set(self.source_artifacts)) != len(self.source_artifacts)
            or self.valid_until.value <= self.as_of.value
        ):
            raise ValueError("diagnostic evidence requires canonical measured facts and PIT lineage")
        _sha256(self.content_sha256, "diagnostic evidence")
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("diagnostic evidence content_sha256 does not match immutable facts")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "category": self.category.value,
            "artifact_id": str(self.artifact_id),
            "producer_role_id": self.producer_role_id,
            "spec": self.spec.value,
            "spec_version": str(self.spec_version),
            "measurements": tuple(value.value for value in self.measurements),
            "source_artifacts": tuple(value.to_dict() for value in self.source_artifacts),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "valid_until": self.valid_until.to_dict()["recorded_at"],
            "revision": None if self.revision is None else self.revision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CritiqueFinding:
    category: CritiqueCategory
    state: FindingState
    severity: IssueSeverity
    resolution: IssueResolution
    summary: str
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.category) is not CritiqueCategory
            or type(self.state) is not FindingState
            or type(self.severity) is not IssueSeverity
            or type(self.resolution) is not IssueResolution
            or type(self.evidence_hashes) is not tuple
        ):
            raise TypeError("critique finding requires exact enums and an immutable evidence tuple")
        if type(self.summary) is not str or not self.summary.strip() or self.summary != self.summary.strip():
            raise ValueError("critique finding requires a canonical non-empty summary")
        if len(set(self.evidence_hashes)) != len(self.evidence_hashes):
            raise ValueError("critique finding evidence hashes must be unique")
        for digest in self.evidence_hashes:
            _sha256(digest, "critique finding evidence")
        if self.state in {FindingState.GAP, FindingState.UNKNOWN}:
            if self.evidence_hashes or self.resolution is not IssueResolution.UNRESOLVED:
                raise ValueError("gap or unknown findings cannot claim evidence or resolution")
        elif not self.evidence_hashes:
            raise ValueError("clear and issue findings require explicit evidence")
        if self.state is FindingState.CLEAR and (
            self.severity is not IssueSeverity.INFO or self.resolution is not IssueResolution.RESOLVED
        ):
            raise ValueError("clear findings must be resolved informational findings")
        if (
            self.state is FindingState.ISSUE
            and self.resolution is IssueResolution.CONCLUSIVE
            and self.severity < IssueSeverity.HIGH
        ):
            raise ValueError("conclusive rejection evidence must be high or critical severity")
        if self.state is not FindingState.ISSUE and self.resolution is IssueResolution.CONCLUSIVE:
            raise ValueError("only an evidenced issue can be conclusive")

    @property
    def unresolved(self) -> bool:
        return self.resolution is IssueResolution.UNRESOLVED

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "category": self.category.value,
            "state": self.state.value,
            "severity": self.severity.name,
            "resolution": self.resolution.value,
            "summary": self.summary,
            "evidence_hashes": self.evidence_hashes,
        }


def finding_from_diagnostic(diagnostic: DiagnosticEvidence) -> CritiqueFinding:
    """Derive, rather than accept, the policy-facing finding state."""

    if diagnostic.measurements == (DiagnosticMeasurement.WITHIN_THRESHOLD,):
        return CritiqueFinding(
            diagnostic.category,
            FindingState.CLEAR,
            IssueSeverity.INFO,
            IssueResolution.RESOLVED,
            f"{diagnostic.spec.value}: within deterministic threshold.",
            (diagnostic.content_sha256,),
        )
    critical = DiagnosticMeasurement.CRITICAL_BREACH in diagnostic.measurements
    resolution = (
        IssueResolution.CONCLUSIVE if critical and diagnostic.revision is not None else IssueResolution.UNRESOLVED
    )
    return CritiqueFinding(
        diagnostic.category,
        FindingState.ISSUE,
        IssueSeverity.CRITICAL if critical else IssueSeverity.HIGH,
        resolution,
        f"{diagnostic.spec.value}: deterministic threshold breach.",
        (diagnostic.content_sha256,),
    )


def _missing_diagnostic_finding(category: CritiqueCategory) -> CritiqueFinding:
    return CritiqueFinding(
        category,
        FindingState.GAP,
        IssueSeverity.HIGH if category is CritiqueCategory.DATA_LEAKAGE else IssueSeverity.MEDIUM,
        IssueResolution.UNRESOLVED,
        f"No typed diagnostic evidence was supplied for {category.value}.",
        (),
    )


def determine_critique_status(
    policy: CritiquePolicy, iteration: int, findings: tuple[CritiqueFinding, ...]
) -> CritiqueStatus:
    """Fail-closed conclusion that an Agent cannot override."""

    if type(policy) is not CritiquePolicy or type(iteration) is not int or iteration < 1:
        raise ValueError("critique evaluation requires a typed policy and positive iteration")
    if type(findings) is not tuple or any(type(item) is not CritiqueFinding for item in findings):
        raise TypeError("critique evaluation requires immutable typed findings")
    if iteration > policy.max_iterations:
        raise ValueError("critique iteration limit is exhausted; no further revision is valid")
    if any(item.unresolved and item.severity >= IssueSeverity.HIGH for item in findings):
        return CritiqueStatus.DEFER
    if any(item.resolution is IssueResolution.CONCLUSIVE for item in findings):
        return CritiqueStatus.REJECT
    unresolved = any(item.unresolved for item in findings)
    if unresolved and iteration >= policy.max_iterations:
        return CritiqueStatus.DEFER
    if unresolved:
        return CritiqueStatus.REVISE
    return CritiqueStatus.PASS


@dataclass(frozen=True, slots=True)
class Critique:
    critique_id: EntityId
    policy: CritiquePolicy
    hypothesis: ResearchArtifactIdentity
    evidence_synthesis: ResearchArtifactIdentity
    experiment_request: ResearchArtifactIdentity
    evaluated_at: RecordedAt
    expires_at: RecordedAt
    iteration: int
    hypothesis_snapshot: FalsifiableHypothesis
    evidence_synthesis_snapshot: EvidenceSynthesis
    experiment_request_snapshot: ExperimentRequest
    diagnostics: tuple[DiagnosticEvidence, ...]
    findings: tuple[CritiqueFinding, ...]
    status: CritiqueStatus
    required_validations: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self.critique_id) is not EntityId or self.critique_id.namespace != "critique":
            raise ValueError("critique requires a critique id")
        if (
            type(self.policy) is not CritiquePolicy
            or type(self.hypothesis) is not ResearchArtifactIdentity
            or type(self.evidence_synthesis) is not ResearchArtifactIdentity
            or type(self.experiment_request) is not ResearchArtifactIdentity
            or type(self.evaluated_at) is not RecordedAt
            or type(self.expires_at) is not RecordedAt
            or type(self.status) is not CritiqueStatus
            or type(self.hypothesis_snapshot) is not FalsifiableHypothesis
            or type(self.evidence_synthesis_snapshot) is not EvidenceSynthesis
            or type(self.experiment_request_snapshot) is not ExperimentRequest
            or type(self.diagnostics) is not tuple
            or type(self.findings) is not tuple
            or type(self.required_validations) is not tuple
        ):
            raise TypeError("critique requires exact immutable typed values")
        if any(type(item) is not CritiqueFinding for item in self.findings):
            raise TypeError("critique findings must be exact immutable values")
        if any(type(item) is not DiagnosticEvidence for item in self.diagnostics):
            raise TypeError("critique diagnostics must be exact immutable values")
        if self.diagnostics or self.required_validations != V1_009_REQUIRED_VALIDATIONS:
            raise ValueError("V1-009 accepts only fixed diagnostic gaps pending V1-010 producers")
        identities = (self.hypothesis, self.evidence_synthesis, self.experiment_request)
        snapshots = (self.hypothesis_snapshot, self.evidence_synthesis_snapshot, self.experiment_request_snapshot)
        if tuple(item.artifact_kind for item in identities) != tuple(ResearchArtifactKind):
            raise ValueError("critique requires exact hypothesis, synthesis, and experiment identities")
        if (
            self.evidence_synthesis_snapshot.hypothesis != self.hypothesis_snapshot
            or self.experiment_request_snapshot.hypothesis != self.hypothesis_snapshot
            or self.hypothesis_snapshot.content_sha256 != canonical_sha256(self.hypothesis_snapshot.payload())
            or self.evidence_synthesis_snapshot.content_sha256
            != canonical_sha256(self.evidence_synthesis_snapshot.payload())
            or self.experiment_request_snapshot.content_sha256
            != canonical_sha256(self.experiment_request_snapshot.payload())
            or tuple(item.content_sha256 for item in snapshots) != tuple(item.content_sha256 for item in identities)
            or tuple(item.schema_version for item in snapshots) != tuple(item.schema_version for item in identities)
            or tuple(item.as_of for item in snapshots) != tuple(item.as_of for item in identities)
            or tuple(item.valid_until for item in snapshots) != tuple(item.valid_until for item in identities)
        ):
            raise ValueError("critique must retain complete verified source snapshots and nested hypothesis lineage")
        if len(self.findings) != len(CritiqueCategory) or {item.category for item in self.findings} != set(
            CritiqueCategory
        ):
            raise ValueError("critique must contain every diagnostic category exactly once")
        if self.findings != tuple(sorted(self.findings, key=lambda item: item.category.value)):
            raise ValueError("critique findings must use canonical category order")
        if len({item.category for item in self.diagnostics}) != len(self.diagnostics) or self.diagnostics != tuple(
            sorted(self.diagnostics, key=lambda item: item.category.value)
        ):
            raise ValueError("critique diagnostics must be closed, unique, and canonical")
        diagnostic_by_category = {item.category: item for item in self.diagnostics}
        expected_findings = tuple(
            finding_from_diagnostic(diagnostic_by_category[category])
            if category in diagnostic_by_category
            else _missing_diagnostic_finding(category)
            for category in sorted(CritiqueCategory, key=lambda item: item.value)
        )
        if self.findings != expected_findings:
            raise ValueError("Critique findings must be deterministically derived from typed diagnostics")
        identities_set = set(identities)
        if any(
            not set(item.source_artifacts).issubset(identities_set)
            or item.as_of.value < max(source.as_of.value for source in item.source_artifacts)
            or item.valid_until.value > min(source.valid_until.value for source in item.source_artifacts)
            for item in self.diagnostics
        ):
            raise ValueError("diagnostic PIT lineage must bind exact Critique source artifacts")
        if any(
            type(value) is not str or not value.strip() or value != value.strip() for value in self.required_validations
        ):
            raise ValueError("required validations must be canonical non-empty strings")
        if len(set(self.required_validations)) != len(self.required_validations):
            raise ValueError("required validations must be unique")
        if self.required_validations != tuple(sorted(self.required_validations)):
            raise ValueError("required validations must use canonical order")
        if self.evaluated_at.value < max(item.as_of.value for item in identities):
            raise ValueError("critique cannot evaluate future research evidence")
        if (
            self.expires_at.value > min(item.valid_until.value for item in identities)
            or self.expires_at.value <= self.evaluated_at.value
        ):
            raise ValueError("critique lifetime must remain inside every source lifetime")
        expected = determine_critique_status(self.policy, self.iteration, self.findings)
        if self.status is not CritiqueStatus.DEFER or self.status is not expected:
            raise ValueError("critique status does not match the deterministic gate")
        if self.status in {CritiqueStatus.REVISE, CritiqueStatus.DEFER} and not self.required_validations:
            raise ValueError("revised or deferred critique requires explicit validation work")
        if self.status is CritiqueStatus.PASS and self.required_validations:
            raise ValueError("passing critique cannot require unresolved validation work")
        allowed_hashes = {item.content_sha256 for item in self.diagnostics}
        if any(not set(item.evidence_hashes).issubset(allowed_hashes) for item in self.findings):
            raise ValueError("critique finding must cite its typed diagnostic evidence")
        _sha256(self.content_sha256, "critique")
        if self.content_sha256 != canonical_sha256(self.payload()):
            raise ValueError("critique content_sha256 does not match immutable content")

    def validate_current(self) -> None:
        """Re-run all immutable/hash checks after crossing an adapter boundary."""
        self.__post_init__()

    def payload(self) -> dict[str, JsonValue]:
        return {
            "policy": self.policy.to_dict(),
            "hypothesis": self.hypothesis.to_dict(),
            "evidence_synthesis": self.evidence_synthesis.to_dict(),
            "experiment_request": self.experiment_request.to_dict(),
            "evaluated_at": self.evaluated_at.to_dict()["recorded_at"],
            "expires_at": self.expires_at.to_dict()["recorded_at"],
            "iteration": self.iteration,
            "source_snapshots": {
                "hypothesis": self.hypothesis_snapshot.payload(),
                "evidence_synthesis": self.evidence_synthesis_snapshot.payload(),
                "experiment_request": self.experiment_request_snapshot.payload(),
            },
            "diagnostics": tuple(item.payload() | {"content_sha256": item.content_sha256} for item in self.diagnostics),
            "findings": tuple(item.to_dict() for item in self.findings),
            "status": self.status.value,
            "required_validations": self.required_validations,
        }


class CritiqueComposer:
    """Bind exact V1-007 artifacts and calculate the only valid conclusion."""

    def compose(
        self,
        policy: CritiquePolicy,
        hypothesis: FalsifiableHypothesis,
        evidence_synthesis: EvidenceSynthesis,
        experiment_request: ExperimentRequest,
        evaluated_at: RecordedAt,
        expires_at: RecordedAt,
        iteration: int,
        diagnostics: tuple[DiagnosticEvidence, ...],
        required_validations: tuple[str, ...],
    ) -> Critique:
        if (
            type(policy) is not CritiquePolicy
            or type(hypothesis) is not FalsifiableHypothesis
            or type(evidence_synthesis) is not EvidenceSynthesis
            or type(experiment_request) is not ExperimentRequest
        ):
            raise TypeError("critique composer requires exact V1 research artifacts")
        if evidence_synthesis.hypothesis != hypothesis or experiment_request.hypothesis != hypothesis:
            raise ValueError("critique sources must bind the exact hypothesis content")
        if hypothesis.content_sha256 != canonical_sha256(hypothesis.payload()):
            raise ValueError("hypothesis content identity is invalid")
        if evidence_synthesis.content_sha256 != canonical_sha256(evidence_synthesis.payload()):
            raise ValueError("evidence synthesis content identity is invalid")
        if experiment_request.content_sha256 != canonical_sha256(experiment_request.payload()):
            raise ValueError("experiment request content identity is invalid")
        if type(diagnostics) is not tuple or any(type(item) is not DiagnosticEvidence for item in diagnostics):
            raise TypeError("critique evaluation requires immutable typed diagnostics")
        # V1-010 owns the executable deterministic diagnostic producers.  Until
        # those artifacts exist, V1-009 must not turn narrative or caller-made
        # measurements into a CLEAR/RESOLVED conclusion.
        if diagnostics:
            raise ValueError("V1-009 has no verified deterministic diagnostic artifacts; findings remain GAP")
        if required_validations != V1_009_REQUIRED_VALIDATIONS:
            raise ValueError("V1-009 requires the fixed closed diagnostic validation set")
        identities = (
            ResearchArtifactIdentity(
                hypothesis.hypothesis_id,
                ResearchArtifactKind.HYPOTHESIS,
                hypothesis.schema_version,
                hypothesis.content_sha256,
                hypothesis.as_of,
                hypothesis.valid_until,
            ),
            ResearchArtifactIdentity(
                evidence_synthesis.synthesis_id,
                ResearchArtifactKind.EVIDENCE_SYNTHESIS,
                evidence_synthesis.schema_version,
                evidence_synthesis.content_sha256,
                evidence_synthesis.as_of,
                evidence_synthesis.valid_until,
            ),
            ResearchArtifactIdentity(
                experiment_request.request_id,
                ResearchArtifactKind.EXPERIMENT_REQUEST,
                experiment_request.schema_version,
                experiment_request.content_sha256,
                experiment_request.as_of,
                experiment_request.valid_until,
            ),
        )
        ordered_diagnostics = tuple(sorted(diagnostics, key=lambda item: item.category.value))
        diagnostic_by_category = {item.category: item for item in ordered_diagnostics}
        ordered_findings = tuple(
            finding_from_diagnostic(diagnostic_by_category[category])
            if category in diagnostic_by_category
            else _missing_diagnostic_finding(category)
            for category in sorted(CritiqueCategory, key=lambda item: item.value)
        )
        ordered_validations = V1_009_REQUIRED_VALIDATIONS
        if (
            type(evaluated_at) is not RecordedAt
            or type(expires_at) is not RecordedAt
            or type(iteration) is not int
            or iteration < 1
            or evaluated_at.value < max(identity.as_of.value for identity in identities)
            or expires_at.value <= evaluated_at.value
            or expires_at.value > min(identity.valid_until.value for identity in identities)
        ):
            raise ValueError("critique requires PIT-valid source snapshots and lifetime")
        status = determine_critique_status(policy, iteration, ordered_findings)
        payload: dict[str, JsonValue] = {
            "policy": policy.to_dict(),
            "hypothesis": identities[0].to_dict(),
            "evidence_synthesis": identities[1].to_dict(),
            "experiment_request": identities[2].to_dict(),
            "evaluated_at": evaluated_at.to_dict()["recorded_at"],
            "expires_at": expires_at.to_dict()["recorded_at"],
            "iteration": iteration,
            "source_snapshots": {
                "hypothesis": hypothesis.payload(),
                "evidence_synthesis": evidence_synthesis.payload(),
                "experiment_request": experiment_request.payload(),
            },
            "diagnostics": tuple(
                item.payload() | {"content_sha256": item.content_sha256} for item in ordered_diagnostics
            ),
            "findings": tuple(item.to_dict() for item in ordered_findings),
            "status": status.value,
            "required_validations": ordered_validations,
        }
        return Critique(
            EntityId.new("critique"),
            policy,
            *identities,
            evaluated_at,
            expires_at,
            iteration,
            hypothesis,
            evidence_synthesis,
            experiment_request,
            ordered_diagnostics,
            ordered_findings,
            status,
            ordered_validations,
            canonical_sha256(payload),
        )
