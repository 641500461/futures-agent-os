"""Deterministic, bounded fan-out/fan-in for V3 specialist collaboration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from threading import Event, Lock, Timer
from time import monotonic

from futures_agent_os.shared_kernel import RecordedAt

from .catalog import AgentRoleId
from .contracts import ArtifactKind, ArtifactRef


class ParallelTaskStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class ConflictRule(StrEnum):
    OWNER_RECHECK = "OWNER_RECHECK"
    CRITIC_BLOCKS_OR_DEFER = "CRITIC_BLOCKS_OR_DEFER"
    PORTFOLIO_MAY_ONLY_REDUCE = "PORTFOLIO_MAY_ONLY_REDUCE"
    RISK_ENGINE_WINS = "RISK_ENGINE_WINS"
    PM_SYNTHESIS_OR_DEFER = "PM_SYNTHESIS_OR_DEFER"


class PMSynthesisDecision(StrEnum):
    TRADE_PLAN_DRAFT = "TRADE_PLAN_DRAFT"
    NO_TRADE = "NO_TRADE"
    DEFER = "DEFER"


@dataclass(frozen=True, slots=True)
class CollaborationBudget:
    max_tasks: int
    max_parallel_tasks: int
    max_rounds: int
    max_tokens: int
    max_tool_calls: int
    max_wall_millis: int
    max_compute_units: int

    def __post_init__(self) -> None:
        values = (
            self.max_tasks,
            self.max_parallel_tasks,
            self.max_rounds,
            self.max_tokens,
            self.max_tool_calls,
            self.max_wall_millis,
            self.max_compute_units,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("collaboration budgets must be positive integer hard limits")
        if self.max_parallel_tasks > self.max_tasks:
            raise ValueError("parallel task limit cannot exceed total task limit")


@dataclass(frozen=True, slots=True)
class SpecialistTaskLimit:
    max_tokens: int
    max_tool_calls: int
    max_wall_millis: int
    max_compute_units: int

    def __post_init__(self) -> None:
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (self.max_tokens, self.max_wall_millis, self.max_compute_units)
            )
            or isinstance(self.max_tool_calls, bool)
            or not isinstance(self.max_tool_calls, int)
            or self.max_tool_calls < 0
        ):
            raise ValueError("specialist task limits require bounded tokens, time, tools and compute")


@dataclass(frozen=True, slots=True)
class CollaborationTask:
    task_key: str
    role: AgentRoleId
    input_refs: tuple[ArtifactRef, ...]
    output_kind: ArtifactKind
    allowed_tools: tuple[str, ...]
    dependencies: tuple[str, ...]
    limits: SpecialistTaskLimit

    def __post_init__(self) -> None:
        if (
            type(self.task_key) is not str
            or not self.task_key
            or self.task_key != self.task_key.strip()
            or any(character.isspace() for character in self.task_key)
        ):
            raise ValueError("collaboration task requires a canonical task key")
        if type(self.role) is not AgentRoleId or type(self.output_kind) is not ArtifactKind:
            raise TypeError("collaboration task requires typed role and output kind")
        if (
            not isinstance(self.input_refs, tuple)
            or not self.input_refs
            or any(type(ref) is not ArtifactRef for ref in self.input_refs)
        ):
            raise ValueError("collaboration task requires immutable artifact inputs")
        if (
            not isinstance(self.allowed_tools, tuple)
            or any(type(tool) is not str or not tool.strip() for tool in self.allowed_tools)
            or len(set(self.allowed_tools)) != len(self.allowed_tools)
        ):
            raise ValueError("collaboration task requires a unique tool allowlist")
        if (
            not isinstance(self.dependencies, tuple)
            or any(type(key) is not str or not key for key in self.dependencies)
            or len(set(self.dependencies)) != len(self.dependencies)
            or self.task_key in self.dependencies
        ):
            raise ValueError("collaboration task requires unique non-self dependencies")
        if type(self.limits) is not SpecialistTaskLimit:
            raise TypeError("collaboration task requires typed hard limits")


@dataclass(frozen=True, slots=True)
class CollaborationPlan:
    tasks: tuple[CollaborationTask, ...]
    budget: CollaborationBudget
    as_of: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if (
            not isinstance(self.tasks, tuple)
            or not self.tasks
            or any(type(task) is not CollaborationTask for task in self.tasks)
        ):
            raise ValueError("collaboration plan requires typed tasks")
        if type(self.budget) is not CollaborationBudget:
            raise TypeError("collaboration plan requires a typed budget")
        if type(self.as_of) is not RecordedAt or type(self.expires_at) is not RecordedAt:
            raise TypeError("collaboration plan requires typed time bounds")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("collaboration plan expiry must follow its PIT cutoff")
        if len(self.tasks) > self.budget.max_tasks:
            raise ValueError("collaboration plan exceeds the task hard limit")
        keys = tuple(task.task_key for task in self.tasks)
        if len(set(keys)) != len(keys):
            raise ValueError("collaboration task keys must be unique")
        known = set(keys)
        if any(not set(task.dependencies).issubset(known) for task in self.tasks):
            raise ValueError("collaboration dependency references an unknown task")
        if any(
            ref.as_of != self.as_of or ref.created_at.value > self.as_of.value
            for task in self.tasks
            for ref in task.input_refs
        ):
            raise ValueError("collaboration inputs must be available at one PIT cutoff")
        if sum(task.limits.max_tokens for task in self.tasks) > self.budget.max_tokens:
            raise ValueError("collaboration token reservations exceed the hard limit")
        if sum(task.limits.max_tool_calls for task in self.tasks) > self.budget.max_tool_calls:
            raise ValueError("collaboration tool reservations exceed the hard limit")
        if sum(task.limits.max_compute_units for task in self.tasks) > self.budget.max_compute_units:
            raise ValueError("collaboration compute reservations exceed the hard limit")
        if any(task.limits.max_wall_millis > self.budget.max_wall_millis for task in self.tasks):
            raise ValueError("specialist wall-time limit exceeds the collaboration limit")
        depths: dict[str, int] = {}

        def depth(key: str, visiting: frozenset[str]) -> int:
            if key in visiting:
                raise ValueError("collaboration dependency graph contains a cycle")
            if key not in depths:
                task = next(item for item in self.tasks if item.task_key == key)
                depths[key] = 1 + max((depth(dep, visiting | {key}) for dep in task.dependencies), default=0)
            return depths[key]

        rounds = max(depth(key, frozenset()) for key in keys)
        if rounds > self.budget.max_rounds:
            raise ValueError("collaboration dependency rounds exceed the loop hard limit")


@dataclass(frozen=True, slots=True)
class StructuredClaim:
    subject: str
    value: str
    scope: str
    evidence_refs: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        if any(type(value) is not str or not value.strip() for value in (self.subject, self.value, self.scope)):
            raise ValueError("structured claim requires subject, value and scope")
        if not self.evidence_refs or any(type(ref) is not ArtifactRef for ref in self.evidence_refs):
            raise ValueError("structured claim requires immutable evidence references")


@dataclass(frozen=True, slots=True)
class SpecialistOutput:
    task_key: str
    role: AgentRoleId
    status: ParallelTaskStatus
    artifact: ArtifactRef | None
    conclusion: str
    claims: tuple[StructuredClaim, ...]
    evidence_refs: tuple[ArtifactRef, ...]
    counter_evidence_refs: tuple[ArtifactRef, ...]
    unknowns: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: Decimal
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if type(self.task_key) is not str or not self.task_key or type(self.role) is not AgentRoleId:
            raise ValueError("specialist output requires task and role identity")
        if type(self.status) is not ParallelTaskStatus or self.status not in {
            ParallelTaskStatus.COMPLETED,
            ParallelTaskStatus.PARTIAL,
            ParallelTaskStatus.DEFERRED,
            ParallelTaskStatus.FAILED,
        }:
            raise ValueError("worker output may only report a normal terminal status")
        if type(self.conclusion) is not str or not self.conclusion.strip():
            raise ValueError("specialist output requires a conclusion")
        if (
            self.status in {ParallelTaskStatus.COMPLETED, ParallelTaskStatus.PARTIAL}
            and type(self.artifact) is not ArtifactRef
        ):
            raise ValueError("completed or partial specialist output requires an artifact")
        if self.status in {ParallelTaskStatus.DEFERRED, ParallelTaskStatus.FAILED} and self.artifact is not None:
            raise ValueError("deferred or failed specialist output cannot publish an artifact")
        for refs in (self.evidence_refs, self.counter_evidence_refs):
            if not isinstance(refs, tuple) or any(type(ref) is not ArtifactRef for ref in refs):
                raise ValueError("specialist output evidence must use immutable references")
        if not isinstance(self.claims, tuple) or any(type(claim) is not StructuredClaim for claim in self.claims):
            raise ValueError("specialist output claims must be structured")
        for texts in (self.unknowns, self.warnings):
            if not isinstance(texts, tuple) or any(type(text) is not str or not text.strip() for text in texts):
                raise ValueError("specialist uncertainty must use immutable canonical text")
        if self.status in {ParallelTaskStatus.DEFERRED, ParallelTaskStatus.FAILED} and not (
            self.unknowns or self.warnings
        ):
            raise ValueError("deferred or failed output requires an unknown or warning")
        if (
            type(self.confidence) is not Decimal
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("specialist confidence must be a finite Decimal in [0, 1]")
        if type(self.expires_at) is not RecordedAt:
            raise TypeError("specialist output requires a typed expiry")


@dataclass(frozen=True, slots=True)
class TaskUsage:
    tokens: int
    tool_calls: int
    compute_units: int
    wall_millis: int


class BudgetExceeded(RuntimeError):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TimeoutError("specialist task cancelled or timed out")


class TaskBudgetMeter:
    """Runtime meter integrated by model and Tool Gateway adapters."""

    def __init__(self, limits: SpecialistTaskLimit) -> None:
        self._limits = limits
        self._tokens = 0
        self._tools = 0
        self._compute = 0
        self._lock = Lock()

    def consume(self, *, tokens: int = 0, tool_calls: int = 0, compute_units: int = 0) -> None:
        values = (tokens, tool_calls, compute_units)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("budget consumption must be non-negative integers")
        with self._lock:
            proposed = (self._tokens + tokens, self._tools + tool_calls, self._compute + compute_units)
            ceilings = (self._limits.max_tokens, self._limits.max_tool_calls, self._limits.max_compute_units)
            if any(actual > ceiling for actual, ceiling in zip(proposed, ceilings, strict=True)):
                raise BudgetExceeded("specialist token, tool, or compute hard limit exceeded")
            self._tokens, self._tools, self._compute = proposed

    def usage(self, wall_millis: int) -> TaskUsage:
        return TaskUsage(self._tokens, self._tools, self._compute, wall_millis)


@dataclass(frozen=True, slots=True)
class TaskExecution:
    task: CollaborationTask
    status: ParallelTaskStatus
    output: SpecialistOutput | None
    usage: TaskUsage
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConflictPosition:
    role: AgentRoleId
    value: str
    scope: str
    evidence_refs: tuple[ArtifactRef, ...]
    as_of: RecordedAt
    confidence: Decimal
    unknowns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    subject: str
    positions: tuple[ConflictPosition, ...]
    rule: ConflictRule


@dataclass(frozen=True, slots=True)
class FanInResult:
    executions: tuple[TaskExecution, ...]
    conflicts: tuple[ConflictRecord, ...]
    rounds: int
    total_usage: TaskUsage

    @property
    def requires_pm_synthesis(self) -> bool:
        return bool(self.conflicts) or any(
            execution.status is not ParallelTaskStatus.COMPLETED for execution in self.executions
        )


@dataclass(frozen=True, slots=True)
class PMSynthesis:
    decision: PMSynthesisDecision
    rationale: str
    evidence_refs: tuple[ArtifactRef, ...]
    conflicts: tuple[ConflictRecord, ...]


class AutonomousQuantPM:
    """Presents all conflicts and makes one bounded synthesis; it never votes."""

    def synthesize(
        self,
        fan_in: FanInResult,
        *,
        decision: PMSynthesisDecision,
        rationale: str,
        evidence_refs: tuple[ArtifactRef, ...],
    ) -> PMSynthesis:
        if type(fan_in) is not FanInResult or type(decision) is not PMSynthesisDecision:
            raise TypeError("PM synthesis requires typed fan-in and decision")
        if type(rationale) is not str or not rationale.strip() or not evidence_refs:
            raise ValueError("PM synthesis requires rationale and evidence")
        if decision is PMSynthesisDecision.TRADE_PLAN_DRAFT and fan_in.requires_pm_synthesis:
            raise ValueError("unresolved conflicts or incomplete specialists require NO_TRADE or DEFER")
        return PMSynthesis(decision, rationale, evidence_refs, fan_in.conflicts)


Worker = Callable[[CollaborationTask, CancellationToken, TaskBudgetMeter], SpecialistOutput]


class StructuredParallelOrchestrator:
    def run(self, plan: CollaborationPlan, workers: Mapping[str, Worker]) -> FanInResult:
        if type(plan) is not CollaborationPlan:
            raise TypeError("parallel orchestration requires a typed collaboration plan")
        if set(workers) != {task.task_key for task in plan.tasks}:
            raise ValueError("workers must exactly match collaboration tasks")
        started = monotonic()
        deadline = started + plan.budget.max_wall_millis / 1000
        executions: dict[str, TaskExecution] = {}
        rounds = 0
        pending = {task.task_key: task for task in plan.tasks}
        while pending:
            if rounds >= plan.budget.max_rounds:
                raise BudgetExceeded("collaboration loop hard limit exceeded")
            rounds += 1
            blocked = [
                task
                for task in pending.values()
                if task.dependencies
                and all(dependency in executions for dependency in task.dependencies)
                and any(
                    executions[dependency].status not in {ParallelTaskStatus.COMPLETED, ParallelTaskStatus.PARTIAL}
                    for dependency in task.dependencies
                )
            ]
            for task in blocked:
                executions[task.task_key] = TaskExecution(
                    task,
                    ParallelTaskStatus.SKIPPED,
                    None,
                    TaskUsage(0, 0, 0, 0),
                    "dependency did not produce a usable artifact",
                )
                pending.pop(task.task_key)
            ready = [task for task in pending.values() if all(dep in executions for dep in task.dependencies)]
            if not ready:
                if pending:
                    raise RuntimeError("collaboration graph made no progress")
                break
            batch_results = self._run_batch(plan, tuple(ready), workers, deadline)
            executions.update((execution.task.task_key, execution) for execution in batch_results)
            for task in ready:
                pending.pop(task.task_key)
        ordered = tuple(executions[task.task_key] for task in plan.tasks)
        # Charge only the bounded orchestration window. Executor cleanup after
        # cancellation is control-plane overhead, not additional worker budget.
        elapsed = min(plan.budget.max_wall_millis, max(0, int((monotonic() - started) * 1000)))
        total = TaskUsage(
            sum(item.usage.tokens for item in ordered),
            sum(item.usage.tool_calls for item in ordered),
            sum(item.usage.compute_units for item in ordered),
            elapsed,
        )
        if (
            total.tokens > plan.budget.max_tokens
            or total.tool_calls > plan.budget.max_tool_calls
            or total.compute_units > plan.budget.max_compute_units
            or total.wall_millis > plan.budget.max_wall_millis
        ):
            raise BudgetExceeded("collaboration aggregate hard limit exceeded")
        return FanInResult(ordered, self._conflicts(plan, ordered), rounds, total)

    def _run_batch(
        self,
        plan: CollaborationPlan,
        tasks: tuple[CollaborationTask, ...],
        workers: Mapping[str, Worker],
        deadline: float,
    ) -> tuple[TaskExecution, ...]:
        executor = ThreadPoolExecutor(max_workers=min(plan.budget.max_parallel_tasks, len(tasks)))
        metadata: dict[
            Future[SpecialistOutput], tuple[CollaborationTask, CancellationToken, TaskBudgetMeter, float, Timer]
        ] = {}
        for task in tasks:
            token = CancellationToken()
            meter = TaskBudgetMeter(task.limits)
            task_started = monotonic()
            timer = Timer(task.limits.max_wall_millis / 1000, token.cancel)
            timer.daemon = True
            timer.start()
            future = executor.submit(workers[task.task_key], task, token, meter)
            metadata[future] = (task, token, meter, task_started, timer)
        remaining = max(0.0, deadline - monotonic())
        done, not_done = wait(metadata, timeout=remaining)
        results: dict[str, TaskExecution] = {}
        for future in done:
            task, token, meter, task_started, timer = metadata[future]
            timer.cancel()
            elapsed = max(0, int((monotonic() - task_started) * 1000))
            output: SpecialistOutput | None
            try:
                output = future.result()
                self._validate_output(plan, task, output)
                if token.cancelled or elapsed > task.limits.max_wall_millis:
                    status, output, reason = ParallelTaskStatus.TIMED_OUT, None, "specialist wall-time limit exceeded"
                else:
                    status, reason = output.status, None
            except BudgetExceeded as error:
                status, output, reason = ParallelTaskStatus.BUDGET_EXHAUSTED, None, str(error)
            except TimeoutError as error:
                status, output, reason = ParallelTaskStatus.TIMED_OUT, None, str(error)
            except Exception as error:
                status, output, reason = ParallelTaskStatus.FAILED, None, f"{type(error).__name__}:{error}"
            results[task.task_key] = TaskExecution(task, status, output, meter.usage(elapsed), reason)
        for future in not_done:
            task, token, meter, task_started, timer = metadata[future]
            timer.cancel()
            token.cancel()
            future.cancel()
            elapsed = max(0, int((monotonic() - task_started) * 1000))
            results[task.task_key] = TaskExecution(
                task,
                ParallelTaskStatus.TIMED_OUT,
                None,
                meter.usage(elapsed),
                "collaboration wall-time limit exceeded",
            )
        executor.shutdown(wait=False, cancel_futures=True)
        return tuple(results[task.task_key] for task in tasks)

    @staticmethod
    def _validate_output(plan: CollaborationPlan, task: CollaborationTask, output: SpecialistOutput) -> None:
        if type(output) is not SpecialistOutput or output.task_key != task.task_key or output.role is not task.role:
            raise ValueError("specialist output identity does not match its deterministic task")
        if output.expires_at.value <= plan.as_of.value or output.expires_at.value > plan.expires_at.value:
            raise ValueError("specialist output expiry is outside the collaboration window")
        if output.artifact is not None and (
            output.artifact.artifact_kind is not task.output_kind
            or output.artifact.as_of != plan.as_of
            or output.artifact.created_at.value > plan.as_of.value
        ):
            raise ValueError("specialist output artifact kind or PIT lineage is invalid")
        evidence = (
            output.evidence_refs
            + output.counter_evidence_refs
            + tuple(ref for claim in output.claims for ref in claim.evidence_refs)
        )
        if any(ref.as_of != plan.as_of or ref.created_at.value > plan.as_of.value for ref in evidence):
            raise ValueError("specialist evidence is outside the collaboration PIT cutoff")

    @staticmethod
    def _conflicts(plan: CollaborationPlan, executions: tuple[TaskExecution, ...]) -> tuple[ConflictRecord, ...]:
        grouped: dict[str, list[tuple[SpecialistOutput, StructuredClaim]]] = defaultdict(list)
        for execution in executions:
            if execution.output is not None:
                for claim in execution.output.claims:
                    grouped[claim.subject].append((execution.output, claim))
        records: list[ConflictRecord] = []
        for subject in sorted(grouped):
            claims = grouped[subject]
            if len({claim.value for _, claim in claims}) < 2:
                continue
            roles = {output.role for output, _ in claims}
            if AgentRoleId.PRE_TRADE_CRITIC in roles:
                rule = ConflictRule.CRITIC_BLOCKS_OR_DEFER
            elif {AgentRoleId.PORTFOLIO, AgentRoleId.STRATEGY}.issubset(roles):
                rule = ConflictRule.PORTFOLIO_MAY_ONLY_REDUCE
            elif AgentRoleId.RISK_ANALYST in roles and subject.startswith("risk_engine:"):
                rule = ConflictRule.RISK_ENGINE_WINS
            elif subject.startswith("fact:"):
                rule = ConflictRule.OWNER_RECHECK
            else:
                rule = ConflictRule.PM_SYNTHESIS_OR_DEFER
            order = {task.task_key: index for index, task in enumerate(plan.tasks)}
            positions = tuple(
                ConflictPosition(
                    output.role,
                    claim.value,
                    claim.scope,
                    claim.evidence_refs,
                    plan.as_of,
                    output.confidence,
                    output.unknowns,
                )
                for output, claim in sorted(claims, key=lambda pair: order[pair[0].task_key])
            )
            records.append(ConflictRecord(subject, positions, rule))
        return tuple(records)


# Compatibility wrapper retained for the early V3 gateway smoke contract. New
# collaboration code must use StructuredParallelOrchestrator and typed tasks.
class ParallelFanout:
    def __init__(self, max_workers: int = 3, max_tasks: int | None = None, timeout_seconds: float | None = None):
        if max_workers < 1 or (max_tasks is not None and max_tasks < 1):
            raise ValueError("max_workers must be positive")
        self.max_workers = max_workers
        self.max_tasks = max_tasks or max_workers
        self.timeout_seconds = timeout_seconds

    def run(self, tasks: dict[str, Callable[[], object]]) -> dict[str, object]:
        if not tasks:
            return {}
        if len(tasks) > self.max_tasks:
            raise ValueError("fan-out task budget exceeded")
        executor = ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks)))
        futures = {key: executor.submit(worker) for key, worker in tasks.items()}
        try:
            return {key: futures[key].result(timeout=self.timeout_seconds) for key in tasks}
        except TimeoutError as error:
            for future in futures.values():
                future.cancel()
            raise TimeoutError("fan-out timeout") from error
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def conflicts(
        results: dict[str, object], fields: tuple[str, ...] = ("decision", "verdict", "target_exposure")
    ) -> tuple[str, ...]:
        found = []
        for field in fields:
            values = {getattr(value, field) for value in results.values() if hasattr(value, field)}
            if len(values) > 1:
                found.append(field)
        return tuple(found)
