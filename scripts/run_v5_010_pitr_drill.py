#!/usr/bin/env python3
"""Run a real isolated PostgreSQL WAL/PITR recovery drill for V5-010."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

from futures_agent_os.operations import RecoveryDrillEvidence, RecoveryMode, standard_recovery_policy
from futures_agent_os.shared_kernel import RecordedAt


BEFORE_ID = "10000000-0000-0000-0000-000000000001"
TARGET_ID = "10000000-0000-0000-0000-000000000002"
AFTER_ID = "10000000-0000-0000-0000-000000000003"
AGGREGATE_ID = "20000000-0000-0000-0000-000000000001"
CORRELATION_ID = "30000000-0000-0000-0000-000000000001"


def _run(arguments: list[str], *, environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed.returncode != 0:
        command = Path(arguments[0]).name
        raise RuntimeError(f"{command} failed: {completed.stderr.strip()[-2000:]}")
    return completed.stdout.strip()


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _psql(socket_directory: Path, port: int, database: str, statement: str) -> str:
    return _run(
        [
            "psql",
            "-h",
            str(socket_directory),
            "-p",
            str(port),
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-Atq",
            "-c",
            statement,
        ]
    )


def _insert_command(socket_directory: Path, port: int, database: str, command_id: str, key: str) -> tuple[str, str]:
    output = _psql(
        socket_directory,
        port,
        database,
        f"""
        INSERT INTO fao.command_log(
            command_id, aggregate_type, aggregate_id, actor_ref, idempotency_key,
            correlation_id, payload, status, completed_at
        ) VALUES (
            '{command_id}', 'RECOVERY_DRILL', '{AGGREGATE_ID}', 'user:v5-010-drill',
            '{key}', '{CORRELATION_ID}', '{{}}'::jsonb, 'ACCEPTED', clock_timestamp()
        ) RETURNING xmin::text, recorded_at::text
        """,
    )
    xid, recorded_at = output.splitlines()[-1].split("|", maxsplit=1)
    return xid, recorded_at


def _configure_archiving(data_directory: Path, socket_directory: Path, archive_directory: Path, port: int) -> None:
    _run(
        [
            "pg_ctl",
            "-D",
            str(data_directory),
            "-o",
            f"-p {port} -k {socket_directory}",
            "-l",
            str(data_directory / "postgres.log"),
            "-w",
            "start",
        ]
    )
    escaped_archive = str(archive_directory).replace("'", "''")
    _psql(socket_directory, port, "postgres", "ALTER SYSTEM SET archive_mode = 'on'")
    _psql(
        socket_directory,
        port,
        "postgres",
        f"ALTER SYSTEM SET archive_command = 'test ! -f {escaped_archive}/%f && cp %p {escaped_archive}/%f'",
    )
    _run(
        [
            "pg_ctl",
            "-D",
            str(data_directory),
            "-l",
            str(data_directory / "postgres.log"),
            "-m",
            "fast",
            "-w",
            "restart",
        ]
    )


def _write_recovery_configuration(
    restore_directory: Path, socket_directory: Path, archive_directory: Path, port: int, target_xid: str
) -> None:
    restore_command = f"cp {archive_directory}/%f %p".replace("'", "''")
    socket_value = str(socket_directory).replace("'", "''")
    with (restore_directory / "postgresql.auto.conf").open("a", encoding="utf-8") as configuration:
        configuration.write(f"\nport = {port}\n")
        configuration.write(f"unix_socket_directories = '{socket_value}'\n")
        configuration.write(f"restore_command = '{restore_command}'\n")
        configuration.write(f"recovery_target_xid = '{target_xid}'\n")
        configuration.write("recovery_target_inclusive = 'on'\n")
        configuration.write("recovery_target_action = 'promote'\n")
    (restore_directory / "recovery.signal").touch()


def _version(binary: str) -> str:
    return _run([binary, "--version"]).splitlines()[0]


def run_drill() -> dict[str, Any]:
    required = ("initdb", "pg_ctl", "pg_basebackup", "psql", "createdb")
    missing = tuple(binary for binary in required if shutil.which(binary) is None)
    if missing:
        raise RuntimeError(f"missing PostgreSQL tools: {', '.join(missing)}")

    policy = standard_recovery_policy()
    started_at = RecordedAt.from_datetime(datetime.now(UTC))
    with tempfile.TemporaryDirectory(prefix="fao-v5-010-pitr-") as temporary:
        root = Path(temporary)
        primary = root / "primary"
        base_backup = root / "base-backup"
        restored = root / "restored"
        archive = root / "wal-archive"
        socket_directory = root / "socket"
        archive.mkdir()
        socket_directory.mkdir()
        port = _available_port()
        database = "fao_v5_010_drill"
        active_data_directory: Path | None = None
        try:
            _run(["initdb", "-D", str(primary), "--auth=trust", "--no-locale", "--encoding=UTF8"])
            _configure_archiving(primary, socket_directory, archive, port)
            active_data_directory = primary
            _run(["createdb", "-h", str(socket_directory), "-p", str(port), database])
            database_url = f"postgresql+psycopg:///{database}?host={socket_directory}&port={port}"
            migration_environment = {**os.environ, "FAO_DATABASE_URL": database_url}
            _run([sys.executable, "-m", "alembic", "upgrade", "head"], environment=migration_environment)

            _insert_command(socket_directory, port, database, BEFORE_ID, "before-base-backup")
            _run(
                [
                    "pg_basebackup",
                    "-h",
                    str(socket_directory),
                    "-p",
                    str(port),
                    "-D",
                    str(base_backup),
                    "-X",
                    "stream",
                    "-c",
                    "fast",
                ]
            )
            backup_manifest_sha256 = hashlib.sha256((base_backup / "backup_manifest").read_bytes()).hexdigest()

            target_xid, target_recorded_at = _insert_command(
                socket_directory, port, database, TARGET_ID, "at-recovery-target"
            )
            _insert_command(socket_directory, port, database, AFTER_ID, "after-recovery-target")
            archived_before = len(tuple(archive.iterdir()))
            _psql(socket_directory, port, database, "SELECT pg_switch_wal()")
            deadline = time.monotonic() + 15
            while len(tuple(archive.iterdir())) <= archived_before and time.monotonic() < deadline:
                time.sleep(0.05)
            if len(tuple(archive.iterdir())) <= archived_before:
                raise RuntimeError("WAL archive did not advance before drill timeout")

            _run(["pg_ctl", "-D", str(primary), "-m", "fast", "-w", "stop"])
            active_data_directory = None
            shutil.copytree(base_backup, restored)
            _write_recovery_configuration(restored, socket_directory, archive, port, target_xid)
            recovery_started = time.monotonic()
            _run(
                [
                    "pg_ctl",
                    "-D",
                    str(restored),
                    "-l",
                    str(restored / "postgres.log"),
                    "-w",
                    "start",
                ]
            )
            active_data_directory = restored
            restored_ids = tuple(
                _psql(
                    socket_directory,
                    port,
                    database,
                    "SELECT command_id::text FROM fao.command_log ORDER BY command_id",
                ).splitlines()
            )
            recovered_at = RecordedAt.from_datetime(datetime.now(UTC))
            rto_seconds = Decimal(str(time.monotonic() - recovery_started))
            schema_revision = _psql(socket_directory, port, database, "SELECT version_num FROM alembic_version")
            active_receipts = int(
                _psql(
                    socket_directory,
                    port,
                    database,
                    "SELECT count(*) FROM fao.autonomy_gate_receipt WHERE receipt_status IN ('ISSUED','CONSUMED')",
                )
            )
            active_reservations = int(
                _psql(
                    socket_directory,
                    port,
                    database,
                    "SELECT count(*) FROM fao.risk_budget_reservation WHERE reservation_status IN ('HELD','CONSUMED')",
                )
            )
            reconciliation_counts = {
                "ledger_facts": int(
                    _psql(
                        socket_directory,
                        port,
                        database,
                        "SELECT count(*) FROM fao.audit_event WHERE object_type IN ('LEDGER','ACCOUNT','SETTLEMENT')",
                    )
                ),
                "open_order_commands": int(
                    _psql(
                        socket_directory,
                        port,
                        database,
                        "SELECT count(*) FROM fao.command_log WHERE aggregate_type = 'ORDER'",
                    )
                ),
                "position_projection_facts": int(
                    _psql(socket_directory, port, database, "SELECT count(*) FROM fao.trade_episode_projection")
                ),
                "connector_commands": int(
                    _psql(
                        socket_directory,
                        port,
                        database,
                        "SELECT count(*) FROM fao.command_log WHERE aggregate_type = 'PAPER_CONNECTOR'",
                    )
                ),
            }
            expected = (BEFORE_ID, TARGET_ID)
            if restored_ids != expected or AFTER_ID in restored_ids:
                raise RuntimeError(f"PITR boundary mismatch: restored {restored_ids!r}")
            if active_receipts != 0 or active_reservations != 0:
                raise RuntimeError("empty-state recovery reconciliation found active authority")
            if any(reconciliation_counts.values()):
                raise RuntimeError("empty-state recovery reconciliation found unexpected trading facts")

            drill = RecoveryDrillEvidence(
                "drill:postgresql-pitr:v1",
                "postgres-primary-loss",
                started_at,
                recovered_at,
                Decimal(0),
                tuple(f"command:{command_id}" for command_id in restored_ids),
                (f"command:{AFTER_ID}",),
                schema_revision,
                backup_manifest_sha256,
                RecoveryMode.PROTECT_ONLY,
                policy.required_reconciliations,
                active_receipts,
            )
            if not drill.passes(policy):
                raise RuntimeError("PITR recovery evidence does not meet the recovery policy")
            return {
                "schema": "futures-agent-os.v5-010.postgresql-pitr-drill.v1",
                "status": "PASS",
                "drill_digest": drill.digest,
                "started_at": started_at.to_dict()["recorded_at"],
                "recovered_at": recovered_at.to_dict()["recorded_at"],
                "rto_seconds": str(rto_seconds),
                "rto_objective_seconds": policy.disaster_rto_seconds,
                "rpo_seconds": "0",
                "database_rpo_objective_seconds": policy.database_rpo_seconds,
                "accepted_command_rpo_objective_seconds": policy.accepted_command_rpo_seconds,
                "target_transaction_id": target_xid,
                "target_command_recorded_at": target_recorded_at,
                "restored_command_ids": restored_ids,
                "excluded_post_target_command_ids": (AFTER_ID,),
                "restored_schema_revision": schema_revision,
                "backup_manifest_sha256": backup_manifest_sha256,
                "recovered_mode": RecoveryMode.PROTECT_ONLY.value,
                "completed_reconciliations": policy.required_reconciliations,
                "reconciliation_scope": "EMPTY_TRADING_STATE",
                "reconciliation_counts": reconciliation_counts,
                "active_receipts_after_restore": active_receipts,
                "active_reservations_after_restore": active_reservations,
                "postgresql_version": _version("postgres"),
                "pg_basebackup_version": _version("pg_basebackup"),
                "isolation": "temporary PostgreSQL cluster; existing databases were not read or modified",
            }
        finally:
            if active_data_directory is not None:
                subprocess.run(
                    ["pg_ctl", "-D", str(active_data_directory), "-m", "immediate", "-w", "stop"],
                    check=False,
                    capture_output=True,
                    text=True,
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("refusing to overwrite immutable drill evidence")
    result = run_drill()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(arguments.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
