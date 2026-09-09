from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.agent_orchestration import (
    AgentTaskEnvelope,
    ArtifactRef,
    ArtifactKind,
    CATALOG_VERSION,
    StrategyAgent,
    StrategyAgentResult,
    StrategyTaskSources,
    TriggerSource,
    definition_for,
    StrategyDelegationOwner,
)
from futures_agent_os.agent_orchestration.v3_durable import StageCommand, WorkflowStage, TriggerOrigin
from futures_agent_os.agent_orchestration.v3_durable import (
    STAGE_ORDER,
    AutonomyWorkflowOrchestrator,
    InMemoryAutonomyWorkflowRepository,
    ReferenceKind,
    StageDisposition,
    StageResult,
    StateReference,
    WorkflowRunStatus,
)
import hashlib
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext


def fixture():
    now = RecordedAt.from_datetime(datetime(2026, 9, 8, tzinfo=UTC))
    ref = ArtifactRef(
        EntityId.new("hypothesis"), ArtifactKind.HYPOTHESIS, SchemaVersion(1, 0), "sha256:" + "a" * 64, now, now
    )
    correlation = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation,
        TraceContext(correlation, EntityId.new("trace")),
        "strategy",
        CATALOG_VERSION,
        "assess hypothesis",
        "produce candidate",
        (TriggerSource.MARKET,),
        (ref,),
        (),
        (),
        definition_for("strategy").budget,
        (ArtifactKind.STRATEGY_CANDIDATE,),
        now,
        RecordedAt.from_datetime(now.value + timedelta(minutes=1)),
    )
    proposal = StrategyAgent().decide_no_trade(
        thesis="no edge", invalidation="new evidence", evidence=(str(ref.artifact_id),), reason="insufficient support"
    )
    return task, StrategyTaskSources((ref,)), proposal


def test_strategy_package_binds_real_task_and_evidence():
    task, sources, proposal = fixture()
    result = StrategyAgent().package(task, sources, proposal)
    assert result.candidate == proposal
    assert result.source_refs == task.input_artifacts
    assert result.as_of == task.as_of and result.expires_at == task.expires_at


def test_strategy_package_rejects_unprovided_evidence():
    task, sources, proposal = fixture()
    with pytest.raises(ValueError, match="input artifact"):
        StrategyAgent().package(task, sources, replace(proposal, evidence=("invented",)))


def test_strategy_package_rejects_wrong_role_and_tool():
    task, sources, proposal = fixture()
    with pytest.raises(ValueError):
        StrategyAgent().package(replace(task, assigned_role_id="research"), sources, proposal)
    with pytest.raises(ValueError):
        StrategyAgent().package(replace(task, allowed_tools=("submit_trade_plan",)), sources, proposal)


def test_strategy_sources_reject_future_creation():
    task, sources, proposal = fixture()
    future_ref = replace(sources.artifacts[0], created_at=task.expires_at)
    with pytest.raises(ValueError, match="unavailable"):
        StrategyAgent().package(
            replace(task, input_artifacts=(future_ref,)), StrategyTaskSources((future_ref,)), proposal
        )


def test_strategy_result_is_injected_at_durable_delegation_boundary():
    task, sources, proposal = fixture()
    result = StrategyAgent().package(task, sources, proposal)
    owner = StrategyDelegationOwner(_Downstream(), result)
    command = StageCommand(
        __import__("uuid").uuid4(), WorkflowStage.DELEGATION_AND_CHALLENGE, "stable", TriggerOrigin.MARKET, ()
    )
    stage_result = owner.execute(command)
    assert stage_result.references[0].kind.value == "DELEGATION"


def test_strategy_result_cannot_bypass_packaging_lineage_guards():
    task, sources, proposal = fixture()
    with pytest.raises(ValueError, match="evidence"):
        StrategyAgentResult(
            replace(proposal, evidence=("invented",)),
            None,
            sources.artifacts,
            task.as_of,
            task.expires_at,
        )
    with pytest.raises(ValueError, match="expiry"):
        StrategyAgentResult(proposal, None, sources.artifacts, task.as_of, task.as_of)
    with pytest.raises(TypeError, match="validated"):
        StrategyDelegationOwner(_Downstream(), object())


def test_strategy_delegation_digest_is_content_and_lineage_stable():
    task, sources, proposal = fixture()
    first = StrategyAgent().package(task, sources, proposal)
    second = StrategyAgent().package(task, sources, proposal)
    assert first.content_sha256() == second.content_sha256()


class _Downstream:
    def execute(self, command):
        raise AssertionError("strategy stage must be handled by strategy adapter")

    def revalidate(self, reference, *, completed_stage, as_of):
        return True


class _AllOwners:
    def __init__(self):
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        required = {
            WorkflowStage.SNAPSHOT: (ReferenceKind.SNAPSHOT,),
            WorkflowStage.OPPORTUNITY_SCAN: (ReferenceKind.OPPORTUNITY_SCAN,),
            WorkflowStage.TRADE_PLAN: (ReferenceKind.TRADE_PLAN,),
            WorkflowStage.AUTHORIZATION_PREFLIGHT: (ReferenceKind.AUTHORIZATION_BASIS,),
            WorkflowStage.SIZING_AND_RESERVATION: (ReferenceKind.RISK_RESERVATION,),
            WorkflowStage.FINAL_RECEIPT_GATE: (ReferenceKind.GATE_RECEIPT,),
            WorkflowStage.RISK_AND_EXECUTION: (ReferenceKind.RISK_DECISION, ReferenceKind.EXECUTION),
            WorkflowStage.MONITORING: (ReferenceKind.MONITORING,),
            WorkflowStage.NOTIFICATION_AND_REVIEW: (ReferenceKind.NOTIFICATION, ReferenceKind.REVIEW),
        }
        refs = tuple(
            StateReference(kind, f"owner:{kind.value.lower()}", 1, hashlib.sha256(kind.value.encode()).hexdigest())
            for kind in required[command.stage]
        )
        return StageResult(StageDisposition.ADVANCE, refs)

    def revalidate(self, reference, *, completed_stage, as_of):
        return True


def test_strategy_delegation_owner_completes_full_durable_cycle():
    task, sources, proposal = fixture()
    result = StrategyAgent().package(task, sources, proposal)
    downstream = _AllOwners()
    owner = StrategyDelegationOwner(downstream, result)
    orchestrator = AutonomyWorkflowOrchestrator(InMemoryAutonomyWorkflowRepository(), owner)
    created = orchestrator.trigger(TriggerOrigin.MARKET, "strategy-golden", {"event": "market"})
    completed = orchestrator.run(created.run_id, "strategy-worker")
    assert completed.status is WorkflowRunStatus.COMPLETED
    assert completed.reference(ReferenceKind.DELEGATION) is not None
    assert [item.stage for item in downstream.commands] == [*STAGE_ORDER[1:3], *STAGE_ORDER[4:]]
