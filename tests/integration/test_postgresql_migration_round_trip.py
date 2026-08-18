"""Real PostgreSQL acceptance tests; skipped unless an isolated DB is supplied."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

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
        for schema, table in (("fao", "inbox"), ("fao", "outbox"), ("fao", "task_lease"), ("fao", "simulation_autonomy_mandate"), ("fao", "plan_approval"), ("agent_checkpoint", "checkpoint")):
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
