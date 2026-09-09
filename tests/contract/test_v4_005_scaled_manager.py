from datetime import UTC, datetime, timedelta
import pytest
from futures_agent_os.research_experiment import (
    BatchStatus,
    ExperimentPlan,
    ResearchBudget,
    ScaledExperimentManager,
    ScaledExperimentPlan,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def at(n):
    return RecordedAt(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=n))


def plan(i, p=0):
    return ExperimentPlan(
        EntityId.deterministic("experiment", str(i)),
        1,
        SchemaVersion(1, 0),
        EntityId.deterministic("experiment_request", str(i)),
        EntityId.deterministic("conversation", "c"),
        at(0),
        at(100),
        ResearchBudget(100, 10, 100),
        p,
    )


def batch():
    return ScaledExperimentPlan(
        EntityId.deterministic("experiment_batch", "b"), 1, (plan("a", 1), plan("b", 0)), ResearchBudget(200, 20, 200)
    )


def test_priority_budget_and_recovery():
    m = ScaledExperimentManager()
    r = m.schedule(batch().batch_id, at(1)) if False else m.register(batch())
    r = m.schedule(r.batch.batch_id, at(1))
    assert [j.experiment.priority for j in r.jobs] == [1, 0]
    r = m.checkpoint(r.batch.batch_id, at(2), tokens=5, tool_calls=1)
    assert r.consumed_tokens == 5
    r = m.recover(r.batch.batch_id, at(3))
    assert r.status is BatchStatus.QUEUED and all(j.attempt == 1 for j in r.jobs)


def test_exact_budget_and_fail_closed_finalize():
    m = ScaledExperimentManager()
    r = m.register(batch())
    m.schedule(r.batch.batch_id, at(1))
    r = m.checkpoint(r.batch.batch_id, at(2), tokens=201, tool_calls=0)
    assert r.status is BatchStatus.FAILED
    with pytest.raises(ValueError):
        m.finalize(r.batch.batch_id, at(3))


def test_cancel_produces_no_evidence():
    m = ScaledExperimentManager()
    r = m.register(batch())
    m.schedule(r.batch.batch_id, at(1))
    r = m.cancel(r.batch.batch_id, at(2))
    assert r.status is BatchStatus.CANCELLED and not r.evidence_refs and not r.complete
