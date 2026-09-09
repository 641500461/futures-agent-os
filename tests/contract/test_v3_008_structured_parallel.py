from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Event, Lock
from time import monotonic

import pytest

from futures_agent_os.agent_orchestration import (
    AgentRoleId,
    ArtifactKind,
    ArtifactRef,
    AutonomousQuantPM,
    CollaborationBudget,
    CollaborationPlan,
    CollaborationTask,
    ConflictRule,
    ParallelTaskStatus,
    PMSynthesisDecision,
    SpecialistOutput,
    SpecialistTaskLimit,
    StructuredClaim,
    StructuredParallelOrchestrator,
    TaskBudgetMeter,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


AS_OF = RecordedAt.from_datetime(datetime(2026, 9, 8, tzinfo=UTC))
EXPIRES = RecordedAt.from_datetime(AS_OF.value + timedelta(minutes=5))


def _ref(kind: ArtifactKind, digit: str = "a") -> ArtifactRef:
    return ArtifactRef(
        EntityId.new("artifact"),
        kind,
        SchemaVersion(1, 0),
        "sha256:" + digit * 64,
        AS_OF,
        AS_OF,
    )


def _limit(*, wall: int = 500, tokens: int = 10, tools: int = 1, compute: int = 2) -> SpecialistTaskLimit:
    return SpecialistTaskLimit(tokens, tools, wall, compute)


def _task(
    key: str,
    role: AgentRoleId,
    kind: ArtifactKind,
    *,
    dependencies: tuple[str, ...] = (),
    limits: SpecialistTaskLimit | None = None,
) -> CollaborationTask:
    return CollaborationTask(
        key, role, (_ref(ArtifactKind.MARKET_SNAPSHOT),), kind, ("read_artifact",), dependencies, limits or _limit()
    )


def _two_wave_tasks() -> tuple[CollaborationTask, ...]:
    first = (
        _task("regime", AgentRoleId.MARKET_REGIME, ArtifactKind.MARKET_STATE_ASSESSMENT),
        _task("portfolio", AgentRoleId.PORTFOLIO, ArtifactKind.PORTFOLIO_PROPOSAL),
    )
    dependencies = ("regime", "portfolio")
    return first + (
        _task("risk", AgentRoleId.RISK_ANALYST, ArtifactKind.RISK_ASSESSMENT, dependencies=dependencies),
        _task("critic", AgentRoleId.PRE_TRADE_CRITIC, ArtifactKind.PRE_TRADE_CRITIQUE, dependencies=dependencies),
        _task(
            "execution",
            AgentRoleId.EXECUTION_ADVISOR,
            ArtifactKind.EXECUTION_RECOMMENDATION,
            dependencies=dependencies,
        ),
    )


def _plan(tasks: tuple[CollaborationTask, ...] | None = None, **budget_changes: int) -> CollaborationPlan:
    selected = tasks or _two_wave_tasks()
    budget_values = {
        "max_tasks": len(selected),
        "max_parallel_tasks": min(3, len(selected)),
        "max_rounds": 2,
        "max_tokens": sum(task.limits.max_tokens for task in selected),
        "max_tool_calls": sum(task.limits.max_tool_calls for task in selected),
        "max_wall_millis": 2_000,
        "max_compute_units": sum(task.limits.max_compute_units for task in selected),
    }
    budget_values.update(budget_changes)
    return CollaborationPlan(selected, CollaborationBudget(**budget_values), AS_OF, EXPIRES)


def _output(
    task: CollaborationTask,
    *,
    status: ParallelTaskStatus = ParallelTaskStatus.COMPLETED,
    claims: tuple[StructuredClaim, ...] = (),
    digit: str = "b",
) -> SpecialistOutput:
    artifact = (
        _ref(task.output_kind, digit) if status in {ParallelTaskStatus.COMPLETED, ParallelTaskStatus.PARTIAL} else None
    )
    return SpecialistOutput(
        task.task_key,
        task.role,
        status,
        artifact,
        f"{task.task_key} conclusion",
        claims,
        (_ref(ArtifactKind.MARKET_SNAPSHOT, "c"),),
        (),
        ("source unavailable",) if status in {ParallelTaskStatus.DEFERRED, ParallelTaskStatus.FAILED} else (),
        (),
        Decimal("0.70"),
        EXPIRES,
    )


def test_two_dag_waves_run_in_parallel_and_fan_in_in_plan_order() -> None:
    plan = _plan()
    first_barrier = Barrier(2)
    second_barrier = Barrier(3)
    completed: set[str] = set()
    lock = Lock()
    active = 0
    peak = 0

    def worker(task: CollaborationTask, _token, meter: TaskBudgetMeter) -> SpecialistOutput:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if task.dependencies:
                assert completed.issuperset(task.dependencies)
        (second_barrier if task.dependencies else first_barrier).wait(timeout=1)
        meter.consume(tokens=3, tool_calls=1, compute_units=1)
        with lock:
            active -= 1
            completed.add(task.task_key)
        return _output(task)

    result = StructuredParallelOrchestrator().run(plan, {task.task_key: worker for task in plan.tasks})

    assert tuple(item.task.task_key for item in result.executions) == tuple(task.task_key for task in plan.tasks)
    assert all(item.status is ParallelTaskStatus.COMPLETED for item in result.executions)
    assert result.rounds == 2
    assert peak == 3
    assert result.total_usage.tokens == 15
    assert result.total_usage.tool_calls == 5


def test_plan_rejects_cycles_unknown_dependencies_pit_drift_and_reserved_budget_overruns() -> None:
    one = _task("one", AgentRoleId.MARKET_REGIME, ArtifactKind.MARKET_STATE_ASSESSMENT, dependencies=("two",))
    two = _task("two", AgentRoleId.PORTFOLIO, ArtifactKind.PORTFOLIO_PROPOSAL, dependencies=("one",))
    with pytest.raises(ValueError, match="cycle"):
        _plan((one, two))
    with pytest.raises(ValueError, match="unknown"):
        _plan((replace(one, dependencies=("missing",)),))
    with pytest.raises(ValueError, match="token reservations"):
        _plan((replace(one, dependencies=()),), max_tokens=9)
    stale = replace(
        one,
        dependencies=(),
        input_refs=(replace(one.input_refs[0], as_of=RecordedAt.from_datetime(AS_OF.value - timedelta(seconds=1))),),
    )
    with pytest.raises(ValueError, match="PIT cutoff"):
        _plan((stale,))
    chain = (
        replace(one, dependencies=()),
        replace(two, dependencies=("one",)),
        _task("three", AgentRoleId.RISK_ANALYST, ArtifactKind.RISK_ASSESSMENT, dependencies=("two",)),
    )
    with pytest.raises(ValueError, match="loop hard limit"):
        _plan(chain, max_rounds=2)


@pytest.mark.parametrize("dimension", ["tokens", "tool_calls", "compute_units"])
def test_runtime_meter_hard_limits_exhaust_task_and_skip_dependants(dimension: str) -> None:
    root = _task("root", AgentRoleId.MARKET_REGIME, ArtifactKind.MARKET_STATE_ASSESSMENT)
    child = _task("child", AgentRoleId.RISK_ANALYST, ArtifactKind.RISK_ASSESSMENT, dependencies=("root",))
    plan = _plan((root, child))

    def over_budget(task: CollaborationTask, _token, meter: TaskBudgetMeter) -> SpecialistOutput:
        meter.consume(**{dimension: getattr(task.limits, f"max_{dimension}") + 1})
        return _output(task)

    result = StructuredParallelOrchestrator().run(plan, {"root": over_budget, "child": over_budget})
    assert tuple(item.status for item in result.executions) == (
        ParallelTaskStatus.BUDGET_EXHAUSTED,
        ParallelTaskStatus.SKIPPED,
    )


def test_task_timeout_is_cancelled_and_dependants_fail_closed() -> None:
    root = _task(
        "root",
        AgentRoleId.MARKET_REGIME,
        ArtifactKind.MARKET_STATE_ASSESSMENT,
        limits=_limit(wall=60),
    )
    child = _task("child", AgentRoleId.RISK_ANALYST, ArtifactKind.RISK_ASSESSMENT, dependencies=("root",))
    plan = _plan((root, child), max_wall_millis=500)

    def cooperative(task: CollaborationTask, token, _meter: TaskBudgetMeter) -> SpecialistOutput:
        while not token.cancelled:
            Event().wait(0.005)
        token.raise_if_cancelled()
        return _output(task)

    result = StructuredParallelOrchestrator().run(plan, {"root": cooperative, "child": cooperative})
    assert tuple(item.status for item in result.executions) == (
        ParallelTaskStatus.TIMED_OUT,
        ParallelTaskStatus.SKIPPED,
    )
    assert result.total_usage.wall_millis < 500


def test_global_deadline_returns_without_waiting_for_non_cooperative_worker() -> None:
    release = Event()
    task = _task(
        "stuck",
        AgentRoleId.MARKET_REGIME,
        ArtifactKind.MARKET_STATE_ASSESSMENT,
        limits=_limit(wall=80),
    )
    plan = _plan((task,), max_wall_millis=80, max_rounds=1)

    def stuck(task: CollaborationTask, _token, _meter: TaskBudgetMeter) -> SpecialistOutput:
        release.wait(timeout=1)
        return _output(task)

    started = monotonic()
    try:
        result = StructuredParallelOrchestrator().run(plan, {"stuck": stuck})
        assert result.executions[0].status is ParallelTaskStatus.TIMED_OUT
        assert monotonic() - started < 0.5
    finally:
        release.set()


def test_invalid_worker_mapping_and_output_identity_fail_closed() -> None:
    task = _task("regime", AgentRoleId.MARKET_REGIME, ArtifactKind.MARKET_STATE_ASSESSMENT)
    plan = _plan((task,), max_rounds=1)
    orchestrator = StructuredParallelOrchestrator()
    with pytest.raises(ValueError, match="exactly match"):
        orchestrator.run(plan, {})

    def wrong_identity(_task, _token, _meter) -> SpecialistOutput:
        return replace(_output(task), task_key="another")

    result = orchestrator.run(plan, {"regime": wrong_identity})
    assert result.executions[0].status is ParallelTaskStatus.FAILED
    assert result.executions[0].output is None
    assert "identity" in (result.executions[0].reason or "")

    future = RecordedAt.from_datetime(AS_OF.value + timedelta(seconds=1))
    future_evidence = replace(_ref(ArtifactKind.MARKET_SNAPSHOT), created_at=future)

    def future_claim(_task, _token, _meter) -> SpecialistOutput:
        claim = StructuredClaim("fact:settlement", "100", "RB2510", (future_evidence,))
        return _output(task, claims=(claim,))

    result = orchestrator.run(plan, {"regime": future_claim})
    assert result.executions[0].status is ParallelTaskStatus.FAILED
    assert "PIT cutoff" in (result.executions[0].reason or "")


def test_conflicts_preserve_all_positions_and_apply_authority_rules_without_voting() -> None:
    evidence = _ref(ArtifactKind.MARKET_SNAPSHOT, "d")
    tasks = (
        _task("strategy", AgentRoleId.STRATEGY, ArtifactKind.TRADE_PLAN_DRAFT),
        _task("portfolio", AgentRoleId.PORTFOLIO, ArtifactKind.PORTFOLIO_PROPOSAL),
        _task("critic", AgentRoleId.PRE_TRADE_CRITIC, ArtifactKind.PRE_TRADE_CRITIQUE),
    )
    plan = _plan(tasks, max_rounds=1)
    values = {"strategy": "increase", "portfolio": "reduce", "critic": "block"}

    def disagree(task: CollaborationTask, _token, _meter) -> SpecialistOutput:
        claim = StructuredClaim("target_exposure", values[task.task_key], "RB2510", (evidence,))
        return replace(_output(task, claims=(claim,)), unknowns=(f"{task.task_key} unknown",))

    result = StructuredParallelOrchestrator().run(plan, {task.task_key: disagree for task in tasks})
    conflict = result.conflicts[0]
    assert conflict.subject == "target_exposure"
    assert conflict.rule is ConflictRule.CRITIC_BLOCKS_OR_DEFER
    assert tuple(position.value for position in conflict.positions) == ("increase", "reduce", "block")
    assert all(position.evidence_refs == (evidence,) for position in conflict.positions)
    assert all(position.as_of == AS_OF and position.scope == "RB2510" for position in conflict.positions)
    assert not ({"winner", "votes", "vote_count"} & {field.name for field in fields(type(conflict))})

    with pytest.raises(ValueError, match="NO_TRADE or DEFER"):
        AutonomousQuantPM().synthesize(
            result,
            decision=PMSynthesisDecision.TRADE_PLAN_DRAFT,
            rationale="majority should never authorize a plan",
            evidence_refs=(evidence,),
        )
    synthesis = AutonomousQuantPM().synthesize(
        result,
        decision=PMSynthesisDecision.DEFER,
        rationale="critic conflict requires deterministic recheck",
        evidence_refs=(evidence,),
    )
    assert synthesis.conflicts == result.conflicts


def test_collaboration_contract_exposes_no_peer_chat_or_free_message_surface() -> None:
    forbidden = {"recipient", "peer", "message", "chat", "send_to"}
    for contract in (CollaborationTask, SpecialistOutput, StructuredClaim):
        assert not forbidden.intersection(field.name for field in fields(contract))


def test_clean_complete_fan_in_can_create_a_draft_synthesis() -> None:
    task = _task("regime", AgentRoleId.MARKET_REGIME, ArtifactKind.MARKET_STATE_ASSESSMENT)
    result = StructuredParallelOrchestrator().run(
        _plan((task,), max_rounds=1), {"regime": lambda task, _token, _meter: _output(task)}
    )
    synthesis = AutonomousQuantPM().synthesize(
        result,
        decision=PMSynthesisDecision.TRADE_PLAN_DRAFT,
        rationale="all bounded specialists completed with no conflict",
        evidence_refs=(_ref(ArtifactKind.MARKET_SNAPSHOT),),
    )
    assert synthesis.decision is PMSynthesisDecision.TRADE_PLAN_DRAFT
