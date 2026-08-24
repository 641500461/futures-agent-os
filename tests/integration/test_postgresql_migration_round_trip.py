"""Real PostgreSQL acceptance tests; skipped unless an isolated DB is supplied."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("FAO_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires isolated PostgreSQL via FAO_DATABASE_URL")


def _alembic(*arguments: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env={**os.environ, "FAO_DATABASE_URL": DATABASE_URL or ""},
        check=True,
    )


def _exists(connection: object, schema: str, table: str) -> bool:
    return bool(
        connection.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"{schema}.{table}"}).scalar_one()
    )  # type: ignore[attr-defined]


def test_empty_database_upgrade_downgrade_upgrade_preserves_schema_isolation() -> None:
    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        for schema, table in (
            ("fao", "inbox"),
            ("fao", "outbox"),
            ("fao", "task_lease"),
            ("fao", "idempotency_effect"),
            ("fao", "trace_span"),
            ("fao", "alert_record"),
            ("fao", "authorization_basis"),
            ("fao", "risk_budget_reservation"),
            ("fao", "autonomy_gate_receipt"),
            ("fao", "decision_journal_entry"),
            ("agent_checkpoint", "checkpoint"),
        ):
            assert _exists(connection, schema, table)
        assert (
            connection.execute(text("SELECT has_schema_privilege('fao_agent_worker', 'fao', 'CREATE')")).scalar_one()
            is False
        )
        assert (
            connection.execute(text("SELECT has_schema_privilege('fao_checkpoint_owner', 'fao', 'USAGE')")).scalar_one()
            is True
        )
        assert (
            connection.execute(
                text("SELECT has_schema_privilege('fao_checkpoint_owner', 'fao', 'CREATE')")
            ).scalar_one()
            is False
        )
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
    command_id, duplicate_command_id, aggregate_id, duplicate_aggregate_id, correlation_id, effect_id = (
        uuid4() for _ in range(6)
    )
    run_key = uuid4().hex
    command_key = f"command-{run_key}"
    effect_key = f"effect-{run_key}"
    policy_id = f"queue-backlog-{run_key}"
    runbook_ref = f"runbook://queue-backlog-{run_key}"
    impact_scope = '["sim-users", "operators"]'
    with engine.connect() as connection:
        connection.execute(
            text("""INSERT INTO fao.command_log
            (command_id, aggregate_type, aggregate_id, actor_ref, idempotency_key, correlation_id, payload, status)
            VALUES (:command_id, 'test', :aggregate_id, 'service:test', :command_key, :correlation_id, '{}'::jsonb, 'COMPLETED')"""),
            {
                "command_id": command_id,
                "aggregate_id": aggregate_id,
                "command_key": command_key,
                "correlation_id": correlation_id,
            },
        )
        connection.execute(
            text("""INSERT INTO fao.idempotency_effect
            (idempotency_key, request_sha256, command_id, effect_id, effect_type, effect_sha256, correlation_id)
            VALUES (:effect_key, :hash, :command_id, :effect_id, 'test_effect', :hash, :correlation_id)"""),
            {
                "effect_key": effect_key,
                "hash": "a" * 64,
                "command_id": command_id,
                "effect_id": effect_id,
                "correlation_id": correlation_id,
            },
        )
        connection.execute(
            text("""INSERT INTO fao.command_log
            (command_id, aggregate_type, aggregate_id, actor_ref, idempotency_key, correlation_id, payload, status)
            VALUES (:command_id, 'test', :aggregate_id, 'service:test', :command_key, :correlation_id, '{}'::jsonb, 'COMPLETED')"""),
            {
                "command_id": duplicate_command_id,
                "aggregate_id": duplicate_aggregate_id,
                "command_key": f"duplicate-{command_key}",
                "correlation_id": correlation_id,
            },
        )
        connection.commit()
        with pytest.raises(IntegrityError):
            connection.execute(
                text("""INSERT INTO fao.idempotency_effect
                (idempotency_key, request_sha256, command_id, effect_id, effect_type, effect_sha256, correlation_id)
                VALUES (:effect_key, :hash, :command_id, :effect_id, 'test_effect', :hash, :correlation_id)"""),
                {
                    "effect_key": effect_key,
                    "hash": "b" * 64,
                    "command_id": duplicate_command_id,
                    "effect_id": uuid4(),
                    "correlation_id": correlation_id,
                },
            )
        connection.rollback()

        alert_id = uuid4()
        connection.execute(
            text("""INSERT INTO fao.alert_policy
            (policy_id, metric_name, severity, runbook_ref, impact_scope, threshold)
            VALUES (:policy_id, 'outbox_backlog', 'ERROR', :runbook_ref, CAST(:impact_scope AS jsonb), 10)"""),
            {
                "policy_id": policy_id,
                "runbook_ref": runbook_ref,
                "impact_scope": impact_scope,
            },
        )
        connection.execute(
            text("""INSERT INTO fao.alert_record
            (alert_id, policy_id, status, severity, observed_value, correlation_id, runbook_ref, impact_scope)
            VALUES (:alert_id, :policy_id, 'FIRING', 'ERROR', 12, :correlation_id, :runbook_ref, CAST(:impact_scope AS jsonb))"""),
            {
                "alert_id": alert_id,
                "policy_id": policy_id,
                "correlation_id": correlation_id,
                "runbook_ref": runbook_ref,
                "impact_scope": impact_scope,
            },
        )
        connection.commit()
        stored_alert = connection.execute(
            text("""SELECT runbook_ref, impact_scope::text
            FROM fao.alert_record WHERE alert_id = :alert_id"""),
            {"alert_id": alert_id},
        ).one()
        assert stored_alert == (runbook_ref, '["sim-users", "operators"]')
        with pytest.raises(IntegrityError):
            connection.execute(
                text("""INSERT INTO fao.alert_policy
                (policy_id, metric_name, severity, runbook_ref, impact_scope, threshold)
                VALUES (:policy_id, 'outbox_backlog', 'ERROR', 'not-a-runbook', CAST(:impact_scope AS jsonb), 10)"""),
                {
                    "policy_id": f"invalid-runbook-{run_key}",
                    "impact_scope": impact_scope,
                },
            )
        connection.rollback()

        audit_id = uuid4()
        connection.execute(
            text("""INSERT INTO fao.audit_event
            (audit_event_id, actor_ref, action, object_type, audit_sha256, correlation_id, retention_class, details)
            VALUES (:audit_id, 'service:test', 'CREATED', 'test', :hash, :correlation_id, 'operational', '{}'::jsonb)"""),
            {
                "audit_id": audit_id,
                "hash": "c" * 64,
                "correlation_id": correlation_id,
            },
        )
        connection.commit()
        chain_position = connection.execute(
            text("SELECT chain_position FROM fao.audit_event WHERE audit_event_id = :audit_id"), {"audit_id": audit_id}
        ).scalar_one()
        assert chain_position > 0
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text("UPDATE fao.audit_event SET action = 'MUTATED' WHERE audit_event_id = :audit_id"),
                {"audit_id": audit_id},
            )
        connection.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text("DELETE FROM fao.audit_event WHERE audit_event_id = :audit_id"), {"audit_id": audit_id}
            )
        connection.rollback()
        assert connection.execute(
            text("SELECT has_table_privilege('fao_runtime', 'fao.audit_event', 'INSERT')")
        ).scalar_one()
        assert (
            connection.execute(
                text("SELECT has_table_privilege('fao_runtime', 'fao.audit_event', 'UPDATE')")
            ).scalar_one()
            is False
        )


def test_v0_014_downgrade_to_v0_010_preserves_v0_007_plan_approval_decision_columns() -> None:
    _alembic("upgrade", "head")


def test_v0_014_hardening_downgrade_restores_v0_014_table_select_acl_snapshot() -> None:
    _alembic("downgrade", "0003_v0_014")
    engine = create_engine(DATABASE_URL)
    acl_sql = text("SELECT has_table_privilege('fao_runtime', 'fao.authorization_basis', 'SELECT')")
    with engine.connect() as connection:
        direct_0003_acl = connection.execute(acl_sql).scalar_one()
    _alembic("upgrade", "head")
    _alembic("downgrade", "0003_v0_014")
    with engine.connect() as connection:
        assert connection.execute(acl_sql).scalar_one() is direct_0003_acl is False
    _alembic("upgrade", "head")


def test_v1_008_upgrade_and_downgrade_preserve_domain_event_acl_and_business_boundary() -> None:
    """0005 adds worker bridges without weakening the V0 event writer ACL."""
    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL)
    runtime_event_acl = text(
        "SELECT has_table_privilege('fao_runtime', 'fao.domain_event', 'SELECT'), "
        "has_table_privilege('fao_runtime', 'fao.domain_event', 'INSERT')"
    )
    checkpoint_business_update = text(
        "SELECT has_table_privilege('fao_checkpoint_owner', 'fao.decision_episode', 'UPDATE')"
    )
    with engine.connect() as connection:
        assert connection.execute(runtime_event_acl).one() == (True, True)
        assert connection.execute(checkpoint_business_update).scalar_one() is False
    _alembic("downgrade", "0004_v0_014_hardening")
    with engine.connect() as connection:
        assert connection.execute(runtime_event_acl).one() == (True, True)
        assert (
            connection.execute(text("SELECT to_regclass('agent_checkpoint.workflow_execution') IS NULL")).scalar_one()
            is True
        )
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(runtime_event_acl).one() == (True, True)
        assert connection.execute(checkpoint_business_update).scalar_one() is False


def test_v1_008_downgrade_upgrade_rebuilds_workflow_sidecar_on_exact_event_retry() -> None:
    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL)
    event_id, aggregate_id, correlation_id = uuid4(), uuid4(), uuid4()
    occurred_at = datetime.now(UTC) - timedelta(seconds=1)
    payload = {"fact": "sidecar-rebuild"}
    canonical, digest = canonical_json_text(payload), canonical_sha256(payload)
    call = text(
        "SELECT fao.append_workflow_domain_event(:event,:aggregate,1,'SidecarFact',:correlation,"
        "'sidecar-rebuild',CAST(:payload AS jsonb),:canonical,:digest,:occurred)"
    )
    parameters = {
        "event": event_id,
        "aggregate": aggregate_id,
        "correlation": correlation_id,
        "payload": canonical,
        "canonical": canonical,
        "digest": digest,
        "occurred": occurred_at,
    }
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert connection.execute(call, parameters).scalar_one() is True

    _alembic("downgrade", "0004_v0_014_hardening")
    _alembic("upgrade", "head")
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE fao_workflow_worker"))
        assert connection.execute(call, parameters).scalar_one() is True
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT canonical_payload,payload_sha256 FROM fao.workflow_source_payload WHERE event_id=:event"),
            {"event": event_id},
        ).one() == (canonical, digest)


def test_v0_014_replaced_reservations_are_fail_closed_normalized_on_upgrade() -> None:
    """An old 0003 database can contain the unreachable REPLACED enum value."""
    _alembic("upgrade", "head")
    _alembic("downgrade", "0003_v0_014")
    engine = create_engine(DATABASE_URL)
    basis_id, mandate_id, reservation_id, binding_id = (uuid4() for _ in range(4))
    account_id, plan_id = uuid4(), uuid4()
    with engine.begin() as connection:
        # Simulate the 0003 schema before this hardening revision removed the
        # unreachable value.  There are no 0004 triggers at this revision.
        connection.execute(text("ALTER TABLE fao.risk_budget_reservation DROP CONSTRAINT ck_v014_reservation_status"))
        connection.execute(
            text("""ALTER TABLE fao.risk_budget_reservation
            ADD CONSTRAINT ck_v014_reservation_status
            CHECK (reservation_status IN ('HELD','CONSUMED','RELEASED','EXPIRED','REPLACED','RECONCILED'))""")
        )
        connection.execute(
            text("""INSERT INTO fao.authorization_basis
            (basis_id,basis_kind,basis_status,basis_sha256,plan_id,plan_version,plan_sha256,account_id,
             instrument_id,strategy_id,session_id,authorized_action,authorized_quantity,
             source_mandate_id,source_mandate_version,source_sha256,scope_snapshot,scope_sha256,
             issued_by,actor_audit_ref,expires_at)
            VALUES (:basis,'MANDATE','ACTIVE',:basis_hash,:plan,1,:plan_hash,:account,
                    'ES','strategy','session','OPEN',1,:mandate,1,:source_hash,'{}'::jsonb,:scope_hash,
                    'service:legacy','audit://legacy',CURRENT_TIMESTAMP + INTERVAL '1 hour')"""),
            {
                "basis": basis_id,
                "basis_hash": "a" * 64,
                "plan": plan_id,
                "plan_hash": "b" * 64,
                "account": account_id,
                "mandate": mandate_id,
                "source_hash": "c" * 64,
                "scope_hash": "d" * 64,
            },
        )
        connection.execute(
            text("""INSERT INTO fao.risk_budget_reservation
            (reservation_id,reservation_version,state_version,reservation_status,reservation_sha256,
             account_id,plan_id,plan_version,plan_sha256,basis_id,basis_sha256,
             risk_constitution_ref,risk_constitution_version,risk_constitution_sha256,
             instrument_id,strategy_id,session_id,risk_dimensions,quantity,worst_case_loss,margin,
             source_kind,source_ref,source_sha256,expires_at,released_at)
            VALUES (:reservation,1,1,'REPLACED',:reservation_hash,
                    :account,:plan,1,:plan_hash,:basis,:basis_hash,
                    'risk://legacy',1,:constitution_hash,
                    'ES','strategy','session','{}'::jsonb,1,0,0,
                    'MANDATE',:mandate,:source_hash,CURRENT_TIMESTAMP + INTERVAL '1 hour',
                    CURRENT_TIMESTAMP - INTERVAL '1 minute')"""),
            {
                "reservation": reservation_id,
                "reservation_hash": "e" * 64,
                "account": account_id,
                "plan": plan_id,
                "plan_hash": "b" * 64,
                "basis": basis_id,
                "basis_hash": "a" * 64,
                "constitution_hash": "f" * 64,
                "mandate": mandate_id,
                "source_hash": "c" * 64,
            },
        )
        connection.execute(
            text("ALTER TABLE fao.autonomy_mode_binding DROP CONSTRAINT ck_v014_binding_qualified_artifact_ref")
        )
        connection.execute(
            text("""INSERT INTO fao.autonomy_mode_binding
            (binding_id,version,mode,binding_status,run_versions_sha256,binding_sha256,
             scope_snapshot,scope_sha256,qualified_artifact_ref,previous_mode,expires_at)
            VALUES (:binding,1,'PAUSED','ACTIVE',:runs,:hash,'{}'::jsonb,:scope,
                    ' artifact://legacy','OBSERVE',CURRENT_TIMESTAMP + INTERVAL '1 hour')"""),
            {"binding": binding_id, "runs": "1" * 64, "hash": "2" * 64, "scope": "3" * 64},
        )
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("""SELECT reservation_status,reservation_version,state_version,released_at IS NOT NULL
            FROM fao.risk_budget_reservation WHERE reservation_id=:reservation"""),
            {"reservation": reservation_id},
        ).one() == ("RELEASED", 2, 2, True)
        constraint = connection.execute(
            text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='fao.risk_budget_reservation'::regclass
              AND conname='ck_v014_reservation_status'""")
        ).scalar_one()
        assert "REPLACED" not in constraint
        assert connection.execute(
            text("""SELECT binding_status,qualified_artifact_ref,expires_at=recorded_at
            FROM fao.autonomy_mode_binding WHERE binding_id=:binding"""),
            {"binding": binding_id},
        ).one() == ("EXPIRED", "legacy://untrusted-qualified-artifact", True)
    _alembic("downgrade", "0003_v0_014")
    with engine.connect() as connection:
        constraint = connection.execute(
            text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='fao.risk_budget_reservation'::regclass
              AND conname='ck_v014_reservation_status'""")
        ).scalar_one()
        assert "REPLACED" in constraint
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("""SELECT reservation_status,reservation_version,state_version
            FROM fao.risk_budget_reservation WHERE reservation_id=:reservation"""),
            {"reservation": reservation_id},
        ).one() == ("RELEASED", 2, 2)


def test_v0_014_populated_v0_010_blank_risk_policy_migrates_fail_closed_and_round_trips() -> None:
    _alembic("downgrade", "0002_v0_010")
    mandate_id, spaced_mandate_id, internal_space_mandate_id, expired_mandate_id, approval_id = (
        uuid4() for _ in range(5)
    )
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO fao.simulation_autonomy_mandate
            (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,risk_policy_ref,expires_at,recorded_by)
            VALUES (:mandate,1,'ACTIVE',:account,'test','{}'::jsonb,'legacy-scope','',CURRENT_TIMESTAMP + INTERVAL '1 hour','user:legacy')"""),
            {"mandate": mandate_id, "account": uuid4()},
        )
        connection.execute(
            text("""INSERT INTO fao.simulation_autonomy_mandate
            (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,risk_policy_ref,expires_at,created_at,recorded_by)
            VALUES (:mandate,1,'ACTIVE',:account,'test','{}'::jsonb,'legacy-scope','risk://legacy',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'user:legacy')"""),
            {"mandate": expired_mandate_id, "account": uuid4()},
        )
        for mandate, risk_policy_ref in (
            (spaced_mandate_id, " risk://legacy"),
            (internal_space_mandate_id, "risk policy"),
        ):
            connection.execute(
                text("""INSERT INTO fao.simulation_autonomy_mandate
                (mandate_id,version,status,simulation_account_id,environment,scope,scope_sha256,risk_policy_ref,expires_at,recorded_by)
                VALUES (:mandate,1,'ACTIVE',:account,'test','{}'::jsonb,'legacy-scope',:risk_policy_ref,CURRENT_TIMESTAMP + INTERVAL '1 hour','user:legacy')"""),
                {"mandate": mandate, "account": uuid4(), "risk_policy_ref": risk_policy_ref},
            )
        connection.execute(
            text("""INSERT INTO fao.plan_approval
            (approval_id,version,status,plan_id,plan_version,plan_sha256,approval_scope,expires_at,requested_at)
            VALUES (:approval,1,'REQUESTED',:plan,1,:hash,'{}'::jsonb,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),
            {"approval": approval_id, "plan": uuid4(), "hash": "a" * 64},
        )
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT status,risk_policy_ref FROM fao.simulation_autonomy_mandate WHERE mandate_id=:mandate"),
            {"mandate": mandate_id},
        ).one() == ("EXPIRED", "legacy://untrusted-risk-policy")
        assert connection.execute(
            text("SELECT status,expires_at>created_at FROM fao.simulation_autonomy_mandate WHERE mandate_id=:mandate"),
            {"mandate": expired_mandate_id},
        ).one() == ("EXPIRED", True)
        for mandate in (spaced_mandate_id, internal_space_mandate_id):
            assert connection.execute(
                text("SELECT status,risk_policy_ref FROM fao.simulation_autonomy_mandate WHERE mandate_id=:mandate"),
                {"mandate": mandate},
            ).one() == ("EXPIRED", "legacy://untrusted-risk-policy")
        assert connection.execute(
            text("SELECT status,expires_at>requested_at FROM fao.plan_approval WHERE approval_id=:approval"),
            {"approval": approval_id},
        ).one() == ("EXPIRED", True)
    _alembic("downgrade", "0002_v0_010")
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT status,risk_policy_ref FROM fao.simulation_autonomy_mandate WHERE mandate_id=:mandate"),
            {"mandate": mandate_id},
        ).one() == ("EXPIRED", "legacy://untrusted-risk-policy")
        assert connection.execute(
            text("SELECT status,risk_policy_ref FROM fao.simulation_autonomy_mandate WHERE mandate_id=:mandate"),
            {"mandate": internal_space_mandate_id},
        ).one() == ("EXPIRED", "legacy://untrusted-risk-policy")
    _alembic("downgrade", "0002_v0_010")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        assert connection.execute(
            text("""SELECT EXISTS (
            SELECT 1 FROM information_schema.columns WHERE table_schema='fao'
              AND table_name='plan_approval' AND column_name='decided_at')""")
        ).scalar_one()
    _alembic("upgrade", "head")
