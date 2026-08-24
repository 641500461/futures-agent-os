"""Versioned, immutable contracts for bounded agent collaboration.

This module deliberately defines orchestration data only.  It does not invoke a
model, authorize a tool, or perform a trading action.  Those responsibilities
remain with later registry, gateway, and deterministic-domain work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class TriggerSource(StrEnum):
    USER = "USER"
    SCHEDULE = "SCHEDULE"
    MARKET = "MARKET"
    ACCOUNT = "ACCOUNT"
    SYSTEM = "SYSTEM"


class FailureDisposition(StrEnum):
    DEFER = "DEFER"
    FAIL_CLOSED = "FAIL_CLOSED"
    FALLBACK_READ_ONLY = "FALLBACK_READ_ONLY"
    KEEP_DRAFT = "KEEP_DRAFT"
    KEEP_PENDING_REVIEW = "KEEP_PENDING_REVIEW"
    KEEP_EXISTING_STATE = "KEEP_EXISTING_STATE"
    QUARANTINE_CANDIDATE = "QUARANTINE_CANDIDATE"


class ResultStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"


class ArtifactKind(StrEnum):
    MARKET_SNAPSHOT = "market_snapshot"
    FEATURE_OBSERVATION = "feature_observation"
    REGIME_ASSESSMENT = "regime_assessment"
    RESEARCH_BRIEF = "research_brief"
    MARKET_STATE_ASSESSMENT = "market_state_assessment"
    HYPOTHESIS = "hypothesis"
    RESEARCH_PLAN = "research_plan"
    EVIDENCE_SYNTHESIS = "evidence_synthesis"
    STRATEGY_CANDIDATE = "strategy_candidate"
    TRADE_PLAN_DRAFT = "trade_plan_draft"
    CRITIQUE = "critique"
    PORTFOLIO_PROPOSAL = "portfolio_proposal"
    RISK_ASSESSMENT = "risk_assessment"
    EXECUTION_RECOMMENDATION = "execution_recommendation"
    TRADE_REVIEW = "trade_review"
    REFLECTION = "reflection"
    EXPERIMENT_PLAN = "experiment_plan"
    LESSON_CANDIDATE = "lesson_candidate"
    CHANGE_PROPOSAL = "change_proposal"
    DECISION_DIGEST = "decision_digest"
    ESCALATION_REQUEST = "escalation_request"


@dataclass(frozen=True, slots=True)
class AgentBudget:
    """Finite model and tool budget; it is never an account risk budget."""

    max_turns: int
    max_tool_calls: int
    max_tokens: int
    timeout_seconds: int
    max_parallel_tasks: int = 1

    def __post_init__(self) -> None:
        values = (self.max_turns, self.max_tool_calls, self.max_tokens, self.timeout_seconds, self.max_parallel_tasks)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("agent budget limits must be positive integers")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Content-addressed immutable artifact reference, never a mutable ORM object."""

    artifact_id: EntityId
    artifact_kind: ArtifactKind
    schema_version: SchemaVersion
    content_hash: str
    created_at: RecordedAt
    as_of: RecordedAt

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.content_hash):
            raise ValueError("artifact content_hash must be a canonical sha256 digest")
        if self.as_of.value > self.created_at.value:
            raise ValueError("artifact as_of cannot be after created_at")


@dataclass(frozen=True, slots=True)
class ArtifactClaim:
    """A compact structured claim with explicit evidence rather than free chat text."""

    claim_kind: str
    statement: str
    evidence_refs: tuple[ArtifactRef, ...]
    is_inference: bool

    def __post_init__(self) -> None:
        if not self.claim_kind or not self.statement:
            raise ValueError("artifact claims require a kind and statement")
        if not self.evidence_refs:
            raise ValueError("artifact claims require immutable evidence references")


@dataclass(frozen=True, slots=True)
class StructuredArtifact:
    """Validated agent output; a proposal or analysis, never domain truth or authority."""

    ref: ArtifactRef
    producer_role_id: str
    producer_run_id: EntityId
    source_refs: tuple[ArtifactRef, ...]
    claims: tuple[ArtifactClaim, ...]
    warnings: tuple[str, ...]
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if not self.producer_role_id:
            raise ValueError("structured artifact requires a producer role")
        if self.expires_at.value <= self.ref.created_at.value:
            raise ValueError("structured artifact expiry must follow creation")
        if not self.source_refs:
            raise ValueError("structured artifact requires source references")


@dataclass(frozen=True, slots=True)
class AgentTaskEnvelope:
    """A bounded task emitted and routed by the deterministic orchestrator."""

    task_id: EntityId
    session_id: EntityId
    correlation_id: EntityId
    trace: TraceContext
    assigned_role_id: str
    catalog_version: SchemaVersion
    objective: str
    completion_definition: str
    trigger_sources: tuple[TriggerSource, ...]
    input_artifacts: tuple[ArtifactRef, ...]
    policy_refs: tuple[ArtifactRef, ...]
    allowed_tools: tuple[str, ...]
    budget: AgentBudget
    required_outputs: tuple[ArtifactKind, ...]
    as_of: RecordedAt
    expires_at: RecordedAt
    may_delegate_research: bool = False
    parent_task_id: EntityId | None = None

    def __post_init__(self) -> None:
        if self.trace.correlation_id != self.correlation_id:
            raise ValueError("task envelope trace must carry the task correlation id")
        if not self.assigned_role_id or not self.objective or not self.completion_definition:
            raise ValueError("task envelope requires role, objective, and completion definition")
        if not self.trigger_sources or not self.input_artifacts or not self.required_outputs:
            raise ValueError("task envelope requires triggers, input artifacts, and output schemas")
        if len(set(self.trigger_sources)) != len(self.trigger_sources):
            raise ValueError("task envelope trigger sources must be unique")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("task envelope allowed tools must be unique")
        if len(set(self.required_outputs)) != len(self.required_outputs):
            raise ValueError("task envelope required outputs must be unique")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("task envelope expiry must follow as_of")


@dataclass(frozen=True, slots=True)
class AgentHandoff:
    """A one-way artifact handoff, routed by the orchestrator rather than peer chat."""

    handoff_id: EntityId
    from_task_id: EntityId
    to_task_id: EntityId
    from_role_id: str
    to_role_id: str
    artifacts: tuple[ArtifactRef, ...]
    unresolved_questions: tuple[str, ...]
    authorization_boundary: str
    created_at: RecordedAt

    def __post_init__(self) -> None:
        if self.from_task_id == self.to_task_id:
            raise ValueError("a handoff cannot target its own task")
        if not self.from_role_id or not self.to_role_id or not self.artifacts:
            raise ValueError("handoff requires source, target, and immutable artifacts")
        if not self.authorization_boundary:
            raise ValueError("handoff must state its authorization boundary")


@dataclass(frozen=True, slots=True)
class SpecialistResult:
    """Terminal specialist outcome, preserving evidence and uncertainty for fan-in."""

    task_id: EntityId
    role_id: str
    status: ResultStatus
    artifacts: tuple[ArtifactRef, ...]
    counter_evidence_refs: tuple[ArtifactRef, ...]
    unknowns: tuple[str, ...]
    warnings: tuple[str, ...]
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if not self.role_id:
            raise ValueError("specialist result requires a role")
        if self.status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL} and not self.artifacts:
            raise ValueError("completed or partial specialist results require an output artifact")
        if self.status in {ResultStatus.DEFERRED, ResultStatus.FAILED} and not (self.unknowns or self.warnings):
            raise ValueError("deferred or failed specialist results require an unknown or warning")
