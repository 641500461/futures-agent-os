"""Create the isolated PostgreSQL persistence foundation.

Revision ID: 0001_v0_007
Revises: None
Create Date: 2026-08-18

This baseline stores contracts only.  Opaque status fields deliberately do not
implement the Mandate, approval, trading, or risk state machines.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0001_v0_007"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute(statements: tuple[str, ...]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _execute((
        "DO $$ BEGIN CREATE ROLE fao_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE ROLE fao_business_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE ROLE fao_checkpoint_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE ROLE fao_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE ROLE fao_agent_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN CREATE ROLE fao_outbox_sender NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "GRANT fao_business_owner, fao_checkpoint_owner TO fao_migrator",
        "CREATE SCHEMA IF NOT EXISTS fao AUTHORIZATION fao_business_owner",
        "ALTER SCHEMA fao OWNER TO fao_business_owner",
        "CREATE SCHEMA IF NOT EXISTS agent_checkpoint AUTHORIZATION fao_checkpoint_owner",
        "ALTER SCHEMA agent_checkpoint OWNER TO fao_checkpoint_owner",
        "REVOKE ALL ON SCHEMA fao, agent_checkpoint FROM PUBLIC",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        "GRANT USAGE ON SCHEMA fao TO fao_runtime, fao_agent_worker, fao_outbox_sender, fao_checkpoint_owner",
        "GRANT USAGE ON SCHEMA agent_checkpoint TO fao_agent_worker",
        "SET ROLE fao_business_owner",
        """CREATE TABLE fao.command_log (
            command_id UUID PRIMARY KEY, aggregate_type TEXT NOT NULL, aggregate_id UUID NOT NULL,
            expected_version BIGINT, actor_ref TEXT NOT NULL, authorization_ref TEXT, policy_ref TEXT,
            idempotency_key TEXT NOT NULL, correlation_id UUID NOT NULL, causation_id UUID,
            payload JSONB NOT NULL, status TEXT NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ, UNIQUE (aggregate_type, aggregate_id, idempotency_key))""",
        """CREATE TABLE fao.domain_event (
            event_id UUID PRIMARY KEY, aggregate_type TEXT NOT NULL, aggregate_id UUID NOT NULL,
            aggregate_version BIGINT NOT NULL CHECK (aggregate_version >= 0), event_type TEXT NOT NULL,
            schema_version TEXT NOT NULL, command_id UUID REFERENCES fao.command_log(command_id),
            correlation_id UUID NOT NULL, causation_id UUID, idempotency_key TEXT NOT NULL, actor_ref TEXT NOT NULL,
            payload JSONB NOT NULL, payload_sha256 TEXT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (aggregate_type, aggregate_id, aggregate_version),
            UNIQUE (aggregate_type, aggregate_id, idempotency_key))""",
        """CREATE TABLE fao.inbox (
            inbox_id UUID PRIMARY KEY, source TEXT NOT NULL, external_event_id TEXT NOT NULL,
            correlation_id UUID, payload JSONB NOT NULL, payload_sha256 TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, processing_state TEXT NOT NULL,
            processed_at TIMESTAMPTZ, UNIQUE (source, external_event_id))""",
        """CREATE TABLE fao.outbox (
            outbox_id UUID PRIMARY KEY, topic TEXT NOT NULL, aggregate_type TEXT, aggregate_id UUID,
            event_id UUID REFERENCES fao.domain_event(event_id), correlation_id UUID NOT NULL,
            idempotency_key TEXT NOT NULL, payload JSONB NOT NULL, payload_sha256 TEXT NOT NULL,
            available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, delivery_state TEXT NOT NULL,
            delivery_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0), last_attempt_at TIMESTAMPTZ,
            delivered_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (topic, idempotency_key))""",
        """CREATE TABLE fao.dead_letter (
            dead_letter_id UUID PRIMARY KEY, source_kind TEXT NOT NULL, source_id UUID NOT NULL,
            reason_code TEXT NOT NULL, payload JSONB NOT NULL, failed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMPTZ)""",
        """CREATE TABLE fao.agent_task (
            task_id UUID PRIMARY KEY, parent_task_id UUID REFERENCES fao.agent_task(task_id), session_id UUID,
            assigned_role_id TEXT NOT NULL, catalog_version TEXT NOT NULL, correlation_id UUID NOT NULL,
            trace_id UUID NOT NULL, idempotency_key TEXT NOT NULL, task_state TEXT NOT NULL, envelope JSONB NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deadline_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
            UNIQUE (correlation_id, idempotency_key))""",
        """CREATE TABLE fao.task_lease (
            task_id UUID PRIMARY KEY REFERENCES fao.agent_task(task_id), worker_id TEXT NOT NULL,
            fencing_token BIGINT NOT NULL CHECK (fencing_token > 0), acquired_at TIMESTAMPTZ NOT NULL,
            heartbeat_at TIMESTAMPTZ NOT NULL, lease_expires_at TIMESTAMPTZ NOT NULL,
            CHECK (lease_expires_at > acquired_at), CHECK (heartbeat_at >= acquired_at))""",
        """CREATE TABLE fao.schedule (
            schedule_id UUID PRIMARY KEY, schedule_key TEXT NOT NULL UNIQUE, schedule_kind TEXT NOT NULL,
            schedule_spec JSONB NOT NULL, schedule_state TEXT NOT NULL, next_run_at TIMESTAMPTZ, last_run_at TIMESTAMPTZ,
            version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0), correlation_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE fao.supervision_notification (
            notification_id UUID PRIMARY KEY, notification_kind TEXT NOT NULL, severity TEXT NOT NULL,
            recipient_ref TEXT NOT NULL, correlation_id UUID NOT NULL, source_event_id UUID REFERENCES fao.domain_event(event_id),
            deduplication_key TEXT NOT NULL UNIQUE, payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, acknowledged_at TIMESTAMPTZ)""",
        """CREATE TABLE fao.simulation_autonomy_mandate (
            mandate_id UUID NOT NULL, version BIGINT NOT NULL CHECK (version > 0), status TEXT NOT NULL,
            simulation_account_id UUID NOT NULL,
            environment TEXT NOT NULL CHECK (environment IN ('local', 'test', 'staging', 'sim_prod')),
            scope JSONB NOT NULL, scope_sha256 TEXT NOT NULL, risk_policy_ref TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            recorded_by TEXT NOT NULL, PRIMARY KEY (mandate_id, version))""",
        """CREATE TABLE fao.plan_approval (
            approval_id UUID NOT NULL, version BIGINT NOT NULL CHECK (version > 0), status TEXT NOT NULL,
            plan_id UUID NOT NULL, plan_version BIGINT NOT NULL CHECK (plan_version > 0), plan_sha256 TEXT NOT NULL,
            approval_scope JSONB NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_at TIMESTAMPTZ, decided_by TEXT,
            PRIMARY KEY (approval_id, version), UNIQUE (plan_id, plan_version, plan_sha256, version))""",
        """CREATE TABLE fao.audit_event (
            audit_event_id UUID PRIMARY KEY, actor_ref TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT NOT NULL,
            object_id UUID, object_version BIGINT, before_sha256 TEXT, after_sha256 TEXT,
            previous_audit_sha256 TEXT, audit_sha256 TEXT NOT NULL, correlation_id UUID NOT NULL,
            causation_id UUID, retention_class TEXT NOT NULL, details JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX ix_outbox_available ON fao.outbox (delivery_state, available_at)",
        "CREATE INDEX ix_task_lease_expiry ON fao.task_lease (lease_expires_at)",
        "CREATE INDEX ix_schedule_next_run ON fao.schedule (schedule_state, next_run_at)",
        "CREATE INDEX ix_domain_event_correlation ON fao.domain_event (correlation_id, occurred_at)",
        "CREATE INDEX ix_notification_correlation ON fao.supervision_notification (correlation_id, created_at)",
        "GRANT REFERENCES ON fao.agent_task TO fao_checkpoint_owner",
        "GRANT SELECT, INSERT, UPDATE ON fao.command_log, fao.inbox, fao.agent_task, fao.task_lease, fao.schedule, fao.supervision_notification TO fao_runtime",
        "GRANT SELECT, INSERT ON fao.domain_event, fao.audit_event TO fao_runtime",
        "GRANT SELECT, INSERT, UPDATE ON fao.outbox, fao.dead_letter TO fao_runtime",
        "GRANT SELECT ON fao.simulation_autonomy_mandate, fao.plan_approval TO fao_runtime, fao_agent_worker",
        "GRANT SELECT, INSERT, UPDATE ON fao.agent_task, fao.task_lease TO fao_agent_worker",
        "GRANT SELECT, UPDATE ON fao.outbox TO fao_outbox_sender",
        "RESET ROLE",
        "SET ROLE fao_checkpoint_owner",
        """CREATE TABLE agent_checkpoint.checkpoint (
            checkpoint_id UUID PRIMARY KEY, task_id UUID NOT NULL REFERENCES fao.agent_task(task_id),
            checkpoint_version BIGINT NOT NULL CHECK (checkpoint_version > 0), state JSONB NOT NULL,
            artifact_refs JSONB NOT NULL, pending_actions JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, superseded_at TIMESTAMPTZ,
            UNIQUE (task_id, checkpoint_version))""",
        "CREATE INDEX ix_checkpoint_task ON agent_checkpoint.checkpoint (task_id, checkpoint_version DESC)",
        "GRANT SELECT, INSERT, UPDATE ON agent_checkpoint.checkpoint TO fao_agent_worker",
        "RESET ROLE",
    ))


def downgrade() -> None:
    _execute((
        "DROP SCHEMA IF EXISTS agent_checkpoint CASCADE",
        "DROP SCHEMA IF EXISTS fao CASCADE",
        "GRANT CREATE ON SCHEMA public TO PUBLIC",
        "REVOKE fao_business_owner, fao_checkpoint_owner FROM fao_migrator",
        "DROP ROLE IF EXISTS fao_outbox_sender",
        "DROP ROLE IF EXISTS fao_agent_worker",
        "DROP ROLE IF EXISTS fao_runtime",
        "DROP ROLE IF EXISTS fao_checkpoint_owner",
        "DROP ROLE IF EXISTS fao_business_owner",
        "DROP ROLE IF EXISTS fao_migrator",
    ))
