"""Add durable V0 observability, idempotency-effect, and audit-chain primitives.

Revision ID: 0002_v0_010
Revises: 0001_v0_007
Create Date: 2026-08-18

The application service must claim an idempotency key, write its one business
effect, audit event, and outbox record in the same PostgreSQL transaction.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0002_v0_010"
down_revision: str | Sequence[str] | None = "0001_v0_007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute(statements: tuple[str, ...]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _execute((
        "SET ROLE fao_business_owner",
        """CREATE TABLE fao.idempotency_effect (
            idempotency_key TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
            command_id UUID NOT NULL UNIQUE REFERENCES fao.command_log(command_id),
            effect_id UUID NOT NULL UNIQUE, effect_type TEXT NOT NULL, effect_sha256 TEXT NOT NULL CHECK (effect_sha256 ~ '^[0-9a-f]{64}$'),
            correlation_id UUID NOT NULL, causation_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """ALTER TABLE fao.audit_event
            ADD COLUMN chain_position BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            ADD CONSTRAINT ck_audit_sha256 CHECK (audit_sha256 ~ '^[0-9a-f]{64}$'),
            ADD CONSTRAINT ck_audit_previous_sha256 CHECK (previous_audit_sha256 IS NULL OR previous_audit_sha256 ~ '^[0-9a-f]{64}$')""",
        """CREATE OR REPLACE FUNCTION fao.reject_audit_event_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fao.audit_event is append-only'; END; $$""",
        """CREATE TRIGGER trg_audit_event_append_only BEFORE UPDATE OR DELETE ON fao.audit_event
            FOR EACH ROW EXECUTE FUNCTION fao.reject_audit_event_mutation()""",
        """CREATE TABLE fao.trace_span (
            span_id UUID PRIMARY KEY, trace_id UUID NOT NULL, correlation_id UUID NOT NULL, causation_id UUID,
            span_name TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NOT NULL,
            attributes JSONB NOT NULL, CHECK (finished_at >= started_at))""",
        """CREATE TABLE fao.metric_sample (
            metric_id UUID PRIMARY KEY, metric_name TEXT NOT NULL, metric_kind TEXT NOT NULL,
            metric_value NUMERIC NOT NULL, labels JSONB NOT NULL, correlation_id UUID,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE fao.observability_log (
            log_id UUID PRIMARY KEY, event_code TEXT NOT NULL, severity TEXT NOT NULL, trace_id UUID NOT NULL,
            correlation_id UUID NOT NULL, causation_id UUID, fields JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE fao.alert_policy (
            policy_id TEXT PRIMARY KEY, metric_name TEXT NOT NULL, severity TEXT NOT NULL,
            runbook_ref TEXT NOT NULL, impact_scope JSONB NOT NULL,
            threshold NUMERIC, absence_after_seconds INTEGER,
            CHECK ((threshold IS NOT NULL) <> (absence_after_seconds IS NOT NULL)),
            CHECK (absence_after_seconds IS NULL OR absence_after_seconds > 0),
            CHECK (runbook_ref ~ '^runbook://[^[:space:]]+$'),
            CHECK (jsonb_typeof(impact_scope) = 'array' AND jsonb_array_length(impact_scope) > 0))""",
        """CREATE TABLE fao.alert_record (
            alert_id UUID PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES fao.alert_policy(policy_id),
            status TEXT NOT NULL, severity TEXT NOT NULL, observed_value NUMERIC, correlation_id UUID,
            runbook_ref TEXT NOT NULL, impact_scope JSONB NOT NULL,
            CHECK (runbook_ref ~ '^runbook://[^[:space:]]+$'),
            CHECK (jsonb_typeof(impact_scope) = 'array' AND jsonb_array_length(impact_scope) > 0),
            observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX ix_trace_span_correlation ON fao.trace_span (correlation_id, started_at)",
        "CREATE INDEX ix_metric_sample_name_recorded ON fao.metric_sample (metric_name, recorded_at)",
        "CREATE INDEX ix_observability_log_correlation ON fao.observability_log (correlation_id, recorded_at)",
        "GRANT SELECT, INSERT ON fao.idempotency_effect, fao.trace_span, fao.metric_sample, fao.observability_log, fao.alert_record TO fao_runtime",
        "GRANT SELECT ON fao.alert_policy TO fao_runtime, fao_agent_worker",
        "RESET ROLE",
    ))


def downgrade() -> None:
    _execute((
        "SET ROLE fao_business_owner",
        "DROP TABLE IF EXISTS fao.alert_record",
        "DROP TABLE IF EXISTS fao.alert_policy",
        "DROP TABLE IF EXISTS fao.observability_log",
        "DROP TABLE IF EXISTS fao.metric_sample",
        "DROP TABLE IF EXISTS fao.trace_span",
        "DROP TRIGGER IF EXISTS trg_audit_event_append_only ON fao.audit_event",
        "DROP FUNCTION IF EXISTS fao.reject_audit_event_mutation()",
        "ALTER TABLE fao.audit_event DROP CONSTRAINT IF EXISTS ck_audit_previous_sha256, DROP CONSTRAINT IF EXISTS ck_audit_sha256, DROP COLUMN IF EXISTS chain_position",
        "DROP TABLE IF EXISTS fao.idempotency_effect",
        "RESET ROLE",
    ))
