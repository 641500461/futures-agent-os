"""V3-015 durable watch queue acceptance tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from futures_agent_os.agent_orchestration import (
    RiskReductionRequest,
    WatchCoordinator,
    WatchEvent,
    WatchTrigger,
)
from futures_agent_os.channel_gateway import DurableWatchWorker, PostgresGatewayStore
from futures_agent_os.channel_gateway import NotificationSLOPolicy, OutboundNotification

DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")


def _upgrade() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True)


def test_watch_event_is_idempotent_and_reclaimed_after_restart() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=5)
    store = PostgresGatewayStore(engine)
    event = WatchEvent(f"v3-015-replay-{uuid4()}", WatchTrigger.POSITION, datetime.now(UTC), "position:fallback")
    assert store.enqueue_watch_event(event) is not None
    assert store.enqueue_watch_event(event) is None
    first = store.claim_watch_events("watch-worker-a", lease_seconds=1)[0]
    assert first[0] == event
    time.sleep(1.1)
    assert store.recover_expired()[0] >= 1
    second = store.claim_watch_events("watch-worker-b")[0]
    assert second[0] == event and second[1].fencing_token > first[1].fencing_token
    assert store.complete_task(second[1].task_id, "watch-worker-b", second[1].fencing_token)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT task_state FROM fao.agent_task WHERE idempotency_key=:key"),
                {"key": "watch:" + event.event_id},
            ).scalar_one()
            == "COMPLETED"
        )


def test_watch_worker_replays_same_event_key_without_duplicate_reduction() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=5)
    store = PostgresGatewayStore(engine)
    event = WatchEvent(f"v3-015-worker-{uuid4()}", WatchTrigger.ORDER, datetime.now(UTC), "order:fallback")
    store.enqueue_watch_event(event)
    reductions: list[str] = []
    coordinator = WatchCoordinator()
    coordinator.register(
        WatchTrigger.ORDER,
        lambda value: (
            reductions.append(value.event_id)
            or RiskReductionRequest("request", "position", 1, "0", "order-state", event.event_id)
        ),
    )
    worker = DurableWatchWorker(store, coordinator, "watch-worker", lambda request: None)
    assert worker.run_once() == ("COMPLETED",)
    # Re-enqueue is a no-op and therefore cannot create another owner effect.
    assert store.enqueue_watch_event(event) is None
    assert reductions == [event.event_id]


def test_reclaimed_watch_event_uses_execution_idempotency_across_worker_restart() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=5)
    store = PostgresGatewayStore(engine)
    event = WatchEvent(f"v3-015-crash-{uuid4()}", WatchTrigger.POSITION, datetime.now(UTC), "position:crash")
    store.enqueue_watch_event(event)
    coordinator = WatchCoordinator()
    coordinator.register(
        WatchTrigger.POSITION,
        lambda value: RiskReductionRequest("request-crash", "position-crash", 1, "0", "stop", event.event_id),
    )
    first = store.claim_watch_events("watch-crashed", lease_seconds=1)[0][1]
    assert first.fencing_token > 0
    request = coordinator.process(event)
    assert request is not None
    execution_effects: dict[str, str] = {}
    execution_effects[request.idempotency_key] = request.idempotency_key
    time.sleep(1.1)
    assert store.recover_expired()[0] >= 1
    restarted = DurableWatchWorker(
        store,
        coordinator=WatchCoordinator(),
        worker_id="watch-restarted",
        reduction_handler=lambda value: execution_effects.setdefault(value.idempotency_key, value.idempotency_key),
    )
    restarted.coordinator.register(
        WatchTrigger.POSITION,
        lambda value: RiskReductionRequest("request-crash", "position-crash", 1, "0", "stop", event.event_id),
    )
    assert restarted.run_once() == ("COMPLETED",)
    assert list(execution_effects) == [event.event_id]


def test_important_notification_escalates_once_when_delivery_slo_expires() -> None:
    _upgrade()
    engine = create_engine(DATABASE_URL or "", pool_size=5)
    store = PostgresGatewayStore(engine)
    key = f"v3-015-slo-{uuid4()}"
    store.enqueue_notification(OutboundNotification("feishu", "chat", "CRITICAL", "risk", key))
    with engine.connect() as connection:
        created_at = connection.execute(
            text("SELECT created_at FROM fao.outbox WHERE idempotency_key=:key"), {"key": key}
        ).scalar_one()
    policy = NotificationSLOPolicy()
    observed = policy.deadline_at("CRITICAL", created_at)
    assert store.escalate_overdue_notifications(now=observed) >= 1
    first_count = store.escalate_overdue_notifications(now=observed)
    assert first_count == 0
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT severity,payload->>'original_severity' FROM fao.supervision_notification "
                "WHERE deduplication_key=:dedup"
            ),
            {
                "dedup": "notification-slo:"
                + str(
                    connection.execute(
                        text("SELECT outbox_id FROM fao.outbox WHERE idempotency_key=:key"), {"key": key}
                    ).scalar_one()
                )
            },
        ).one()
    assert row[0] == "CRITICAL" and row[1] == "CRITICAL"
