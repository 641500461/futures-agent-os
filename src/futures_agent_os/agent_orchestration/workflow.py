"""V1-008 deterministic, read-only research workflow orchestration.

The Main adapter only validates a typed delegation graph.  Durable state is
owned by the orchestrator/store; this module has no trade, authorization, or
accounting imports and never creates domain trading facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from enum import StrEnum
from threading import RLock
from uuid import UUID

from sqlalchemy import Connection, text

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue
from futures_agent_os.research_experiment.critique import Critique, CritiqueRevisionStore, CritiqueStatus

from .catalog import CATALOG_VERSION, AgentRoleId, definition_for
from .contracts import AgentBudget, ArtifactKind, ArtifactRef, StructuredArtifact, TriggerSource


class CycleStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class EpisodeStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class WorkflowTaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED = "SKIPPED"


_TERMINAL_TASKS = frozenset(
    {
        WorkflowTaskStatus.COMPLETED,
        WorkflowTaskStatus.DEFERRED,
        WorkflowTaskStatus.FAILED,
        WorkflowTaskStatus.CANCELLED,
        WorkflowTaskStatus.TIMED_OUT,
        WorkflowTaskStatus.SKIPPED,
    }
)
_TERMINAL_EPISODES = frozenset(
    {EpisodeStatus.COMPLETED, EpisodeStatus.DEFERRED, EpisodeStatus.CANCELLED, EpisodeStatus.TIMED_OUT}
)
_READ_ONLY_ROLES = frozenset(
    {AgentRoleId.MARKET_REGIME.value, AgentRoleId.RESEARCH.value, AgentRoleId.PRE_TRADE_CRITIC.value}
)
_CRITIC_INPUT_KINDS = (
    ArtifactKind.HYPOTHESIS,
    ArtifactKind.EVIDENCE_SYNTHESIS,
    ArtifactKind.EXPERIMENT_REQUEST,
)


def _validate_role_contract(
    role_id: str,
    direct_inputs: tuple[ArtifactRef, ...],
    required_outputs: tuple[ArtifactKind, ...],
    dependency_output_kinds: tuple[ArtifactKind, ...] = (),
) -> None:
    """Apply the current catalog to both direct and deterministic fan-in inputs."""

    definition = definition_for(role_id, CATALOG_VERSION)
    if role_id not in _READ_ONLY_ROLES:
        raise ValueError("future role is not enabled in V1 observe workflow")
    effective_kinds = tuple(ref.artifact_kind for ref in direct_inputs) + dependency_output_kinds
    if not set(effective_kinds).issubset(definition.input_kinds):
        raise ValueError("delegation input artifact is outside the role contract")
    if required_outputs and not set(required_outputs).issubset(definition.output_kinds):
        raise ValueError("delegation output artifact is outside the role contract")
    # In V1, a Research fan-in consumes the persisted Market Regime result;
    # callers cannot smuggle a predeclared substitute alongside that result.
    if role_id == AgentRoleId.RESEARCH.value and dependency_output_kinds and direct_inputs:
        raise ValueError("research fan-in must consume dependency artifacts rather than direct substitutes")
    if role_id == AgentRoleId.PRE_TRADE_CRITIC.value:
        if required_outputs and required_outputs != (ArtifactKind.CRITIQUE,):
            raise ValueError("critic delegation must produce exactly one critique")
        if dependency_output_kinds and direct_inputs:
            raise ValueError("critic fan-in must consume dependency artifacts rather than direct substitutes")
        # DelegationStep performs a first local validation before its parent
        # graph is available.  The parent plan supplies dependency outputs and
        # makes this exact check mandatory.
        if effective_kinds and effective_kinds != _CRITIC_INPUT_KINDS:
            raise ValueError("critic delegation requires exact Research artifact fan-in")


@dataclass(frozen=True, slots=True)
class CycleTrigger:
    source: TriggerSource
    idempotency_key: str
    occurred_at: RecordedAt
    input_artifacts: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        if type(self.source) is not TriggerSource or type(self.occurred_at) is not RecordedAt:
            raise TypeError("cycle trigger requires a versioned source and timestamp")
        if (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key.strip()
            or self.idempotency_key != self.idempotency_key.strip()
        ):
            raise ValueError("cycle trigger requires a stable idempotency key")
        if (
            type(self.input_artifacts) is not tuple
            or not self.input_artifacts
            or any(type(value) is not ArtifactRef for value in self.input_artifacts)
        ):
            raise ValueError("cycle trigger requires immutable input artifacts")

    @property
    def deduplication_hash(self) -> str:
        return canonical_sha256({"source": self.source.value, "idempotency_key": self.idempotency_key})


@dataclass(frozen=True, slots=True)
class AutonomyCycle:
    cycle_id: EntityId
    trigger: CycleTrigger
    started_at: RecordedAt
    expires_at: RecordedAt
    status: CycleStatus = CycleStatus.RUNNING
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            type(self.cycle_id) is not EntityId
            or self.cycle_id.namespace != "autonomy_cycle"
            or type(self.trigger) is not CycleTrigger
            or type(self.started_at) is not RecordedAt
            or type(self.expires_at) is not RecordedAt
            or type(self.status) is not CycleStatus
            or (self.correlation_id is not None and type(self.correlation_id) is not UUID)
        ):
            raise TypeError("cycle requires an autonomy_cycle identity")
        if self.expires_at.value <= self.started_at.value:
            raise ValueError("cycle expiry must follow start")


@dataclass(frozen=True, slots=True)
class DecisionEpisode:
    episode_id: EntityId
    cycle_id: EntityId
    candidate_key: str
    started_at: RecordedAt
    expires_at: RecordedAt
    status: EpisodeStatus = EpisodeStatus.RUNNING
    terminal_reason: str | None = None
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            type(self.episode_id) is not EntityId
            or self.episode_id.namespace != "decision_episode"
            or type(self.cycle_id) is not EntityId
            or self.cycle_id.namespace != "autonomy_cycle"
            or type(self.started_at) is not RecordedAt
            or type(self.expires_at) is not RecordedAt
            or type(self.status) is not EpisodeStatus
            or (self.correlation_id is not None and type(self.correlation_id) is not UUID)
        ):
            raise TypeError("episode requires exact decision_episode and autonomy_cycle identities")
        if not self.candidate_key or self.candidate_key != self.candidate_key.strip():
            raise ValueError("decision episode requires a stable candidate key")
        if self.expires_at.value <= self.started_at.value:
            raise ValueError("episode expiry must follow start")
        if self.status in _TERMINAL_EPISODES and not self.terminal_reason:
            raise ValueError("terminal episode requires an immutable reason")
        if self.status not in _TERMINAL_EPISODES and self.terminal_reason is not None:
            raise ValueError("non-terminal episode cannot have a terminal reason")


@dataclass(frozen=True, slots=True)
class DelegationStep:
    step_key: str
    role_id: str
    input_artifacts: tuple[ArtifactRef, ...]
    required_outputs: tuple[ArtifactKind, ...]
    budget: AgentBudget
    depends_on: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.step_key or self.step_key != self.step_key.strip() or not self.role_id:
            raise ValueError("delegation step requires a stable key and role")
        if (
            type(self.input_artifacts) is not tuple
            or type(self.required_outputs) is not tuple
            or type(self.depends_on) is not tuple
            or type(self.budget) is not AgentBudget
        ):
            raise TypeError("delegation step requires exact immutable contract values")
        if self.role_id not in _READ_ONLY_ROLES:
            raise ValueError("future role is not enabled in V1 observe workflow")
        if (
            (not self.input_artifacts and not self.depends_on)
            or not self.required_outputs
            or any(type(value) is not ArtifactRef for value in self.input_artifacts)
            or any(type(value) is not ArtifactKind for value in self.required_outputs)
        ):
            raise ValueError("delegation step requires inputs and typed outputs")
        if (
            len(set(self.input_artifacts)) != len(self.input_artifacts)
            or len(set(self.required_outputs)) != len(self.required_outputs)
            or len(set(self.depends_on)) != len(self.depends_on)
            or self.step_key in self.depends_on
            or any(not isinstance(value, str) or not value for value in self.depends_on)
        ):
            raise ValueError("delegation dependencies must be unique and non-cyclic")
        _validate_role_contract(self.role_id, self.input_artifacts, self.required_outputs)


@dataclass(frozen=True, slots=True)
class DelegationPlan:
    plan_id: EntityId
    cycle_id: EntityId
    episode_id: EntityId
    as_of: RecordedAt
    expires_at: RecordedAt
    steps: tuple[DelegationStep, ...]
    cycle_budget: AgentBudget

    def __post_init__(self) -> None:
        if (
            type(self.plan_id) is not EntityId
            or self.plan_id.namespace != "delegation_plan"
            or type(self.cycle_id) is not EntityId
            or self.cycle_id.namespace != "autonomy_cycle"
            or type(self.episode_id) is not EntityId
            or self.episode_id.namespace != "decision_episode"
            or type(self.steps) is not tuple
            or type(self.cycle_budget) is not AgentBudget
        ):
            raise TypeError("delegation plan requires exact identities and immutable values")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("delegation plan must expire in the future")
        if not self.steps or len({step.step_key for step in self.steps}) != len(self.steps):
            raise ValueError("delegation plan requires unique steps")
        names = {step.step_key for step in self.steps}
        if any(not set(step.depends_on).issubset(names) for step in self.steps):
            raise ValueError("delegation plan references an unknown dependency")
        _assert_acyclic(self.steps)
        by_key = {step.step_key: step for step in self.steps}
        for step in self.steps:
            dependent_outputs = tuple(output for name in step.depends_on for output in by_key[name].required_outputs)
            if step.role_id == AgentRoleId.PRE_TRADE_CRITIC.value and (
                len(step.depends_on) != 1
                or by_key[step.depends_on[0]].role_id != AgentRoleId.RESEARCH.value
                or dependent_outputs != _CRITIC_INPUT_KINDS
            ):
                raise ValueError("critic delegation must depend on one complete Research result")
            _validate_role_contract(
                step.role_id,
                step.input_artifacts,
                step.required_outputs,
                dependent_outputs,
            )
        totals = tuple(
            sum(getattr(step.budget, name) for step in self.steps)
            for name in ("max_turns", "max_tool_calls", "max_tokens", "timeout_seconds")
        )
        if any(
            total > cap
            for total, cap in zip(
                totals,
                (
                    self.cycle_budget.max_turns,
                    self.cycle_budget.max_tool_calls,
                    self.cycle_budget.max_tokens,
                    self.cycle_budget.timeout_seconds,
                ),
                strict=True,
            )
        ):
            raise ValueError("delegation plan budget exceeds cycle budget")


@dataclass(frozen=True, slots=True)
class WorkflowTask:
    task_id: EntityId
    episode_id: EntityId
    step_key: str
    role_id: str
    deadline_at: RecordedAt
    status: WorkflowTaskStatus = WorkflowTaskStatus.PENDING
    input_artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.task_id) is not EntityId
            or self.task_id.namespace != "workflow_task"
            or type(self.episode_id) is not EntityId
            or self.episode_id.namespace != "decision_episode"
            or type(self.status) is not WorkflowTaskStatus
            or type(self.deadline_at) is not RecordedAt
            or not isinstance(self.step_key, str)
            or not self.step_key
            or self.role_id not in _READ_ONLY_ROLES
            or type(self.input_artifacts) is not tuple
            or any(type(value) is not ArtifactRef for value in self.input_artifacts)
        ):
            raise TypeError("workflow task requires exact typed values")
        _validate_role_contract(self.role_id, self.input_artifacts, ())


@dataclass(frozen=True, slots=True)
class WorkflowTaskResult:
    task_id: EntityId
    status: WorkflowTaskStatus
    artifacts: tuple[ArtifactRef, ...]
    unknowns: tuple[str, ...]
    warnings: tuple[str, ...]
    # Critic conclusions are domain facts.  This field is deliberately not a
    # generic worker supplied status: the orchestrator maps it to the task and
    # episode transitions below.
    critique_status: CritiqueStatus | None = None

    def __post_init__(self) -> None:
        if (
            type(self.task_id) is not EntityId
            or self.task_id.namespace != "workflow_task"
            or type(self.status) is not WorkflowTaskStatus
            or type(self.artifacts) is not tuple
            or type(self.unknowns) is not tuple
            or type(self.warnings) is not tuple
            or (self.critique_status is not None and type(self.critique_status) is not CritiqueStatus)
        ):
            raise TypeError("workflow result requires exact immutable typed values")
        if self.status not in _TERMINAL_TASKS - {WorkflowTaskStatus.CANCELLED, WorkflowTaskStatus.TIMED_OUT}:
            raise ValueError("workflow result must be a completed, deferred, or failed terminal result")
        if self.status is WorkflowTaskStatus.COMPLETED and (
            not self.artifacts or any(type(value) is not ArtifactRef for value in self.artifacts)
        ):
            raise ValueError("completed workflow result requires immutable artifacts")
        if self.status is not WorkflowTaskStatus.COMPLETED and not (self.unknowns or self.warnings):
            raise ValueError("non-completed workflow result requires a reason")
        if len(set(self.artifacts)) != len(self.artifacts) or any(
            not isinstance(value, str) or not value.strip() for value in (*self.unknowns, *self.warnings)
        ):
            raise ValueError("workflow result must preserve unique artifacts and non-empty reasons")


def _critic_task_status(status: CritiqueStatus) -> WorkflowTaskStatus:
    """The only workflow projection of a Critique verdict.

    PASS and REJECT both preserve the immutable critique artifact as a
    completed task.  REJECT is nevertheless a fail-closed episode outcome;
    REVISE and DEFER are terminal deferred work.  A caller cannot choose a
    different projection by changing ``WorkflowTaskResult.status``.
    """

    return (
        WorkflowTaskStatus.COMPLETED
        if status in {CritiqueStatus.PASS, CritiqueStatus.REJECT}
        else WorkflowTaskStatus.DEFERRED
    )


class MainAgent:
    """Read-only Main boundary: it proposes a graph and owns no durable runtime."""

    forbidden_authority_terms = (
        "trade_plan",
        "order",
        "fill",
        "position",
        "ledger",
        "mandate",
        "approval",
        "strategy_candidate",
    )

    def create_delegation_plan(self, plan: DelegationPlan) -> DelegationPlan:
        if not isinstance(plan, DelegationPlan):
            raise TypeError("Main accepts only a typed delegation plan")
        return plan


class WorkflowOrchestrator:
    """Deterministic in-memory reference model suitable for replay and unit tests."""

    def __init__(self) -> None:
        self._cycles_by_dedup: dict[str, AutonomyCycle] = {}
        self._cycles: dict[EntityId, AutonomyCycle] = {}
        self._episodes: dict[EntityId, DecisionEpisode] = {}
        self._episodes_by_key: dict[tuple[EntityId, str], EntityId] = {}
        self._plans: dict[EntityId, DelegationPlan] = {}
        self._tasks: dict[EntityId, WorkflowTask] = {}
        self._task_results: dict[EntityId, WorkflowTaskResult] = {}
        self._critic_completions: dict[EntityId, tuple[StructuredArtifact, Critique]] = {}
        self._lock = RLock()

    def start_cycle(self, trigger: CycleTrigger, expires_at: RecordedAt) -> AutonomyCycle:
        with self._lock:
            prior = self._cycles_by_dedup.get(trigger.deduplication_hash)
            if prior is not None:
                if prior.trigger != trigger:
                    raise ValueError("cycle idempotency key conflicts with a different trigger fact")
                return prior
            cycle = AutonomyCycle(EntityId.new("autonomy_cycle"), trigger, trigger.occurred_at, expires_at)
            self._cycles_by_dedup[trigger.deduplication_hash] = cycle
            self._cycles[cycle.cycle_id] = cycle
            return cycle

    def start_episode(self, cycle_id: EntityId, candidate_key: str, expires_at: RecordedAt) -> DecisionEpisode:
        with self._lock:
            cycle = self._cycles[cycle_id]
            if cycle.status is not CycleStatus.RUNNING:
                raise ValueError("decision episode requires a running autonomy cycle")
            if expires_at.value > cycle.expires_at.value:
                raise ValueError("episode cannot outlive its autonomy cycle")
            key = (cycle_id, candidate_key)
            existing_id = self._episodes_by_key.get(key)
            if existing_id is not None:
                return self._episodes[existing_id]
            episode = DecisionEpisode(
                EntityId.new("decision_episode"), cycle_id, candidate_key, cycle.started_at, expires_at
            )
            self._episodes[episode.episode_id] = episode
            self._episodes_by_key[key] = episode.episode_id
            return episode

    def accept_delegation_plan(self, plan: DelegationPlan) -> tuple[WorkflowTask, ...]:
        with self._lock:
            episode = self._episodes.get(plan.episode_id)
            if episode is None or episode.cycle_id != plan.cycle_id or episode.status is not EpisodeStatus.RUNNING:
                raise ValueError("delegation plan must target a running episode in its cycle")
            if plan.expires_at.value > episode.expires_at.value:
                raise ValueError("delegation plan cannot outlive its decision episode")
            existing = self._plans.get(plan.episode_id)
            if existing is not None:
                if existing != plan:
                    raise ValueError("running episode already has a different delegation plan")
                return tuple(task for task in self._tasks.values() if task.episode_id == plan.episode_id)
            self._plans[plan.episode_id] = plan
            tasks = tuple(
                WorkflowTask(
                    EntityId.new("workflow_task"),
                    plan.episode_id,
                    step.step_key,
                    step.role_id,
                    RecordedAt(
                        min(plan.expires_at.value, plan.as_of.value + timedelta(seconds=step.budget.timeout_seconds))
                    ),
                    WorkflowTaskStatus.PENDING,
                    step.input_artifacts,
                )
                for step in plan.steps
            )
            self._tasks.update({task.task_id: task for task in tasks})
            return tasks

    def ready_tasks(self, episode_id: EntityId, now: RecordedAt) -> tuple[WorkflowTask, ...]:
        with self._lock:
            self._timeout(episode_id, now)
            episode = self._episodes[episode_id]
            if episode.status is not EpisodeStatus.RUNNING:
                return ()
            plan = self._plans.get(episode_id)
            if plan is None:
                return ()
            by_key = {task.step_key: task for task in self._tasks.values() if task.episode_id == episode_id}
            self._propagate_terminal_dependencies(episode_id, plan, by_key)
            by_key = {task.step_key: task for task in self._tasks.values() if task.episode_id == episode_id}
            self._close_episode_if_terminal(episode_id)
            if self._episodes[episode_id].status is not EpisodeStatus.RUNNING:
                return ()
            running = sum(task.status is WorkflowTaskStatus.RUNNING for task in by_key.values())
            slots = max(0, plan.cycle_budget.max_parallel_tasks - running)
            ready: list[WorkflowTask] = []
            for step in plan.steps:
                task = self._tasks[by_key[step.step_key].task_id]
                if task.status is not WorkflowTaskStatus.PENDING or not all(
                    self._tasks[by_key[name].task_id].status is WorkflowTaskStatus.COMPLETED for name in step.depends_on
                ):
                    continue
                resolved = self._resolved_input_artifacts(step, by_key)
                ready_task = WorkflowTask(
                    task.task_id,
                    task.episode_id,
                    task.step_key,
                    task.role_id,
                    task.deadline_at,
                    task.status,
                    resolved,
                )
                self._tasks[task.task_id] = ready_task
                by_key[step.step_key] = ready_task
                ready.append(ready_task)
            return tuple(ready[:slots])

    def _resolved_input_artifacts(
        self, step: DelegationStep, by_key: Mapping[str, WorkflowTask]
    ) -> tuple[ArtifactRef, ...]:
        dependency_artifacts: list[ArtifactRef] = []
        for name in step.depends_on:
            dependency = by_key[name]
            result = self._task_results.get(dependency.task_id)
            if dependency.status is not WorkflowTaskStatus.COMPLETED or result is None:
                raise ValueError("fan-in dependency has no completed immutable result")
            if result.task_id != dependency.task_id or result.status is not WorkflowTaskStatus.COMPLETED:
                raise ValueError("fan-in result identity is inconsistent with its dependency task")
            dependency_artifacts.extend(result.artifacts)
        resolved = (*step.input_artifacts, *dependency_artifacts)
        if len(set(resolved)) != len(resolved):
            raise ValueError("fan-in input artifacts must remain unique")
        _validate_role_contract(step.role_id, resolved, ())
        return resolved

    def _propagate_terminal_dependencies(
        self, episode_id: EntityId, plan: DelegationPlan, by_key: dict[str, WorkflowTask]
    ) -> None:
        while True:
            skipped = False
            for step in plan.steps:
                task = by_key[step.step_key]
                if task.status is WorkflowTaskStatus.PENDING and any(
                    by_key[name].status in _TERMINAL_TASKS - {WorkflowTaskStatus.COMPLETED} for name in step.depends_on
                ):
                    replacement = WorkflowTask(
                        task.task_id,
                        task.episode_id,
                        task.step_key,
                        task.role_id,
                        task.deadline_at,
                        WorkflowTaskStatus.SKIPPED,
                        task.input_artifacts,
                    )
                    self._tasks[task.task_id] = replacement
                    by_key[step.step_key] = replacement
                    skipped = True
            if not skipped:
                return

    def _close_episode_if_terminal(self, episode_id: EntityId) -> None:
        episode = self._episodes[episode_id]
        values = tuple(task for task in self._tasks.values() if task.episode_id == episode_id)
        if (
            episode.status is EpisodeStatus.RUNNING
            and values
            and all(task.status in _TERMINAL_TASKS for task in values)
        ):
            critic_rejected = any(
                task.role_id == AgentRoleId.PRE_TRADE_CRITIC.value
                and (result := self._task_results.get(task.task_id)) is not None
                and result.critique_status is CritiqueStatus.REJECT
                for task in values
            )
            final = (
                EpisodeStatus.COMPLETED
                if not critic_rejected and all(task.status is WorkflowTaskStatus.COMPLETED for task in values)
                else EpisodeStatus.DEFERRED
            )
            self._episodes[episode_id] = DecisionEpisode(
                episode.episode_id,
                episode.cycle_id,
                episode.candidate_key,
                episode.started_at,
                episode.expires_at,
                final,
                "all_tasks_terminal",
                episode.correlation_id,
            )
            self._close_cycle_if_done(episode.cycle_id)

    def claim_ready_tasks(
        self, episode_id: EntityId, now: RecordedAt, limit: int | None = None
    ) -> tuple[WorkflowTask, ...]:
        with self._lock:
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
                raise ValueError("claim limit must be a positive integer")
            ready = self.ready_tasks(episode_id, now)
            claimed = ready if limit is None else ready[:limit]
            result = tuple(
                WorkflowTask(
                    task.task_id,
                    task.episode_id,
                    task.step_key,
                    task.role_id,
                    task.deadline_at,
                    WorkflowTaskStatus.RUNNING,
                    task.input_artifacts,
                )
                for task in claimed
            )
            self._tasks.update({task.task_id: task for task in result})
            return result

    def complete_task(self, episode_id: EntityId, result: WorkflowTaskResult, now: RecordedAt) -> WorkflowTask:
        """Complete non-Critic work only; Critic has a typed gate command."""
        task = self._tasks.get(result.task_id)
        if task is not None and task.role_id == AgentRoleId.PRE_TRADE_CRITIC.value:
            raise ValueError("generic completion cannot complete a Critic task")
        return self._complete_task(episode_id, result, now)

    def complete_critic_task(
        self,
        episode_id: EntityId,
        task_id: EntityId,
        artifact: StructuredArtifact,
        critique: Critique,
        sources: tuple[StructuredArtifact, ...],
        revisions: CritiqueRevisionStore,
        now: RecordedAt,
    ) -> WorkflowTask:
        """Atomically project a pre-reserved canonical Critique into workflow state."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.episode_id != episode_id or task.role_id != AgentRoleId.PRE_TRADE_CRITIC.value:
                raise ValueError("critic completion requires the episode's Critic task")
            prior = self._critic_completions.get(task_id)
            if task.status in _TERMINAL_TASKS:
                if prior == (artifact, critique):
                    return task
                raise ValueError("critic exact retry conflicts with immutable canonical completion")
            if (
                type(artifact) is not StructuredArtifact
                or type(critique) is not Critique
                or type(sources) is not tuple
                or type(revisions) is not CritiqueRevisionStore
                or len(sources) != 3
                or any(type(source) is not StructuredArtifact for source in sources)
                or tuple(source.ref for source in sources) != task.input_artifacts
                or any(source.producer_role_id != AgentRoleId.RESEARCH.value for source in sources)
                or any(source.producer_run_id.namespace != "agent_run" for source in sources)
                or any(source.producer_run_id != sources[0].producer_run_id for source in sources[1:])
                or any(source.source_refs != sources[0].source_refs for source in sources[1:])
                or any(source.expires_at != sources[0].expires_at for source in sources[1:])
                or artifact.ref.artifact_kind is not ArtifactKind.CRITIQUE
                or artifact.ref.artifact_id != critique.critique_id
                or artifact.ref.schema_version != critique.policy.schema_version
                or artifact.ref.content_hash != "sha256:" + critique.content_sha256
                or artifact.ref.created_at != critique.evaluated_at
                or artifact.ref.as_of != critique.hypothesis.as_of
                or artifact.producer_role_id != AgentRoleId.PRE_TRADE_CRITIC.value
                or artifact.producer_run_id.namespace != "agent_run"
                or artifact.source_refs != task.input_artifacts
                or artifact.expires_at != critique.expires_at
                or now.value >= critique.expires_at.value
                or task.deadline_at.value > min(source.expires_at.value for source in sources)
                or critique.expires_at.value > min(source.expires_at.value for source in sources)
            ):
                raise ValueError("critic completion requires exact live StructuredArtifact fan-in")
            critique.validate_current()
            identities = (critique.hypothesis, critique.evidence_synthesis, critique.experiment_request)
            if any(
                str(identity.artifact_id) != str(source.ref.artifact_id)
                or identity.content_sha256 != source.ref.content_hash.removeprefix("sha256:")
                or identity.as_of != source.ref.as_of
                or identity.valid_until != source.expires_at
                for identity, source in zip(identities, sources, strict=True)
            ):
                raise ValueError("critic source snapshot does not match actual structured fan-in")
            reservation = revisions.require(
                episode_id, critique.hypothesis.content_sha256, critique.policy, critique.content_sha256
            )
            if reservation.iteration != critique.iteration:
                raise ValueError("critic completion revision does not match its reservation")
            completed = self._complete_task(
                episode_id,
                WorkflowTaskResult(
                    task_id,
                    _critic_task_status(critique.status),
                    (artifact.ref,) if critique.status in {CritiqueStatus.PASS, CritiqueStatus.REJECT} else (),
                    (f"critique:{critique.status.value}",)
                    if critique.status in {CritiqueStatus.REVISE, CritiqueStatus.DEFER}
                    else (),
                    (),
                    critique.status,
                ),
                now,
            )
            self._critic_completions[task_id] = (artifact, critique)
            return completed

    def _complete_task(self, episode_id: EntityId, result: WorkflowTaskResult, now: RecordedAt) -> WorkflowTask:
        with self._lock:
            self._timeout(episode_id, now)
            task = self._tasks[result.task_id]
            if task.episode_id != episode_id or self._episodes[episode_id].status is not EpisodeStatus.RUNNING:
                raise ValueError("cannot complete a task outside a running episode")
            if task.status in _TERMINAL_TASKS:
                if self._task_results.get(task.task_id) != result:
                    raise ValueError("task terminal result conflicts with immutable prior result")
                return task
            if task.status is WorkflowTaskStatus.PENDING and all(
                candidate.task_id != task.task_id for candidate in self.ready_tasks(episode_id, now)
            ):
                raise ValueError("task dependencies are not ready for deterministic fan-in")
            if task.status not in {WorkflowTaskStatus.PENDING, WorkflowTaskStatus.RUNNING}:
                raise ValueError("task is not claimable for completion")
            plan = self._plans[episode_id]
            expected = next(step for step in plan.steps if step.step_key == task.step_key)
            if task.role_id == AgentRoleId.PRE_TRADE_CRITIC.value:
                if result.critique_status is None:
                    raise ValueError("critic completion requires its canonical Critique verdict")
                projected = _critic_task_status(result.critique_status)
                if result.status is not projected:
                    raise ValueError("caller cannot override the deterministic Critique workflow outcome")
            elif result.critique_status is not None:
                raise ValueError("only the Critic task may carry a Critique verdict")
            if (
                result.status is WorkflowTaskStatus.COMPLETED
                and tuple(value.artifact_kind for value in result.artifacts) != expected.required_outputs
            ):
                raise ValueError("task result does not match required typed outputs")
            completed = WorkflowTask(
                task.task_id,
                task.episode_id,
                task.step_key,
                task.role_id,
                task.deadline_at,
                result.status,
                task.input_artifacts,
            )
            self._tasks[task.task_id] = completed
            self._task_results[task.task_id] = result
            # A failure/defer is a terminal dependency fact, not a later poll:
            # recursively skip descendants and close the episode in this same
            # deterministic transition.
            self._propagate_terminal_dependencies(
                episode_id,
                plan,
                {value.step_key: value for value in self._tasks.values() if value.episode_id == episode_id},
            )
            self._close_episode_if_terminal(episode_id)
            return self._tasks[result.task_id]

    def cancel_episode(self, episode_id: EntityId, reason: str, now: RecordedAt) -> DecisionEpisode:
        with self._lock:
            self._timeout(episode_id, now)
            episode = self._episodes[episode_id]
            if episode.status in _TERMINAL_EPISODES:
                return episode
            if not reason.strip():
                raise ValueError("cancellation needs a reason")
            for task_id, task in tuple(self._tasks.items()):
                if task.episode_id == episode_id and task.status not in _TERMINAL_TASKS:
                    self._tasks[task_id] = WorkflowTask(
                        task.task_id,
                        task.episode_id,
                        task.step_key,
                        task.role_id,
                        task.deadline_at,
                        WorkflowTaskStatus.CANCELLED,
                        task.input_artifacts,
                    )
            terminal = DecisionEpisode(
                episode.episode_id,
                episode.cycle_id,
                episode.candidate_key,
                episode.started_at,
                episode.expires_at,
                EpisodeStatus.CANCELLED,
                reason,
                episode.correlation_id,
            )
            self._episodes[episode_id] = terminal
            self._close_cycle_if_done(episode.cycle_id)
            return terminal

    def episode(self, episode_id: EntityId) -> DecisionEpisode:
        return self._episodes[episode_id]

    def recover(self, now: RecordedAt) -> tuple[AutonomyCycle, ...]:
        with self._lock:
            for episode_id in tuple(self._episodes):
                self._timeout(episode_id, now)
            for cycle_id, cycle in tuple(self._cycles.items()):
                if (
                    cycle.status is CycleStatus.RUNNING
                    and not any(episode.cycle_id == cycle_id for episode in self._episodes.values())
                    and now.value >= cycle.expires_at.value
                ):
                    self._cycles[cycle_id] = AutonomyCycle(
                        cycle.cycle_id,
                        cycle.trigger,
                        cycle.started_at,
                        cycle.expires_at,
                        CycleStatus.TIMED_OUT,
                        cycle.correlation_id,
                    )
            return tuple(cycle for cycle in self._cycles.values() if cycle.status is CycleStatus.RUNNING)

    def _timeout(self, episode_id: EntityId, now: RecordedAt) -> None:
        episode = self._episodes[episode_id]
        for task_id, task in tuple(self._tasks.items()):
            if (
                task.episode_id == episode_id
                and task.status in {WorkflowTaskStatus.PENDING, WorkflowTaskStatus.RUNNING}
                and now.value >= task.deadline_at.value
            ):
                self._tasks[task_id] = WorkflowTask(
                    task.task_id,
                    task.episode_id,
                    task.step_key,
                    task.role_id,
                    task.deadline_at,
                    WorkflowTaskStatus.TIMED_OUT,
                    task.input_artifacts,
                )
        plan = self._plans.get(episode_id)
        if plan is not None and episode.status is EpisodeStatus.RUNNING:
            self._propagate_terminal_dependencies(
                episode_id,
                plan,
                {task.step_key: task for task in self._tasks.values() if task.episode_id == episode_id},
            )
            self._close_episode_if_terminal(episode_id)
            episode = self._episodes[episode_id]
        if episode.status is EpisodeStatus.RUNNING and now.value >= episode.expires_at.value:
            for task_id, task in tuple(self._tasks.items()):
                if task.episode_id == episode_id and task.status not in _TERMINAL_TASKS:
                    self._tasks[task_id] = WorkflowTask(
                        task.task_id,
                        task.episode_id,
                        task.step_key,
                        task.role_id,
                        task.deadline_at,
                        WorkflowTaskStatus.TIMED_OUT,
                        task.input_artifacts,
                    )
            self._episodes[episode_id] = DecisionEpisode(
                episode.episode_id,
                episode.cycle_id,
                episode.candidate_key,
                episode.started_at,
                episode.expires_at,
                EpisodeStatus.TIMED_OUT,
                "deadline_exceeded",
                episode.correlation_id,
            )
            self._close_cycle_if_done(episode.cycle_id)

    def _close_cycle_if_done(self, cycle_id: EntityId) -> None:
        cycle = self._cycles[cycle_id]
        episodes = tuple(value for value in self._episodes.values() if value.cycle_id == cycle_id)
        if (
            episodes
            and cycle.status is CycleStatus.RUNNING
            and all(value.status in _TERMINAL_EPISODES for value in episodes)
        ):
            status = (
                CycleStatus.COMPLETED
                if all(value.status is EpisodeStatus.COMPLETED for value in episodes)
                else CycleStatus.DEFERRED
            )
            self._cycles[cycle_id] = AutonomyCycle(
                cycle.cycle_id, cycle.trigger, cycle.started_at, cycle.expires_at, status, cycle.correlation_id
            )


