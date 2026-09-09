"""V3-001 real PostgreSQL acceptance tests.

The suite is skipped without an explicitly supplied disposable
``FAO_DATABASE_URL``. It exercises the durable boundaries rather than the
in-memory fixture adapter.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from futures_agent_os.channel_gateway import (
    ControlCallback,
    IdentityMapping,
    InboundEvent,
    OutboundNotification,
    PostgresGatewayStore,
    OutboxWorker,
)

DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")


def _upgrade() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True)


def test_concurrent_ingest_enqueues_one_task_and_restart_reclaims_lease() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=12)
    store = PostgresGatewayStore(engine, require_identity_mapping=True)
    store.register_mapping(IdentityMapping("feishu", "user-v3", "chat-v3", "user:owner", "account:sim"))
    event_id = f"v3-event-{uuid4()}"
    event = InboundEvent("feishu", event_id, "user-v3", "chat-v3", "message", {"text": "go"}, datetime.now(UTC))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.ingest(event), range(8)))
    assert sum(item.accepted for item in results) == 1
    assert len({item.task_id for item in results}) == 1
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM fao.agent_task WHERE idempotency_key=:key"),
                {"key": f"inbound:feishu:{event_id}"},
            ).scalar_one()
            == 1
        )

    first = next(
        item
        for item in store.claim_tasks("worker-one", limit=1000, lease_seconds=1)
        if item.task_id == results[0].task_id
    )
    time.sleep(1.1)
    assert store.recover_expired()[0] >= 1
    second = next(item for item in store.claim_tasks("worker-two", limit=1000) if item.task_id == first.task_id)
    assert second.task_id == first.task_id and second.fencing_token > first.fencing_token


def test_outbox_retry_and_one_use_expiry_bound_control() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=5)
    store = PostgresGatewayStore(engine)
    notification = OutboundNotification("feishu", "chat-v3", "RISK", "risk", f"same-key-{uuid4()}")
    assert store.enqueue_notification(notification)
    assert not store.enqueue_notification(notification)
    with pytest.raises(ValueError, match="conflicting replay"):
        store.enqueue_notification(
            OutboundNotification("feishu", "chat-v3", "RISK", "changed", notification.idempotency_key)
        )
    item = store.claim_outbox("sender-v3")[0]
    assert store.mark_failed(item.outbox_id, "sender-v3", "offline") == "RETRY"

    called: list[str] = []
    callback = store.issue_control(
        ControlCallback(
            channel="feishu",
            callback_id=f"callback-{uuid4()}",
            actor_id="user-v3",
            action="pause",
            payload={},
            target_id="account:sim",
            target_version=3,
            target_sha256="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )

    class Owner:
        def dispatch(self, value: ControlCallback, connection: object) -> None:
            called.append(value.action)

    assert store.dispatch_control(callback, Owner())
    assert not store.dispatch_control(callback, Owner())
    assert called == ["pause"]


def test_unknown_or_mismatched_control_cannot_self_issue_and_concurrent_replay_is_single_use() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=12)
    store = PostgresGatewayStore(engine)
    expiry = datetime.now(UTC) + timedelta(minutes=2)
    unknown = ControlCallback(
        channel="feishu",
        callback_id=f"unknown-{uuid4()}",
        actor_id="operator",
        action="pause",
        payload={},
        target_id="mandate:one",
        target_version=4,
        target_sha256="b" * 64,
        expires_at=expiry,
        token="attacker-token",
    )
    assert not store.persist_control(unknown)
    with pytest.raises(ValueError, match="not issued"):
        store.dispatch_control(unknown, lambda value: None)

    issued = store.issue_control(
        ControlCallback(
            channel="feishu",
            callback_id=f"issued-{uuid4()}",
            actor_id="operator",
            action="pause",
            payload={},
            target_id="mandate:one",
            target_version=4,
            target_sha256="b" * 64,
            expires_at=expiry,
        )
    )
    for changes in (
        {"actor_id": "other"},
        {"target_version": 5},
        {"target_sha256": "c" * 64},
        {"token": "wrong"},
    ):
        values = {name: getattr(issued, name) for name in issued.__dataclass_fields__}
        values.update(changes)
        with pytest.raises(PermissionError):
            store.dispatch_control(ControlCallback(**values), lambda value: None)

    calls: list[str] = []

    def handle(value: ControlCallback) -> None:
        calls.append(value.callback_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: store.dispatch_control(issued, handle), range(8)))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert calls == [issued.callback_id]


def test_control_expiry_fails_closed_without_invoking_owner() -> None:
    _upgrade()
    store = PostgresGatewayStore(create_engine(DATABASE_URL or ""))
    expiry = datetime.now(UTC) + timedelta(seconds=30)
    callback = store.issue_control(
        ControlCallback(
            channel="feishu",
            callback_id=f"expiry-{uuid4()}",
            actor_id="operator",
            action="revoke",
            payload={},
            target_id="mandate:expired",
            target_version=1,
            target_sha256="d" * 64,
            expires_at=expiry,
        )
    )
    called: list[bool] = []
    assert not store.dispatch_control(callback, lambda value: called.append(True), now=expiry)
    assert called == []


def test_outbox_attempt_history_retry_delivery_dead_letter_and_worker_idempotency() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "")
    store = PostgresGatewayStore(engine)
    key = f"attempts-{uuid4()}"
    notification = OutboundNotification("feishu", "chat", "CRITICAL", "alert", key)
    assert store.enqueue_notification(notification)
    assert not store.enqueue_notification(notification)

    class FlakyAdapter:
        channel = "feishu"

        def __init__(self) -> None:
            self.calls = 0

        def send(self, value: OutboundNotification) -> None:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("offline")

    adapter = FlakyAdapter()
    worker = OutboxWorker(store, {"feishu": adapter}, "sender-history")
    assert worker.run_once() == ("RETRY",)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE fao.outbox SET available_at=clock_timestamp() WHERE delivery_key=:key"),
            {"key": notification.delivery_key},
        )
    assert worker.run_once() == ("DELIVERED",)
    assert worker.run_once() == ()
    with engine.connect() as connection:
        attempts = connection.execute(
            text("""SELECT attempt_number,attempt_state,error_code FROM fao.outbox_delivery_attempt a
            JOIN fao.outbox o USING(outbox_id) WHERE o.delivery_key=:key ORDER BY attempt_number"""),
            {"key": notification.delivery_key},
        ).all()
    assert attempts == [(1, "RETRY", "transport:ConnectionError"), (2, "DELIVERED", None)]

    dead = OutboundNotification("feishu", "chat", "RISK", "dead", f"dead-{uuid4()}")
    assert store.enqueue_notification(dead)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE fao.outbox SET max_attempts=1 WHERE delivery_key=:key"), {"key": dead.delivery_key}
        )
    claimed = store.claim_outbox("dead-sender")
    target = next(item for item in claimed if item.delivery_key == dead.delivery_key)
    assert store.mark_failed(target.outbox_id, "dead-sender", "offline") == "DEAD"
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM fao.dead_letter WHERE source_id=:id"), {"id": target.outbox_id}
            ).scalar_one()
            == 1
        )


def test_ingest_latency_p95_is_under_two_seconds_and_channel_ids_are_namespaced() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=10)
    store = PostgresGatewayStore(engine)
    durations: list[float] = []
    shared_id = f"shared-{uuid4()}"
    for index in range(100):
        event = InboundEvent(
            "feishu",
            shared_id if index == 0 else f"latency-{uuid4()}",
            "actor",
            "chat",
            "message",
            {"index": index},
            datetime.now(UTC),
        )
        started = time.perf_counter()
        assert store.ingest(event).accepted
        durations.append(time.perf_counter() - started)
    other = InboundEvent("other", shared_id, "actor", "chat", "message", {"index": 0}, datetime.now(UTC))
    assert store.ingest(other).accepted
    p95 = statistics.quantiles(durations, n=100, method="inclusive")[94]
    assert p95 < 2.0
