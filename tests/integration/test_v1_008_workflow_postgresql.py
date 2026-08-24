"""PostgreSQL recovery and projection checks for V1-008."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4 as legacy_uuid4, uuid7

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from futures_agent_os.agent_orchestration import (
    AgentBudget,
    AgentRoleId,
    ArtifactKind,
    ArtifactRef,
    CycleTrigger,
    DelegationPlan,
    DelegationStep,
    TriggerSource,
)
from futures_agent_os.agent_orchestration.workflow import PostgresWorkflowRepository
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_json_text, canonical_sha256


DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")

# All V1 workflow identities are UUIDv7.  Keep one explicit legacy generator
# only for rejection tests below.
uuid4 = uuid7


def _raw_execution_payload(
    cycle: object, episode: object, now: datetime
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """A deliberately ordinary JSON representation used to probe DB validation."""
    budget = {"max_turns": 1, "max_tool_calls": 1, "max_tokens": 100, "timeout_seconds": 60, "max_parallel_tasks": 1}
    artifact = {
        "id": str(uuid7()),
        "namespace": "artifact",
        "kind": "market_state_assessment",
        "schema": "1.0",
        "hash": "sha256:" + "a" * 64,
        "created_at": now.isoformat(),
        "as_of": now.isoformat(),
    }
    step = {
        "step_key": "research",
        "role_id": "research",
        "input_artifacts": (artifact,),
        "required_outputs": ("hypothesis",),
        "budget": budget,
        "depends_on": (),
    }
    task = {
        "task_id": str(uuid7()),
        "episode_id": str(episode),
        "step_key": "research",
        "role_id": "research",
        "depends_on": (),
        "deadline_at": (now + timedelta(seconds=60)).isoformat(),
        "required_outputs": ("hypothesis",),
        "input_artifacts": (artifact,),
        "budget": budget,
    }
    return (
        {
            "plan_id": str(uuid7()),
            "cycle_id": str(cycle),
            "episode_id": str(episode),
            "as_of": now.isoformat(),
            "expires_at": (now + timedelta(minutes=3)).isoformat(),
            "cycle_budget": budget,
            "steps": (step,),
        },
        (task,),
    )


def _raw_trigger(source: str, idempotency_key: str, now: datetime) -> dict[str, object]:
    return {
        "source": source,
        "idempotency_key": idempotency_key,
        "occurred_at": now.isoformat(),
        "input_artifacts": (
            {
                "id": "01a03265-1e39-7381-b8e0-d9555e29a1f2",
                "namespace": "artifact",
                "kind": "market_snapshot",
                "schema": "1.0",
                "hash": "sha256:" + "a" * 64,
                "created_at": now.isoformat(),
                "as_of": now.isoformat(),
            },
        ),
    }


def _artifact_payload(ref: ArtifactRef) -> dict[str, object]:
    return {
        "id": str(ref.artifact_id.value),
        "namespace": ref.artifact_id.namespace,
        "kind": ref.artifact_kind.value,
        "schema": str(ref.schema_version),
        "hash": ref.content_hash,
        "created_at": ref.created_at.value.isoformat(),
        "as_of": ref.as_of.value.isoformat(),
    }


def test_cycle_dedup_recovery_and_journal_rebuild_preserve_source_fact() -> None:
    engine = create_engine(DATABASE_URL)
    repo = PostgresWorkflowRepository()
    now = datetime.now(UTC)
    cycle_id = uuid4()
    correlation_id = uuid4()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        key = f"dataset:CU:one:{cycle_id}"
        trigger = _raw_trigger("DATA", key, now)
        trigger_hash = canonical_sha256(trigger)
        first = repo.start_cycle(
            connection,
            cycle_id,
            "DATA",
            key,
            correlation_id,
            trigger,
            trigger_hash,
            now + timedelta(minutes=5),
        )
        second = repo.start_cycle(
            connection,
            cycle_id,
            "DATA",
            key,
            correlation_id,
            trigger,
            trigger_hash,
            now + timedelta(minutes=5),
        )
        assert first == second == cycle_id
        episode_id = uuid4()
        assert (
            repo.start_episode(connection, episode_id, cycle_id, "CU:daily", now + timedelta(minutes=4)) == episode_id
        )
        assert (
            repo.start_episode(connection, episode_id, cycle_id, "CU:daily", now + timedelta(minutes=4)) == episode_id
        )
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="cycle idempotency conflict"):
            repo.start_cycle(
                connection,
                uuid4(),
                "DATA",
                key,
                correlation_id,
                trigger,
                trigger_hash,
                now + timedelta(minutes=5),
            )
        connection.rollback()
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="invalid cycle"):
            repo.start_cycle(
                connection,
                legacy_uuid4(),
                "DATA",
                f"legacy-cycle:{cycle_id}",
                correlation_id,
                trigger,
                trigger_hash,
                now + timedelta(minutes=5),
            )
        connection.rollback()
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="invalid episode"):
            repo.start_episode(connection, legacy_uuid4(), cycle_id, "legacy-episode", now + timedelta(minutes=4))
        connection.rollback()

    # A fresh connection models a worker/process restart: recovery reads only
    # the durable checkpoint and Main has no runtime state to resurrect.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert cycle_id in repo.recover_cycle_ids(connection, now)
        assert episode_id in repo.recover_episode_ids(connection, now)
        assert repo.cancel_episode(connection, episode_id, "user_cancel")
        assert episode_id not in repo.recover_episode_ids(connection, now)

    event_id, journal_id = uuid4(), uuid4()
    event_payload = {"fact": "frozen"}
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert connection.execute(
            text(
                "SELECT fao.append_workflow_domain_event(:event,:aggregate,1,'AutonomyCycleStarted',:correlation,'cycle-start',CAST(:payload AS jsonb),:canonical,:hash,:now)"
            ),
            {
                "event": event_id,
                "aggregate": cycle_id,
                "correlation": correlation_id,
                "payload": json.dumps(event_payload),
                "canonical": canonical_json_text(event_payload),
                "hash": canonical_sha256(event_payload),
                "now": now,
            },
        ).scalar_one()
        assert connection.execute(
            text("SELECT fao.bind_workflow_source_episode(:event,:episode)"),
            {"event": event_id, "episode": episode_id},
        ).scalar_one()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_learning_projector"))
        with engine.connect() as cutoff_connection:
            cutoff = cutoff_connection.execute(
                text("SELECT decision_cutoff_at FROM fao.decision_episode WHERE episode_id=:episode"),
                {"episode": episode_id},
            ).scalar_one()
        projected = datetime.now(UTC) + timedelta(seconds=1)
        assert repo.rebuild_journal(connection, journal_id, episode_id, correlation_id, cutoff, projected) == 1
        assert repo.rebuild_journal(connection, journal_id, episode_id, correlation_id, cutoff, projected) == 0
    with engine.connect() as connection:
        assert (
            json.loads(
                connection.execute(
                    text("SELECT payload::text FROM fao.domain_event WHERE event_id=:event"), {"event": event_id}
                ).scalar_one()
            )
            == event_payload
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM fao.decision_journal_entry WHERE journal_id=:journal"),
                {"journal": journal_id},
            ).scalar_one()
            == 1
        )


def test_concurrent_duplicate_trigger_is_one_effect_and_worker_has_no_direct_table_writes() -> None:
    engine = create_engine(DATABASE_URL)
    repo = PostgresWorkflowRepository()
    correlation_id = uuid4()
    cycle_id = uuid4()
    now = datetime.now(UTC)
    key = f"market:CU:bar-close:{cycle_id}"

    def start() -> object:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
            trigger = _raw_trigger("MARKET", key, now)
            return repo.start_cycle(
                connection,
                cycle_id,
                "MARKET",
                key,
                correlation_id,
                trigger,
                canonical_sha256(trigger),
                now + timedelta(minutes=5),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert len(set(executor.map(lambda _: start(), range(2)))) == 1

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
            connection.execute(
                text(
                    "INSERT INTO agent_checkpoint.workflow_execution (episode_id,plan_payload,plan_canonical,plan_sha256,task_set_payload,task_set_canonical,task_set_sha256) VALUES (:id,'{}','{}',repeat('0',64),'[]','[]',repeat('0',64))"
                ),
                {"id": uuid4()},
            )


def test_checkpoint_lease_fencing_rejects_old_worker_and_fresh_worker_finishes() -> None:
    engine = create_engine(DATABASE_URL)
    repo = PostgresWorkflowRepository()
    now, correlation, cycle = datetime.now(UTC), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"lease:{cycle}",
            correlation,
            _raw_trigger("DATA", f"lease:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"lease:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "lease", now + timedelta(minutes=4))
        task_id = uuid7()
        artifact_id = uuid7()
        budget = {
            "max_turns": 1,
            "max_tool_calls": 1,
            "max_tokens": 100,
            "timeout_seconds": 60,
            "max_parallel_tasks": 1,
        }
        artifact = {
            "id": str(artifact_id),
            "namespace": "artifact",
            "kind": "market_state_assessment",
            "schema": "1.0",
            "hash": "sha256:" + "a" * 64,
            "created_at": now.isoformat(),
            "as_of": now.isoformat(),
        }
        expires = now + timedelta(minutes=3)
        plan = {
            "plan_id": str(uuid7()),
            "cycle_id": str(cycle),
            "episode_id": str(episode),
            "as_of": now.isoformat(),
            "expires_at": expires.isoformat(),
            "cycle_budget": budget,
            "steps": (
                {
                    "step_key": "research",
                    "role_id": "research",
                    "input_artifacts": (artifact,),
                    "required_outputs": ("hypothesis",),
                    "budget": budget,
                    "depends_on": (),
                },
            ),
        }
        task = {
            "task_id": str(task_id),
            "episode_id": str(episode),
            "step_key": "research",
            "role_id": "research",
            "depends_on": (),
            "deadline_at": (now + timedelta(seconds=60)).isoformat(),
            "required_outputs": ("hypothesis",),
            "input_artifacts": (artifact,),
            "budget": budget,
        }
        assert repo.persist_execution(connection, episode, 0, plan, (task,)) == 1
        claimed_a = repo.claim_task(connection, episode, "worker-a", 1)
        assert claimed_a is not None
    # Separate connections model a real process restart; database time, not the
    # caller clock, decides the lease is over.
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_sleep(1.1)"))
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        claimed_b = repo.claim_task(connection, episode, "worker-b", 30)
        assert claimed_b is not None and claimed_b[2] > claimed_a[2]
        result = {
            "status": "COMPLETED",
            "artifacts": ({**artifact, "kind": "hypothesis"},),
            "unknowns": (),
            "warnings": (),
        }
        assert not repo.complete_task_fenced(connection, task_id, claimed_a[1], claimed_a[2], result)
        assert repo.complete_task_fenced(connection, task_id, claimed_b[1], claimed_b[2], result)
        # Terminal delivery is idempotent only for the *entire* persisted
        # result fact, not merely matching text with a stale fence/version.
        assert repo.complete_task_fenced(connection, task_id, claimed_b[1], claimed_b[2], result)
        assert not repo.complete_task_fenced(
            connection,
            task_id,
            claimed_b[1],
            claimed_b[2],
            {**result, "warnings": ("different immutable result",)},
        )
    # Result JSON is checkpoint data too: its canonical representation and
    # digest are part of the recovered fact, never metadata that hydrate may
    # silently discard.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_checkpoint_owner"))
        connection.execute(
            text(
                "UPDATE agent_checkpoint.workflow_task_checkpoint SET result_sha256=repeat('0',64) WHERE task_id=:task"
            ),
            {"task": task_id},
        )
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert not repo.complete_task_fenced(connection, task_id, claimed_b[1], claimed_b[2], result)
        with pytest.raises(DBAPIError, match="checkpoint integrity drift"):
            connection.execute(text("SELECT fao.hydrate_workflow_episode(:episode)"), {"episode": episode})


def test_typed_graph_hydrates_after_new_connection_without_raw_json() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now = datetime.now(UTC)
    artifact = ArtifactRef(
        EntityId.new("artifact"),
        ArtifactKind.MARKET_SNAPSHOT,
        SchemaVersion(1, 0),
        "sha256:" + "b" * 64,
        RecordedAt(now),
        RecordedAt(now),
    )
    trigger = CycleTrigger(TriggerSource.DATA, f"typed:{now.isoformat()}", RecordedAt(now), (artifact,))
    cycle_id, episode_id = EntityId.new("autonomy_cycle"), EntityId.new("decision_episode")
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_typed_cycle(connection, cycle_id, trigger, uuid4(), RecordedAt(now + timedelta(minutes=5)))
        repo.start_episode(connection, episode_id.value, cycle_id.value, "typed", now + timedelta(minutes=4))
        step = DelegationStep(
            "regime",
            AgentRoleId.MARKET_REGIME.value,
            (artifact,),
            (ArtifactKind.MARKET_STATE_ASSESSMENT,),
            AgentBudget(1, 1, 100, 60),
            (),
        )
        plan = DelegationPlan(
            EntityId.new("delegation_plan"),
            cycle_id,
            episode_id,
            RecordedAt(now),
            RecordedAt(now + timedelta(minutes=3)),
            (step,),
            AgentBudget(1, 1, 100, 60),
        )
        repo.persist_typed_execution(connection, plan)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        restored_cycle, restored_episode, restored_plan, tasks, results = repo.hydrate_typed_episode(
            connection, episode_id
        )
    assert restored_cycle.trigger == trigger and restored_episode.episode_id == episode_id
    assert restored_plan == plan and len(tasks) == 1 and results == ()

    # Operational checkpoint updates may move a lease or terminal result, but
    # they cannot reinterpret the durable task graph.
    with pytest.raises(DBAPIError, match="workflow task definition is immutable"):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_checkpoint_owner"))
            connection.execute(
                text(
                    "UPDATE agent_checkpoint.workflow_task_checkpoint "
                    'SET task_payload=task_payload || \'{"order":"forbidden"}\'::jsonb WHERE episode_id=:episode'
                ),
                {"episode": episode_id.value},
            )
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "UPDATE agent_checkpoint.workflow_task_checkpoint "
                'SET task_payload=task_payload || \'{"order":"forbidden"}\'::jsonb WHERE episode_id=:episode'
            ),
            {"episode": episode_id.value},
        )
        connection.execute(text("SET LOCAL session_replication_role = origin"))
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="checkpoint integrity drift"):
            repo.claim_task(connection, episode_id.value, "corrupt-graph-worker", 30)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="checkpoint integrity drift"):
            repo.hydrate_typed_episode(connection, episode_id)


def test_typed_retry_is_idempotent_and_postgres_claim_fans_in_dependency_artifacts() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now = datetime.now(UTC)
    snapshot = ArtifactRef(
        EntityId.new("market_snapshot"),
        ArtifactKind.MARKET_SNAPSHOT,
        SchemaVersion(1, 0),
        "sha256:" + "c" * 64,
        RecordedAt(now),
        RecordedAt(now),
    )
    cycle_id, episode_id = EntityId.new("autonomy_cycle"), EntityId.new("decision_episode")
    trigger = CycleTrigger(TriggerSource.DATA, f"fanin:{cycle_id.value}", RecordedAt(now), (snapshot,))
    regime = DelegationStep(
        "regime",
        AgentRoleId.MARKET_REGIME.value,
        (snapshot,),
        (ArtifactKind.MARKET_STATE_ASSESSMENT,),
        AgentBudget(1, 1, 100, 60),
        (),
    )
    research = DelegationStep(
        "research",
        AgentRoleId.RESEARCH.value,
        (),
        (ArtifactKind.HYPOTHESIS,),
        AgentBudget(1, 1, 100, 60),
        ("regime",),
    )
    plan = DelegationPlan(
        EntityId.new("delegation_plan"),
        cycle_id,
        episode_id,
        RecordedAt(now),
        RecordedAt(now + timedelta(minutes=3)),
        (regime, research),
        AgentBudget(2, 2, 200, 120),
    )
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_typed_cycle(connection, cycle_id, trigger, uuid4(), RecordedAt(now + timedelta(minutes=5)))
        repo.start_episode(connection, episode_id.value, cycle_id.value, "fanin", now + timedelta(minutes=4))

    # Two fresh workers can observe no checkpoint before either persists it.
    # Exact at-least-once retries must converge to one immutable task set.
    barrier = Barrier(2)

    def persist_from_fresh_connection() -> int:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
            barrier.wait()
            return repo.persist_typed_execution(connection, plan)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: persist_from_fresh_connection(), range(2))) == [1, 1]

    # A lost response can also be retried after the initial concurrent effect.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert repo.persist_typed_execution(connection, plan) == 1
        with pytest.raises(ValueError, match="immutable prior plan"):
            repo.persist_typed_execution(connection, replace(plan, expires_at=RecordedAt(now + timedelta(minutes=2))))
        regime_claim = repo.claim_task(connection, episode_id.value, "regime-worker", 30)
        assert regime_claim is not None and regime_claim[3]["step_key"] == "regime"
        regime_task_id = regime_claim[0]
        regime_output = ArtifactRef(
            EntityId.new("market_state_assessment"),
            ArtifactKind.MARKET_STATE_ASSESSMENT,
            SchemaVersion(1, 0),
            "sha256:" + "d" * 64,
            RecordedAt(now),
            RecordedAt(now),
        )
        assert repo.complete_task_fenced(
            connection,
            regime_task_id,
            regime_claim[1],
            regime_claim[2],
            {
                "status": "COMPLETED",
                "artifacts": (_artifact_payload(regime_output),),
                "unknowns": (),
                "warnings": (),
            },
        )
        research_claim = repo.claim_task(connection, episode_id.value, "research-worker", 30)
        assert research_claim is not None and research_claim[3]["step_key"] == "research"
        assert research_claim[3]["input_artifacts"] == [_artifact_payload(regime_output)]


def test_postgres_claim_rejects_duplicate_fan_in_artifact_identity_without_claiming() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now = datetime.now(UTC)
    snapshot = ArtifactRef(
        EntityId.new("market_snapshot"),
        ArtifactKind.MARKET_SNAPSHOT,
        SchemaVersion(1, 0),
        "sha256:" + "e" * 64,
        RecordedAt(now),
        RecordedAt(now),
    )
    cycle_id, episode_id = EntityId.new("autonomy_cycle"), EntityId.new("decision_episode")
    trigger = CycleTrigger(TriggerSource.DATA, f"duplicate-fanin:{cycle_id.value}", RecordedAt(now), (snapshot,))
    budget = AgentBudget(1, 1, 100, 60)
    plan = DelegationPlan(
        EntityId.new("delegation_plan"),
        cycle_id,
        episode_id,
        RecordedAt(now),
        RecordedAt(now + timedelta(minutes=3)),
        (
            DelegationStep(
                "regime-a",
                AgentRoleId.MARKET_REGIME.value,
                (snapshot,),
                (ArtifactKind.MARKET_STATE_ASSESSMENT,),
                budget,
                (),
            ),
            DelegationStep(
                "regime-b",
                AgentRoleId.MARKET_REGIME.value,
                (snapshot,),
                (ArtifactKind.MARKET_STATE_ASSESSMENT,),
                budget,
                (),
            ),
            DelegationStep(
                "research",
                AgentRoleId.RESEARCH.value,
                (),
                (ArtifactKind.HYPOTHESIS,),
                budget,
                ("regime-a", "regime-b"),
            ),
        ),
        AgentBudget(3, 3, 300, 180, 2),
    )
    duplicate_output = ArtifactRef(
        EntityId.new("market_state_assessment"),
        ArtifactKind.MARKET_STATE_ASSESSMENT,
        SchemaVersion(1, 0),
        "sha256:" + "f" * 64,
        RecordedAt(now),
        RecordedAt(now),
    )
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_typed_cycle(connection, cycle_id, trigger, uuid4(), RecordedAt(now + timedelta(minutes=5)))
        repo.start_episode(connection, episode_id.value, cycle_id.value, "duplicate-fanin", now + timedelta(minutes=4))
        assert repo.persist_typed_execution(connection, plan) == 1
        first = repo.claim_task(connection, episode_id.value, "regime-a-worker", 30)
        second = repo.claim_task(connection, episode_id.value, "regime-b-worker", 30)
        assert first is not None and second is not None
        for claim in (first, second):
            assert repo.complete_task_fenced(
                connection,
                claim[0],
                claim[1],
                claim[2],
                {
                    "status": "COMPLETED",
                    "artifacts": (_artifact_payload(duplicate_output),),
                    "unknowns": (),
                    "warnings": (),
                },
            )

    with pytest.raises(DBAPIError, match="fan-in input artifacts must remain unique"):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
            repo.claim_task(connection, episode_id.value, "research-worker", 30)

    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT task_status FROM agent_checkpoint.workflow_task_checkpoint "
                    "WHERE episode_id=:episode AND step_key='research'"
                ),
                {"episode": episode_id.value},
            ).scalar_one()
            == "PENDING"
        )


def test_raw_checkpoint_graph_is_rejected_before_any_checkpoint_row_exists() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now, cycle, correlation = datetime.now(UTC), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"raw-reject:{cycle}",
            correlation,
            _raw_trigger("DATA", f"raw-reject:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"raw-reject:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "raw-reject", now + timedelta(minutes=4))
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="invalid typed workflow execution"):
            repo.persist_execution(connection, episode, 0, {"cycle_budget": {"max_parallel_tasks": 1}}, ())
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM agent_checkpoint.workflow_execution WHERE episode_id=:episode"),
                {"episode": episode},
            ).scalar_one()
            == 0
        )


def test_postgres_role_contract_matches_catalog_for_both_enabled_roles() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now, cycle, correlation = datetime.now(UTC), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        key = f"role-contract:{cycle}"
        trigger = _raw_trigger("DATA", key, now)
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            key,
            correlation,
            trigger,
            canonical_sha256(trigger),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "role-contract", now + timedelta(minutes=4))
        plan, tasks = _raw_execution_payload(cycle, episode, now)
        research_wrong = json.loads(json.dumps(plan))
        research_wrong_tasks = json.loads(json.dumps(tasks))
        research_wrong["steps"][0]["required_outputs"] = ["market_state_assessment"]
        research_wrong_tasks[0]["required_outputs"] = ["market_state_assessment"]
        regime_wrong = json.loads(json.dumps(plan))
        regime_wrong_tasks = json.loads(json.dumps(tasks))
        regime_wrong["steps"][0].update(
            {
                "role_id": "market_regime",
                "required_outputs": ["hypothesis"],
                "input_artifacts": [{**regime_wrong["steps"][0]["input_artifacts"][0], "kind": "market_snapshot"}],
            }
        )
        regime_wrong_tasks[0].update(
            {
                "role_id": "market_regime",
                "required_outputs": ["hypothesis"],
                "input_artifacts": regime_wrong["steps"][0]["input_artifacts"],
            }
        )
        connection.execute(text("SET LOCAL ROLE fao_checkpoint_owner"))
        statement = text("SELECT fao.v1005_valid_execution(:episode,CAST(:plan AS jsonb),CAST(:tasks AS jsonb))")
        assert not connection.execute(
            statement,
            {"episode": episode, "plan": json.dumps(research_wrong), "tasks": json.dumps(research_wrong_tasks)},
        ).scalar_one()
        assert not connection.execute(
            statement,
            {"episode": episode, "plan": json.dumps(regime_wrong), "tasks": json.dumps(regime_wrong_tasks)},
        ).scalar_one()


def test_existing_execution_retry_revalidates_stored_execution_and_materialized_tasks() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now, cycle, correlation = datetime.now(UTC), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"retry-audit:{cycle}",
            correlation,
            _raw_trigger("DATA", f"retry-audit:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"retry-audit:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "retry-audit", now + timedelta(minutes=4))
        plan, tasks = _raw_execution_payload(cycle, episode, now)
        assert repo.persist_execution(connection, episode, 0, plan, tasks) == 1
        assert repo.persist_execution(connection, episode, 0, plan, tasks) == 1
    with engine.begin() as connection:
        # Simulate storage corruption outside the application ACL; the normal
        # owner cannot mutate this immutable execution row.
        connection.execute(
            text(
                "ALTER TABLE agent_checkpoint.workflow_execution DISABLE TRIGGER tr_v1005_workflow_execution_immutable"
            )
        )
        connection.execute(
            text("UPDATE agent_checkpoint.workflow_execution SET plan_sha256=repeat('0',64) WHERE episode_id=:episode"),
            {"episode": episode},
        )
        connection.execute(
            text("ALTER TABLE agent_checkpoint.workflow_execution ENABLE TRIGGER tr_v1005_workflow_execution_immutable")
        )
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="checkpoint integrity drift"):
            repo.persist_execution(connection, episode, 0, plan, tasks)


def test_checkpoint_json_helpers_reject_closed_world_authority_and_budget_fields() -> None:
    engine = create_engine(DATABASE_URL)
    now, cycle, correlation = datetime.now(UTC), uuid4(), uuid4()
    artifact = {
        "id": str(uuid7()),
        "namespace": "artifact",
        "kind": "market_snapshot",
        "schema": "1.0",
        "hash": "sha256:" + "a" * 64,
        "created_at": now.isoformat(),
        "as_of": now.isoformat(),
    }
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo = PostgresWorkflowRepository()
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"closed-world:{cycle}",
            correlation,
            _raw_trigger("DATA", f"closed-world:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"closed-world:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "closed-world", now + timedelta(minutes=4))
        plan, tasks = _raw_execution_payload(cycle, episode, now)
        connection.execute(text("SET LOCAL ROLE fao_checkpoint_owner"))
        assert (
            connection.execute(
                text("SELECT fao.v1005_valid_execution(:episode,CAST(:plan AS jsonb),CAST(:tasks AS jsonb))"),
                {"episode": episode, "plan": canonical_json_text(plan), "tasks": canonical_json_text(tasks)},
            ).scalar_one()
            is True
        )
        for target, field, value in (
            (plan, "trade_plan", "forbidden"),
            (plan, "plan_id", str(legacy_uuid4())),
            (tasks[0], "order", "forbidden"),
            (plan["cycle_budget"], "max_tokens", 0),
            (plan["cycle_budget"], "max_tokens", 1),
        ):
            mutated_plan, mutated_tasks = json.loads(canonical_json_text(plan)), json.loads(canonical_json_text(tasks))
            if target is plan:
                mutated_plan[field] = value
            elif target is tasks[0]:
                mutated_tasks[0][field] = value
            else:
                mutated_plan["cycle_budget"][field] = value
            assert not connection.execute(
                text("SELECT fao.v1005_valid_execution(:episode,CAST(:plan AS jsonb),CAST(:tasks AS jsonb))"),
                {
                    "episode": episode,
                    "plan": json.dumps(mutated_plan, sort_keys=True),
                    "tasks": json.dumps(mutated_tasks, sort_keys=True),
                },
            ).scalar_one()
        empty_inputs_plan = json.loads(canonical_json_text(plan))
        empty_inputs_plan["steps"][0]["input_artifacts"] = []
        assert not connection.execute(
            text("SELECT fao.v1005_valid_execution(:episode,CAST(:plan AS jsonb),CAST(:tasks AS jsonb))"),
            {"episode": episode, "plan": json.dumps(empty_inputs_plan), "tasks": canonical_json_text(tasks)},
        ).scalar_one()
        valid_result = {
            "task_id": tasks[0]["task_id"],
            "status": "COMPLETED",
            "artifacts": ({**artifact, "kind": "hypothesis"},),
            "unknowns": (),
            "warnings": (),
        }
        assert (
            connection.execute(
                text("SELECT fao.v1005_valid_task_result(CAST(:task AS jsonb),CAST(:result AS jsonb))"),
                {"task": canonical_json_text(tasks[0]), "result": canonical_json_text(valid_result)},
            ).scalar_one()
            is True
        )
        assert (
            connection.execute(
                text("SELECT fao.v1005_valid_task_result(CAST(:task AS jsonb),CAST(:result AS jsonb))"),
                {
                    "task": canonical_json_text(tasks[0]),
                    "result": canonical_json_text({**valid_result, "approval": "forbidden"}),
                },
            ).scalar_one()
            is False
        )
        assert (
            connection.execute(
                text("SELECT fao.v1005_valid_task_result(CAST(:task AS jsonb),CAST(:result AS jsonb))"),
                {
                    "task": canonical_json_text(tasks[0]),
                    "result": canonical_json_text(
                        {
                            "task_id": tasks[0]["task_id"],
                            "status": "FAILED",
                            "artifacts": (),
                            "unknowns": (123,),
                            "warnings": (),
                        }
                    ),
                },
            ).scalar_one()
            is False
        )
        assert (
            connection.execute(
                text("SELECT fao.v1005_valid_artifact(CAST(:artifact AS jsonb))"),
                {"artifact": canonical_json_text({**artifact, "fill": "forbidden"})},
            ).scalar_one()
            is False
        )


def test_recovery_recursively_skips_deadline_dependents_and_closes_cycle() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now, cycle, correlation = datetime.now(UTC), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"deadline-tree:{cycle}",
            correlation,
            _raw_trigger("DATA", f"deadline-tree:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"deadline-tree:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "deadline-tree", now + timedelta(minutes=4))
        plan, (a,) = _raw_execution_payload(cycle, episode, now - timedelta(minutes=2))
        plan["expires_at"] = (now + timedelta(minutes=3)).isoformat()
        plan["cycle_budget"] = {
            "max_turns": 2,
            "max_tool_calls": 2,
            "max_tokens": 200,
            "timeout_seconds": 120,
            "max_parallel_tasks": 1,
        }
        steps = []
        tasks = []
        regime_inputs = tuple({**value, "kind": "market_snapshot"} for value in plan["steps"][0]["input_artifacts"])
        for key, role, output, inputs, deps, deadline in (
            (
                "a",
                "market_regime",
                "market_state_assessment",
                regime_inputs,
                (),
                now - timedelta(seconds=1),
            ),
            ("b", "research", "hypothesis", (), ("a",), now + timedelta(minutes=1)),
        ):
            step = {
                **plan["steps"][0],
                "step_key": key,
                "role_id": role,
                "input_artifacts": inputs,
                "required_outputs": (output,),
                "depends_on": deps,
            }
            steps.append(step)
            tasks.append(
                {
                    **a,
                    "task_id": str(uuid7()),
                    "step_key": key,
                    "role_id": role,
                    "input_artifacts": inputs,
                    "depends_on": deps,
                    "required_outputs": (output,),
                    "deadline_at": deadline.isoformat(),
                }
            )
        plan["steps"] = tuple(steps)
        assert repo.persist_execution(connection, episode, 0, plan, tuple(tasks)) == 1
        # Claim itself normalizes expired work before choosing a candidate;
        # downstream tasks never leak through as independently runnable work.
        assert repo.claim_task(connection, episode, "deadline-worker", 30) is None
        repo.recover_cycle_ids(connection, now)
        connection.execute(text("SET LOCAL ROLE fao_business_owner"))
        statuses = dict(
            connection.execute(
                text(
                    "SELECT step_key,task_status FROM agent_checkpoint.workflow_task_checkpoint WHERE episode_id=:episode"
                ),
                {"episode": episode},
            ).all()
        )
        assert statuses == {"a": "TIMED_OUT", "b": "SKIPPED"}
        assert (
            connection.execute(
                text("SELECT episode_status FROM fao.decision_episode WHERE episode_id=:episode"), {"episode": episode}
            ).scalar_one()
            == "DEFERRED"
        )
        assert (
            connection.execute(
                text("SELECT cycle_status FROM fao.autonomy_cycle WHERE cycle_id=:cycle"), {"cycle": cycle}
            ).scalar_one()
            == "DEFERRED"
        )


def test_workflow_event_is_immutable_and_checkpoint_owner_cannot_update_business_episode() -> None:
    engine = create_engine(DATABASE_URL)
    now, cycle, correlation, event = datetime.now(UTC), uuid4(), uuid4(), uuid4()
    payload = {"nested": {"unicode": "中文", "facts": (1, True)}}
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo = PostgresWorkflowRepository()
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"tamper:{cycle}",
            correlation,
            _raw_trigger("DATA", f"tamper:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"tamper:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "tamper", now + timedelta(minutes=4))
        other_episode = repo.start_episode(connection, uuid4(), cycle, "tamper-other", now + timedelta(minutes=4))
        assert connection.execute(
            text(
                "SELECT fao.append_workflow_domain_event(:id,:aggregate,1,'Fact',:corr,'fact',CAST(:payload AS jsonb),:canonical,:hash,:at)"
            ),
            {
                "id": event,
                "aggregate": cycle,
                "corr": correlation,
                "payload": canonical_json_text(payload),
                "canonical": canonical_json_text(payload),
                "hash": canonical_sha256(payload),
                "at": now,
            },
        ).scalar_one()
        assert connection.execute(
            text("SELECT fao.bind_workflow_source_episode(:event,:episode)"), {"event": event, "episode": episode}
        ).scalar_one()
        assert not connection.execute(
            text("SELECT fao.bind_workflow_source_episode(:event,:episode)"),
            {"event": event, "episode": other_episode},
        ).scalar_one()
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE fao.domain_event SET payload='{}'::jsonb WHERE event_id=:event"), {"event": event}
            )
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_checkpoint_owner"))
            connection.execute(
                text("UPDATE fao.decision_episode SET episode_status='CANCELLED' WHERE episode_id=:episode"),
                {"episode": episode},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_business_owner"))
            connection.execute(text("DELETE FROM fao.workflow_episode_source WHERE event_id=:event"), {"event": event})


def test_workflow_event_rejects_hash_and_immutable_field_drift_exactly() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now, cycle, correlation, event = datetime.now(UTC), uuid4(), uuid4(), uuid4()
    payload = {"nested": {"unicode": "中文", "decimal": "12.50"}, "items": (1, True, "x")}
    canonical, digest = canonical_json_text(payload), canonical_sha256(payload)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        repo.start_cycle(
            connection,
            cycle,
            "DATA",
            f"event-integrity:{cycle}",
            correlation,
            _raw_trigger("DATA", f"event-integrity:{cycle}", now),
            canonical_sha256(_raw_trigger("DATA", f"event-integrity:{cycle}", now)),
            now + timedelta(minutes=5),
        )
        episode = repo.start_episode(connection, uuid4(), cycle, "integrity", now + timedelta(minutes=4))
        arguments = {
            "id": event,
            "aggregate": cycle,
            "corr": correlation,
            "payload": canonical,
            "canonical": canonical,
            "hash": digest,
            "at": now,
        }
        statement = text(
            "SELECT fao.append_workflow_domain_event(:id,:aggregate,1,'Fact',:corr,'fact',"
            "CAST(:payload AS jsonb),:canonical,:hash,:at)"
        )
        assert connection.execute(statement, arguments).scalar_one() is True
        assert connection.execute(statement, arguments).scalar_one() is True
        assert (
            connection.execute(
                statement,
                {**arguments, "id": uuid4(), "hash": "0" * 64},
            ).scalar_one()
            is False
        )
        assert (
            connection.execute(
                statement,
                {
                    **arguments,
                    "canonical": canonical_json_text({"changed": True}),
                    "hash": canonical_sha256({"changed": True}),
                },
            ).scalar_one()
            is False
        )
        assert (
            connection.execute(
                text("SELECT fao.bind_workflow_source_episode(:event,:episode)"), {"event": event, "episode": episode}
            ).scalar_one()
            is True
        )

    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE fao.workflow_source_payload SET canonical_payload='{}' WHERE event_id=:event"),
                {"event": event},
            )
    journal_id, projected_at = uuid4(), now + timedelta(seconds=2)
    with engine.connect() as connection:
        cutoff = connection.execute(
            text("SELECT decision_cutoff_at FROM fao.decision_episode WHERE episode_id=:episode"),
            {"episode": episode},
        ).scalar_one()
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_learning_projector"))
        assert repo.rebuild_journal(connection, journal_id, episode, correlation, cutoff, projected_at) == 1

    # An operator-level bypass is deliberately simulated: projector validation
    # must still reject a corrupted previously-projected fact.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("UPDATE fao.domain_event SET payload=CAST(:payload AS jsonb) WHERE event_id=:event"),
            {"event": event, "payload": '{"tampered":true}'},
        )
        connection.execute(text("SET LOCAL session_replication_role = origin"))
    with pytest.raises(
        DBAPIError, match="source immutable fact mismatch|source identity drift|journal immutable fact mismatch"
    ):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_learning_projector"))
            repo.rebuild_journal(connection, journal_id, episode, correlation, cutoff, projected_at)


def test_creation_facts_are_closed_world_immutable_and_hydrate_detects_operator_correlation_drift() -> None:
    engine, repo = create_engine(DATABASE_URL), PostgresWorkflowRepository()
    now, cycle, episode, correlation = datetime.now(UTC), uuid4(), uuid4(), uuid4()
    key = f"creation-integrity:{cycle}"
    trigger = _raw_trigger("DATA", key, now)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert (
            repo.start_cycle(
                connection,
                cycle,
                "DATA",
                key,
                correlation,
                trigger,
                canonical_sha256(trigger),
                now + timedelta(minutes=5),
            )
            == cycle
        )
        assert (
            repo.start_episode(connection, episode, cycle, "creation-integrity", now + timedelta(minutes=4)) == episode
        )
        assert (
            repo.start_episode(connection, episode, cycle, "creation-integrity", now + timedelta(minutes=4)) == episode
        )
        hydrated = connection.execute(
            text("SELECT fao.hydrate_workflow_episode(:episode)"), {"episode": episode}
        ).scalar_one()
        assert hydrated["cycle"]["correlation_id"] == str(correlation)
        assert hydrated["episode"]["correlation_id"] == str(correlation)

    with engine.connect() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        with pytest.raises(DBAPIError, match="episode conflict"):
            repo.start_episode(connection, uuid4(), cycle, "creation-integrity", now + timedelta(minutes=4))
        connection.rollback()

    with pytest.raises(DBAPIError, match="workflow creation facts are immutable"):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_business_owner"))
            connection.execute(
                text("UPDATE fao.autonomy_cycle SET trigger_payload='{}'::jsonb WHERE cycle_id=:cycle"),
                {"cycle": cycle},
            )
    with pytest.raises(DBAPIError, match="workflow creation facts are immutable"):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_business_owner"))
            connection.execute(
                text("UPDATE fao.decision_episode SET correlation_id=:other WHERE episode_id=:episode"),
                {"other": uuid4(), "episode": episode},
            )

    # Direct owner writes are blocked; a privileged physical corruption still
    # cannot be silently hydrated by a fresh worker process.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("UPDATE fao.decision_episode SET correlation_id=:other WHERE episode_id=:episode"),
            {"other": uuid4(), "episode": episode},
        )
        connection.execute(text("SET LOCAL session_replication_role = origin"))
    with pytest.raises(DBAPIError, match="workflow creation integrity drift"):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
            connection.execute(text("SELECT fao.hydrate_workflow_episode(:episode)"), {"episode": episode})