class PostgresWorkflowRepository:
    """Only invokes owner-controlled functions for durable checkpoints/projections."""

    def start_cycle(
        self,
        connection: Connection,
        cycle_id: UUID,
        trigger_source: str,
        idempotency_key: str,
        correlation_id: UUID,
        trigger_payload: JsonValue,
        trigger_sha256: str,
        expires_at: object,
    ) -> UUID:
        canonical = canonical_json_text(trigger_payload)  # rejects mutable lists/Decimal at ingress
        if trigger_sha256 != canonical_sha256(trigger_payload):
            raise ValueError("trigger hash must be the Python canonical SHA-256")
        return connection.execute(
            text(
                "SELECT fao.start_autonomy_cycle(:id,:source,:key,:correlation,CAST(:payload AS jsonb),:canonical,:hash,:expires)"
            ),
            {
                "id": cycle_id,
                "source": trigger_source,
                "key": idempotency_key,
                "correlation": correlation_id,
                "payload": canonical,
                "canonical": canonical,
                "hash": trigger_sha256,
                "expires": expires_at,
            },
        ).scalar_one()

    def reserve_critique_revision(
        self,
        connection: Connection,
        episode_id: EntityId,
        hypothesis_sha256: str,
        policy_id: EntityId,
        policy_version: int,
        policy_schema: SchemaVersion,
        max_iterations: int,
        evaluation_sha256: str,
    ) -> int:
        """Atomically allocate an immutable Critique revision in PostgreSQL."""
        if (
            type(episode_id) is not EntityId
            or episode_id.namespace != "decision_episode"
            or type(policy_id) is not EntityId
            or policy_id.namespace != "critique_policy"
            or type(policy_schema) is not SchemaVersion
            or type(policy_version) is not int
            or type(max_iterations) is not int
        ):
            raise TypeError("critique revision requires exact episode and policy identities")
        for value in (hypothesis_sha256, evaluation_sha256):
            if type(value) is not str or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError("critique revision requires canonical SHA-256 identities")
        return int(
            connection.execute(
                text(
                    "SELECT agent_checkpoint.reserve_critique_revision(:episode,:hypothesis,:policy,:version,:schema,:maximum,:evaluation)"
                ),
                {
                    "episode": episode_id.value,
                    "hypothesis": hypothesis_sha256,
                    "policy": policy_id.value,
                    "version": policy_version,
                    "schema": str(policy_schema),
                    "maximum": max_iterations,
                    "evaluation": evaluation_sha256,
                },
            ).scalar_one()
        )

    def start_typed_cycle(
        self,
        connection: Connection,
        cycle_id: EntityId,
        trigger: CycleTrigger,
        correlation_id: UUID,
        expires_at: RecordedAt,
    ) -> UUID:
        if (
            type(cycle_id) is not EntityId
            or cycle_id.namespace != "autonomy_cycle"
            or type(expires_at) is not RecordedAt
        ):
            raise TypeError("typed cycle persistence requires cycle identity and RecordedAt expiry")
        payload: JsonValue = {
            "source": trigger.source.value,
            "idempotency_key": trigger.idempotency_key,
            "occurred_at": trigger.occurred_at.value.isoformat(),
            "input_artifacts": tuple(cast(JsonValue, _ref_json(value)) for value in trigger.input_artifacts),
        }
        return self.start_cycle(
            connection,
            cycle_id.value,
            trigger.source.value,
            trigger.idempotency_key,
            correlation_id,
            payload,
            canonical_sha256(payload),
            expires_at.value,
        )

    def recover_cycle_ids(self, connection: Connection, now: object) -> tuple[UUID, ...]:
        del now
        return tuple(connection.execute(text("SELECT cycle_id FROM fao.recoverable_workflow_cycles()")).scalars())

    def start_episode(
        self,
        connection: Connection,
        episode_id: UUID,
        cycle_id: UUID,
        candidate_key: str,
        expires_at: object,
    ) -> UUID:
        return connection.execute(
            text("SELECT fao.start_decision_episode(:episode,:cycle,:candidate,:expires)"),
            {
                "episode": episode_id,
                "cycle": cycle_id,
                "candidate": candidate_key,
                "expires": expires_at,
            },
        ).scalar_one()

    def recover_episode_ids(self, connection: Connection, now: object) -> tuple[UUID, ...]:
        self.recover_cycle_ids(connection, now)
        return tuple(connection.execute(text("SELECT episode_id FROM fao.recoverable_workflow_episodes()")).scalars())

    def cancel_episode(self, connection: Connection, episode_id: UUID, reason: str) -> bool:
        return bool(
            connection.execute(
                text("SELECT fao.cancel_decision_episode(:episode,:reason)"),
                {"episode": episode_id, "reason": reason},
            ).scalar_one()
        )

    def rebuild_journal(
        self,
        connection: Connection,
        journal_id: UUID,
        episode_id: UUID,
        correlation_id: UUID,
        cutoff_at: object,
        projected_at: object,
    ) -> int:
        return int(
            connection.execute(
                text(
                    "SELECT fao.rebuild_decision_journal_projection(:journal,:episode,:correlation,:cutoff,:projected)"
                ),
                {
                    "journal": journal_id,
                    "episode": episode_id,
                    "correlation": correlation_id,
                    "cutoff": cutoff_at,
                    "projected": projected_at,
                },
            ).scalar_one()
        )

    def persist_execution(
        self, connection: Connection, episode_id: UUID, expected_version: int, plan: JsonValue, tasks: JsonValue
    ) -> int:
        plan_text, task_text = canonical_json_text(plan), canonical_json_text(tasks)
        return int(
            connection.execute(
                text(
                    "SELECT agent_checkpoint.persist_workflow_execution(:episode,:version,CAST(:plan AS jsonb),:plan_text,:plan_hash,CAST(:tasks AS jsonb),:task_text,:task_hash)"
                ),
                {
                    "episode": episode_id,
                    "version": expected_version,
                    "plan": plan_text,
                    "plan_text": plan_text,
                    "plan_hash": canonical_sha256(plan),
                    "tasks": task_text,
                    "task_text": task_text,
                    "task_hash": canonical_sha256(tasks),
                },
            ).scalar_one()
        )

    def claim_task(
        self, connection: Connection, episode_id: UUID, worker_id: str, lease_seconds: int
    ) -> tuple[UUID, int, int, dict[str, object]] | None:
        row = (
            connection.execute(
                text("SELECT * FROM agent_checkpoint.claim_workflow_task(:episode,:worker,:lease)"),
                {"episode": episode_id, "worker": worker_id, "lease": lease_seconds},
            )
            .mappings()
            .first()
        )
        return None if row is None else (row["task_id"], row["version"], row["fencing_token"], row["task_payload"])

    def complete_task_fenced(
        self, connection: Connection, task_id: UUID, version: int, fencing_token: int, result: JsonValue
    ) -> bool:
        if not isinstance(result, Mapping):
            raise TypeError("workflow result must be an immutable mapping")
        result = {**result, "task_id": str(task_id)}
        result_text = canonical_json_text(result)
        return bool(
            connection.execute(
                text(
                    "SELECT agent_checkpoint.complete_workflow_task(:task,:version,:fence,CAST(:result AS jsonb),:canonical,:hash)"
                ),
                {
                    "task": task_id,
                    "version": version,
                    "fence": fencing_token,
                    "result": result_text,
                    "canonical": result_text,
                    "hash": canonical_sha256(result),
                },
            ).scalar_one()
        )

    def complete_critic_task_fenced(
        self,
        connection: Connection,
        task_id: UUID,
        version: int,
        fencing_token: int,
        artifact: StructuredArtifact,
        critique: Critique,
        sources: tuple[StructuredArtifact, ...],
    ) -> bool:
        """Persist a Critique through the only verdict-owning SQL command.

        There is deliberately no caller status parameter.  PostgreSQL validates
        the complete canonical Critique, checks its reserved revision and
        source fan-in, and maps PASS/REJECT/REVISE/DEFER itself.
        """
        if (
            type(artifact) is not StructuredArtifact
            or type(critique) is not Critique
            or type(sources) is not tuple
            or len(sources) != 3
            or any(type(source) is not StructuredArtifact for source in sources)
        ):
            raise TypeError("critic completion requires exact StructuredArtifact fan-in and Critique")
        critique.validate_current()
        refs = tuple(source.ref for source in sources)
        if (
            tuple(source.producer_role_id for source in sources) != (AgentRoleId.RESEARCH.value,) * 3
            or tuple(source.ref.artifact_kind for source in sources) != _CRITIC_INPUT_KINDS
            or any(source.producer_run_id.namespace != "agent_run" for source in sources)
            or any(source.producer_run_id != sources[0].producer_run_id for source in sources[1:])
            or any(source.source_refs != sources[0].source_refs for source in sources[1:])
            or any(source.expires_at != sources[0].expires_at for source in sources[1:])
            or artifact.producer_role_id != AgentRoleId.PRE_TRADE_CRITIC.value
            or artifact.producer_run_id.namespace != "agent_run"
            or artifact.ref.artifact_kind is not ArtifactKind.CRITIQUE
            or artifact.ref.artifact_id != critique.critique_id
            or artifact.ref.schema_version != critique.policy.schema_version
            or artifact.ref.content_hash != "sha256:" + critique.content_sha256
            or artifact.ref.created_at != critique.evaluated_at
            or artifact.ref.as_of != critique.hypothesis.as_of
            or artifact.source_refs != refs
            or artifact.expires_at != critique.expires_at
            or critique.expires_at.value > min(source.expires_at.value for source in sources)
            or any(
                str(identity.artifact_id) != str(source.ref.artifact_id)
                or identity.content_sha256 != source.ref.content_hash.removeprefix("sha256:")
                or identity.as_of != source.ref.as_of
                or identity.valid_until != source.expires_at
                for identity, source in zip(
                    (critique.hypothesis, critique.evidence_synthesis, critique.experiment_request),
                    sources,
                    strict=True,
                )
            )
            or critique.content_sha256 != canonical_sha256(critique.payload())
        ):
            raise ValueError("critic artifact and canonical Critique payload must match exactly")
        payload = critique.payload()
        payload_text = canonical_json_text(payload)
        return bool(
            connection.execute(
                text(
                    "SELECT agent_checkpoint.complete_critic_workflow_task(:task,:version,:fence,CAST(:artifact AS jsonb),CAST(:critique AS jsonb),:canonical,:hash)"
                ),
                {
                    "task": task_id,
                    "version": version,
                    "fence": fencing_token,
                    "artifact": canonical_json_text(cast(JsonValue, _ref_json(artifact.ref))),
                    "critique": payload_text,
                    "canonical": payload_text,
                    "hash": critique.content_sha256,
                },
            ).scalar_one()
        )

    def persist_typed_execution(self, connection: Connection, plan: DelegationPlan, expected_version: int = 0) -> int:
        """Persist only a fully validated typed graph; no caller JSON enters here."""
        _assert_observe_plan(plan)
        payload = connection.execute(
            text("SELECT fao.hydrate_workflow_episode(:episode)"), {"episode": plan.episode_id.value}
        ).scalar_one_or_none()
        if payload is None:
            raise KeyError("unknown workflow episode")
        existing = cast(dict[str, object], payload).get("execution")
        if existing is not None:
            existing_value = cast(dict[str, object], existing)
            persisted_plan = _plan_from_json(cast(dict[str, object], existing_value["plan"]))
            if persisted_plan != plan:
                raise ValueError("typed workflow execution conflicts with immutable prior plan")
            return int(cast(int | str, existing_value["version"]))
        plan_json = _plan_json(plan)
        tasks = tuple(_task_json(plan, step) for step in plan.steps)
        return self.persist_execution(
            connection, plan.episode_id.value, expected_version, cast(JsonValue, plan_json), cast(JsonValue, tasks)
        )

    def hydrate_typed_episode(
        self, connection: Connection, episode_id: EntityId
    ) -> tuple[
        AutonomyCycle, DecisionEpisode, DelegationPlan | None, tuple[WorkflowTask, ...], tuple[WorkflowTaskResult, ...]
    ]:
        if type(episode_id) is not EntityId or episode_id.namespace != "decision_episode":
            raise TypeError("hydrate requires a decision_episode identity")
        payload = connection.execute(
            text("SELECT fao.hydrate_workflow_episode(:episode)"), {"episode": episode_id.value}
        ).scalar_one_or_none()
        if payload is None:
            raise KeyError("unknown workflow episode")
        value = cast(dict[str, object], payload)
        cycle_data = cast(dict[str, object], value["cycle"])
        episode_data = cast(dict[str, object], value["episode"])
        trigger = _trigger_from_json(cast(dict[str, object], cycle_data["trigger"]))
        cycle = AutonomyCycle(
            EntityId("autonomy_cycle", UUID(str(cycle_data["cycle_id"]))),
            trigger,
            RecordedAt.parse(str(cycle_data["started_at"])),
            RecordedAt.parse(str(cycle_data["expires_at"])),
            CycleStatus(str(cycle_data["status"])),
            UUID(str(cycle_data["correlation_id"])),
        )
        episode = DecisionEpisode(
            EntityId("decision_episode", UUID(str(episode_data["episode_id"]))),
            cycle.cycle_id,
            str(episode_data["candidate_key"]),
            RecordedAt.parse(str(episode_data["started_at"])),
            RecordedAt.parse(str(episode_data["expires_at"])),
            EpisodeStatus(str(episode_data["status"])),
            cast(str | None, episode_data["terminal_reason"]),
            UUID(str(episode_data["correlation_id"])),
        )
        execution = value.get("execution")
        if execution is None:
            return cycle, episode, None, (), ()
        execution_data = cast(dict[str, object], execution)
        plan = _plan_from_json(cast(dict[str, object], execution_data["plan"]))
        if plan.cycle_id != cycle.cycle_id or plan.episode_id != episode.episode_id:
            raise ValueError("persisted plan identity drift")
        task_rows = cast(list[dict[str, object]], value["tasks"])
        tasks = tuple(_task_from_json(row) for row in task_rows)
        results = tuple(
            _result_from_json(cast(dict[str, object], row["result"])) for row in task_rows if row["result"] is not None
        )
        return cycle, episode, plan, _resolve_hydrated_task_inputs(plan, tasks, results), results

    def hydrate_critic_completion(
        self, connection: Connection, task_id: UUID, episode_id: EntityId
    ) -> dict[str, object] | None:
        """Read the complete DB-validated Critic sidecar through its owner API.

        Workers are intentionally not granted table access: the SQL function
        re-authenticates the canonical Critique and derived verdict before it
        returns the immutable artifact/payload pair.
        """
        if type(task_id) is not UUID or type(episode_id) is not EntityId or episode_id.namespace != "decision_episode":
            raise TypeError("critic hydration requires exact task and decision_episode identities")
        value = connection.execute(
            text("SELECT agent_checkpoint.hydrate_critic_completion(:task,:episode)"),
            {"task": task_id, "episode": episode_id.value},
        ).scalar_one_or_none()
        if value is None:
            return None
        payload = cast(dict[str, object], value)
        if set(payload) != {"artifact", "critique", "canonical", "hash", "status"}:
            raise ValueError("invalid hydrated Critic completion envelope")
        critique = cast(dict[str, object], payload["critique"])
        immutable_critique = _freeze_loaded_json(critique)
        canonical = payload["canonical"]
        digest = payload["hash"]
        if (
            type(canonical) is not str
            or type(digest) is not str
            or canonical != canonical_json_text(immutable_critique)
            or digest != canonical_sha256(immutable_critique)
            or payload["status"] != critique.get("status")
        ):
            raise ValueError("hydrated Critic completion canonical integrity drift")
        return payload

    def hydrate_critic_verdict(
        self, connection: Connection, task_id: UUID, episode_id: EntityId
    ) -> CritiqueStatus | None:
        """Recover the DB-owned Critic verdict without direct sidecar access."""
        completion = self.hydrate_critic_completion(connection, task_id, episode_id)
        return None if completion is None else CritiqueStatus(str(completion["status"]))


