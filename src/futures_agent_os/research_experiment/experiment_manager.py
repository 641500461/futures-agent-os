"""Small, deterministic Experiment Manager for the V1-011 research loop.

The manager owns only research registration and job lifecycle facts.  It does
not execute a strategy, create an order, or qualify/promote a strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


class ResearchJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


_TERMINAL = frozenset(
    {
        ResearchJobStatus.SUCCEEDED,
        ResearchJobStatus.FAILED,
        ResearchJobStatus.CANCELLED,
        ResearchJobStatus.TIMED_OUT,
    }
)


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    """Finite compute/time budget; it is never an account risk budget."""

    max_tokens: int
    max_tool_calls: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in (self.max_tokens, self.max_tool_calls, self.timeout_seconds)):
            raise ValueError("research budget limits must be positive integers")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_tokens": self.max_tokens,
            "max_tool_calls": self.max_tool_calls,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    """Immutable, pre-registered research experiment definition."""

    experiment_id: EntityId
    version: int
    schema_version: SchemaVersion
    request_ref: EntityId
    original_conversation_id: EntityId
    as_of: RecordedAt
    expires_at: RecordedAt
    budget: ResearchBudget
    priority: int = 0

    def __post_init__(self) -> None:
        if self.experiment_id.namespace != "experiment" or self.request_ref.namespace != "experiment_request":
            raise ValueError("experiment plan has invalid research identities")
        if self.original_conversation_id.namespace != "conversation":
            raise ValueError("experiment plan requires its originating conversation")
        if type(self.version) is not int or self.version < 1 or type(self.priority) is not int or self.priority < 0:
            raise ValueError("experiment version and priority must be non-negative integers")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("experiment plan expiry must follow as_of")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "experiment_id": str(self.experiment_id),
            "version": self.version,
            "schema_version": str(self.schema_version),
            "request_ref": str(self.request_ref),
            "original_conversation_id": str(self.original_conversation_id),
            "as_of": self.as_of.to_dict()["recorded_at"],
            "expires_at": self.expires_at.to_dict()["recorded_at"],
            "budget": self.budget.to_dict(),
            "priority": self.priority,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        return self.payload()

    @property
    def content_sha256(self) -> str:
        """Stable identity for the pre-registered plan payload."""
        return canonical_sha256(self.payload())


@dataclass(frozen=True, slots=True)
class ResearchJob:
    """A durable state-machine projection for one execution attempt."""

    job_id: EntityId
    experiment: ExperimentPlan
    status: ResearchJobStatus
    created_at: RecordedAt
    updated_at: RecordedAt
    attempt: int = 1
    result_ref: EntityId | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    consumed_tokens: int = 0
    consumed_tool_calls: int = 0

    def __post_init__(self) -> None:
        if self.job_id.namespace != "research_job":
            raise ValueError("research job requires a research_job id")
        if self.updated_at.value < self.created_at.value or type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("research job timestamps/attempt are invalid")
        if any(type(v) is not int or v < 0 for v in (self.consumed_tokens, self.consumed_tool_calls)):
            raise ValueError("research usage counters must be non-negative integers")
        if (
            self.consumed_tokens > self.experiment.budget.max_tokens
            or self.consumed_tool_calls > self.experiment.budget.max_tool_calls
        ):
            raise ValueError("research job usage exceeds its pre-registered budget")
        if self.status is ResearchJobStatus.SUCCEEDED and self.result_ref is None:
            raise ValueError("successful research job requires an immutable result reference")
        if self.status is ResearchJobStatus.FAILED and not self.failure_code:
            raise ValueError("failed research job requires a failure code")
        if self.status in _TERMINAL and self.status is not ResearchJobStatus.SUCCEEDED and self.result_ref is not None:
            raise ValueError("non-success terminal job cannot publish a result")

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "job_id": str(self.job_id),
            "experiment": self.experiment.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at.to_dict()["recorded_at"],
            "updated_at": self.updated_at.to_dict()["recorded_at"],
            "attempt": self.attempt,
            "result_ref": str(self.result_ref) if self.result_ref else None,
            "failure_code": self.failure_code,
            "failure_detail": self.failure_detail,
            "consumed_tokens": self.consumed_tokens,
            "consumed_tool_calls": self.consumed_tool_calls,
        }


class ExperimentManager:
    """In-process reference manager; persistence adapters may project these facts."""

    def __init__(self) -> None:
        self._jobs: dict[EntityId, ResearchJob] = {}
        self._by_experiment: dict[EntityId, EntityId] = {}

    def register(self, plan: ExperimentPlan) -> ResearchJob:
        if plan.experiment_id in self._by_experiment:
            raise ValueError("experiment is already registered")
        now = plan.as_of
        job = ResearchJob(EntityId.new("research_job"), plan, ResearchJobStatus.QUEUED, now, now)
        self._jobs[job.job_id] = job
        self._by_experiment[plan.experiment_id] = job.job_id
        return job

    def get(self, job_id: EntityId) -> ResearchJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown research job: {job_id}") from exc

    def start(self, job_id: EntityId, now: RecordedAt) -> ResearchJob:
        job = self.get(job_id)
        if job.status is not ResearchJobStatus.QUEUED:
            raise ValueError("only queued research jobs can start")
        if now.value >= job.experiment.expires_at.value:
            return self._transition(job, ResearchJobStatus.TIMED_OUT, now, failure_code="DEADLINE_EXCEEDED")
        return self._transition(job, ResearchJobStatus.RUNNING, now)

    def checkpoint(
        self, job_id: EntityId, now: RecordedAt, *, tokens: int, tool_calls: int, partial: bool = False
    ) -> ResearchJob:
        job = self.get(job_id)
        if job.status is not ResearchJobStatus.RUNNING:
            raise ValueError("only running research jobs accept checkpoints")
        if type(tokens) is not int or type(tool_calls) is not int or tokens < 0 or tool_calls < 0:
            raise ValueError("checkpoint usage must be non-negative integers")
        next_tokens = job.consumed_tokens + tokens
        next_calls = job.consumed_tool_calls + tool_calls
        if next_tokens > job.experiment.budget.max_tokens or next_calls > job.experiment.budget.max_tool_calls:
            return self._transition(job, ResearchJobStatus.TIMED_OUT, now, failure_code="BUDGET_EXCEEDED")
        status = ResearchJobStatus.PARTIAL if partial else ResearchJobStatus.RUNNING
        return replace(job, status=status, updated_at=now, consumed_tokens=next_tokens, consumed_tool_calls=next_calls)

    def complete(self, job_id: EntityId, now: RecordedAt, result_ref: EntityId) -> ResearchJob:
        job = self.get(job_id)
        if job.status not in {ResearchJobStatus.RUNNING, ResearchJobStatus.PARTIAL}:
            raise ValueError("only running or partial research jobs can complete")
        if result_ref.namespace != "research_result":
            raise ValueError("research results must use the research_result namespace")
        if now.value >= job.experiment.expires_at.value:
            return self._transition(job, ResearchJobStatus.TIMED_OUT, now, failure_code="DEADLINE_EXCEEDED")
        return self._transition(job, ResearchJobStatus.SUCCEEDED, now, result_ref=result_ref)

    def fail(self, job_id: EntityId, now: RecordedAt, code: str, detail: str = "") -> ResearchJob:
        if not code or code != code.strip():
            raise ValueError("failure code is required")
        job = self.get(job_id)
        if job.is_terminal:
            raise ValueError("terminal research jobs cannot transition")
        return self._transition(job, ResearchJobStatus.FAILED, now, failure_code=code, failure_detail=detail or None)

    def cancel(self, job_id: EntityId, now: RecordedAt, reason: str = "cancelled_by_request") -> ResearchJob:
        job = self.get(job_id)
        if job.is_terminal:
            raise ValueError("terminal research jobs cannot transition")
        return self._transition(job, ResearchJobStatus.CANCELLED, now, failure_code=reason)

    def recover(self, job_id: EntityId, now: RecordedAt) -> ResearchJob:
        """Requeue an interrupted RUNNING/PARTIAL attempt without changing its plan."""
        job = self.get(job_id)
        if job.status not in {ResearchJobStatus.RUNNING, ResearchJobStatus.PARTIAL}:
            raise ValueError("only interrupted running jobs can recover")
        if now.value >= job.experiment.expires_at.value:
            return self._transition(job, ResearchJobStatus.TIMED_OUT, now, failure_code="DEADLINE_EXCEEDED")
        return replace(job, status=ResearchJobStatus.QUEUED, updated_at=now, attempt=job.attempt + 1)

    def result_for_conversation(self, conversation_id: EntityId) -> tuple[ResearchJob, ...]:
        if conversation_id.namespace != "conversation":
            raise ValueError("conversation id has invalid namespace")
        return tuple(job for job in self._jobs.values() if job.experiment.original_conversation_id == conversation_id)

    def _transition(self, job: ResearchJob, status: ResearchJobStatus, now: RecordedAt, **changes: Any) -> ResearchJob:
        updated = replace(job, status=status, updated_at=now, **changes)
        self._jobs[job.job_id] = updated
        return updated


__all__ = ["ExperimentManager", "ExperimentPlan", "ResearchBudget", "ResearchJob", "ResearchJobStatus"]
