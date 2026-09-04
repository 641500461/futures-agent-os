"""V1-011 research-only experiment registration and async job facts."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "0007_v1_011"
down_revision: str | Sequence[str] | None = "0006_v1_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET ROLE fao_business_owner")
    op.execute(
        """CREATE TABLE fao.experiment (
          experiment_id UUID PRIMARY KEY,
          version BIGINT NOT NULL CHECK(version > 0),
          request_id UUID NOT NULL,
          original_conversation_id UUID NOT NULL,
          schema_version TEXT NOT NULL,
          plan_payload JSONB NOT NULL,
          plan_sha256 TEXT NOT NULL CHECK(plan_sha256 ~ '^[0-9a-f]{64}$'),
          as_of TIMESTAMPTZ NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL CHECK(expires_at > as_of),
          max_tokens BIGINT NOT NULL CHECK(max_tokens > 0),
          max_tool_calls BIGINT NOT NULL CHECK(max_tool_calls > 0),
          timeout_seconds BIGINT NOT NULL CHECK(timeout_seconds > 0),
          priority INTEGER NOT NULL DEFAULT 0 CHECK(priority >= 0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(experiment_id, version)
        )"""
    )
    op.execute(
        """CREATE TABLE fao.research_job (
          job_id UUID PRIMARY KEY,
          experiment_id UUID NOT NULL REFERENCES fao.experiment(experiment_id),
          status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','PARTIAL','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')),
          attempt INTEGER NOT NULL DEFAULT 1 CHECK(attempt > 0),
          consumed_tokens BIGINT NOT NULL DEFAULT 0 CHECK(consumed_tokens >= 0),
          consumed_tool_calls BIGINT NOT NULL DEFAULT 0 CHECK(consumed_tool_calls >= 0),
          result_ref UUID,
          failure_code TEXT,
          failure_detail TEXT,
          original_conversation_id UUID NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          UNIQUE(experiment_id)
        )"""
    )
    op.execute("CREATE INDEX ix_research_job_queue ON fao.research_job(status, updated_at)")
    op.execute("CREATE INDEX ix_research_job_conversation ON fao.research_job(original_conversation_id, updated_at)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON fao.experiment, fao.research_job TO fao_runtime, fao_agent_worker")
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fao.research_job")
    op.execute("DROP TABLE IF EXISTS fao.experiment")
