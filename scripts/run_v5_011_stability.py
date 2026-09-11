#!/usr/bin/env python3
"""Operate the genuine wall-clock V5-011 simulation stability run."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, cast

from futures_agent_os.operations import (
    StabilityEvaluation,
    StabilityJournal,
    StabilityRunPlan,
    evaluate_stability_run,
    run_simulation_stability_probe,
)
from futures_agent_os.shared_kernel import RecordedAt, canonical_json_text, canonical_sha256


def _now() -> RecordedAt:
    return RecordedAt.from_datetime(datetime.now(UTC))


def _git_commit() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _require_clean_worktree() -> None:
    result = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("stability run requires a completely clean frozen worktree")


def _evaluation_payload(evaluation: StabilityEvaluation) -> dict[str, object]:
    return {
        "complete": evaluation.complete,
        "reason_codes": evaluation.reason_codes,
        "heartbeat_count": evaluation.heartbeat_count,
        "elapsed_seconds": str(evaluation.elapsed_seconds),
        "total_gap_seconds": str(evaluation.total_gap_seconds),
        "incident_count": evaluation.incident_count,
        "final_digest": evaluation.final_digest,
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_text(cast(Any, value)) + "\n", encoding="utf-8")


def _append_heartbeat(journal: StabilityJournal, now: RecordedAt) -> dict[str, object]:
    _require_clean_worktree()
    probe = run_simulation_stability_probe(now=now)
    heartbeat = journal.append(
        now=now,
        code_commit=_git_commit(),
        health_ok=probe.health_ok,
        simulated_trade_count=probe.simulated_trade_count,
        duplicate_trade_count=probe.duplicate_trade_count,
        unprotected_position_count=probe.unprotected_position_count,
        audit_chain_break_count=probe.audit_chain_break_count,
        ledger_difference=probe.ledger_difference,
    )
    return heartbeat.to_payload()


def start(directory: Path) -> dict[str, object]:
    _require_clean_worktree()
    now = _now()
    run_id = f"v5-011-{now.value.strftime('%Y%m%dT%H%M%S%fZ')}"
    plan = StabilityRunPlan(
        run_id,
        now,
        RecordedAt.from_datetime(now.value + timedelta(days=1)),
        _git_commit(),
        "sim-prod",
    )
    journal = StabilityJournal(directory)
    journal.start(plan)
    heartbeat = _append_heartbeat(journal, now)
    return {
        "status": "RUNNING",
        "directory": str(directory.resolve()),
        "plan": plan.to_payload(),
        "heartbeat": heartbeat,
    }


def heartbeat(directory: Path) -> dict[str, object]:
    journal = StabilityJournal(directory)
    item = _append_heartbeat(journal, _now())
    evaluation = evaluate_stability_run(journal.load_plan(), journal.load_heartbeats(), now=_now())
    return {
        "status": "COMPLETE" if evaluation.complete else "RUNNING",
        "heartbeat": item,
        "evaluation": _evaluation_payload(evaluation),
    }


def status(directory: Path) -> dict[str, object]:
    journal = StabilityJournal(directory)
    evaluation = evaluate_stability_run(journal.load_plan(), journal.load_heartbeats(), now=_now())
    return {"status": "COMPLETE" if evaluation.complete else "RUNNING", "evaluation": _evaluation_payload(evaluation)}


def finalize(directory: Path, output: Path) -> dict[str, object]:
    journal = StabilityJournal(directory)
    plan = journal.load_plan()
    heartbeats = journal.load_heartbeats()
    evaluation = evaluate_stability_run(plan, heartbeats, now=_now())
    if not evaluation.complete:
        raise ValueError(f"stability run is not complete: {','.join(evaluation.reason_codes)}")
    plan_bytes = journal.plan_path.read_bytes()
    heartbeat_bytes = journal.heartbeat_path.read_bytes()
    evidence: dict[str, object] = {
        "schema": "v5-011.stability-evidence.v1",
        "task": "V5-011",
        "research_and_simulation_only": True,
        "plan": plan.to_payload(),
        "plan_digest": plan.digest,
        "evaluation": _evaluation_payload(evaluation),
        "journal": {
            "plan_file_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "heartbeat_file_sha256": hashlib.sha256(heartbeat_bytes).hexdigest(),
            "heartbeat_chain_head": heartbeats[-1].digest,
        },
        "implementation_model": "NOT_EXPOSED",
        "implementation_reasoning_effort": "NOT_EXPOSED",
    }
    evidence["evidence_digest"] = canonical_sha256(cast(Any, evidence))
    _write_json(output, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "heartbeat", "status"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
    finish = commands.add_parser("finalize")
    finish.add_argument("--directory", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "start":
            payload = start(arguments.directory)
        elif arguments.command == "heartbeat":
            payload = heartbeat(arguments.directory)
        elif arguments.command == "status":
            payload = status(arguments.directory)
        else:
            payload = finalize(arguments.directory, arguments.output)
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, sort_keys=True))
        return 1
    print(canonical_json_text(cast(Any, payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
