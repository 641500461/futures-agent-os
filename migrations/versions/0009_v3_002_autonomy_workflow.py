"""V3-002 durable autonomous simulation workflow checkpoints."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0009_v3_002"
down_revision: str | Sequence[str] | None = "0008_v3_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE fao_checkpoint_owner")
    op.execute(
        """CREATE TABLE agent_checkpoint.v3_autonomy_workflow_run (
          run_id UUID PRIMARY KEY,
          trigger_origin TEXT NOT NULL CHECK(trigger_origin IN ('USER','SCHEDULE','MARKET','ACCOUNT','SYSTEM')),
          trigger_idempotency_key TEXT NOT NULL CHECK(trigger_idempotency_key=btrim(trigger_idempotency_key) AND trigger_idempotency_key<>''),
          trigger_payload JSONB NOT NULL,
          trigger_canonical TEXT NOT NULL,
          trigger_sha256 TEXT NOT NULL CHECK(trigger_sha256 ~ '^[0-9a-f]{64}$'),
          current_stage TEXT NOT NULL DEFAULT 'TRIGGERED' CHECK(current_stage IN
            ('TRIGGERED','SNAPSHOT','OPPORTUNITY_SCAN','DELEGATION_AND_CHALLENGE','TRADE_PLAN',
             'AUTHORIZATION_PREFLIGHT','SIZING_AND_RESERVATION','FINAL_RECEIPT_GATE','RISK_AND_EXECUTION',
             'MONITORING','NOTIFICATION_AND_REVIEW')),
          run_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(run_status IN ('ACTIVE','INTERRUPTED','COMPLETED','DEFERRED','FAILED')),
          state_references JSONB NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(state_references)='array'),
          state_references_canonical TEXT NOT NULL DEFAULT '[]',
          state_references_sha256 TEXT NOT NULL CHECK(state_references_sha256 ~ '^[0-9a-f]{64}$'),
          version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
          fencing_token BIGINT NOT NULL DEFAULT 0 CHECK(fencing_token>=0),
          lease_owner TEXT,
          lease_expires_at TIMESTAMPTZ,
          last_error TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(trigger_origin,trigger_idempotency_key)
        )"""
    )
    op.execute(
        """CREATE TABLE agent_checkpoint.v3_autonomy_workflow_history (
          history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          run_id UUID NOT NULL REFERENCES agent_checkpoint.v3_autonomy_workflow_run(run_id),
          run_version BIGINT NOT NULL CHECK(run_version>0),
          stage TEXT NOT NULL,
          run_status TEXT NOT NULL,
          state_references JSONB NOT NULL CHECK(jsonb_typeof(state_references)='array'),
          state_references_canonical TEXT NOT NULL,
          state_references_sha256 TEXT NOT NULL CHECK(state_references_sha256 ~ '^[0-9a-f]{64}$'),
          recorded_at TIMESTAMPTZ NOT NULL,
          UNIQUE(run_id,run_version)
        )"""
    )
    op.execute(
        "CREATE INDEX ix_v3_autonomy_claim ON agent_checkpoint.v3_autonomy_workflow_run(run_status,lease_expires_at)"
    )
    op.execute("GRANT SELECT,INSERT,UPDATE ON agent_checkpoint.v3_autonomy_workflow_run TO fao_agent_worker")
    op.execute("GRANT SELECT,INSERT ON agent_checkpoint.v3_autonomy_workflow_history TO fao_agent_worker")
    op.execute(
        "GRANT USAGE,SELECT ON SEQUENCE agent_checkpoint.v3_autonomy_workflow_history_history_id_seq TO fao_agent_worker"
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET ROLE fao_checkpoint_owner")
    op.execute("DROP TABLE IF EXISTS agent_checkpoint.v3_autonomy_workflow_history")
    op.execute("DROP TABLE IF EXISTS agent_checkpoint.v3_autonomy_workflow_run")
    op.execute("RESET ROLE")
