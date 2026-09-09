"""V3-002 deterministic autonomy workflow acceptance contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from futures_agent_os.agent_orchestration.v3_durable import (
    STAGE_ORDER,
    AutonomyWorkflowOrchestrator,
    InMemoryAutonomyWorkflowRepository,
    ReferenceKind,
    StageCommand,
    StageDisposition,
    StageResult,
    StateReference,
    TriggerOrigin,
    WorkflowRunStatus,
    WorkflowStage,
)


OUTPUTS = {
    WorkflowStage.SNAPSHOT: (ReferenceKind.SNAPSHOT,),
    WorkflowStage.OPPORTUNITY_SCAN: (ReferenceKind.OPPORTUNITY_SCAN,),
    WorkflowStage.DELEGATION_AND_CHALLENGE: (ReferenceKind.DELEGATION,),
    WorkflowStage.TRADE_PLAN: (ReferenceKind.TRADE_PLAN,),
    WorkflowStage.AUTHORIZATION_PREFLIGHT: (ReferenceKind.AUTHORIZATION_BASIS,),
    WorkflowStage.SIZING_AND_RESERVATION: (ReferenceKind.RISK_RESERVATION,),
    WorkflowStage.FINAL_RECEIPT_GATE: (ReferenceKind.GATE_RECEIPT,),
    WorkflowStage.RISK_AND_EXECUTION: (ReferenceKind.RISK_DECISION, ReferenceKind.EXECUTION),
    WorkflowStage.MONITORING: (ReferenceKind.MONITORING,),
    WorkflowStage.NOTIFICATION_AND_REVIEW: (ReferenceKind.NOTIFICATION, ReferenceKind.REVIEW),
}


def _ref(kind: ReferenceKind) -> StateReference:
    digest = hashlib.sha256(kind.value.encode()).hexdigest()
    return StateReference(kind, f"owner:{kind.value.lower()}", 1, digest)


class Owners:
    def __init__(self, *, interrupt_before: WorkflowStage | None = None, stale: ReferenceKind | None = None) -> None:
        self.interrupt_before = interrupt_before
        self.stale = stale
        self.commands: list[StageCommand] = []
        self.revalidated: list[ReferenceKind] = []

    def execute(self, command: StageCommand) -> StageResult:
        self.commands.append(command)
        if command.stage is self.interrupt_before:
            return StageResult(StageDisposition.INTERRUPT, reason="controlled exception interrupt")
        return StageResult(StageDisposition.ADVANCE, tuple(_ref(kind) for kind in OUTPUTS[command.stage]))

    def revalidate(self, reference: StateReference, *, completed_stage: WorkflowStage, as_of: datetime) -> bool:
        self.revalidated.append(reference.kind)
        return reference.kind is not self.stale


@pytest.mark.parametrize("origin", list(TriggerOrigin))
def test_every_trigger_origin_completes_authorized_cycle_without_user_wait(origin: TriggerOrigin) -> None:
    repository, owners = InMemoryAutonomyWorkflowRepository(), Owners()
    orchestrator = AutonomyWorkflowOrchestrator(repository, owners)
    created = orchestrator.trigger(origin, f"cycle-{origin.value}", {"event": origin.value})

    completed = orchestrator.run(created.run_id, "worker", now=datetime(2026, 9, 8, tzinfo=UTC))

    assert completed.status is WorkflowRunStatus.COMPLETED
    assert completed.stage is WorkflowStage.NOTIFICATION_AND_REVIEW
    assert [command.stage for command in owners.commands] == list(STAGE_ORDER[1:])
    assert all(command.idempotency_key.endswith(command.stage.value) for command in owners.commands)
    assert len(completed.references) == len(ReferenceKind)


@pytest.mark.parametrize("completed_stage", list(STAGE_ORDER[1:-1]))
def test_every_checkpoint_recovers_after_interrupt_and_revalidates_truth(completed_stage: WorkflowStage) -> None:
    repository = InMemoryAutonomyWorkflowRepository()
    next_stage = STAGE_ORDER[STAGE_ORDER.index(completed_stage) + 1]
    first = AutonomyWorkflowOrchestrator(repository, Owners(interrupt_before=next_stage))
    created = first.trigger(TriggerOrigin.SCHEDULE, f"resume-{completed_stage.value}", {"schedule": "hourly"})
    interrupted = first.run(created.run_id, "worker-a", now=datetime(2026, 9, 8, tzinfo=UTC))
    assert interrupted.status is WorkflowRunStatus.INTERRUPTED
    assert interrupted.stage is completed_stage

    restarted_owners = Owners()
    restarted = AutonomyWorkflowOrchestrator(repository, restarted_owners)
    completed = restarted.run(created.run_id, "worker-b", now=datetime(2026, 9, 8, tzinfo=UTC))

    assert completed.status is WorkflowRunStatus.COMPLETED
    acquired_truth = {
        reference.kind
        for reference in interrupted.references
        if reference.kind
        in {
            ReferenceKind.SNAPSHOT,
            ReferenceKind.TRADE_PLAN,
            ReferenceKind.AUTHORIZATION_BASIS,
            ReferenceKind.GATE_RECEIPT,
            ReferenceKind.RISK_DECISION,
        }
    }
    assert set(restarted_owners.revalidated) == acquired_truth


@pytest.mark.parametrize(
    "stale",
    [
        ReferenceKind.SNAPSHOT,
        ReferenceKind.TRADE_PLAN,
        ReferenceKind.AUTHORIZATION_BASIS,
        ReferenceKind.GATE_RECEIPT,
        ReferenceKind.RISK_DECISION,
    ],
)
def test_recovery_fails_closed_before_effect_when_trading_truth_is_stale(stale: ReferenceKind) -> None:
    repository = InMemoryAutonomyWorkflowRepository()
    first = AutonomyWorkflowOrchestrator(repository, Owners(interrupt_before=WorkflowStage.MONITORING))
    created = first.trigger(TriggerOrigin.MARKET, f"stale-cycle-{stale.value}", {"tick": "market-event"})
    interrupted = first.run(created.run_id, "worker-a", now=datetime(2026, 9, 8, tzinfo=UTC))
    assert interrupted.reference(stale) is not None

    owners = Owners(stale=stale)
    with pytest.raises(ValueError, match=f"stale {stale.value}"):
        AutonomyWorkflowOrchestrator(repository, owners).run(
            created.run_id, "worker-b", now=datetime(2026, 9, 8, tzinfo=UTC)
        )
    assert owners.commands == []


def test_trigger_replay_is_idempotent_but_conflicting_payload_is_rejected() -> None:
    orchestrator = AutonomyWorkflowOrchestrator(InMemoryAutonomyWorkflowRepository(), Owners())
    first = orchestrator.trigger(TriggerOrigin.SYSTEM, "same", {"health": "ok"})
    assert orchestrator.trigger(TriggerOrigin.SYSTEM, "same", {"health": "ok"}) == first
    with pytest.raises(ValueError, match="conflicting trigger replay"):
        orchestrator.trigger(TriggerOrigin.SYSTEM, "same", {"health": "degraded"})


def test_checkpoint_accepts_only_owner_references_and_fenced_workers() -> None:
    repository = InMemoryAutonomyWorkflowRepository()
    created = repository.create(TriggerOrigin.ACCOUNT, "fence", {"account": "sim"})
    now = datetime(2026, 9, 8, tzinfo=UTC)
    claimed = repository.claim(created.run_id, "worker-a", lease_seconds=30, now=now)
    with pytest.raises(RuntimeError, match="another worker"):
        repository.claim(created.run_id, "worker-b", lease_seconds=30, now=now)
    snapshot = (_ref(ReferenceKind.SNAPSHOT),)
    updated = repository.checkpoint(claimed, "worker-a", WorkflowStage.SNAPSHOT, snapshot, now=now)
    with pytest.raises(RuntimeError, match="stale workflow fencing"):
        repository.checkpoint(claimed, "worker-a", WorkflowStage.SNAPSHOT, snapshot, now=now)
    assert updated.references == snapshot


def test_checkpoint_reference_is_closed_and_contains_no_business_payload() -> None:
    value = _ref(ReferenceKind.RISK_DECISION).to_dict()
    assert set(value) == {"kind", "object_id", "version", "sha256"}
    with pytest.raises(ValueError, match="fields are not exact"):
        StateReference.hydrate({**value, "decision": "PERMIT"})


def test_stage_cannot_omit_its_output_or_smuggle_future_business_references() -> None:
    class SmugglingOwners(Owners):
        def execute(self, command: StageCommand) -> StageResult:
            return StageResult(
                StageDisposition.ADVANCE,
                (_ref(ReferenceKind.SNAPSHOT), _ref(ReferenceKind.AUTHORIZATION_BASIS)),
            )

    repository = InMemoryAutonomyWorkflowRepository()
    orchestrator = AutonomyWorkflowOrchestrator(repository, SmugglingOwners())
    created = orchestrator.trigger(TriggerOrigin.USER, "closed-stage", {"intent": "scan"})
    interrupted = orchestrator.run(created.run_id, "worker", now=datetime(2026, 9, 8, tzinfo=UTC))
    assert interrupted.status is WorkflowRunStatus.INTERRUPTED
    assert interrupted.stage is WorkflowStage.TRIGGERED
    assert interrupted.references == ()
    assert "owner references are not exact" in (interrupted.last_error or "")
