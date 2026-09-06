"""Explicit MANUAL_TEST simulation entry boundary."""

from __future__ import annotations

import json
import os
import tempfile
import fcntl
from functools import wraps
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any

from .autonomy_contracts import (
    ApprovalAction,
    ApprovalScope,
    ExecutionOrigin,
    PlanApproval,
    PlanApprovalRegistry,
    PlanApprovalStatus,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256


def _approval_to_payload(approval: PlanApproval) -> dict[str, object]:
    scope = approval.scope
    return {
        "approval_id": str(approval.approval_id),
        "version": approval.version,
        "status": approval.status.value,
        "plan_id": str(approval.plan_id),
        "plan_version": approval.plan_version,
        "plan_hash": approval.plan_hash,
        "account_id": str(approval.account_id),
        "scope": {
            "account": str(scope.simulation_account_id),
            "instruments": list(scope.instruments),
            "strategies": list(scope.strategies),
            "sessions": list(scope.sessions),
            "actions": sorted(action.value for action in scope.actions),
            "quantity_ceiling": str(scope.quantity_ceiling),
            "valid_from": scope.valid_from_at.to_dict()["recorded_at"],
            "valid_until": scope.valid_until_at.to_dict()["recorded_at"],
        },
        "approval_token": str(approval.approval_token),
        "requested_by": approval.requested_by,
        "expires_at": approval.expires_at.to_dict()["recorded_at"],
        "requested_at": approval.requested_at.to_dict()["recorded_at"],
        "consumer_basis_id": str(approval.consumer_basis_id) if approval.consumer_basis_id else None,
        "consumed_at": approval.consumed_at.to_dict()["recorded_at"] if approval.consumed_at else None,
        "decided_at": approval.decided_at.to_dict()["recorded_at"] if approval.decided_at else None,
        "decided_by": approval.decided_by,
        "schema_version": str(approval.schema_version),
        "source_ref": approval.source_ref,
    }


def _approval_from_payload(payload: object) -> PlanApproval:
    if not isinstance(payload, dict) or not isinstance(payload.get("scope"), dict):
        raise ValueError("manual approval payload must be an object")
    scope = payload["scope"]
    return PlanApproval(
        EntityId.parse(str(payload["approval_id"])),
        int(str(payload["version"])),
        PlanApprovalStatus(str(payload["status"])),
        EntityId.parse(str(payload["plan_id"])),
        int(str(payload["plan_version"])),
        str(payload["plan_hash"]),
        EntityId.parse(str(payload["account_id"])),
        ApprovalScope(
            EntityId.parse(str(scope["account"])),
            tuple(str(v) for v in scope["instruments"]),
            tuple(str(v) for v in scope["strategies"]),
            tuple(str(v) for v in scope["sessions"]),
            frozenset(ApprovalAction(str(v)) for v in scope["actions"]),
            Decimal(str(scope["quantity_ceiling"])),
            RecordedAt.parse(str(scope["valid_from"])),
            RecordedAt.parse(str(scope["valid_until"])),
        ),
        EntityId.parse(str(payload["approval_token"])),
        str(payload["requested_by"]),
        RecordedAt.parse(str(payload["expires_at"])),
        RecordedAt.parse(str(payload["requested_at"])),
        EntityId.parse(str(payload["consumer_basis_id"])) if payload.get("consumer_basis_id") else None,
        RecordedAt.parse(str(payload["consumed_at"])) if payload.get("consumed_at") else None,
        RecordedAt.parse(str(payload["decided_at"])) if payload.get("decided_at") else None,
        str(payload["decided_by"]) if payload.get("decided_by") else None,
        SchemaVersion.parse(str(payload.get("schema_version", "1.0"))),
        str(payload.get("source_ref", "source:v2")),
    )


@dataclass(frozen=True, slots=True)
class ManualTestContext:
    actor_ref: str
    environment_policy_ref: str
    approval_basis_id: str
    simulation_only: bool = True

    def __post_init__(self) -> None:
        for value, label in (
            (self.actor_ref, "actor_ref"),
            (self.environment_policy_ref, "environment_policy_ref"),
            (self.approval_basis_id, "approval_basis_id"),
        ):
            if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
                raise ValueError(f"{label} must be canonical text")
        if not self.actor_ref.startswith("user:"):
            raise ValueError("MANUAL_TEST actor must identify an authorized user")
        if self.environment_policy_ref != "environment://simulation-only" or not self.simulation_only:
            raise ValueError("MANUAL_TEST requires simulation-only environment")


def require_manual_test(origin: ExecutionOrigin, context: ManualTestContext) -> None:
    if origin is not ExecutionOrigin.MANUAL_TEST:
        raise ValueError("manual entry requires MANUAL_TEST execution origin")
    if not isinstance(context, ManualTestContext):
        raise TypeError("manual entry requires typed context")


def _process_locked(method: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize approval read-modify-write operations across processes."""

    @wraps(method)
    def wrapped(self: ManualTestApprovalStore, *args: Any, **kwargs: Any) -> Any:
        # Resolve both paths so independently constructed stores always use
        # the same OS lock, even when callers use different relative cwd.
        lock_path = self.path.expanduser().resolve().with_name(f".{self.path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                # Every process may have been constructed before another
                # process committed. Refresh under the lock before deciding.
                if self.path.exists():
                    self._load()
                return method(self, *args, **kwargs)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return wrapped


@dataclass(frozen=True, slots=True)
class ManualApprovalCommandResult:
    approval: PlanApproval
    changed: bool
    reason: str
    basis: object | None = None


class ManualTestApprovalStore:
    """Durable MANUAL_TEST approval state machine.

    PlanApproval remains an immutable domain fact.  This store appends a small
    transition record to a local state file and atomically replaces it, making
    request/grant/reject/expire/consume idempotent across process restarts.
    It is a simulation/emergency fallback and never grants AUTONOMOUS authority.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = RLock()
        self._registry = PlanApprovalRegistry()
        self._approvals: dict[EntityId, PlanApproval] = {}
        self._durable: dict[str, dict[str, object]] = {}
        if self.path.exists():
            self._load()

    @_process_locked
    def request(self, approval: PlanApproval) -> ManualApprovalCommandResult:
        if not isinstance(approval, PlanApproval) or approval.status is not PlanApprovalStatus.REQUESTED:
            raise ValueError("MANUAL_TEST requests require REQUESTED PlanApproval")
        with self._lock:
            key = str(approval.approval_id)
            existing = self._durable.get(key)
            if existing is not None:
                current = self._approvals.get(approval.approval_id)
                if current is None or (
                    current.plan_id,
                    current.plan_version,
                    current.plan_hash,
                    current.account_id,
                    current.scope,
                    current.approval_token,
                    current.requested_by,
                    current.expires_at,
                    current.requested_at,
                ) != (
                    approval.plan_id,
                    approval.plan_version,
                    approval.plan_hash,
                    approval.account_id,
                    approval.scope,
                    approval.approval_token,
                    approval.requested_by,
                    approval.expires_at,
                    approval.requested_at,
                ):
                    return ManualApprovalCommandResult(approval, False, "APPROVAL_CONFLICT")
                return ManualApprovalCommandResult(current, False, "REPLAYED")
            self._approvals[approval.approval_id] = approval
            self._record(approval, "REQUESTED")
            return ManualApprovalCommandResult(approval, True, "REQUESTED")

    def get(self, approval_id: EntityId) -> PlanApproval | None:
        if not isinstance(approval_id, EntityId):
            raise TypeError("approval id must be typed")
        with self._lock:
            return self._approvals.get(approval_id)

    @_process_locked
    def claim_shadow(self, approval_id: EntityId, now: RecordedAt) -> bool:
        """Atomically claim the single SHADOW execution for a consumed approval."""
        with self._lock:
            approval = self._require(approval_id)
            record = self._durable.get(str(approval_id))
            if approval.status is not PlanApprovalStatus.CONSUMED or record is None:
                return False
            if record.get("shadow_status") in {"CLAIMED", "COMPLETED"}:
                return False
            record["shadow_status"] = "CLAIMED"
            record["shadow_claimed_at"] = now.to_dict()["recorded_at"]
            self._persist()
            return True

    @_process_locked
    def complete_shadow(self, approval_id: EntityId, now: RecordedAt, *, report: dict[str, Any]) -> bool:
        """Commit the result and completion marker in the same atomic state write."""
        with self._lock:
            approval = self._require(approval_id)
            record = self._durable.get(str(approval_id))
            if record is None or record.get("shadow_status") != "CLAIMED":
                return False
            expected = {
                "approval_id": str(approval_id),
                "basis_id": str(approval.consumer_basis_id),
                "plan_id": str(approval.plan_id),
                "plan_version": approval.plan_version,
                "plan_hash": approval.plan_hash,
                "execution_origin": "MANUAL_TEST",
            }
            if any(report.get(key) != value for key, value in expected.items()):
                raise ValueError("shadow report authorization binding mismatch")
            # Copy JSON data before storing; callers cannot mutate durable state
            # through a reference to their report.
            persisted_report = json.loads(json.dumps(report, allow_nan=False))
            record["shadow_status"] = "COMPLETED"
            record["shadow_completed_at"] = now.to_dict()["recorded_at"]
            record["shadow_report"] = persisted_report
            self._persist()
            return True

    @_process_locked
    def shadow_report(self, approval_id: EntityId) -> dict[str, Any] | None:
        """Read a committed result after restart without granting another run."""
        with self._lock:
            self._require(approval_id)
            record = self._durable.get(str(approval_id))
            if record is None or record.get("shadow_status") != "COMPLETED":
                return None
            report = record.get("shadow_report")
            if not isinstance(report, dict):
                raise ValueError("completed shadow has no persisted report")
            result: dict[str, Any] = json.loads(json.dumps(report))
            digest = result.pop("report_hash", None)
            if not isinstance(digest, str) or canonical_sha256(result) != digest:
                raise ValueError("completed shadow report hash mismatch")
            result["report_hash"] = digest
            return result

    @_process_locked
    def decide(
        self,
        approval_id: EntityId,
        target: PlanApprovalStatus,
        now: RecordedAt,
        *,
        actor: str = "user:authorized",
    ) -> ManualApprovalCommandResult:
        if target not in {PlanApprovalStatus.GRANTED, PlanApprovalStatus.REJECTED}:
            raise ValueError("manual approval decisions must be GRANTED or REJECTED")
        with self._lock:
            approval = self._require(approval_id)
            if approval.status is target and approval.status_at(now) is target:
                return ManualApprovalCommandResult(approval, False, "REPLAYED")
            updated = approval.decide(target, now, actor=actor)
            self._approvals[approval_id] = updated
            self._record(updated, target.value)
            return ManualApprovalCommandResult(updated, True, target.value)

    @_process_locked
    def expire(self, approval_id: EntityId, now: RecordedAt) -> ManualApprovalCommandResult:
        if not isinstance(now, RecordedAt):
            raise TypeError("expiry requires a RecordedAt")
        with self._lock:
            approval = self._require(approval_id)
            if approval.status_at(now) is not PlanApprovalStatus.EXPIRED:
                return ManualApprovalCommandResult(approval, False, "NOT_EXPIRED")
            if approval.status is PlanApprovalStatus.EXPIRED:
                return ManualApprovalCommandResult(approval, False, "REPLAYED")
            updated = replace(approval, status=PlanApprovalStatus.EXPIRED, version=approval.version + 1)
            self._approvals[approval_id] = updated
            self._record(updated, "EXPIRED")
            return ManualApprovalCommandResult(updated, True, "EXPIRED")

    @_process_locked
    def consume(
        self, approval_id: EntityId, now: RecordedAt, basis_id: EntityId, **scope: Any
    ) -> ManualApprovalCommandResult:
        """Atomically emit exactly one PLAN_APPROVAL Basis for this approval."""
        with self._lock:
            approval = self._require(approval_id)
            prior = self._durable.get(str(approval_id))
            if prior is not None and prior.get("status") == PlanApprovalStatus.CONSUMED.value:
                if prior.get("basis_id") != str(basis_id):
                    return ManualApprovalCommandResult(approval, False, "APPROVAL_ALREADY_CONSUMED")
                prior_scope = prior.get("consume_scope")
                requested_scope = {key: str(value) for key, value in scope.items()}
                if prior_scope != requested_scope:
                    return ManualApprovalCommandResult(approval, False, "CONSUME_REPLAY_SCOPE_MISMATCH")
                return ManualApprovalCommandResult(approval, False, "REPLAYED")
            consumed, basis = self._registry.consume(approval, now, basis_id, **scope)
            if basis is None:
                if consumed.status is not approval.status:
                    self._approvals[approval_id] = consumed
                    self._record(consumed, consumed.status.value)
                return ManualApprovalCommandResult(consumed, False, "CONSUME_REJECTED")
            self._approvals[approval_id] = consumed
            self._record(consumed, "CONSUMED", basis_id=basis_id, consume_scope=scope)
            return ManualApprovalCommandResult(consumed, True, "CONSUMED", basis)

    def _require(self, approval_id: EntityId) -> PlanApproval:
        if not isinstance(approval_id, EntityId):
            raise TypeError("approval id must be typed")
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"unknown approval: {approval_id}")
        return approval

    def _record(
        self,
        approval: PlanApproval,
        status: str,
        *,
        basis_id: EntityId | None = None,
        consume_scope: dict[str, object] | None = None,
    ) -> None:
        self._durable[str(approval.approval_id)] = {
            "status": status,
            "version": str(approval.version),
            "approval_hash": approval.authorization_hash,
            "basis_id": str(basis_id) if basis_id else None,
            "consume_scope": {key: str(value) for key, value in consume_scope.items()} if consume_scope else None,
            "recorded_at": approval.consumed_at.to_dict()["recorded_at"]
            if approval.consumed_at
            else approval.requested_at.to_dict()["recorded_at"],
            "approval": _approval_to_payload(approval),
        }
        self._persist()

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._durable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self) -> None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("manual approval state must be an object")
            # Replace, rather than merge, the in-memory projection.  A store
            # may be long-lived while another process commits transitions;
            # merging can retain stale approval facts and defeat replay gates.
            loaded: dict[EntityId, PlanApproval] = {}
            for key, record in value.items():
                if not isinstance(key, str) or not isinstance(record, dict):
                    raise ValueError("invalid manual approval state")
                if record.get("status") not in {item.value for item in PlanApprovalStatus}:
                    raise ValueError("invalid manual approval status")
                EntityId.parse(key)
                persisted = _approval_from_payload(record.get("approval"))
                if persisted.approval_id != EntityId.parse(key):
                    raise ValueError("approval identity does not match state key")
                loaded[persisted.approval_id] = persisted
            self._durable = value
            self._approvals = loaded
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("cannot load manual approval state") from error


__all__ = ["ManualTestContext", "ManualApprovalCommandResult", "ManualTestApprovalStore", "require_manual_test"]