def _assert_acyclic(steps: tuple[DelegationStep, ...]) -> None:
    dependencies = {step.step_key: set(step.depends_on) for step in steps}
    resolved: set[str] = set()
    while dependencies:
        ready = {name for name, refs in dependencies.items() if refs <= resolved}
        if not ready:
            raise ValueError("delegation plan dependencies are cyclic")
        resolved.update(ready)
        for name in ready:
            dependencies.pop(name)


def _ref_json(ref: ArtifactRef) -> dict[str, object]:
    return {
        "id": str(ref.artifact_id.value),
        "namespace": ref.artifact_id.namespace,
        "kind": ref.artifact_kind.value,
        "schema": str(ref.schema_version),
        "hash": ref.content_hash,
        "created_at": ref.created_at.value.isoformat(),
        "as_of": ref.as_of.value.isoformat(),
    }


def _freeze_loaded_json(value: object) -> JsonValue:
    """Convert driver-owned JSON lists into the immutable canonical contract."""

    if value is None or type(value) in {str, int, bool}:
        return cast(JsonValue, value)
    if type(value) is list:
        return tuple(_freeze_loaded_json(item) for item in cast(list[object], value))
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if any(type(key) is not str for key in mapping):
            raise ValueError("persisted JSON object keys must be strings")
        return {cast(str, key): _freeze_loaded_json(item) for key, item in mapping.items()}
    raise ValueError("persisted value must be finite JSON-compatible data")


