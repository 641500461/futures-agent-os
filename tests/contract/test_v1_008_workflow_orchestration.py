"""Acceptance contracts for V1-008's read-only durable research workflow."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.agent_orchestration import (
    AgentBudget,
    AgentRoleId,
    ArtifactKind,
    ArtifactRef,
    CycleTrigger,
    DelegationPlan,
    DelegationStep,
    MainAgent,
    TriggerSource,
    WorkflowOrchestrator,
    WorkflowTaskResult,
    WorkflowTaskStatus,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 24, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _ref(kind: ArtifactKind = ArtifactKind.MARKET_SNAPSHOT) -> ArtifactRef:
    return ArtifactRef(EntityId.new("artifact"), kind, SchemaVersion(1, 0), "sha256:" + "a" * 64, _at(1), _at())


def _plan(cycle_id: EntityId, episode_id: EntityId) -> DelegationPlan:
    regime = DelegationStep(
        "regime",
        AgentRoleId.MARKET_REGIME.value,
        (_ref(ArtifactKind.MARKET_SNAPSHOT),),
        (ArtifactKind.MARKET_STATE_ASSESSMENT,),
        AgentBudget(4, 16, 12_000, 120),
        (),
    )
    research = DelegationStep(
        "research",
        AgentRoleId.RESEARCH.value,
        (),
        (ArtifactKind.HYPOTHESIS, ArtifactKind.EVIDENCE_SYNTHESIS, ArtifactKind.EXPERIMENT_REQUEST),
        AgentBudget(6, 24, 18_000, 300, 2),
        ("regime",),
    )
    return DelegationPlan(
        EntityId.new("delegation_plan"),
        cycle_id,
        episode_id,
        _at(),
        _at(20),
        (regime, research),
        AgentBudget(12, 48, 36_000, 600, 2),
    )


def test_data_is_a_versioned_trigger_and_main_is_observe_only() -> None:
    assert TriggerSource.DATA.value == "DATA"
    main = MainAgent()
    assert main.create_delegation_plan is not None
    forbidden = {"trade_plan", "order", "fill", "position", "ledger", "mandate", "approval", "strategy_candidate"}
    assert not (set(main.forbidden_authority_terms) & {""})
    assert forbidden <= set(main.forbidden_authority_terms)


def test_duplicate_trigger_creates_one_cycle_and_one_episode_then_recovers() -> None:
    orchestrator = WorkflowOrchestrator()
    trigger = CycleTrigger(TriggerSource.DATA, "dataset:CU:2026-08-24T08:00Z", _at(), (_ref(),))
    first = orchestrator.start_cycle(trigger, _at(30))
    second = orchestrator.start_cycle(trigger, _at(30))
    assert second.cycle_id == first.cycle_id
    episode = orchestrator.start_episode(first.cycle_id, "CU:daily", _at(30))
    assert orchestrator.start_episode(first.cycle_id, "CU:daily", _at(30)).episode_id == episode.episode_id
    assert orchestrator.recover(_at(2)) == (first,)


def test_deterministic_fan_out_fan_in_timeout_cancellation_and_budget_are_bounded() -> None:
    orchestrator = WorkflowOrchestrator()
    cycle = orchestrator.start_cycle(CycleTrigger(TriggerSource.SCHEDULE, "scan:CU:1", _at(), (_ref(),)), _at(20))
    episode = orchestrator.start_episode(cycle.cycle_id, "CU:daily", _at(20))
    plan = _plan(cycle.cycle_id, episode.episode_id)
    tasks = orchestrator.accept_delegation_plan(plan)
    assert tuple(task.step_key for task in tasks) == ("regime", "research")
    assert orchestrator.ready_tasks(episode.episode_id, _at(1)) == (tasks[0],)

    with pytest.raises(ValueError, match="dependencies"):
        orchestrator.complete_task(
            episode.episode_id,
            WorkflowTaskResult(
                tasks[1].task_id,
                WorkflowTaskStatus.COMPLETED,
                (
                    _ref(ArtifactKind.HYPOTHESIS),
                    _ref(ArtifactKind.EVIDENCE_SYNTHESIS),
                    _ref(ArtifactKind.EXPERIMENT_REQUEST),
                ),
                (),
                (),
            ),
            _at(1),
        )

    regime_output = _ref(ArtifactKind.MARKET_STATE_ASSESSMENT)
    regime_result = WorkflowTaskResult(tasks[0].task_id, WorkflowTaskStatus.COMPLETED, (regime_output,), (), ())
    orchestrator.complete_task(episode.episode_id, regime_result, _at(1))
    research_task = orchestrator.ready_tasks(episode.episode_id, _at(1))
    assert len(research_task) == 1 and research_task[0].input_artifacts == (regime_output,)
    orchestrator.cancel_episode(episode.episode_id, "user_cancel", _at(4))
    assert orchestrator.ready_tasks(episode.episode_id, _at(4)) == ()
    assert orchestrator.episode(episode.episode_id).terminal_reason == "user_cancel"

    with pytest.raises(ValueError, match="budget"):
        replace(plan, cycle_budget=AgentBudget(1, 1, 1, 1))
    with pytest.raises(ValueError, match="future"):
        replace(plan, expires_at=_at())
    with pytest.raises(ValueError, match="future role"):
        replace(plan.steps[0], role_id=AgentRoleId.STRATEGY.value)


def test_failure_recursively_skips_descendants_and_closes_without_a_poll() -> None:
    orchestrator = WorkflowOrchestrator()
    cycle = orchestrator.start_cycle(CycleTrigger(TriggerSource.MARKET, "failure:CU", _at(), (_ref(),)), _at(20))
    episode = orchestrator.start_episode(cycle.cycle_id, "CU:failure", _at(20))
    tasks = orchestrator.accept_delegation_plan(_plan(cycle.cycle_id, episode.episode_id))
    orchestrator.complete_task(
        episode.episode_id,
        WorkflowTaskResult(tasks[0].task_id, WorkflowTaskStatus.FAILED, (), (), ("source unavailable",)),
        _at(1),
    )
    assert orchestrator.episode(episode.episode_id).status.name == "DEFERRED"
    assert orchestrator._tasks[tasks[1].task_id].status is WorkflowTaskStatus.SKIPPED


def test_main_never_owns_durable_schedule_or_effectful_outputs() -> None:
    source = __import__("inspect").getsource(MainAgent)
    assert "Postgres" not in source and "repository" not in source.lower()
    assert "TradePlan" not in source and "StrategyCandidate" not in source


def test_catalog_exact_role_boundaries_and_expired_empty_cycle_fail_closed() -> None:
    with pytest.raises(ValueError, match="output artifact"):
        DelegationStep(
            "bad-regime",
            AgentRoleId.MARKET_REGIME.value,
            (_ref(),),
            (ArtifactKind.HYPOTHESIS,),
            AgentBudget(1, 1, 1, 1),
            (),
        )
    with pytest.raises(ValueError, match="output artifact"):
        DelegationStep(
            "bad-research",
            AgentRoleId.RESEARCH.value,
            (_ref(ArtifactKind.MARKET_STATE_ASSESSMENT),),
            (ArtifactKind.MARKET_STATE_ASSESSMENT,),
            AgentBudget(1, 1, 1, 1),
            (),
        )
    orchestrator = WorkflowOrchestrator()
    cycle = orchestrator.start_cycle(CycleTrigger(TriggerSource.DATA, "empty-cycle", _at(), (_ref(),)), _at(1))
    assert orchestrator.recover(_at(1)) == ()
    with pytest.raises(ValueError, match="running autonomy cycle"):
        orchestrator.start_episode(cycle.cycle_id, "too-late", _at(2))
