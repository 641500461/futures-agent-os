"""Durable, deterministic V3 autonomy workflow orchestration.

The checkpoint contains only orchestration state and immutable references. It
never owns market, authorization, risk, order, fill, position, or ledger truth.
Every effectful stage is reached through an injected owner command port and is
safe to retry by its stable command idempotency key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Mapping, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Engine, RowMapping, text


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return current.astimezone(UTC)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


# Compatibility surface introduced alongside V3-001. Production V3-002 uses
# the richer state model below.
class Checkpoint(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    SCAN = "SCAN"
    DELEGATE = "DELEGATE"
    PLAN = "PLAN"
    PREFLIGHT = "PREFLIGHT"
    FINAL = "FINAL"
    EXECUTE = "EXECUTE"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class DurableState:
    run_id: str
    checkpoint: Checkpoint
    plan_hash: str
    snapshot_hash: str
    basis_hash: str | None = None
    receipt_hash: str | None = None
    risk_hash: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "run_id": self.run_id,
            "checkpoint": self.checkpoint.value,
            "plan_hash": self.plan_hash,
            "snapshot_hash": self.snapshot_hash,
            "basis_hash": self.basis_hash,
            "receipt_hash": self.receipt_hash,
            "risk_hash": self.risk_hash,
        }


_LEGACY_ORDER = tuple(Checkpoint)


def advance(state: DurableState, target: Checkpoint) -> DurableState:
    if _LEGACY_ORDER.index(target) != _LEGACY_ORDER.index(state.checkpoint) + 1:
        raise ValueError("invalid checkpoint transition")
    return replace(state, checkpoint=target)


class DurableOrchestrator:
    """In-memory compatibility fixture; not the production store."""

    def __init__(self) -> None:
        self._store: dict[str, DurableState] = {}

    def save(self, state: DurableState) -> DurableState:
        if not state.run_id or not state.plan_hash or not state.snapshot_hash:
            raise ValueError("invalid checkpoint")
        self._store[state.run_id] = state
        return state

    def start(self, run_id: str, plan_hash: str, snapshot_hash: str) -> DurableState:
        return self.save(DurableState(run_id, Checkpoint.SNAPSHOT, plan_hash, snapshot_hash))

    def trigger(self, run_id: str, plan_hash: str, snapshot_hash: str) -> DurableState:
        prior = self._store.get(run_id)
        if prior is not None:
            if prior.plan_hash != plan_hash or prior.snapshot_hash != snapshot_hash:
                raise ValueError("conflicting trigger replay")
            return prior
        return self.start(run_id, plan_hash, snapshot_hash)

    def advance(self, run_id: str, target: Checkpoint) -> DurableState:
        return self.save(advance(self._store[run_id], target))

    def interrupt(self, run_id: str) -> DurableState:
        return self._store[run_id]

    def recover(
        self,
        run_id: str,
        *,
        plan_hash: str,
        snapshot_hash: str,
        basis_hash: str | None = None,
        receipt_hash: str | None = None,
        risk_hash: str | None = None,
    ) -> DurableState:
        state = self._store[run_id]
        actual = (state.plan_hash, state.snapshot_hash, state.basis_hash, state.receipt_hash, state.risk_hash)
        if actual != (plan_hash, snapshot_hash, basis_hash, receipt_hash, risk_hash):
            raise ValueError("stale checkpoint inputs")
        return state


class TriggerOrigin(StrEnum):
    USER = "USER"
    SCHEDULE = "SCHEDULE"
    MARKET = "MARKET"
    ACCOUNT = "ACCOUNT"
    SYSTEM = "SYSTEM"


class WorkflowStage(StrEnum):
    TRIGGERED = "TRIGGERED"
    SNAPSHOT = "SNAPSHOT"
    OPPORTUNITY_SCAN = "OPPORTUNITY_SCAN"
    DELEGATION_AND_CHALLENGE = "DELEGATION_AND_CHALLENGE"
    TRADE_PLAN = "TRADE_PLAN"
    AUTHORIZATION_PREFLIGHT = "AUTHORIZATION_PREFLIGHT"
    SIZING_AND_RESERVATION = "SIZING_AND_RESERVATION"
    FINAL_RECEIPT_GATE = "FINAL_RECEIPT_GATE"
    RISK_AND_EXECUTION = "RISK_AND_EXECUTION"
    MONITORING = "MONITORING"
    NOTIFICATION_AND_REVIEW = "NOTIFICATION_AND_REVIEW"


STAGE_ORDER = tuple(WorkflowStage)


class WorkflowRunStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"


class ReferenceKind(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    OPPORTUNITY_SCAN = "OPPORTUNITY_SCAN"
    DELEGATION = "DELEGATION"
    TRADE_PLAN = "TRADE_PLAN"
    AUTHORIZATION_BASIS = "AUTHORIZATION_BASIS"
    RISK_RESERVATION = "RISK_RESERVATION"
    GATE_RECEIPT = "GATE_RECEIPT"
    RISK_DECISION = "RISK_DECISION"
    EXECUTION = "EXECUTION"
    MONITORING = "MONITORING"
    NOTIFICATION = "NOTIFICATION"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class StateReference:
    """Pointer to owner-controlled state, never a copy of that state."""

    kind: ReferenceKind
    object_id: str
    version: int
    sha256: str

    def __post_init__(self) -> None:
        if not self.object_id or self.object_id != self.object_id.strip():
            raise ValueError("reference object_id must be non-empty canonical text")
        if self.version < 1:
            raise ValueError("reference version must be positive")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256):
            raise ValueError("reference sha256 must be lowercase hex")

    def to_dict(self) -> dict[str, str | int]:
        return {"kind": self.kind.value, "object_id": self.object_id, "version": self.version, "sha256": self.sha256}

    @classmethod
    def hydrate(cls, value: object) -> StateReference:
        if not isinstance(value, Mapping) or set(value) != {"kind", "object_id", "version", "sha256"}:
            raise ValueError("checkpoint reference fields are not exact")
        if not isinstance(value["kind"], str) or not isinstance(value["object_id"], str):
            raise ValueError("checkpoint reference text fields are invalid")
        if not isinstance(value["version"], int) or isinstance(value["version"], bool):
            raise ValueError("checkpoint reference version is invalid")
        if not isinstance(value["sha256"], str):
            raise ValueError("checkpoint reference digest is invalid")
        return cls(ReferenceKind(value["kind"]), value["object_id"], value["version"], value["sha256"])


@dataclass(frozen=True, slots=True)
class AutonomyWorkflowRun:
    run_id: UUID
    trigger_origin: TriggerOrigin
    trigger_idempotency_key: str
    trigger_sha256: str
    stage: WorkflowStage = WorkflowStage.TRIGGERED
    status: WorkflowRunStatus = WorkflowRunStatus.ACTIVE
    references: tuple[StateReference, ...] = ()
    version: int = 1
    fencing_token: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.trigger_idempotency_key or self.trigger_idempotency_key != self.trigger_idempotency_key.strip():
            raise ValueError("trigger idempotency key must be non-empty canonical text")
        if len(self.trigger_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.trigger_sha256
        ):
            raise ValueError("trigger digest is invalid")
        kinds = tuple(item.kind for item in self.references)
        if len(kinds) != len(set(kinds)):
            raise ValueError("checkpoint contains duplicate reference kinds")
        if self.version < 1 or self.fencing_token < 0:
            raise ValueError("workflow counters are invalid")

    def reference(self, kind: ReferenceKind) -> StateReference | None:
        return next((item for item in self.references if item.kind is kind), None)


@dataclass(frozen=True, slots=True)
class StageCommand:
    run_id: UUID
    stage: WorkflowStage
    idempotency_key: str
    trigger_origin: TriggerOrigin
    references: tuple[StateReference, ...]


class StageDisposition(StrEnum):
    ADVANCE = "ADVANCE"
    INTERRUPT = "INTERRUPT"
    DEFER = "DEFER"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class StageResult:
    disposition: StageDisposition
    references: tuple[StateReference, ...] = ()
    reason: str | None = None


class AutonomyOwnerPort(Protocol):
    """Commands owners; implementations enforce idempotency and domain truth."""

    def execute(self, command: StageCommand) -> StageResult: ...

    def revalidate(self, reference: StateReference, *, completed_stage: WorkflowStage, as_of: datetime) -> bool: ...


class AutonomyWorkflowRepository(Protocol):
    def create(
        self, origin: TriggerOrigin, idempotency_key: str, payload: Mapping[str, object]
    ) -> AutonomyWorkflowRun: ...

    def load(self, run_id: UUID) -> AutonomyWorkflowRun: ...

    def claim(self, run_id: UUID, worker_id: str, *, lease_seconds: int, now: datetime) -> AutonomyWorkflowRun: ...

    def checkpoint(
        self,
        run: AutonomyWorkflowRun,
        worker_id: str,
        stage: WorkflowStage,
        references: tuple[StateReference, ...],
        *,
        now: datetime,
    ) -> AutonomyWorkflowRun: ...

    def finish(
        self, run: AutonomyWorkflowRun, worker_id: str, status: WorkflowRunStatus, reason: str | None, *, now: datetime
    ) -> AutonomyWorkflowRun: ...


_REQUIRED_OUTPUTS: dict[WorkflowStage, frozenset[ReferenceKind]] = {
    WorkflowStage.SNAPSHOT: frozenset({ReferenceKind.SNAPSHOT}),
    WorkflowStage.OPPORTUNITY_SCAN: frozenset({ReferenceKind.OPPORTUNITY_SCAN}),
    WorkflowStage.DELEGATION_AND_CHALLENGE: frozenset({ReferenceKind.DELEGATION}),
    WorkflowStage.TRADE_PLAN: frozenset({ReferenceKind.TRADE_PLAN}),
    WorkflowStage.AUTHORIZATION_PREFLIGHT: frozenset({ReferenceKind.AUTHORIZATION_BASIS}),
    WorkflowStage.SIZING_AND_RESERVATION: frozenset({ReferenceKind.RISK_RESERVATION}),
    WorkflowStage.FINAL_RECEIPT_GATE: frozenset({ReferenceKind.GATE_RECEIPT}),
    WorkflowStage.RISK_AND_EXECUTION: frozenset({ReferenceKind.RISK_DECISION, ReferenceKind.EXECUTION}),
    WorkflowStage.MONITORING: frozenset({ReferenceKind.MONITORING}),
    WorkflowStage.NOTIFICATION_AND_REVIEW: frozenset({ReferenceKind.NOTIFICATION, ReferenceKind.REVIEW}),
}
_RECOVERY_TRUTH = frozenset(
    {
        ReferenceKind.SNAPSHOT,
        ReferenceKind.TRADE_PLAN,
        ReferenceKind.AUTHORIZATION_BASIS,
        ReferenceKind.GATE_RECEIPT,
        ReferenceKind.RISK_DECISION,
    }
)


def _merge_references(
    prior: tuple[StateReference, ...], additions: tuple[StateReference, ...]
) -> tuple[StateReference, ...]:
    merged = {item.kind: item for item in prior}
    for item in additions:
        existing = merged.get(item.kind)
        if existing is not None and existing != item:
            raise ValueError(f"owner result attempted to replace immutable {item.kind.value} reference")
        merged[item.kind] = item
    return tuple(merged[kind] for kind in ReferenceKind if kind in merged)


class AutonomyWorkflowOrchestrator:
    """Deterministically advances one bounded V3 cycle without model-owned loops."""

    def __init__(self, repository: AutonomyWorkflowRepository, owners: AutonomyOwnerPort) -> None:
        self.repository = repository
        self.owners = owners

    def trigger(
        self, origin: TriggerOrigin, idempotency_key: str, payload: Mapping[str, object]
    ) -> AutonomyWorkflowRun:
        return self.repository.create(origin, idempotency_key, payload)

    def run(
        self, run_id: UUID, worker_id: str, *, lease_seconds: int = 30, now: datetime | None = None
    ) -> AutonomyWorkflowRun:
        def clock() -> datetime:
            return _utc(now) if now is not None else datetime.now(UTC)

        instant = clock()
        persisted = self.repository.load(run_id)
        if persisted.status in {WorkflowRunStatus.COMPLETED, WorkflowRunStatus.DEFERRED, WorkflowRunStatus.FAILED}:
            return persisted
        if persisted.stage is not WorkflowStage.TRIGGERED:
            self._revalidate(persisted, instant)
        run = self.repository.claim(run_id, worker_id, lease_seconds=lease_seconds, now=clock())
        while True:
            index = STAGE_ORDER.index(run.stage)
            if index == len(STAGE_ORDER) - 1:
                return self.repository.finish(run, worker_id, WorkflowRunStatus.COMPLETED, None, now=clock())
            target = STAGE_ORDER[index + 1]
            command = StageCommand(
                run.run_id,
                target,
                f"v3-autonomy:{run.run_id}:{target.value}",
                run.trigger_origin,
                run.references,
            )
            try:
                result = self.owners.execute(command)
                if not isinstance(result, StageResult):
                    raise TypeError("owner command must return StageResult")
                if result.disposition is StageDisposition.INTERRUPT:
                    return self.repository.finish(
                        run, worker_id, WorkflowRunStatus.INTERRUPTED, result.reason or "OWNER_INTERRUPT", now=clock()
                    )
                if result.disposition is StageDisposition.DEFER:
                    return self.repository.finish(
                        run, worker_id, WorkflowRunStatus.DEFERRED, result.reason or "DEFERRED", now=clock()
                    )
                if result.disposition is StageDisposition.FAIL:
                    return self.repository.finish(
                        run, worker_id, WorkflowRunStatus.FAILED, result.reason or "FAILED", now=clock()
                    )
                provided = tuple(reference.kind for reference in result.references)
                if len(provided) != len(set(provided)) or set(provided) != _REQUIRED_OUTPUTS[target]:
                    raise ValueError(f"stage {target.value} owner references are not exact")
                references = _merge_references(run.references, result.references)
                run = self.repository.checkpoint(run, worker_id, target, references, now=clock())
            except Exception as error:
                return self.repository.finish(
                    run, worker_id, WorkflowRunStatus.INTERRUPTED, f"{type(error).__name__}:{error}", now=clock()
                )

    def _revalidate(self, run: AutonomyWorkflowRun, now: datetime) -> None:
        by_kind = {item.kind: item for item in run.references}
        required = {
            kind
            for stage in STAGE_ORDER[1 : STAGE_ORDER.index(run.stage) + 1]
            for kind in _REQUIRED_OUTPUTS.get(stage, frozenset())
        }
        if not required.issubset(by_kind):
            raise ValueError("checkpoint is missing completed-stage references")
        for kind in _RECOVERY_TRUTH & required:
            if not self.owners.revalidate(by_kind[kind], completed_stage=run.stage, as_of=now):
                raise ValueError(f"stale {kind.value} prevents recovery")


class InMemoryAutonomyWorkflowRepository:
    """Deterministic contract fixture with the same fencing rules as PostgreSQL."""

    def __init__(self) -> None:
        self.runs: dict[UUID, AutonomyWorkflowRun] = {}
        self.keys: dict[tuple[TriggerOrigin, str], UUID] = {}

    def create(self, origin: TriggerOrigin, idempotency_key: str, payload: Mapping[str, object]) -> AutonomyWorkflowRun:
        digest = _digest(payload)
        key = (origin, idempotency_key)
        if key in self.keys:
            run = self.runs[self.keys[key]]
            if run.trigger_sha256 != digest:
                raise ValueError("conflicting trigger replay")
            return run
        run_id = uuid5(NAMESPACE_URL, f"fao:v3:{origin.value}:{idempotency_key}")
        run = AutonomyWorkflowRun(run_id, origin, idempotency_key, digest)
        self.keys[key] = run_id
        self.runs[run_id] = run
        return run

    def load(self, run_id: UUID) -> AutonomyWorkflowRun:
        return self.runs[run_id]

    def claim(self, run_id: UUID, worker_id: str, *, lease_seconds: int, now: datetime) -> AutonomyWorkflowRun:
        run = self.load(run_id)
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if run.lease_expires_at is not None and run.lease_expires_at > now and run.lease_owner != worker_id:
            raise RuntimeError("workflow lease is held by another worker")
        claimed = replace(
            run,
            status=WorkflowRunStatus.ACTIVE,
            fencing_token=run.fencing_token + 1,
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            version=run.version + 1,
            last_error=None,
        )
        self.runs[run_id] = claimed
        return claimed

    def checkpoint(
        self,
        run: AutonomyWorkflowRun,
        worker_id: str,
        stage: WorkflowStage,
        references: tuple[StateReference, ...],
        *,
        now: datetime,
    ) -> AutonomyWorkflowRun:
        current = self.load(run.run_id)
        if (
            current.version != run.version
            or current.fencing_token != run.fencing_token
            or current.lease_owner != worker_id
        ):
            raise RuntimeError("stale workflow fencing token")
        if STAGE_ORDER.index(stage) != STAGE_ORDER.index(run.stage) + 1:
            raise ValueError("invalid workflow stage transition")
        updated = replace(run, stage=stage, references=references, version=run.version + 1)
        self.runs[run.run_id] = updated
        return updated

    def finish(
        self, run: AutonomyWorkflowRun, worker_id: str, status: WorkflowRunStatus, reason: str | None, *, now: datetime
    ) -> AutonomyWorkflowRun:
        current = self.load(run.run_id)
        if (
            current.version != run.version
            or current.fencing_token != run.fencing_token
            or current.lease_owner != worker_id
        ):
            raise RuntimeError("stale workflow fencing token")
        updated = replace(
            run,
            status=status,
            last_error=reason,
            lease_owner=None,
            lease_expires_at=None,
            version=run.version + 1,
        )
        self.runs[run.run_id] = updated
        return updated


class PostgresAutonomyWorkflowRepository:
    """PostgreSQL checkpoint repository with optimistic version and lease fencing."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _refs_payload(references: tuple[StateReference, ...]) -> list[dict[str, str | int]]:
        return [item.to_dict() for item in references]

    @staticmethod
    def _hydrate(row: RowMapping) -> AutonomyWorkflowRun:
        trigger_payload = row["trigger_payload"]
        if _canonical(trigger_payload) != row["trigger_canonical"] or _digest(trigger_payload) != row["trigger_sha256"]:
            raise ValueError("checkpoint trigger integrity drift")
        raw_refs = row["state_references"]
        if not isinstance(raw_refs, list):
            raise ValueError("checkpoint references must be a JSON array")
        references = tuple(StateReference.hydrate(item) for item in raw_refs)
        if (
            _canonical(raw_refs) != row["state_references_canonical"]
            or _digest(raw_refs) != row["state_references_sha256"]
        ):
            raise ValueError("checkpoint reference integrity drift")
        return AutonomyWorkflowRun(
            UUID(str(row["run_id"])),
            TriggerOrigin(str(row["trigger_origin"])),
            str(row["trigger_idempotency_key"]),
            str(row["trigger_sha256"]),
            WorkflowStage(str(row["current_stage"])),
            WorkflowRunStatus(str(row["run_status"])),
            references,
            int(str(row["version"])),
            int(str(row["fencing_token"])),
            str(row["lease_owner"]) if row["lease_owner"] is not None else None,
            row["lease_expires_at"] if isinstance(row["lease_expires_at"], datetime) else None,
            str(row["last_error"]) if row["last_error"] is not None else None,
        )

    def create(self, origin: TriggerOrigin, idempotency_key: str, payload: Mapping[str, object]) -> AutonomyWorkflowRun:
        if not idempotency_key or idempotency_key != idempotency_key.strip():
            raise ValueError("trigger idempotency key must be non-empty canonical text")
        payload_text, payload_hash = _canonical(payload), _digest(payload)
        run_id = uuid5(NAMESPACE_URL, f"fao:v3:{origin.value}:{idempotency_key}")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO agent_checkpoint.v3_autonomy_workflow_run
                    (run_id,trigger_origin,trigger_idempotency_key,trigger_payload,trigger_canonical,trigger_sha256,
                     state_references,state_references_canonical,state_references_sha256)
                    VALUES (:run,:origin,:key,CAST(:payload AS jsonb),:canonical,:sha,'[]'::jsonb,'[]',:empty_sha)
                    ON CONFLICT DO NOTHING"""
                ),
                {
                    "run": run_id,
                    "origin": origin.value,
                    "key": idempotency_key,
                    "payload": payload_text,
                    "canonical": payload_text,
                    "sha": payload_hash,
                    "empty_sha": _digest([]),
                },
            )
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM agent_checkpoint.v3_autonomy_workflow_run WHERE trigger_origin=:origin AND trigger_idempotency_key=:key"
                    ),
                    {"origin": origin.value, "key": idempotency_key},
                )
                .mappings()
                .one()
            )
            if row["trigger_canonical"] != payload_text or row["trigger_sha256"] != payload_hash:
                raise ValueError("conflicting trigger replay")
            return self._hydrate(row)

    def load(self, run_id: UUID) -> AutonomyWorkflowRun:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM agent_checkpoint.v3_autonomy_workflow_run WHERE run_id=:run"), {"run": run_id}
                )
                .mappings()
                .one()
            )
        return self._hydrate(row)

    def claim(self, run_id: UUID, worker_id: str, *, lease_seconds: int, now: datetime) -> AutonomyWorkflowRun:
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker and positive lease are required")
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM agent_checkpoint.v3_autonomy_workflow_run WHERE run_id=:run FOR UPDATE"),
                    {"run": run_id},
                )
                .mappings()
                .one()
            )
            current = self._hydrate(row)
            if (
                current.lease_expires_at is not None
                and current.lease_expires_at > now
                and current.lease_owner != worker_id
            ):
                raise RuntimeError("workflow lease is held by another worker")
            updated = (
                connection.execute(
                    text(
                        """UPDATE agent_checkpoint.v3_autonomy_workflow_run
                        SET run_status='ACTIVE',version=version+1,fencing_token=fencing_token+1,lease_owner=:worker,
                            lease_expires_at=:expiry,last_error=NULL,updated_at=:now
                        WHERE run_id=:run RETURNING *"""
                    ),
                    {"run": run_id, "worker": worker_id, "expiry": now + timedelta(seconds=lease_seconds), "now": now},
                )
                .mappings()
                .one()
            )
            return self._hydrate(updated)

    def checkpoint(
        self,
        run: AutonomyWorkflowRun,
        worker_id: str,
        stage: WorkflowStage,
        references: tuple[StateReference, ...],
        *,
        now: datetime,
    ) -> AutonomyWorkflowRun:
        if STAGE_ORDER.index(stage) != STAGE_ORDER.index(run.stage) + 1:
            raise ValueError("invalid workflow stage transition")
        payload = self._refs_payload(references)
        canonical = _canonical(payload)
        with self.engine.begin() as connection:
            updated = (
                connection.execute(
                    text(
                        """UPDATE agent_checkpoint.v3_autonomy_workflow_run
                        SET current_stage=:stage,state_references=CAST(:refs AS jsonb),state_references_canonical=:canonical,
                            state_references_sha256=:sha,version=version+1,updated_at=:now
                        WHERE run_id=:run AND version=:version AND fencing_token=:fence AND lease_owner=:worker
                          AND lease_expires_at>:now RETURNING *"""
                    ),
                    {
                        "stage": stage.value,
                        "refs": canonical,
                        "canonical": canonical,
                        "sha": _digest(payload),
                        "now": now,
                        "run": run.run_id,
                        "version": run.version,
                        "fence": run.fencing_token,
                        "worker": worker_id,
                    },
                )
                .mappings()
                .first()
            )
            if updated is None:
                raise RuntimeError("stale or expired workflow fencing token")
            connection.execute(
                text(
                    """INSERT INTO agent_checkpoint.v3_autonomy_workflow_history
                    (run_id,run_version,stage,run_status,state_references,state_references_canonical,state_references_sha256,recorded_at)
                    VALUES (:run,:version,:stage,'ACTIVE',CAST(:refs AS jsonb),:canonical,:sha,:now)"""
                ),
                {
                    "run": run.run_id,
                    "version": updated["version"],
                    "stage": stage.value,
                    "refs": canonical,
                    "canonical": canonical,
                    "sha": _digest(payload),
                    "now": now,
                },
            )
            return self._hydrate(updated)

    def finish(
        self, run: AutonomyWorkflowRun, worker_id: str, status: WorkflowRunStatus, reason: str | None, *, now: datetime
    ) -> AutonomyWorkflowRun:
        if status is WorkflowRunStatus.ACTIVE:
            raise ValueError("finish requires a non-active status")
        with self.engine.begin() as connection:
            updated = (
                connection.execute(
                    text(
                        """UPDATE agent_checkpoint.v3_autonomy_workflow_run
                        SET run_status=:status,last_error=:reason,lease_owner=NULL,lease_expires_at=NULL,
                            version=version+1,updated_at=:now
                        WHERE run_id=:run AND version=:version AND fencing_token=:fence AND lease_owner=:worker
                        RETURNING *"""
                    ),
                    {
                        "status": status.value,
                        "reason": reason,
                        "now": now,
                        "run": run.run_id,
                        "version": run.version,
                        "fence": run.fencing_token,
                        "worker": worker_id,
                    },
                )
                .mappings()
                .first()
            )
            if updated is None:
                raise RuntimeError("stale workflow fencing token")
            return self._hydrate(updated)