def _ref_from_json(value: dict[str, object]) -> ArtifactRef:
    return ArtifactRef(
        EntityId(str(value["namespace"]), UUID(str(value["id"]))),
        ArtifactKind(str(value["kind"])),
        SchemaVersion.parse(str(value["schema"])),
        str(value["hash"]),
        RecordedAt.parse(str(value["created_at"])),
        RecordedAt.parse(str(value["as_of"])),
    )


def _budget_json(value: AgentBudget) -> dict[str, int]:
    return {
        "max_turns": value.max_turns,
        "max_tool_calls": value.max_tool_calls,
        "max_tokens": value.max_tokens,
        "timeout_seconds": value.timeout_seconds,
        "max_parallel_tasks": value.max_parallel_tasks,
    }


def _budget_from_json(value: dict[str, object]) -> AgentBudget:
    return AgentBudget(
        *[
            int(cast(int | str, value[key]))
            for key in ("max_turns", "max_tool_calls", "max_tokens", "timeout_seconds", "max_parallel_tasks")
        ]
    )


def _trigger_from_json(value: dict[str, object]) -> CycleTrigger:
    return CycleTrigger(
        TriggerSource(str(value["source"])),
        str(value["idempotency_key"]),
        RecordedAt.parse(str(value["occurred_at"])),
        tuple(_ref_from_json(item) for item in cast(list[dict[str, object]], value["input_artifacts"])),
    )


