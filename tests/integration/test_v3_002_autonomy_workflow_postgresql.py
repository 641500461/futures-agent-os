"""V3-002 PostgreSQL restart, idempotency, and fencing acceptance."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from futures_agent_os.agent_orchestration.v3_durable import (
    STAGE_ORDER,
    AutonomyWorkflowOrchestrator,
    PostgresAutonomyWorkflowRepository,
    ReferenceKind,
    StageCommand,
    StageDisposition,
    StageResult,
    StateReference,
    TriggerOrigin,
    WorkflowRunStatus,
    WorkflowStage,
)
from futures_agent_os.agent_orchestration.strategy_agent import (
    StrategyAgent,
    StrategyAgentResult,
    StrategyDelegationOwner,
)
from futures_agent_os.agent_orchestration.contracts import ArtifactKind, ArtifactRef
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion

DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")

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


def _upgrade() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True)


def _ref(command: StageCommand, kind: ReferenceKind) -> StateReference:
    object_id = f"{kind.value.lower()}:{command.run_id}"
    return StateReference(kind, object_id, 1, hashlib.sha256(object_id.encode()).hexdigest())


class DurableOwners:
    """Represents owner services whose stable command keys survive worker loss."""

    def __init__(self, effects: dict[str, StageResult], fail_once_at: WorkflowStage | None = None) -> None:
        self.effects = effects
        self.fail_once_at = fail_once_at
        self.failed = False
        self.revalidated: list[ReferenceKind] = []

    def execute(self, command: StageCommand) -> StageResult:
        result = self.effects.setdefault(
            command.idempotency_key,
            StageResult(StageDisposition.ADVANCE, tuple(_ref(command, kind) for kind in OUTPUTS[command.stage])),
        )
        if command.stage is self.fail_once_at and not self.failed:
            self.failed = True
            raise ConnectionError("worker lost after owner command committed")
        return result

    def revalidate(self, reference: StateReference, *, completed_stage: WorkflowStage, as_of: datetime) -> bool:
        self.revalidated.append(reference.kind)
        return True


@pytest.mark.parametrize("fail_at", list(STAGE_ORDER[1:]))
def test_restart_revalidates_and_retries_owner_command_without_duplicate_effect(fail_at: WorkflowStage) -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "")
    effects: dict[str, StageResult] = {}
    first_owners = DurableOwners(effects, fail_once_at=fail_at)
    first = AutonomyWorkflowOrchestrator(PostgresAutonomyWorkflowRepository(engine), first_owners)
    key = f"restart-{fail_at.value}-{uuid4()}"
    created = first.trigger(TriggerOrigin.SCHEDULE, key, {"schedule_ref": "hourly-v1"})
    interrupted = first.run(created.run_id, "worker-before-restart")
    assert interrupted.status is WorkflowRunStatus.INTERRUPTED
    expected_checkpoint = STAGE_ORDER[STAGE_ORDER.index(fail_at) - 1]
    assert interrupted.stage is expected_checkpoint
    assert len(effects) == STAGE_ORDER.index(fail_at)  # failed effect already committed under its stable key

    engine.dispose()
    restarted_engine = create_engine(DATABASE_URL or "")
    restarted_owners = DurableOwners(effects)
    completed = AutonomyWorkflowOrchestrator(
        PostgresAutonomyWorkflowRepository(restarted_engine), restarted_owners
    ).run(created.run_id, "worker-after-restart")

    assert completed.status is WorkflowRunStatus.COMPLETED
    assert completed.stage is WorkflowStage.NOTIFICATION_AND_REVIEW
    assert len(effects) == 10  # ten unique stages; retry did not duplicate the sixth owner effect
    expected_revalidated = {
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
    assert set(restarted_owners.revalidated) == expected_revalidated
    with restarted_engine.connect() as connection:
        history = (
            connection.execute(
                text(
                    "SELECT stage FROM agent_checkpoint.v3_autonomy_workflow_history WHERE run_id=:run ORDER BY run_version"
                ),
                {"run": created.run_id},
            )
            .scalars()
            .all()
        )
    assert len(history) == 10
    assert history[-1] == WorkflowStage.NOTIFICATION_AND_REVIEW.value


def test_strategy_delegation_survives_postgresql_restart_and_remains_reference_only() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "")
    now = RecordedAt.from_datetime(datetime.now(UTC))
    source = ArtifactRef(
        EntityId.new("hypothesis"),
        ArtifactKind.HYPOTHESIS,
        SchemaVersion(1, 0),
        "sha256:" + "a" * 64,
        now,
        now,
    )
    candidate = StrategyAgent().decide_no_trade(
        thesis="no qualified edge",
        invalidation="new supporting evidence",
        evidence=(str(source.artifact_id),),
        reason="evidence threshold not met",
    )
    strategy_result = StrategyAgentResult(
        candidate, None, (source,), now, RecordedAt.from_datetime(now.value + timedelta(minutes=5))
    )
    effects: dict[str, StageResult] = {}
    first_downstream = DurableOwners(effects, fail_once_at=WorkflowStage.TRADE_PLAN)
    first = AutonomyWorkflowOrchestrator(
        PostgresAutonomyWorkflowRepository(engine), StrategyDelegationOwner(first_downstream, strategy_result)
    )
    created = first.trigger(TriggerOrigin.MARKET, f"strategy-{uuid4()}", {"event": "strategy-candidate"})
    interrupted = first.run(created.run_id, "strategy-worker-a")
    assert interrupted.status is WorkflowRunStatus.INTERRUPTED
    delegation = interrupted.reference(ReferenceKind.DELEGATION)
    assert delegation is not None and delegation.object_id.startswith("strategy:")

    engine.dispose()
    restarted_engine = create_engine(DATABASE_URL or "")
    restarted = AutonomyWorkflowOrchestrator(
        PostgresAutonomyWorkflowRepository(restarted_engine),
        StrategyDelegationOwner(DurableOwners(effects), strategy_result),
    ).run(created.run_id, "strategy-worker-b")
    assert restarted.status is WorkflowRunStatus.COMPLETED
    assert restarted.reference(ReferenceKind.DELEGATION) == delegation
    with restarted_engine.connect() as connection:
        payload = connection.execute(
            text("SELECT state_references FROM agent_checkpoint.v3_autonomy_workflow_run WHERE run_id=:run"),
            {"run": created.run_id},
        ).scalar_one()
    assert "thesis" not in str(payload).lower()
    assert "evidence" not in str(payload).lower()


def test_concurrent_trigger_is_single_run_and_active_lease_is_fenced() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=10)
    key = f"concurrent-{uuid4()}"

    def create() -> object:
        return PostgresAutonomyWorkflowRepository(engine).create(TriggerOrigin.MARKET, key, {"event": "quote-v1"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        runs = list(pool.map(lambda _: create(), range(8)))
    assert len({run.run_id for run in runs}) == 1
    repository = PostgresAutonomyWorkflowRepository(engine)
    now = datetime.now(UTC)
    claimed = repository.claim(runs[0].run_id, "worker-a", lease_seconds=30, now=now)
    with pytest.raises(RuntimeError, match="another worker"):
        repository.claim(runs[0].run_id, "worker-b", lease_seconds=30, now=now)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM agent_checkpoint.v3_autonomy_workflow_run "
                    "WHERE trigger_origin='MARKET' AND trigger_idempotency_key=:key"
                ),
                {"key": key},
            ).scalar_one()
            == 1
        )
    assert claimed.fencing_token == 1


def test_postgresql_trigger_conflicting_replay_fails_closed() -> None:
    _upgrade()
    repository = PostgresAutonomyWorkflowRepository(create_engine(DATABASE_URL or ""))
    key = f"conflict-{uuid4()}"
    repository.create(TriggerOrigin.SYSTEM, key, {"health": "ok"})
    with pytest.raises(ValueError, match="conflicting trigger replay"):
        repository.create(TriggerOrigin.SYSTEM, key, {"health": "halt"})
