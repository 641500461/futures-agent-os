"""V4-005 scalable research orchestration; never writes trading truth."""

from __future__ import annotations
from dataclasses import dataclass, replace
from enum import StrEnum
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from .experiment_manager import ExperimentPlan, ResearchBudget, ResearchJob, ResearchJobStatus


class BatchStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ScaledExperimentPlan:
    batch_id: EntityId
    version: int
    plans: tuple[ExperimentPlan, ...]
    budget: ResearchBudget
    priority: int = 0

    def __post_init__(self) -> None:
        if self.batch_id.namespace != "experiment_batch" or not self.plans:
            raise ValueError("batch requires identity and plans")
        if type(self.version) is not int or self.version < 1 or type(self.priority) is not int or self.priority < 0:
            raise ValueError("invalid batch version/priority")
        if len({p.experiment_id for p in self.plans}) != len(self.plans):
            raise ValueError("duplicate experiment in batch")
        if (
            sum(p.budget.max_tokens for p in self.plans) > self.budget.max_tokens
            or sum(p.budget.max_tool_calls for p in self.plans) > self.budget.max_tool_calls
        ):
            raise ValueError("child budgets exceed batch budget")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "batch_id": str(self.batch_id),
                "version": self.version,
                "plans": tuple(p.content_sha256 for p in self.plans),
                "budget": self.budget.to_dict(),
                "priority": self.priority,
            }
        )


@dataclass(frozen=True, slots=True)
class BatchRun:
    batch: ScaledExperimentPlan
    status: BatchStatus
    jobs: tuple[ResearchJob, ...]
    created_at: RecordedAt
    updated_at: RecordedAt
    consumed_tokens: int = 0
    consumed_tool_calls: int = 0
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if len(self.jobs) != len(self.batch.plans) or any(j.experiment not in self.batch.plans for j in self.jobs):
            raise ValueError("batch jobs must cover exact child plans")
        if (
            self.consumed_tokens > self.batch.budget.max_tokens
            or self.consumed_tool_calls > self.batch.budget.max_tool_calls
        ):
            raise ValueError("batch usage exceeds budget")

    @property
    def complete(self) -> bool:
        return self.status is BatchStatus.SUCCEEDED and all(j.status is ResearchJobStatus.SUCCEEDED for j in self.jobs)

    @property
    def evidence_refs(self) -> tuple[EntityId, ...]:
        return tuple(j.result_ref for j in self.jobs if j.result_ref is not None)


class ScaledExperimentManager:
    """Deterministic parent/child lifecycle with priority ordering and fail-closed aggregation."""

    def __init__(self) -> None:
        self._batches: dict[EntityId, BatchRun] = {}

    def register(self, plan: ScaledExperimentPlan) -> BatchRun:
        if plan.batch_id in self._batches:
            raise ValueError("batch already registered")
        now = plan.plans[0].as_of
        jobs = tuple(
            ResearchJob(EntityId.new("research_job"), child, ResearchJobStatus.QUEUED, now, now) for child in plan.plans
        )
        run = BatchRun(plan, BatchStatus.QUEUED, jobs, now, now)
        self._batches[plan.batch_id] = run
        return run

    def get(self, batch_id: EntityId) -> BatchRun:
        return self._batches[batch_id]

    def schedule(self, batch_id: EntityId, now: RecordedAt) -> BatchRun:
        run = self.get(batch_id)
        if run.status is not BatchStatus.QUEUED:
            raise ValueError("only queued batch can schedule")
        jobs = tuple(sorted(run.jobs, key=lambda j: (-j.experiment.priority, str(j.job_id))))
        return self._save(replace(run, status=BatchStatus.RUNNING, jobs=jobs, updated_at=now))

    def checkpoint(self, batch_id: EntityId, now: RecordedAt, *, tokens: int, tool_calls: int) -> BatchRun:
        run = self.get(batch_id)
        if run.status is not BatchStatus.RUNNING:
            raise ValueError("batch is not running")
        if tokens < 0 or tool_calls < 0:
            raise ValueError("usage must be non-negative")
        nt, nc = run.consumed_tokens + tokens, run.consumed_tool_calls + tool_calls
        if nt > run.batch.budget.max_tokens or nc > run.batch.budget.max_tool_calls:
            return self._save(
                replace(
                    run,
                    status=BatchStatus.FAILED,
                    updated_at=now,
                    failure_detail="BATCH_BUDGET_EXCEEDED",
                    consumed_tokens=nt if nt <= run.batch.budget.max_tokens else run.batch.budget.max_tokens,
                    consumed_tool_calls=nc
                    if nc <= run.batch.budget.max_tool_calls
                    else run.batch.budget.max_tool_calls,
                )
            )
        return self._save(replace(run, updated_at=now, consumed_tokens=nt, consumed_tool_calls=nc))

    def cancel(self, batch_id: EntityId, now: RecordedAt, reason: str = "cancelled_by_request") -> BatchRun:
        run = self.get(batch_id)
        if run.status in {BatchStatus.SUCCEEDED, BatchStatus.FAILED, BatchStatus.CANCELLED}:
            raise ValueError("terminal batch cannot transition")
        jobs = tuple(
            replace(j, status=ResearchJobStatus.CANCELLED, updated_at=now, failure_code=reason)
            for j in run.jobs
            if not j.is_terminal
        )
        return self._save(replace(run, status=BatchStatus.CANCELLED, jobs=jobs, updated_at=now, failure_detail=reason))

    def finalize(self, batch_id: EntityId, now: RecordedAt) -> BatchRun:
        run = self.get(batch_id)
        if run.status is not BatchStatus.RUNNING:
            raise ValueError("batch is not running")
        if any(
            j.status in {ResearchJobStatus.RUNNING, ResearchJobStatus.QUEUED, ResearchJobStatus.PARTIAL}
            for j in run.jobs
        ):
            raise ValueError("cannot finalize incomplete children")
        status = (
            BatchStatus.SUCCEEDED
            if all(j.status is ResearchJobStatus.SUCCEEDED for j in run.jobs)
            else BatchStatus.FAILED
        )
        return self._save(replace(run, status=status, updated_at=now))

    def recover(self, batch_id: EntityId, now: RecordedAt) -> BatchRun:
        run = self.get(batch_id)
        if run.status is not BatchStatus.RUNNING:
            raise ValueError("only running batch can recover")
        jobs = tuple(
            replace(j, status=ResearchJobStatus.QUEUED, updated_at=now, attempt=j.attempt + 1)
            if j.status in {ResearchJobStatus.RUNNING, ResearchJobStatus.PARTIAL}
            else j
            for j in run.jobs
        )
        return self._save(replace(run, status=BatchStatus.QUEUED, jobs=jobs, updated_at=now))

    def _save(self, run: BatchRun) -> BatchRun:
        self._batches[run.batch.batch_id] = run
        return run


__all__ = ["BatchRun", "BatchStatus", "ScaledExperimentManager", "ScaledExperimentPlan"]
