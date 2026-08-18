"""Real PostgreSQL acceptance tests; skipped unless an isolated DB is supplied."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")


def _alembic(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *arguments], cwd=PROJECT_ROOT,
                   env={**os.environ, "FAO_DATABASE_URL": DATABASE_URL or ""}, check=True)


def _exists(connection: object, schema: str, table: str) -> bool:
    return bool(connection.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"{schema}.{table}"}).scalar_one())  # type: ignore[attr-defined]


def test_empty_database_upgrade_downgrade_upgrade_preserves_schema_isolation() -> None:
    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        for schema, table in (
            ("fao", "inbox"), ("fao", "outbox"), ("fao", "task_lease"),
            ("fao", "idempotency_effect"), ("fao", "trace_span"), ("fao", "alert_record"),
            ("agent_checkpoint", "checkpoint"),
        ):
            assert _exists(connection, schema, table)
        assert connection.execute(text("SELECT has_schema_privilege('fao_agent_worker', 'fao', 'CREATE')")).scalar_one() is False
        assert connection.execute(text("SELECT has_schema_privilege('fao_checkpoint_owner', 'fao', 'USAGE')")).scalar_one() is True
        assert connection.execute(text("SELECT has_schema_privilege('fao_checkpoint_owner', 'fao', 'CREATE')")).scalar_one() is False
    _alembic("downgrade", "base")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT to_regnamespace('fao') IS NULL")).scalar_one()
        assert connection.execute(text("SELECT to_regnamespace('agent_checkpoint') IS NULL")).scalar_one()
        assert connection.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar_one()
        assert connection.execute(text("SELECT count(*) = 0 FROM public.alembic_version")).scalar_one()
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert _exists(connection, "fao", "idempotency_effect")
        assert _exists(connection, "agent_checkpoint", "checkpoint")


def test_v0_010_database_constraints_reject_second_effect_and_audit_mutation() -> None:
    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL)
    command_id, duplicate_command_id, aggregate_id, duplicate_aggregate_id, correlation_id, effect_id = (uuid4() for _ in range(6))
    run_key = uuid4().hex
    command_key = f"command-{run_key}"
    effect_key = f"effect-{run_key}"
    policy_id = f"queue-backlog-{run_key}"
    runbook_ref = f"runbook://queue-backlog-{run_key}"
    impact_scope = '["sim-users", "operators"]'
    with engine.connect() as connection:
        connection.execute(text("""INSERT INTO fao.command_log
            (command_id, aggregate_type, aggregate_id, actor_ref, idempotency_key, correlation_id, payload, status)
            VALUES (:command_id, 'test', :aggregate_id, 'service:test', :command_key, :correlation_id, '{}'::jsonb, 'COMPLETED')"""), {
            "command_id": command_id, "aggregate_id": aggregate_id, "command_key": command_key, "correlation_id": correlation_id,
        })
        connection.execute(text("""INSERT INTO fao.idempotency_effect
            (idempotency_key, request_sha256, command_id, effect_id, effect_type, effect_sha256, correlation_id)
            VALUES (:effect_key, :hash, :command_id, :effect_id, 'test_effect', :hash, :correlation_id)"""), {
            "effect_key": effect_key, "hash": "a" * 64, "command_id": command_id, "effect_id": effect_id, "correlation_id": correlation_id,
        })
        connection.execute(text("""INSERT INTO fao.command_log
            (command_id, aggregate_type, aggregate_id, actor_ref, idempotency_key, correlation_id, payload, status)
            VALUES (:command_id, 'test', :aggregate_id, 'service:test', :command_key, :correlation_id, '{}'::jsonb, 'COMPLETED')"""), {
            "command_id": duplicate_command_id, "aggregate_id": duplicate_aggregate_id,
            "command_key": f"duplicate-{command_key}", "correlation_id": correlation_id,
        })
        connection.commit()
        with pytest.raises(IntegrityError):
            connection.execute(text("""INSERT INTO fao.idempotency_effect
                (idempotency_key, request_sha256, command_id, effect_id, effect_type, effect_sha256, correlation_id)
                VALUES (:effect_key, :hash, :command_id, :effect_id, 'test_effect', :hash, :correlation_id)"""), {
                "effect_key": effect_key, "hash": "b" * 64, "command_id": duplicate_command_id,
                "effect_id": uuid4(), "correlation_id": correlation_id,
            })
        connection.rollback()

        alert_id = uuid4()
        connection.execute(text("""INSERT INTO fao.alert_policy
            (policy_id, metric_name, severity, runbook_ref, impact_scope, threshold)
            VALUES (:policy_id, 'outbox_backlog', 'ERROR', :runbook_ref, CAST(:impact_scope AS jsonb), 10)"""), {
            "policy_id": policy_id, "runbook_ref": runbook_ref, "impact_scope": impact_scope,
        })
        connection.execute(text("""INSERT INTO fao.alert_record
            (alert_id, policy_id, status, severity, observed_value, correlation_id, runbook_ref, impact_scope)
            VALUES (:alert_id, :policy_id, 'FIRING', 'ERROR', 12, :correlation_id, :runbook_ref, CAST(:impact_scope AS jsonb))"""), {
            "alert_id": alert_id, "policy_id": policy_id, "correlation_id": correlation_id,
            "runbook_ref": runbook_ref, "impact_scope": impact_scope,
        })
        connection.commit()
        stored_alert = connection.execute(text("""SELECT runbook_ref, impact_scope::text
            FROM fao.alert_record WHERE alert_id = :alert_id"""), {"alert_id": alert_id}).one()
        assert stored_alert == (runbook_ref, '["sim-users", "operators"]')
        with pytest.raises(IntegrityError):
            connection.execute(text("""INSERT INTO fao.alert_policy
                (policy_id, metric_name, severity, runbook_ref, impact_scope, threshold)
                VALUES (:policy_id, 'outbox_backlog', 'ERROR', 'not-a-runbook', CAST(:impact_scope AS jsonb), 10)"""), {
                "policy_id": f"invalid-runbook-{run_key}", "impact_scope": impact_scope,
            })
        connection.rollback()

        audit_id = uuid4()
        connection.execute(text("""INSERT INTO fao.audit_event
            (audit_event_id, actor_ref, action, object_type, audit_sha256, correlation_id, retention_class, details)
            VALUES (:audit_id, 'service:test', 'CREATED', 'test', :hash, :correlation_id, 'operational', '{}'::jsonb)"""), {
            "audit_id": audit_id, "hash": "c" * 64, "correlation_id": correlation_id,
        })
        connection.commit()
        chain_position = connection.execute(text("SELECT chain_position FROM fao.audit_event WHERE audit_event_id = :audit_id"), {"audit_id": audit_id}).scalar_one()
        assert chain_position > 0
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("UPDATE fao.audit_event SET action = 'MUTATED' WHERE audit_event_id = :audit_id"), {"audit_id": audit_id})
        connection.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("DELETE FROM fao.audit_event WHERE audit_event_id = :audit_id"), {"audit_id": audit_id})
        connection.rollback()
        assert connection.execute(text("SELECT has_table_privilege('fao_runtime', 'fao.audit_event', 'INSERT')")).scalar_one()
        assert connection.execute(text("SELECT has_table_privilege('fao_runtime', 'fao.audit_event', 'UPDATE')")).scalar_one() is False
