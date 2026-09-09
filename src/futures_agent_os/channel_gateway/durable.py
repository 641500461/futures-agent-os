"""PostgreSQL-backed gateway inbox, task queue, controls, and outbox.

This module is intentionally an application service.  It owns transport and
queue state only; business services supplied as control handlers remain the
owners of mandate, risk, order, and ledger truth.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, text

from .contracts import ControlCallback, InboundEvent, OutboundNotification, validate_control

if TYPE_CHECKING:
    from futures_agent_os.agent_orchestration.v3_runtime import WatchEvent


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return current.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class IdentityMapping:
    channel: str
    external_actor_id: str
    external_conversation_id: str
    actor_ref: str
    target_ref: str
    mapping_id: UUID | None = None
    version: int = 1
    active: bool = True


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: bool
    duplicate: bool
    task_id: UUID
    inbox_id: UUID
    correlation_id: UUID
    actor_ref: str
    target_ref: str


@dataclass(frozen=True, slots=True)
class GatewayTask:
    task_id: UUID
    envelope: Mapping[str, Any]
    fencing_token: int
    worker_id: str


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    outbox_id: UUID
    channel: str
    conversation_id: str
    severity: str
    text: str
    idempotency_key: str
    delivery_key: str
    attempts: int
    max_attempts: int
    lease_owner: str | None = None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class NotificationSLOPolicy:
    """Target delivery windows for important notifications."""

    deadlines_seconds: Mapping[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        defaults = {"INFO": 300, "TRADE": 60, "ACTION_REQUIRED": 60, "RISK": 30, "CRITICAL": 15}
        configured = defaults if self.deadlines_seconds is None else dict(self.deadlines_seconds)
        if set(configured) != set(defaults) or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in configured.values()
        ):
            raise ValueError("SLO policy must define positive deadlines for every notification severity")
        object.__setattr__(self, "deadlines_seconds", MappingProxyType(configured))

    def deadline_at(self, severity: str, created_at: datetime) -> datetime:
        normalized = severity.upper()
        if normalized not in self.deadlines_seconds:
            raise ValueError("unsupported notification severity")
        return _utc(created_at) + timedelta(seconds=self.deadlines_seconds[normalized])

    def overdue(self, severity: str, created_at: datetime, *, now: datetime) -> bool:
        return _utc(now) >= self.deadline_at(severity, created_at)


class ControlHandler(Protocol):
    """Existing owner command boundary used by callback dispatch.

    A handler must perform its domain command using the caller-owned
    transaction.  The gateway never writes Mandate, Mode, Position, Order,
    or Ledger state itself.
    """

    def dispatch(self, callback: ControlCallback, connection: Connection) -> object: ...


def _require_bound_control(callback: ControlCallback) -> None:
    if callback.target_id is None or not callback.target_id.strip():
        raise ValueError("control callbacks require target_id")
    if callback.target_version is None:
        raise ValueError("control callbacks require target_version")
    if callback.target_sha256 is None:
        raise ValueError("control callbacks require target_sha256")
    if callback.expires_at is None or _utc(callback.expires_at) <= datetime.now(UTC):
        raise ValueError("control callbacks require a future expiry")


class PostgresGatewayStore:
    """Durable V3-001 persistence service.

    Each public operation opens one transaction on the supplied Engine.  A
    Connection can be supplied to the private helpers by worker code when a
    larger transaction is required.
    """

    def __init__(self, engine: Engine, *, require_identity_mapping: bool = False) -> None:
        self.engine = engine
        self.require_identity_mapping = require_identity_mapping

    def register_mapping(self, mapping: IdentityMapping) -> IdentityMapping:
        mapping_id = mapping.mapping_id or uuid4()
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """INSERT INTO fao.gateway_identity_map
                    (mapping_id,channel,external_actor_id,external_conversation_id,actor_ref,target_ref,version,active)
                    VALUES (:id,:channel,:actor,:conversation,:actor_ref,:target_ref,:version,:active)
                    ON CONFLICT (channel,external_actor_id,external_conversation_id)
                    DO UPDATE SET actor_ref=EXCLUDED.actor_ref,target_ref=EXCLUDED.target_ref,
                      version=EXCLUDED.version,active=EXCLUDED.active,updated_at=clock_timestamp()
                    RETURNING mapping_id,version,active"""
                    ),
                    {
                        "id": mapping_id,
                        "channel": mapping.channel,
                        "actor": mapping.external_actor_id,
                        "conversation": mapping.external_conversation_id,
                        "actor_ref": mapping.actor_ref,
                        "target_ref": mapping.target_ref,
                        "version": mapping.version,
                        "active": mapping.active,
                    },
                )
                .mappings()
                .one()
            )
        return IdentityMapping(
            mapping.channel,
            mapping.external_actor_id,
            mapping.external_conversation_id,
            mapping.actor_ref,
            mapping.target_ref,
            row["mapping_id"],
            row["version"],
            row["active"],
        )

    def resolve_mapping(self, event: InboundEvent, connection: Connection | None = None) -> IdentityMapping | None:
        def query(conn: Connection) -> IdentityMapping | None:
            row = (
                conn.execute(
                    text(
                        """SELECT mapping_id,channel,external_actor_id,external_conversation_id,actor_ref,target_ref,version,active
                    FROM fao.gateway_identity_map
                    WHERE channel=:channel AND external_actor_id=:actor AND external_conversation_id=:conversation
                      AND active = TRUE"""
                    ),
                    {"channel": event.channel, "actor": event.actor_id, "conversation": event.conversation_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return IdentityMapping(
                row["channel"],
                row["external_actor_id"],
                row["external_conversation_id"],
                row["actor_ref"],
                row["target_ref"],
                row["mapping_id"],
                row["version"],
                row["active"],
            )

        if connection is not None:
            return query(connection)
        with self.engine.connect() as owned:
            return query(owned)

    # InboxStore-compatible surface retained for callers that only need the
    # deduplication boundary and do not care about the task result details.
    def put_if_absent(self, event: InboundEvent) -> bool:
        return self.ingest(event).accepted

    def get(self, key: str) -> InboundEvent | None:
        try:
            channel, event_id = key.split(":", 1)
        except ValueError:
            return None
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT payload FROM fao.inbox WHERE source=:source AND external_event_id=:event"),
                    {"source": channel, "event": event_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return InboundEvent(
            payload["channel"],
            payload["event_id"],
            payload["actor_id"],
            payload["conversation_id"],
            payload["kind"],
            payload["payload"],
            datetime.fromisoformat(payload["occurred_at"]),
        )

    def ingest(self, event: InboundEvent, *, deadline_at: datetime | None = None) -> IngestResult:
        """Atomically deduplicate an event and enqueue exactly one task."""

        now = _utc()
        correlation_id = uuid5(NAMESPACE_URL, f"fao:gateway:correlation:{event.dedup_key}")
        task_id = uuid5(NAMESPACE_URL, f"fao:gateway:task:{event.dedup_key}")
        inbox_id = uuid5(NAMESPACE_URL, f"fao:gateway:inbox:{event.dedup_key}")
        payload = {
            "channel": event.channel,
            "event_id": event.event_id,
            "actor_id": event.actor_id,
            "conversation_id": event.conversation_id,
            "kind": event.kind,
            "payload": dict(event.payload),
            "occurred_at": _utc(event.occurred_at).isoformat(),
        }
        payload_hash = _sha256(payload)
        with self.engine.begin() as connection:
            mapping = self.resolve_mapping(event, connection)
            if mapping is None and self.require_identity_mapping:
                raise PermissionError("channel identity is not mapped")
            actor_ref = mapping.actor_ref if mapping else f"{event.channel}:actor:{event.actor_id}"
            target_ref = mapping.target_ref if mapping else f"{event.channel}:conversation:{event.conversation_id}"

            inserted = connection.execute(
                text(
                    """INSERT INTO fao.inbox
                    (inbox_id,source,external_event_id,correlation_id,payload,payload_sha256,received_at,processing_state,
                     channel,actor_id,conversation_id,event_kind,occurred_at,mapped_actor_ref,mapped_target_ref)
                    VALUES (:inbox_id,:source,:external_id,:correlation_id,CAST(:payload AS jsonb),:payload_hash,:received,'QUEUED',
                     :channel,:actor,:conversation,:kind,:occurred,:actor_ref,:target_ref)
                    ON CONFLICT (source,external_event_id) DO NOTHING"""
                ),
                {
                    "inbox_id": inbox_id,
                    "source": event.channel,
                    "external_id": event.event_id,
                    "correlation_id": correlation_id,
                    "payload": _canonical(payload),
                    "payload_hash": payload_hash,
                    "received": now,
                    "channel": event.channel,
                    "actor": event.actor_id,
                    "conversation": event.conversation_id,
                    "kind": event.kind,
                    "occurred": _utc(event.occurred_at),
                    "actor_ref": actor_ref,
                    "target_ref": target_ref,
                },
            )
            if inserted.rowcount == 0:
                old = (
                    connection.execute(
                        text(
                            "SELECT inbox_id,correlation_id,payload_sha256,task_id,mapped_actor_ref,mapped_target_ref FROM fao.inbox WHERE source=:source AND external_event_id=:external_id FOR UPDATE"
                        ),
                        {"source": event.channel, "external_id": event.event_id},
                    )
                    .mappings()
                    .one()
                )
                if old["payload_sha256"] != payload_hash:
                    raise ValueError("conflicting replay for channel event")
                return IngestResult(
                    False,
                    True,
                    old["task_id"] or task_id,
                    old["inbox_id"],
                    old["correlation_id"] or correlation_id,
                    old["mapped_actor_ref"] or actor_ref,
                    old["mapped_target_ref"] or target_ref,
                )

            connection.execute(
                text(
                    """INSERT INTO fao.agent_task
                    (task_id,assigned_role_id,catalog_version,correlation_id,trace_id,idempotency_key,task_state,envelope,requested_at,deadline_at)
                    VALUES (:task_id,'gateway.inbound','v3.001',:correlation_id,:trace_id,:idempotency,'QUEUED',CAST(:envelope AS jsonb),:requested,:deadline)
                    ON CONFLICT (correlation_id,idempotency_key) DO NOTHING"""
                ),
                {
                    "task_id": task_id,
                    "correlation_id": correlation_id,
                    "trace_id": correlation_id,
                    "idempotency": f"inbound:{event.channel}:{event.event_id}",
                    "envelope": _canonical(payload | {"actor_ref": actor_ref, "target_ref": target_ref}),
                    "requested": now,
                    "deadline": _utc(deadline_at) if deadline_at else None,
                },
            )
            connection.execute(
                text("UPDATE fao.inbox SET task_id=:task WHERE inbox_id=:inbox"),
                {"task": task_id, "inbox": inbox_id},
            )
            return IngestResult(True, False, task_id, inbox_id, correlation_id, actor_ref, target_ref)

    def enqueue_notification(
        self,
        notification: OutboundNotification,
        *,
        correlation_id: UUID | None = None,
        connection: Connection | None = None,
    ) -> bool:
        """Write a notification to the transactional outbox.

        The channel is part of both the topic and delivery key, so equal keys
        in two adapters cannot suppress each other.
        """

        outbox_id = uuid4()
        correlation_id = correlation_id or uuid4()
        payload = {
            "channel": notification.channel,
            "conversation_id": notification.conversation_id,
            "severity": notification.severity,
            "text": notification.text,
            "idempotency_key": notification.idempotency_key,
            "payload": dict(notification.payload) if notification.payload is not None else None,
        }

        def insert(conn: Connection) -> bool:
            result = conn.execute(
                text(
                    """INSERT INTO fao.outbox
                    (outbox_id,topic,aggregate_type,correlation_id,idempotency_key,payload,payload_sha256,
                     available_at,delivery_state,channel,conversation_id,severity,delivery_key,max_attempts)
                    VALUES (:id,:topic,'Notification',:correlation,:key,CAST(:payload AS jsonb),:hash,:available,'PENDING',
                     :channel,:conversation,:severity,:delivery_key,8)
                    ON CONFLICT (topic,idempotency_key) DO NOTHING"""
                ),
                {
                    "id": outbox_id,
                    "topic": f"channel:{notification.channel}",
                    "correlation": correlation_id,
                    "key": notification.idempotency_key,
                    "payload": _canonical(payload),
                    "hash": _sha256(payload),
                    "available": datetime.now(UTC),
                    "channel": notification.channel,
                    "conversation": notification.conversation_id,
                    "severity": notification.severity,
                    "delivery_key": notification.delivery_key,
                },
            )
            if result.rowcount == 1:
                return True
            existing_hash = conn.execute(
                text("SELECT payload_sha256 FROM fao.outbox WHERE topic=:topic AND idempotency_key=:key"),
                {"topic": f"channel:{notification.channel}", "key": notification.idempotency_key},
            ).scalar_one()
            if existing_hash != _sha256(payload):
                raise ValueError("conflicting replay for outbound notification")
            return False

        if connection is not None:
            return insert(connection)
        with self.engine.begin() as owned:
            return insert(owned)

    def claim_tasks(
        self,
        worker_id: str,
        *,
        limit: int = 10,
        lease_seconds: int = 30,
        assigned_role_prefix: str | None = None,
    ) -> tuple[GatewayTask, ...]:
        if not worker_id.strip() or limit < 1 or lease_seconds < 1:
            raise ValueError("worker_id, limit, and lease_seconds must be positive")
        now = datetime.now(UTC)
        expiry = now + timedelta(seconds=lease_seconds)
        if assigned_role_prefix is not None and not assigned_role_prefix.strip():
            raise ValueError("assigned_role_prefix must be non-empty when provided")
        role_clause = "AND t.assigned_role_id LIKE :role_prefix" if assigned_role_prefix is not None else ""
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    text(
                        f"""WITH candidates AS (
                      SELECT t.task_id FROM fao.agent_task t
                      LEFT JOIN fao.task_lease l ON l.task_id=t.task_id
                    WHERE t.task_state IN ('QUEUED','RETRY') AND t.requested_at <= :now
                        {role_clause}
                        AND (l.task_id IS NULL OR l.lease_expires_at <= :now)
                      ORDER BY t.requested_at FOR UPDATE OF t SKIP LOCKED LIMIT :limit
                    ), changed AS (
                      UPDATE fao.agent_task t SET task_state='RUNNING'
                      FROM candidates c WHERE t.task_id=c.task_id RETURNING t.task_id,t.envelope
                    )
                    SELECT c.task_id,c.envelope,COALESCE(l.fencing_token,0)+1 AS fencing_token
                    FROM changed c LEFT JOIN fao.task_lease l ON l.task_id=c.task_id"""
                    ),
                    {
                        "now": now,
                        "limit": limit,
                        **({"role_prefix": f"{assigned_role_prefix}%"} if assigned_role_prefix is not None else {}),
                    },
                )
                .mappings()
                .all()
            )
            result: list[GatewayTask] = []
            for row in rows:
                token = int(row["fencing_token"])
                connection.execute(
                    text(
                        """INSERT INTO fao.task_lease(task_id,worker_id,fencing_token,acquired_at,heartbeat_at,lease_expires_at)
                        VALUES (:task,:worker,:token,:now,:now,:expiry)
                        ON CONFLICT(task_id) DO UPDATE SET worker_id=EXCLUDED.worker_id,fencing_token=EXCLUDED.fencing_token,
                          acquired_at=EXCLUDED.acquired_at,heartbeat_at=EXCLUDED.heartbeat_at,lease_expires_at=EXCLUDED.lease_expires_at"""
                    ),
                    {"task": row["task_id"], "worker": worker_id, "token": token, "now": now, "expiry": expiry},
                )
                result.append(GatewayTask(row["task_id"], row["envelope"], token, worker_id))
            return tuple(result)

    def enqueue_watch_event(self, event: object, *, deadline_at: datetime | None = None) -> UUID | None:
        """Persist one watch event in the durable task queue.

        The event id is the queue idempotency key.  Replaying the same event
        returns ``None``; changing its trigger or payload reference under the
        same key is rejected.  The queue stores only the event facts and never
        an owner result or a trading side effect.
        """
        from futures_agent_os.agent_orchestration.v3_runtime import WatchEvent

        if not isinstance(event, WatchEvent):
            raise TypeError("enqueue_watch_event requires a WatchEvent")
        task_id = uuid5(NAMESPACE_URL, f"fao:watch-task:{event.event_id}")
        correlation_id = uuid5(NAMESPACE_URL, f"fao:watch-correlation:{event.event_id}")
        idempotency_key = f"watch:{event.event_id}"
        envelope = {
            "schema": "v3.015.watch-event.1",
            "event_id": event.event_id,
            "trigger": event.trigger.value,
            "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
            "payload_ref": event.payload_ref,
        }
        with self.engine.begin() as connection:
            inserted = connection.execute(
                text(
                    """INSERT INTO fao.agent_task
                    (task_id,assigned_role_id,catalog_version,correlation_id,trace_id,idempotency_key,
                     task_state,envelope,requested_at,deadline_at)
                    VALUES (:task,'watch.' || :trigger,'v3.015',:correlation,:trace,:idempotency,'QUEUED',
                            CAST(:envelope AS jsonb),:requested,:deadline)
                    ON CONFLICT (correlation_id,idempotency_key) DO NOTHING"""
                ),
                {
                    "task": task_id,
                    "trigger": event.trigger.value.lower(),
                    "correlation": correlation_id,
                    "trace": uuid5(NAMESPACE_URL, f"fao:watch-trace:{event.event_id}"),
                    "idempotency": idempotency_key,
                    "envelope": _canonical(envelope),
                    "requested": _utc(event.occurred_at),
                    "deadline": _utc(deadline_at) if deadline_at is not None else None,
                },
            ).rowcount
            if inserted == 1:
                return task_id
            existing = (
                connection.execute(
                    text(
                        "SELECT task_id,envelope FROM fao.agent_task WHERE correlation_id=:correlation AND idempotency_key=:idempotency"
                    ),
                    {"correlation": correlation_id, "idempotency": idempotency_key},
                )
                .mappings()
                .first()
            )
            if existing is None:
                raise RuntimeError("watch event insert disappeared")
            prior = existing["envelope"]
            if isinstance(prior, str):
                prior = json.loads(prior)
            if prior != envelope:
                raise ValueError("conflicting replay for watch event")
            return None

    def claim_watch_events(
        self, worker_id: str, *, limit: int = 10, lease_seconds: int = 30
    ) -> tuple[tuple[WatchEvent, GatewayTask], ...]:
        """Claim only watch tasks and hydrate events after a process restart."""
        from futures_agent_os.agent_orchestration.v3_runtime import WatchEvent, WatchTrigger

        claimed = self.claim_tasks(worker_id, limit=limit, lease_seconds=lease_seconds, assigned_role_prefix="watch.")
        hydrated: list[tuple[WatchEvent, GatewayTask]] = []
        for task in claimed:
            value = task.envelope
            required = {"schema", "event_id", "trigger", "occurred_at", "payload_ref"}
            if set(value) != required or value["schema"] != "v3.015.watch-event.1":
                self.complete_task(task.task_id, worker_id, task.fencing_token, success=False)
                raise ValueError("invalid durable watch event envelope")
            try:
                event = WatchEvent(
                    str(value["event_id"]),
                    WatchTrigger(str(value["trigger"])),
                    datetime.fromisoformat(str(value["occurred_at"])),
                    str(value["payload_ref"]),
                )
            except (TypeError, ValueError) as error:
                self.complete_task(task.task_id, worker_id, task.fencing_token, success=False)
                raise ValueError("invalid durable watch event") from error
            hydrated.append((event, task))
        return tuple(hydrated)

    def complete_task(self, task_id: UUID, worker_id: str, fencing_token: int, *, success: bool = True) -> bool:
        state = "COMPLETED" if success else "FAILED"
        with self.engine.begin() as connection:
            changed = connection.execute(
                text(
                    """UPDATE fao.agent_task t SET task_state=:state,completed_at=clock_timestamp()
                    WHERE t.task_id=:task AND EXISTS (
                      SELECT 1 FROM fao.task_lease l WHERE l.task_id=t.task_id AND l.worker_id=:worker AND l.fencing_token=:token
                    )"""
                ),
                {"state": state, "task": task_id, "worker": worker_id, "token": fencing_token},
            ).rowcount
            if changed:
                connection.execute(
                    text(
                        "DELETE FROM fao.task_lease WHERE task_id=:task AND worker_id=:worker AND fencing_token=:token"
                    ),
                    {"task": task_id, "worker": worker_id, "token": fencing_token},
                )
            return changed == 1

    def retry_task(self, task_id: UUID, worker_id: str, fencing_token: int, *, backoff_seconds: int = 1) -> bool:
        """Return a leased task to RETRY after a transient worker failure."""
        if isinstance(backoff_seconds, bool) or backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        with self.engine.begin() as connection:
            changed = connection.execute(
                text(
                    """UPDATE fao.agent_task t SET task_state='RETRY',
                        requested_at=clock_timestamp() + (:delay * interval '1 second')
                    WHERE t.task_id=:task AND t.task_state='RUNNING' AND EXISTS (
                      SELECT 1 FROM fao.task_lease l WHERE l.task_id=t.task_id
                        AND l.worker_id=:worker AND l.fencing_token=:token
                    )"""
                ),
                {"task": task_id, "worker": worker_id, "token": fencing_token, "delay": backoff_seconds},
            ).rowcount
            if changed:
                connection.execute(
                    text(
                        "DELETE FROM fao.task_lease WHERE task_id=:task AND worker_id=:worker AND fencing_token=:token"
                    ),
                    {"task": task_id, "worker": worker_id, "token": fencing_token},
                )
            return changed == 1

    def claim_outbox(self, worker_id: str, *, limit: int = 10, lease_seconds: int = 30) -> tuple[OutboxRecord, ...]:
        if not worker_id.strip() or limit < 1 or lease_seconds < 1:
            raise ValueError("worker_id, limit, and lease_seconds must be positive")
        now = datetime.now(UTC)
        expiry = now + timedelta(seconds=lease_seconds)
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    text(
                        """WITH candidates AS (
                      SELECT outbox_id FROM fao.outbox
                      WHERE delivery_state IN ('PENDING','RETRY') AND available_at <= :now
                        AND (lease_expires_at IS NULL OR lease_expires_at <= :now)
                      ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :limit
                    )
                    UPDATE fao.outbox o SET delivery_state='IN_FLIGHT',delivery_attempts=o.delivery_attempts+1,
                      last_attempt_at=:now,lease_owner=:worker,lease_expires_at=:expiry
                    FROM candidates c WHERE o.outbox_id=c.outbox_id
                    RETURNING o.outbox_id,o.channel,o.conversation_id,o.severity,o.payload,o.idempotency_key,
                      o.delivery_key,o.delivery_attempts,o.max_attempts,o.lease_owner"""
                    ),
                    {"now": now, "limit": limit, "worker": worker_id, "expiry": expiry},
                )
                .mappings()
                .all()
            )
            result: list[OutboxRecord] = []
            for row in rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                result.append(
                    OutboxRecord(
                        row["outbox_id"],
                        row["channel"],
                        row["conversation_id"],
                        row["severity"],
                        payload.get("text", ""),
                        row["idempotency_key"],
                        row["delivery_key"],
                        row["delivery_attempts"],
                        row["max_attempts"],
                        row["lease_owner"],
                        payload,
                    )
                )
                connection.execute(
                    text("""INSERT INTO fao.outbox_delivery_attempt
                    (attempt_id,outbox_id,attempt_number,worker_id,attempt_state,started_at)
                    VALUES (:attempt,:outbox,:number,:worker,'IN_FLIGHT',:started)
                    ON CONFLICT(outbox_id,attempt_number) DO NOTHING"""),
                    {
                        "attempt": uuid4(),
                        "outbox": row["outbox_id"],
                        "number": row["delivery_attempts"],
                        "worker": worker_id,
                        "started": now,
                    },
                )
            return tuple(result)

    def mark_delivered(self, outbox_id: UUID, worker_id: str) -> bool:
        with self.engine.begin() as connection:
            changed = connection.execute(
                text("""UPDATE fao.outbox SET delivery_state='DELIVERED',delivered_at=clock_timestamp(),lease_owner=NULL,lease_expires_at=NULL
                WHERE outbox_id=:id AND delivery_state='IN_FLIGHT' AND lease_owner=:worker"""),
                {"id": outbox_id, "worker": worker_id},
            ).rowcount
            if changed:
                connection.execute(
                    text("""UPDATE fao.outbox_delivery_attempt a SET attempt_state='DELIVERED',finished_at=clock_timestamp()
                    FROM fao.outbox o WHERE a.outbox_id=o.outbox_id AND a.outbox_id=:id
                      AND a.attempt_number=o.delivery_attempts AND a.worker_id=:worker AND a.attempt_state='IN_FLIGHT'"""),
                    {"id": outbox_id, "worker": worker_id},
                )
            return changed == 1

    def mark_failed(self, outbox_id: UUID, worker_id: str, error: str, *, backoff_seconds: int = 5) -> str:
        if not error.strip():
            raise ValueError("error is required")
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT delivery_attempts,max_attempts FROM fao.outbox WHERE outbox_id=:id AND delivery_state='IN_FLIGHT' AND lease_owner=:worker FOR UPDATE"
                    ),
                    {"id": outbox_id, "worker": worker_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return "IGNORED"
            attempts, max_attempts = int(row["delivery_attempts"]), int(row["max_attempts"])
            if attempts >= max_attempts:
                state = "DEAD"
                connection.execute(
                    text(
                        """UPDATE fao.outbox SET delivery_state='DEAD',last_error=:error,lease_owner=NULL,lease_expires_at=NULL WHERE outbox_id=:id"""
                    ),
                    {"id": outbox_id, "error": error[:1000]},
                )
                connection.execute(
                    text("""INSERT INTO fao.dead_letter(dead_letter_id,source_kind,source_id,reason_code,payload)
                    SELECT :dl,'outbox',outbox_id,'DELIVERY_EXHAUSTED',payload FROM fao.outbox WHERE outbox_id=:id
                    ON CONFLICT DO NOTHING"""),
                    {"dl": uuid4(), "id": outbox_id},
                )
            else:
                state = "RETRY"
                delay = max(1, backoff_seconds) * (2 ** min(attempts - 1, 8))
                connection.execute(
                    text("""UPDATE fao.outbox SET delivery_state='RETRY',last_error=:error,
                    available_at=clock_timestamp() + (:delay * interval '1 second'),lease_owner=NULL,lease_expires_at=NULL WHERE outbox_id=:id"""),
                    {"id": outbox_id, "error": error[:1000], "delay": delay},
                )
            connection.execute(
                text("""UPDATE fao.outbox_delivery_attempt SET attempt_state=:state,error_code=:error,finished_at=clock_timestamp()
                WHERE outbox_id=:id AND attempt_number=:attempt AND worker_id=:worker AND attempt_state='IN_FLIGHT'"""),
                {"state": state, "error": error[:1000], "id": outbox_id, "attempt": attempts, "worker": worker_id},
            )
            return state

    def recover_expired(self) -> tuple[int, int]:
        """Return expired in-flight task and outbox rows to their queues."""

        with self.engine.begin() as connection:
            outbox = connection.execute(
                text("""UPDATE fao.outbox SET delivery_state='RETRY',lease_owner=NULL,lease_expires_at=NULL
                WHERE delivery_state='IN_FLIGHT' AND lease_expires_at <= clock_timestamp()""")
            ).rowcount
            connection.execute(
                text("""UPDATE fao.outbox_delivery_attempt a SET attempt_state='LOST_LEASE',finished_at=clock_timestamp()
                FROM fao.outbox o WHERE a.outbox_id=o.outbox_id AND a.attempt_number=o.delivery_attempts
                  AND a.attempt_state='IN_FLIGHT' AND o.delivery_state='RETRY'""")
            )
            tasks = connection.execute(
                text("""UPDATE fao.agent_task t SET task_state='QUEUED'
                WHERE task_state='RUNNING' AND EXISTS (SELECT 1 FROM fao.task_lease l WHERE l.task_id=t.task_id AND l.lease_expires_at <= clock_timestamp())""")
            ).rowcount
            # Keep the expired lease row so a restarted worker receives a
            # strictly higher fencing token on the next claim.
            return tasks, outbox

    def escalate_overdue_notifications(
        self, *, now: datetime | None = None, policy: NotificationSLOPolicy | None = None
    ) -> int:
        """Create one durable operator escalation for each overdue delivery.

        The unique ``deduplication_key`` makes concurrent monitors and
        repeated heartbeats idempotent.  The escalation is written to the
        existing supervision table and can itself be delivered by the normal
        outbox/ops path.
        """
        policy = policy or NotificationSLOPolicy()
        observed_at = _utc(now)
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    text(
                        """SELECT outbox_id,channel,conversation_id,severity,delivery_state,
                                  correlation_id,created_at,available_at,delivery_attempts
                           FROM fao.outbox
                          WHERE delivery_state <> 'DELIVERED'
                            AND severity IN ('TRADE','ACTION_REQUIRED','RISK','CRITICAL')"""
                    )
                )
                .mappings()
                .all()
            )
            created = 0
            for row in rows:
                severity = str(row["severity"]).upper()
                created_at = _utc(row["created_at"])
                if not policy.overdue(severity, created_at, now=observed_at):
                    continue
                escalation_severity = "CRITICAL" if severity == "CRITICAL" else "ACTION_REQUIRED"
                deduplication_key = f"notification-slo:{row['outbox_id']}"
                payload = {
                    "schema": "v3.015.notification-slo.1",
                    "outbox_id": str(row["outbox_id"]),
                    "channel": row["channel"],
                    "conversation_id": row["conversation_id"],
                    "original_severity": severity,
                    "delivery_state": row["delivery_state"],
                    "delivery_attempts": int(row["delivery_attempts"]),
                    "deadline_at": policy.deadline_at(severity, created_at).isoformat(),
                    "observed_at": observed_at.isoformat(),
                }
                result = connection.execute(
                    text(
                        """INSERT INTO fao.supervision_notification
                           (notification_id,notification_kind,severity,recipient_ref,correlation_id,
                            deduplication_key,payload)
                           VALUES (:id,'NOTIFICATION_SLO_ESCALATION',:severity,'user:operator',:correlation,
                                   :dedup,CAST(:payload AS jsonb))
                           ON CONFLICT (deduplication_key) DO NOTHING"""
                    ),
                    {
                        "id": uuid5(NAMESPACE_URL, deduplication_key),
                        "severity": escalation_severity,
                        "correlation": row["correlation_id"],
                        "dedup": deduplication_key,
                        "payload": _canonical(payload),
                    },
                )
                created += int(result.rowcount or 0)
            return created

    def issue_control(self, callback: ControlCallback) -> ControlCallback:
        """Persist a one-use callback and return the secret token once."""

        validate_control(callback)
        _require_bound_control(callback)
        expiry = callback.expires_at
        assert expiry is not None
        token = callback.token or secrets.token_urlsafe(32)
        persisted = ControlCallback(
            callback.channel,
            callback.callback_id,
            callback.actor_id,
            callback.action,
            callback.payload,
            callback.target_id,
            callback.target_version,
            callback.target_sha256,
            expiry,
            token,
        )
        if not self._persist_control(persisted, row_id=uuid4()):
            raise ValueError("control callback id is already issued")
        return persisted

    def persist_control(self, callback: ControlCallback) -> bool:
        """Verify that an adapter callback matches a server-issued row.

        Received channel data is never allowed to create its own authorization
        record. The authoritative PENDING row is created only by issue_control.
        """
        validate_control(callback)
        _require_bound_control(callback)
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""SELECT actor_id,target_id,target_version,target_sha256,action,token_sha256,expires_at
                    FROM fao.control_callback WHERE channel=:channel AND callback_id=:callback"""),
                    {"channel": callback.channel, "callback": callback.callback_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return False
        token_matches = callback.token is not None and secrets.compare_digest(
            row["token_sha256"], hashlib.sha256(callback.token.encode()).hexdigest()
        )
        return bool(
            token_matches
            and row["actor_id"] == callback.actor_id
            and row["target_id"] == callback.target_id
            and row["target_version"] == callback.target_version
            and row["target_sha256"] == callback.target_sha256
            and row["action"] == callback.action
            and row["expires_at"] == _utc(callback.expires_at)
        )

    def _persist_control(self, callback: ControlCallback, *, row_id: UUID) -> bool:
        expiry = callback.expires_at
        if expiry is None:
            raise ValueError("control callbacks require expiry")
        token = callback.token
        with self.engine.begin() as connection:
            result = connection.execute(
                text("""INSERT INTO fao.control_callback
                    (callback_row_id,channel,callback_id,actor_id,target_id,target_version,target_sha256,action,payload,token_sha256,expires_at,callback_state)
                    VALUES (:row,:channel,:callback,:actor,:target,:target_version,:target_sha256,:action,CAST(:payload AS jsonb),:token,:expires,'PENDING')
                    ON CONFLICT(channel,callback_id) DO NOTHING"""),
                {
                    "row": row_id,
                    "channel": callback.channel,
                    "callback": callback.callback_id,
                    "actor": callback.actor_id,
                    "target": callback.target_id,
                    "target_version": callback.target_version,
                    "target_sha256": callback.target_sha256,
                    "action": callback.action,
                    "payload": _canonical(dict(callback.payload)),
                    "token": hashlib.sha256(token.encode()).hexdigest() if token else None,
                    "expires": _utc(expiry),
                },
            )
            return result.rowcount == 1

    def dispatch_control(
        self, callback: ControlCallback, handler: ControlHandler | Callable[..., object], *, now: datetime | None = None
    ) -> bool:
        """Consume and dispatch one callback in the owner transaction."""

        validate_control(callback)
        _require_bound_control(callback)
        current = _utc(now)
        if callback.expires_at is None:
            raise ValueError("control callbacks require expiry")
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""SELECT * FROM fao.control_callback
                WHERE channel=:channel AND callback_id=:callback FOR UPDATE"""),
                    {"channel": callback.channel, "callback": callback.callback_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError("control callback was not issued")
            if row["callback_state"] != "PENDING":
                return False
            if current >= row["expires_at"]:
                connection.execute(
                    text("UPDATE fao.control_callback SET callback_state='EXPIRED' WHERE callback_row_id=:row"),
                    {"row": row["callback_row_id"]},
                )
                return False
            if (
                row["actor_id"] != callback.actor_id
                or row["target_id"] != callback.target_id
                or row["target_version"] != callback.target_version
                or row["target_sha256"] != callback.target_sha256
                or row["action"] != callback.action
                or row["expires_at"] != _utc(callback.expires_at)
                or _canonical(row["payload"]) != _canonical(dict(callback.payload))
            ):
                raise PermissionError("control callback binding mismatch")
            if row["token_sha256"] is not None:
                if callback.token is None or not secrets.compare_digest(
                    row["token_sha256"], hashlib.sha256(callback.token.encode()).hexdigest()
                ):
                    raise PermissionError("control callback token mismatch")
            self._call_handler(handler, callback, connection)
            connection.execute(
                text(
                    "UPDATE fao.control_callback SET callback_state='CONSUMED',consumed_at=:now WHERE callback_row_id=:row AND callback_state='PENDING'"
                ),
                {"now": current, "row": row["callback_row_id"]},
            )
            return True

    @staticmethod
    def _call_handler(
        handler: ControlHandler | Callable[..., object], callback: ControlCallback, connection: Connection
    ) -> object:
        if hasattr(handler, "dispatch"):
            dispatch = getattr(handler, "dispatch")
            return dispatch(callback, connection)
        if inspect.isfunction(handler) or inspect.ismethod(handler):
            parameters = inspect.signature(handler).parameters
            if len(parameters) >= 2:
                return handler(callback, connection)
            return handler(callback)
        method = getattr(handler, callback.action, None)
        if method is None:
            raise ValueError(f"owner command does not support {callback.action}")
        parameters = inspect.signature(method).parameters
        if len(parameters) >= 2:
            return method(callback, connection)
        else:
            return method(callback)


class OutboxWorker:
    """At-least-once delivery loop with adapter-owned idempotency."""

    def __init__(self, store: PostgresGatewayStore, adapters: Mapping[str, Any], worker_id: str) -> None:
        self.store = store
        self.adapters = adapters
        self.worker_id = worker_id

    def run_once(self, *, limit: int = 10) -> tuple[str, ...]:
        results: list[str] = []
        for item in self.store.claim_outbox(self.worker_id, limit=limit):
            adapter = self.adapters.get(item.channel)
            if adapter is None:
                results.append(self.store.mark_failed(item.outbox_id, self.worker_id, "channel adapter unavailable"))
                continue
            try:
                adapter.send(
                    OutboundNotification(
                        item.channel,
                        item.conversation_id,
                        item.severity,
                        item.text,
                        item.idempotency_key,
                        item.payload.get("payload") if isinstance(item.payload, Mapping) else None,
                    )
                )
            except Exception as exc:  # transport failures are durable retry state
                # Persist only an exception class. Vendor exceptions may echo
                # request headers or credential material in their message.
                results.append(
                    self.store.mark_failed(item.outbox_id, self.worker_id, f"transport:{type(exc).__name__}")
                )
            else:
                results.append(
                    "DELIVERED" if self.store.mark_delivered(item.outbox_id, self.worker_id) else "LOST_LEASE"
                )
        return tuple(results)


class DurableWatchWorker:
    """Restart-safe consumer for the five-domain V3-015 watch queue.

    The reduction handler is an injected owner command boundary.  This worker
    only claims/reclaims queue leases and never writes order, position, or
    ledger state itself.
    """

    def __init__(self, store: PostgresGatewayStore, coordinator: Any, worker_id: str, reduction_handler: Any) -> None:
        if not worker_id.strip() or not callable(reduction_handler):
            raise ValueError("watch worker requires worker id and reduction handler")
        self.store = store
        self.coordinator = coordinator
        self.worker_id = worker_id
        self.reduction_handler = reduction_handler

    def run_once(self, *, limit: int = 10, max_attempts: int = 2) -> tuple[str, ...]:
        results: list[str] = []
        for event, task in self.store.claim_watch_events(self.worker_id, limit=limit):
            try:
                request = self.coordinator.process_with_retry(event, max_attempts=max_attempts)
                if request is not None:
                    self.reduction_handler(request)
            except RuntimeError, TimeoutError, ConnectionError:
                self.store.retry_task(task.task_id, self.worker_id, task.fencing_token)
                results.append("RETRY")
            except TypeError, ValueError:
                self.store.complete_task(task.task_id, self.worker_id, task.fencing_token, success=False)
                results.append("FAILED")
            else:
                self.store.complete_task(task.task_id, self.worker_id, task.fencing_token, success=True)
                results.append("COMPLETED")
        return tuple(results)


class PostgresNotificationSink:
    """NotificationSink-compatible transactional outbox adapter."""

    def __init__(self, store: PostgresGatewayStore) -> None:
        self.store = store

    def send(self, adapter: Any, notification: OutboundNotification) -> bool:
        if notification.channel != adapter.channel:
            raise ValueError("notification channel does not match adapter")
        capabilities = getattr(adapter, "capabilities", lambda: frozenset({"notify"}))()
        if "notify" not in capabilities:
            raise NotImplementedError(f"channel {adapter.channel} does not support notifications")
        return self.store.enqueue_notification(notification)


__all__ = [
    "GatewayTask",
    "IdentityMapping",
    "IngestResult",
    "OutboxRecord",
    "OutboxWorker",
    "DurableWatchWorker",
    "PostgresGatewayStore",
    "PostgresNotificationSink",
    "ControlHandler",
]
