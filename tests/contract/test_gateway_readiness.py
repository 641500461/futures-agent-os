"""Contract tests for the read-only gateway doctor."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from futures_agent_os.channel_gateway.config import GatewayConfig
from futures_agent_os.channel_gateway.readiness import diagnose_gateway, diagnose_gateway_file


class _Result:
    def __init__(
        self, *, scalar: Any = None, scalars: list[Any] | None = None, rows: list[dict[str, Any]] | None = None
    ) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one(self) -> Any:
        return self._scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any] | list[dict[str, Any]]:
        return self._scalars if self._scalars else self._rows

    def mappings(self) -> _Result:
        return self


class _Connection:
    def __init__(
        self, *, heads: list[str], mappings: int, inbound: list[dict[str, Any]], outbox: list[dict[str, Any]]
    ) -> None:
        self.heads = heads
        self.mapping_count = mappings
        self.inbound = inbound
        self.outbox = outbox

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: Any, _params: Any = None) -> _Result:
        sql = str(statement)
        if "SET TRANSACTION READ ONLY" in sql:
            return _Result()
        if "version_num" in sql:
            return _Result(scalars=self.heads)
        if "gateway_identity_map" in sql:
            return _Result(scalar=self.mapping_count)
        if "agent_task" in sql:
            return _Result(rows=self.inbound)
        if "fao.outbox" in sql:
            return _Result(rows=self.outbox)
        raise AssertionError(f"unexpected diagnostic query: {sql}")


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> _Connection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _config() -> GatewayConfig:
    return GatewayConfig("postgresql://user@host/db", "app-id", "credential-placeholder", require_identity_mapping=True)


def _factory(connection: _Connection, seen: list[str]) -> Callable[[str], _Engine]:
    def make(url: str) -> _Engine:
        seen.append(url)
        return _Engine(connection)

    return make


def test_doctor_success_is_redacted_and_marks_transport_unknown() -> None:
    seen: list[str] = []
    connection = _Connection(
        heads=["head"],
        mappings=2,
        inbound=[{"state": "QUEUED", "count": 3}],
        outbox=[{"state": "PENDING", "count": 4}, {"state": "DELIVERED", "count": 1}],
    )
    report = diagnose_gateway(_config(), engine_factory=_factory(connection, seen), code_heads=("head",))
    encoded = json.dumps(report, sort_keys=True)
    assert report["status"] == "STATIC_READY"
    assert report["checks"]["transport"] == {"status": "UNKNOWN", "code": "TRANSPORT_NOT_PROBED"}
    assert report["checks"]["control_handler"] == {"status": "PASS", "code": "LOCAL_SIMULATION_OWNER_WIRED"}
    assert report["checks"]["feishu_identity_mappings"]["active_count"] == 2
    assert report["checks"]["inbound_queue"]["counts_by_state"] == {"QUEUED": 3}
    assert report["checks"]["outbox"]["counts_by_state"] == {"DELIVERED": 1, "PENDING": 4}
    assert seen == [_config().database_url]
    assert "credential-placeholder" not in encoded


def test_doctor_old_migration_fails_before_gateway_queries() -> None:
    connection = _Connection(heads=["old"], mappings=1, inbound=[], outbox=[])
    report = diagnose_gateway(_config(), engine_factory=_factory(connection, []), code_heads=("head",))
    assert report["static_ready"] is False
    assert report["error"] == {"type": "MIGRATION_ERROR"}
    assert report["checks"]["migration"]["code"] == "MIGRATION_HEAD_MISMATCH"
    assert report["checks"]["migration"]["database_heads"] == ["old"]


def test_doctor_no_mapping_is_not_ready() -> None:
    connection = _Connection(heads=["head"], mappings=0, inbound=[], outbox=[])
    report = diagnose_gateway(_config(), engine_factory=_factory(connection, []), code_heads=("head",))
    assert report["static_ready"] is False
    assert report["error"] == {"type": "IDENTITY_ERROR"}
    assert report["checks"]["feishu_identity_mappings"]["code"] == "NO_ACTIVE_FEISHU_IDENTITY_MAPPING"


def test_doctor_dead_letters_are_degraded() -> None:
    connection = _Connection(
        heads=["head"],
        mappings=1,
        inbound=[{"state": "FAILED", "count": 1}],
        outbox=[{"state": "DEAD", "count": 2}],
    )
    report = diagnose_gateway(_config(), engine_factory=_factory(connection, []), code_heads=("head",))
    assert report["static_ready"] is False
    assert report["error"] == {"type": "QUEUE_DEGRADED"}
    assert report["checks"]["inbound_queue"]["code"] == "INBOUND_FAILED_TASKS"
    assert report["checks"]["outbox"]["code"] == "OUTBOX_DEAD_LETTERS"


def test_doctor_database_failure_has_no_exception_text() -> None:
    database_url = "postgresql://user@host/private"

    def unavailable(_url: str) -> _Engine:
        raise RuntimeError(database_url)

    report = diagnose_gateway(
        GatewayConfig(database_url, "app-id", "credential-placeholder"),
        engine_factory=unavailable,
        code_heads=("head",),
    )
    encoded = json.dumps(report, sort_keys=True)
    assert report["error"] == {"type": "DATABASE_ERROR"}
    assert report["checks"]["database"] == {"status": "FAIL", "code": "DATABASE_UNAVAILABLE"}
    assert database_url not in encoded and "credential-placeholder" not in encoded


def test_doctor_missing_config_is_stable_and_redacted(tmp_path: Path) -> None:
    report = diagnose_gateway_file(tmp_path / "missing.json", code_heads=("head",))
    assert report == {
        "schema_version": "gateway-readiness.v1",
        "status": "NOT_READY",
        "static_ready": False,
        "checks": {"config": {"status": "FAIL", "code": "CONFIG_NOT_FOUND"}},
        "error": {"type": "CONFIG_ERROR"},
    }
