from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.research_experiment import (
    ExperimentManager,
    ExperimentPlan,
    ResearchBudget,
    ResearchJobStatus,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def _at(seconds: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds))


def _plan() -> ExperimentPlan:
    return ExperimentPlan(
        EntityId.new("experiment"),
        1,
        SchemaVersion(1, 0),
        EntityId.new("experiment_request"),
        EntityId.new("conversation"),
        _at(),
        _at(60),
        ResearchBudget(1000, 4, 60),
    )


def test_register_start_partial_complete_and_result_returns_to_origin() -> None:
    manager = ExperimentManager()
    plan = _plan()
    queued = manager.register(plan)
    assert queued.status is ResearchJobStatus.QUEUED
    assert len(plan.content_sha256) == 64
    running = manager.start(queued.job_id, _at(1))
    partial = manager.checkpoint(running.job_id, _at(2), tokens=100, tool_calls=1, partial=True)
    assert partial.status is ResearchJobStatus.PARTIAL
    result = manager.complete(partial.job_id, _at(3), EntityId.new("research_result"))
    assert result.status is ResearchJobStatus.SUCCEEDED
    assert manager.result_for_conversation(result.experiment.original_conversation_id) == (result,)


@pytest.mark.parametrize("action", ["cancel", "fail"])
def test_terminal_failure_and_cancel_are_fail_closed(action: str) -> None:
    manager = ExperimentManager()
    job = manager.register(_plan())
    if action == "cancel":
        terminal = manager.cancel(job.job_id, _at(1))
    else:
        terminal = manager.fail(job.job_id, _at(1), "PROVIDER_FAILED")
    assert terminal.status in {ResearchJobStatus.CANCELLED, ResearchJobStatus.FAILED}
    with pytest.raises(ValueError):
        manager.start(job.job_id, _at(2))


def test_budget_and_deadline_fail_closed_and_recovery_requeues_same_plan() -> None:
    manager = ExperimentManager()
    job = manager.register(_plan())
    running = manager.start(job.job_id, _at(1))
    timed_out = manager.checkpoint(running.job_id, _at(2), tokens=1001, tool_calls=0)
    assert timed_out.status is ResearchJobStatus.TIMED_OUT

    recoverable = manager.register(_plan())
    running = manager.start(recoverable.job_id, _at(1))
    running = manager.checkpoint(running.job_id, _at(2), tokens=10, tool_calls=1)
    requeued = manager.recover(running.job_id, _at(3))
    assert requeued.status is ResearchJobStatus.QUEUED
    assert requeued.attempt == 2
    assert requeued.experiment == running.experiment


def test_manager_rejects_trade_like_result_and_invalid_ids() -> None:
    manager = ExperimentManager()
    job = manager.register(_plan())
    running = manager.start(job.job_id, _at(1))
    with pytest.raises(ValueError):
        manager.complete(running.job_id, _at(2), EntityId.new("order"))
    with pytest.raises(ValueError):
        manager.result_for_conversation(EntityId.new("account"))