def _plan_json(plan: DelegationPlan) -> dict[str, object]:
    return {
        "plan_id": str(plan.plan_id.value),
        "cycle_id": str(plan.cycle_id.value),
        "episode_id": str(plan.episode_id.value),
        "as_of": plan.as_of.value.isoformat(),
        "expires_at": plan.expires_at.value.isoformat(),
        "cycle_budget": _budget_json(plan.cycle_budget),
        "steps": tuple(
            {
                "step_key": s.step_key,
                "role_id": s.role_id,
                "input_artifacts": tuple(_ref_json(x) for x in s.input_artifacts),
                "required_outputs": tuple(x.value for x in s.required_outputs),
                "budget": _budget_json(s.budget),
                "depends_on": s.depends_on,
            }
            for s in plan.steps
        ),
    }


def _plan_from_json(value: dict[str, object]) -> DelegationPlan:
    steps = tuple(
        DelegationStep(
            str(s["step_key"]),
            str(s["role_id"]),
            tuple(_ref_from_json(x) for x in cast(list[dict[str, object]], s["input_artifacts"])),
            tuple(ArtifactKind(str(x)) for x in cast(list[str], s["required_outputs"])),
            _budget_from_json(cast(dict[str, object], s["budget"])),
            tuple(cast(list[str], s["depends_on"])),
        )
        for s in cast(list[dict[str, object]], value["steps"])
    )
    return DelegationPlan(
        EntityId("delegation_plan", UUID(str(value["plan_id"]))),
        EntityId("autonomy_cycle", UUID(str(value["cycle_id"]))),
        EntityId("decision_episode", UUID(str(value["episode_id"]))),
        RecordedAt.parse(str(value["as_of"])),
        RecordedAt.parse(str(value["expires_at"])),
        steps,
        _budget_from_json(cast(dict[str, object], value["cycle_budget"])),
    )


