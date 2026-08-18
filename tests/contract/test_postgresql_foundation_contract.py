"""Static contracts for the V0-007 PostgreSQL-only storage baseline."""
from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = PROJECT_ROOT / "migrations" / "versions" / "0001_v0_007_postgresql_foundation.py"
OBSERVABILITY_MIGRATION = PROJECT_ROOT / "migrations" / "versions" / "0002_v0_010_observability_idempotency.py"
ALEMBIC_ENV = PROJECT_ROOT / "migrations" / "env.py"
RUNBOOK = PROJECT_ROOT / "scripts" / "postgres_v0_007.sh"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "postgresql.yml"


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_postgresql_baseline_is_a_real_alembic_revision_with_a_downgrade() -> None:
    module = ast.parse(_source(), filename=str(MIGRATION))
    assert {node.name for node in module.body if isinstance(node, ast.FunctionDef)} >= {"upgrade", "downgrade"}
    assert 'revision = "0001_v0_007"' in _source()
    assert "GRANT CREATE ON SCHEMA public TO PUBLIC" in _source()
    assert "alembic" in ALEMBIC_ENV.read_text(encoding="utf-8")


def test_alembic_environment_preserves_url_encoded_credentials() -> None:
    assert 'database_url.replace("%", "%%")' in ALEMBIC_ENV.read_text(encoding="utf-8")


def test_business_and_checkpoint_storage_are_physically_isolated() -> None:
    source = _source()
    for required in (
        "CREATE SCHEMA IF NOT EXISTS fao", "CREATE SCHEMA IF NOT EXISTS agent_checkpoint",
        "CREATE TABLE agent_checkpoint.checkpoint", "CREATE TABLE fao.command_log",
        "CREATE TABLE fao.domain_event", "CREATE TABLE fao.inbox", "CREATE TABLE fao.outbox",
        "CREATE TABLE fao.task_lease", "CREATE TABLE fao.schedule",
        "CREATE TABLE fao.supervision_notification", "CREATE TABLE fao.simulation_autonomy_mandate",
        "CREATE TABLE fao.plan_approval",
    ):
        assert required in source
    task_definition = source.split("CREATE TABLE fao.agent_task", 1)[1].split("CREATE TABLE fao.task_lease", 1)[0]
    assert "checkpoint" not in task_definition


def test_roles_are_no_login_least_privilege_and_agent_cannot_write_business_authority() -> None:
    source = _source()
    for role in ("fao_migrator", "fao_business_owner", "fao_checkpoint_owner", "fao_runtime", "fao_agent_worker", "fao_outbox_sender"):
        assert f"CREATE ROLE {role} NOLOGIN" in source
    assert "REVOKE ALL ON SCHEMA fao, agent_checkpoint FROM PUBLIC" in source
    assert "GRANT USAGE ON SCHEMA fao TO fao_runtime, fao_agent_worker, fao_outbox_sender, fao_checkpoint_owner" in source
    assert "GRANT SELECT, INSERT, UPDATE ON agent_checkpoint.checkpoint TO fao_agent_worker" in source
    assert "GRANT SELECT ON fao.simulation_autonomy_mandate, fao.plan_approval TO fao_runtime, fao_agent_worker" in source
    assert "INSERT ON fao.simulation_autonomy_mandate" not in source
    assert "INSERT ON fao.plan_approval" not in source


def test_migration_preserves_alembic_round_trip_reachability_without_default_privilege_grants() -> None:
    source = _source()
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in source
    assert "GRANT CREATE ON SCHEMA public TO PUBLIC" in source
    assert "ALTER DEFAULT PRIVILEGES" not in source


def test_schema_has_idempotency_and_append_only_primitives_without_legacy_imports() -> None:
    source = _source().lower()
    for required in (
        "unique (source, external_event_id)", "unique (aggregate_type, aggregate_id, idempotency_key)",
        "unique (topic, idempotency_key)", "unique (task_id, checkpoint_version)",
        "payload_sha256", "previous_audit_sha256",
    ):
        assert required in source
    assert "sqlite" not in source
    assert "futures_workflow" not in source
    assert "legacy" not in source


def test_v0_010_migration_makes_effect_keys_global_audit_append_only_and_telemetry_local() -> None:
    source = OBSERVABILITY_MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "0001_v0_007"' in source
    for required in (
        "CREATE TABLE fao.idempotency_effect", "idempotency_key TEXT PRIMARY KEY",
        "request_sha256", "effect_id UUID NOT NULL UNIQUE", "CREATE TRIGGER trg_audit_event_append_only",
        "CREATE TABLE fao.trace_span", "CREATE TABLE fao.metric_sample", "CREATE TABLE fao.observability_log",
        "CREATE TABLE fao.alert_policy", "CREATE TABLE fao.alert_record",
        "runbook_ref TEXT NOT NULL", "impact_scope JSONB NOT NULL",
    ):
        assert required in source
    assert "futures_workflow" not in source


def test_local_postgres_runbook_uses_pinned_postgres_and_round_trip() -> None:
    script = RUNBOOK.read_text(encoding="utf-8")
    assert "postgres:17.5-alpine" in script
    assert "uv run alembic upgrade head" in script
    assert "uv run alembic downgrade base" in script
    assert "uv run pytest tests/integration -q" in script
    assert "sqlite" not in script.lower()


def test_ci_uses_the_same_pinned_postgresql_service_and_real_integration_url() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "postgres:17.5-alpine" in workflow
    assert "FAO_DATABASE_URL" in workflow
    assert "uv sync --locked" in workflow
    assert "uv run pytest" in workflow
