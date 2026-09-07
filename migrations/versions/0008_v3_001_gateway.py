"""Durable channel gateway state for V3-001.

The original V0 inbox/outbox tables remain the storage boundary.  This
migration adds the channel identity, delivery, lease, and one-use callback
columns required by the production gateway without introducing a second
queue or a vendor-specific schema.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0008_v3_001"
down_revision: str | Sequence[str] | None = "0007_v1_011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute(
        """CREATE TABLE fao.gateway_identity_map (
          mapping_id UUID PRIMARY KEY,
          channel TEXT NOT NULL,
          external_actor_id TEXT NOT NULL,
          external_conversation_id TEXT NOT NULL,
          actor_ref TEXT NOT NULL,
          target_ref TEXT NOT NULL,
          version BIGINT NOT NULL DEFAULT 1 CHECK(version > 0),
          active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(channel, external_actor_id, external_conversation_id)
        )"""
    )
    op.execute("CREATE INDEX ix_gateway_identity_target ON fao.gateway_identity_map(channel, target_ref, active)")
    op.execute(
        """ALTER TABLE fao.inbox
          ADD COLUMN IF NOT EXISTS channel TEXT,
          ADD COLUMN IF NOT EXISTS actor_id TEXT,
          ADD COLUMN IF NOT EXISTS conversation_id TEXT,
          ADD COLUMN IF NOT EXISTS event_kind TEXT,
          ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS mapped_actor_ref TEXT,
          ADD COLUMN IF NOT EXISTS mapped_target_ref TEXT,
          ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES fao.agent_task(task_id),
          ADD COLUMN IF NOT EXISTS processing_error TEXT"""
    )
    op.execute("UPDATE fao.inbox SET channel = source WHERE channel IS NULL")
    op.execute("CREATE INDEX ix_gateway_inbox_processing ON fao.inbox(processing_state, received_at)")
    op.execute(
        """ALTER TABLE fao.outbox
          ADD COLUMN IF NOT EXISTS channel TEXT,
          ADD COLUMN IF NOT EXISTS conversation_id TEXT,
          ADD COLUMN IF NOT EXISTS severity TEXT,
          ADD COLUMN IF NOT EXISTS delivery_key TEXT,
          ADD COLUMN IF NOT EXISTS lease_owner TEXT,
          ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 8 CHECK(max_attempts > 0),
          ADD COLUMN IF NOT EXISTS last_error TEXT"""
    )
    op.execute("UPDATE fao.outbox SET channel = split_part(topic, ':', 2) WHERE channel IS NULL")
    op.execute(
        "UPDATE fao.outbox SET delivery_key = COALESCE(channel || ':' || idempotency_key, idempotency_key) WHERE delivery_key IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_gateway_outbox_delivery ON fao.outbox(channel, delivery_key) WHERE channel IS NOT NULL AND delivery_key IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_gateway_outbox_claim ON fao.outbox(delivery_state, available_at, lease_expires_at)")
    op.execute(
        """CREATE TABLE fao.control_callback (
          callback_row_id UUID PRIMARY KEY,
          channel TEXT NOT NULL,
          callback_id TEXT NOT NULL,
          actor_id TEXT NOT NULL,
          target_id TEXT,
          target_version BIGINT,
          target_sha256 TEXT,
          action TEXT NOT NULL,
          payload JSONB NOT NULL,
          token_sha256 TEXT,
          expires_at TIMESTAMPTZ NOT NULL,
          callback_state TEXT NOT NULL CHECK(callback_state IN ('PENDING','CONSUMED','EXPIRED','REJECTED')),
          consumed_at TIMESTAMPTZ,
          command_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(channel, callback_id),
          CHECK(target_version IS NULL OR target_version >= 0),
          CHECK(target_sha256 IS NULL OR target_sha256 ~ '^[0-9a-f]{64}$'),
          CHECK(token_sha256 IS NULL OR token_sha256 ~ '^[0-9a-f]{64}$')
        )"""
    )
    op.execute("CREATE INDEX ix_control_callback_expiry ON fao.control_callback(callback_state, expires_at)")
    op.execute(
        """CREATE TABLE fao.outbox_delivery_attempt (
          attempt_id UUID PRIMARY KEY,
          outbox_id UUID NOT NULL REFERENCES fao.outbox(outbox_id),
          attempt_number INTEGER NOT NULL CHECK(attempt_number > 0),
          worker_id TEXT NOT NULL,
          attempt_state TEXT NOT NULL CHECK(attempt_state IN ('IN_FLIGHT','DELIVERED','RETRY','DEAD','LOST_LEASE')),
          error_code TEXT,
          started_at TIMESTAMPTZ NOT NULL,
          finished_at TIMESTAMPTZ,
          UNIQUE(outbox_id, attempt_number)
        )"""
    )
    op.execute(
        "CREATE INDEX ix_outbox_delivery_attempt_outbox ON fao.outbox_delivery_attempt(outbox_id, attempt_number)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON fao.gateway_identity_map, fao.control_callback TO fao_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON fao.outbox, fao.outbox_delivery_attempt TO fao_outbox_sender")
    op.execute("GRANT SELECT, INSERT, UPDATE ON fao.outbox_delivery_attempt TO fao_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON fao.inbox, fao.agent_task, fao.task_lease TO fao_runtime")
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute("DROP TABLE IF EXISTS fao.outbox_delivery_attempt")
    op.execute("DROP TABLE IF EXISTS fao.control_callback")
    op.execute("DROP INDEX IF EXISTS fao.ux_gateway_outbox_delivery")
    op.execute("DROP INDEX IF EXISTS fao.ix_gateway_outbox_claim")
    op.execute(
        """ALTER TABLE fao.outbox
          DROP COLUMN IF EXISTS last_error,
          DROP COLUMN IF EXISTS max_attempts,
          DROP COLUMN IF EXISTS lease_expires_at,
          DROP COLUMN IF EXISTS lease_owner,
          DROP COLUMN IF EXISTS delivery_key,
          DROP COLUMN IF EXISTS severity,
          DROP COLUMN IF EXISTS conversation_id,
          DROP COLUMN IF EXISTS channel"""
    )
    op.execute("DROP INDEX IF EXISTS fao.ix_gateway_inbox_processing")
    op.execute(
        """ALTER TABLE fao.inbox
          DROP COLUMN IF EXISTS processing_error,
          DROP COLUMN IF EXISTS task_id,
          DROP COLUMN IF EXISTS mapped_target_ref,
          DROP COLUMN IF EXISTS mapped_actor_ref,
          DROP COLUMN IF EXISTS occurred_at,
          DROP COLUMN IF EXISTS event_kind,
          DROP COLUMN IF EXISTS conversation_id,
          DROP COLUMN IF EXISTS actor_id,
          DROP COLUMN IF EXISTS channel"""
    )
    op.execute("DROP INDEX IF EXISTS fao.ix_gateway_identity_target")
    op.execute("DROP TABLE IF EXISTS fao.gateway_identity_map")
    op.execute("RESET ROLE")