def _task_json(plan: DelegationPlan, step: DelegationStep) -> dict[str, object]:
    deadline = min(plan.expires_at.value, plan.as_of.value + timedelta(seconds=step.budget.timeout_seconds))
    return {
        "task_id": str(_workflow_task_id(plan, step).value),
        "episode_id": str(plan.episode_id.value),
        "step_key": step.step_key,
        "role_id": step.role_id,
        "deadline_at": deadline.isoformat(),
        "depends_on": step.depends_on,
        "required_outputs": tuple(x.value for x in step.required_outputs),
        "input_artifacts": tuple(_ref_json(x) for x in step.input_artifacts),
        "budget": _budget_json(step.budget),
    }


def _workflow_task_id(plan: DelegationPlan, step: DelegationStep) -> EntityId:
    """Derive a stable UUIDv7 task identity from immutable plan facts.

    A lost response may cause two fresh workers to materialize the same typed
    plan concurrently.  Task identities are checkpoint facts, so retries must
    not introduce a second random task set.  Preserve the plan UUIDv7 timestamp
    while deriving the remaining UUID bits from the plan/episode/step identity.
    """

    value = bytearray(plan.plan_id.value.bytes)
    digest = bytes.fromhex(
        canonical_sha256(
            {
                "plan_id": str(plan.plan_id.value),
                "episode_id": str(plan.episode_id.value),
                "step_key": step.step_key,
            }
        )
    )
    value[6:] = digest[:10]
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return EntityId("workflow_task", UUID(bytes=bytes(value)))


