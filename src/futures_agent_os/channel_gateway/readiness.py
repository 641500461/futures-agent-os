"""Read-only startup diagnostics for the channel gateway.

The doctor deliberately does not construct a transport adapter.  A valid
configuration therefore proves only that the local process can be started;
it does not prove that the Feishu long connection is online.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text

from .config import GatewayConfig

EngineFactory = Callable[[str], Engine]


def _check(status: str, code: str, **details: object) -> dict[str, object]:
    return {"status": status, "code": code, **details}


def _code_heads() -> tuple[str, ...]:
    project_root = Path(__file__).resolve().parents[3]
    alembic_config = Config(str(project_root / "alembic.ini"))
    return tuple(sorted(ScriptDirectory.from_config(alembic_config).get_heads()))


def _state_counts(connection: Any, statement: str) -> dict[str, int]:
    rows = connection.execute(text(statement)).mappings().all()
    return {str(row["state"]): int(row["count"]) for row in rows}


def diagnose_gateway(
    config: GatewayConfig,
    *,
    engine_factory: EngineFactory | None = None,
    code_heads: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Return a redacted, JSON-ready snapshot of static gateway readiness."""

    checks: dict[str, object] = {
        "config": _check(
            "PASS",
            "CONFIG_VALID",
            database_configured=True,
            feishu_app_configured=True,
            identity_mapping_required=config.require_identity_mapping,
        ),
        "transport": _check("UNKNOWN", "TRANSPORT_NOT_PROBED"),
        "control_handler": _check("PASS", "LOCAL_SIMULATION_OWNER_WIRED"),
    }
    try:
        expected_heads = tuple(sorted(code_heads if code_heads is not None else _code_heads()))
    except Exception:
        checks["migration"] = _check("FAIL", "CODE_MIGRATION_HEADS_UNAVAILABLE")
        return _report(False, checks, "MIGRATION_ERROR")

    factory = engine_factory or create_engine
    engine: Engine | None = None
    try:
        engine = factory(config.database_url)
        with engine.connect() as connection:
            # PostgreSQL enforces the diagnostic's no-write contract even if
            # a future query is accidentally changed.
            connection.execute(text("SET TRANSACTION READ ONLY"))
            database_heads = tuple(
                sorted(
                    str(value)
                    for value in connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                )
            )
            checks["database"] = _check("PASS", "DATABASE_REACHABLE")
            if database_heads != expected_heads:
                checks["migration"] = _check(
                    "FAIL",
                    "MIGRATION_HEAD_MISMATCH",
                    code_heads=list(expected_heads),
                    database_heads=list(database_heads),
                )
                return _report(False, checks, "MIGRATION_ERROR")

            checks["migration"] = _check(
                "PASS",
                "MIGRATION_CURRENT",
                code_heads=list(expected_heads),
                database_heads=list(database_heads),
            )
            mapping_count = int(
                connection.execute(
                    text(
                        """SELECT count(*) FROM fao.gateway_identity_map
                        WHERE channel = :channel AND active IS TRUE
                          AND btrim(external_actor_id) <> ''
                          AND btrim(external_conversation_id) <> ''
                          AND btrim(actor_ref) <> '' AND btrim(target_ref) <> ''"""
                    ),
                    {"channel": "feishu"},
                ).scalar_one()
            )
            checks["feishu_identity_mappings"] = _check(
                "PASS" if mapping_count > 0 else "FAIL",
                "IDENTITY_MAPPINGS_PRESENT" if mapping_count > 0 else "NO_ACTIVE_FEISHU_IDENTITY_MAPPING",
                active_count=mapping_count,
            )
            inbound_counts = _state_counts(
                connection,
                """SELECT task_state AS state, count(*) AS count
                    FROM fao.agent_task WHERE assigned_role_id = 'gateway.inbound'
                    GROUP BY task_state ORDER BY task_state""",
            )
            inbound_failed = inbound_counts.get("FAILED", 0)
            checks["inbound_queue"] = _check(
                "DEGRADED" if inbound_failed else "PASS",
                "INBOUND_FAILED_TASKS" if inbound_failed else "INBOUND_QUEUE_READABLE",
                counts_by_state=inbound_counts,
            )
            outbox_counts = _state_counts(
                connection,
                """SELECT delivery_state AS state, count(*) AS count
                    FROM fao.outbox WHERE channel IS NOT NULL
                    GROUP BY delivery_state ORDER BY delivery_state""",
            )
            dead_outbox = outbox_counts.get("DEAD", 0)
            checks["outbox"] = _check(
                "DEGRADED" if dead_outbox else "PASS",
                "OUTBOX_DEAD_LETTERS" if dead_outbox else "OUTBOX_READABLE",
                counts_by_state=outbox_counts,
            )
            ready = mapping_count > 0 and not inbound_failed and not dead_outbox
            error = None if ready else ("IDENTITY_ERROR" if mapping_count == 0 else "QUEUE_DEGRADED")
            return _report(ready, checks, error)
    except Exception:
        checks["database"] = _check("FAIL", "DATABASE_UNAVAILABLE")
        return _report(False, checks, "DATABASE_ERROR")
    finally:
        if engine is not None:
            engine.dispose()


def diagnose_gateway_file(
    path: str | Path,
    *,
    engine_factory: EngineFactory | None = None,
    code_heads: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Load and diagnose a gateway config without exposing exception text."""

    try:
        config = GatewayConfig.from_file(path)
        config.validate()
    except FileNotFoundError:
        return _config_error("CONFIG_NOT_FOUND")
    except PermissionError:
        return _config_error("CONFIG_UNREADABLE")
    except Exception:
        return _config_error("CONFIG_INVALID")
    return diagnose_gateway(config, engine_factory=engine_factory, code_heads=code_heads)


def _config_error(code: str) -> dict[str, object]:
    return _report(False, {"config": _check("FAIL", code)}, "CONFIG_ERROR")


def _report(static_ready: bool, checks: dict[str, object], error_type: str | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "gateway-readiness.v1",
        "status": "STATIC_READY" if static_ready else "NOT_READY",
        "static_ready": static_ready,
        "checks": checks,
    }
    if error_type is not None:
        payload["error"] = {"type": error_type}
    return payload


__all__ = ["diagnose_gateway", "diagnose_gateway_file"]