def _task_from_json(value: dict[str, object]) -> WorkflowTask:
    return WorkflowTask(
        EntityId("workflow_task", UUID(str(value["task_id"]))),
        EntityId("decision_episode", UUID(str(value["episode_id"]))),
        str(value["step_key"]),
        str(value["role_id"]),
        RecordedAt.parse(str(value["deadline_at"])),
        WorkflowTaskStatus(str(value["status"])),
        tuple(_ref_from_json(x) for x in cast(list[dict[str, object]], value["input_artifacts"])),
    )


def _result_from_json(value: dict[str, object]) -> WorkflowTaskResult:
    return WorkflowTaskResult(
        EntityId("workflow_task", UUID(str(value["task_id"]))),
        WorkflowTaskStatus(str(value["status"])),
        tuple(_ref_from_json(x) for x in cast(list[dict[str, object]], value.get("artifacts", []))),
        tuple(cast(list[str], value.get("unknowns", []))),
        tuple(cast(list[str], value.get("warnings", []))),
    )


def _resolve_hydrated_task_inputs(
    plan: DelegationPlan, tasks: tuple[WorkflowTask, ...], results: tuple[WorkflowTaskResult, ...]
) -> tuple[WorkflowTask, ...]:
    by_key = {task.step_key: task for task in tasks}
    by_id = {result.task_id: result for result in results}
    resolved: list[WorkflowTask] = []
    for step in plan.steps:
        task = by_key[step.step_key]
        if not step.depends_on or not all(
            by_key[name].status is WorkflowTaskStatus.COMPLETED and by_key[name].task_id in by_id
            for name in step.depends_on
        ):
            resolved.append(task)
            continue
        artifacts = (
            *step.input_artifacts,
            *(ref for name in step.depends_on for ref in by_id[by_key[name].task_id].artifacts),
        )
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("persisted fan-in artifacts are not unique")
        _validate_role_contract(step.role_id, artifacts, ())
        resolved_task = WorkflowTask(
            task.task_id,
            task.episode_id,
            task.step_key,
            task.role_id,
            task.deadline_at,
            task.status,
            artifacts,
        )
        by_key[step.step_key] = resolved_task
        resolved.append(resolved_task)
    return tuple(resolved)


def _assert_observe_plan(plan: DelegationPlan) -> None:
    if type(plan) is not DelegationPlan:
        raise TypeError("durable execution requires a DelegationPlan")
    # Reconstructing guarantees deep fields, dependencies, budgets and outputs
    # still satisfy domain validation even if a caller retained a bad subclass.
    checked = _plan_from_json(_plan_json(plan))
    if checked != plan or any(
        kind in {ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.STRATEGY_CANDIDATE, ArtifactKind.EXECUTION_RECOMMENDATION}
        for step in plan.steps
        for kind in step.required_outputs
    ):
        raise ValueError("only validated observe/research plans are durable in V1")
