"""Plan or run the minimal real MVP-R-002 provider capability probe.

The default is a no-network plan.  ``--execute`` makes at most three fixed-order
empty-tool provider attempts, stopping after the first failure.  Receipts are not
qualification receipts: full qualification later requires four Critical and at
least one Fault case per profile, with real case evidence.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from futures_agent_os.adapters import OfficialCodexAppServerTransport
from futures_agent_os.research_experiment.mvp_r_002_runtime import (
    MvpR002PhaseZeroOrchestrator,
    mvp_r_002_capability_probe_plan,
)
from futures_agent_os.shared_kernel import canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FILENAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}\.json$")
_PROTOCOL = "mvp-r-002.phase0.capability-probe.v1"


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "UNAVAILABLE"


def build_plan() -> dict[str, JsonValue]:
    profiles = tuple(spec.to_dict() for spec in mvp_r_002_capability_probe_plan())
    return {
        "record_type": "MVP_R_002_CAPABILITY_PROBE_PLAN",
        "protocol": _PROTOCOL,
        "mode": "PLAN_ONLY",
        "authorization_boundary": "AUTHORIZED_NOT_FROZEN",
        "credential_handling": "existing_local_chatgpt_codex_session_is_not_read_or_printed",
        "profiles": profiles,
        "minimal_capability_probe": {
            "expected_provider": "openai",
            "expected_max_transport_attempts": len(profiles),
            "successful_run_exact_transport_attempt_count": len(profiles),
            "successful_run_exact_provider_turn_started_count": len(profiles),
            "successful_run_exact_provider_response_observed_count": len(profiles),
            "failure_policy": "FIXED_ORDER_STOP_ON_FIRST_FAILURE",
            "successful_run_one_attempt_per_profile": True,
            "uses_diagnostic_roster": False,
            "uses_holdout_roster": False,
            "uses_shadow": False,
            "creates_frozen_suite": False,
            "creates_active_binding": False,
        },
        "full_qualification_not_executed": {
            "required_critical_cases_per_profile": 4,
            "required_fault_cases_per_profile_minimum": 1,
            "minimum_required_qualification_receipt_count": len(profiles) * 5,
            "receipt_origin_is_not_assumed": "future_frozen_qualification_contract_decides_case_execution",
            "minimal_receipts_are_qualification_receipts": False,
        },
        "runtime": {
            "sdk_version": _package_version("openai-codex"),
            "cli_version": _package_version("openai-codex-cli-bin"),
            "repository_root_sha256": canonical_sha256({"repository_root": str(_REPOSITORY_ROOT)}),
        },
        "crash_recovery_policy": "reservation_lock_is_retained_for_manual_evidence_recovery_and_blocks_new_transport",
    }


def _safe_evidence_path(value: str, *, repository_root: Path = _REPOSITORY_ROOT) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.parent != Path(".") or not _FILENAME.fullmatch(candidate.name):
        raise ValueError("evidence filename must be a simple canonical .json filename")
    destination_root = (repository_root / "evidence" / "mvp-r-002").resolve()
    destination = (destination_root / candidate.name).resolve()
    if destination.parent != destination_root:
        raise ValueError("evidence path must stay in evidence/mvp-r-002")
    return destination


@dataclass(slots=True)
class EvidenceReservation:
    final_path: Path
    temp_path: Path
    descriptor: int
    lock_path: Path
    lock_descriptor: int

    def publish(self, payload: dict[str, JsonValue]) -> None:
        """Flush a same-directory temp file, then atomically no-clobber publish it."""

        encoded = canonical_json_text(payload).encode("utf-8") + b"\n"
        published = False
        try:
            with os.fdopen(self.descriptor, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.link(self.temp_path, self.final_path)
            published = True
            directory = os.open(self.final_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.temp_path.unlink()
            self._release_lock()
        except BaseException:
            self.temp_path.unlink(missing_ok=True)
            if published:
                self.final_path.unlink(missing_ok=True)
            self._release_lock()
            raise

    def abandon(self) -> None:
        try:
            os.close(self.descriptor)
        except OSError:
            pass
        self.temp_path.unlink(missing_ok=True)
        self._release_lock()

    def _release_lock(self) -> None:
        try:
            os.close(self.lock_descriptor)
        except OSError:
            pass
        self.lock_path.unlink(missing_ok=True)
        _fsync_directory(self.final_path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _best_effort_close(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _cleanup_untransferred_reservation(
    *,
    directory: Path,
    temp_path: Path | None,
    temp_descriptor: int | None,
    lock_path: Path,
    lock_descriptor: int | None,
) -> None:
    """Clean up only resources created after this process acquired its lock."""

    owns_temp = temp_descriptor is not None
    _best_effort_close(temp_descriptor)
    _best_effort_close(lock_descriptor)
    if owns_temp and temp_path is not None:
        temp_path.unlink(missing_ok=True)
    lock_path.unlink(missing_ok=True)
    try:
        _fsync_directory(directory)
    except OSError:
        pass


def reserve_new_evidence(path: Path) -> EvidenceReservation:
    """Reserve a safe new output before any transport attempt is possible."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("evidence path already exists; choose a new run filename")
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise FileExistsError(
            "evidence attempt is already reserved; recover its evidence before another transport"
        ) from error
    temp_path: Path | None = None
    temp_descriptor: int | None = None
    try:
        temp_path = path.with_name(f".{path.name}.{uuid4()}.tmp")
        temp_descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        _fsync_directory(path.parent)
        reservation = EvidenceReservation(path, temp_path, temp_descriptor, lock_path, lock_descriptor)
    except BaseException:
        _cleanup_untransferred_reservation(
            directory=path.parent,
            temp_path=temp_path,
            temp_descriptor=temp_descriptor,
            lock_path=lock_path,
            lock_descriptor=lock_descriptor,
        )
        raise
    # Ownership is now exclusively in ``reservation``.  Do not close or unlink
    # these resources in this factory after this point.
    return reservation


def execute_probe(run_id: str) -> dict[str, JsonValue]:
    plan = build_plan()
    orchestrator = cast(Any, MvpR002PhaseZeroOrchestrator).create_capability_probe(OfficialCodexAppServerTransport())
    receipts = tuple(receipt.to_dict() for receipt in orchestrator.run_plan_once())
    completed = all(receipt["status"] == "COMPLETED" for receipt in receipts)
    counts = {
        "transport": len(receipts),
        "turn_started": sum(receipt["provider_turn_started"] is True for receipt in receipts),
        "response_observed": sum(receipt["provider_response_observed"] is True for receipt in receipts),
    }
    expected = len(mvp_r_002_capability_probe_plan())
    completed = completed and len(receipts) == expected and all(value == expected for value in counts.values())
    failure_stages = tuple(receipt["failure_stage"] for receipt in receipts if receipt["failure_stage"] is not None)
    payload: dict[str, JsonValue] = {
        "record_type": "MVP_R_002_CAPABILITY_PROBE_EVIDENCE",
        "protocol": _PROTOCOL,
        "run_id": run_id,
        "executed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "COMPLETED" if completed else "FAILED",
        "failure_stages": failure_stages,
        "qualification_status": "NOT_QUALIFIED_MINIMAL_CAPABILITY_PROBE_ONLY",
        "plan_sha256": canonical_sha256(plan),
        "transport_attempt_count": counts["transport"],
        "provider_turn_started_count": counts["turn_started"],
        "provider_response_observed_count": counts["response_observed"],
        "expected_max_transport_attempts": expected,
        "stopped_after_workload": None if completed else receipts[-1]["profile"]["workload_id"],
        "receipt_sha256s": tuple(canonical_sha256(receipt) for receipt in receipts),
        "receipts": receipts,
        "no_raw_prompt_or_response_retained": True,
        "credential_handling": "existing_local_chatgpt_codex_session_is_not_read_or_printed",
        "full_qualification_still_requires": plan["full_qualification_not_executed"],
        "runtime": plan["runtime"],
    }
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="print the no-network plan (the default)")
    mode.add_argument("--dry-run", action="store_true", help="alias for --plan")
    mode.add_argument("--execute", action="store_true", help="make at most three fixed-order provider attempts")
    parser.add_argument("--evidence-file", help="new filename under evidence/mvp-r-002; only valid with --execute")
    parser.add_argument("--run-id", help="canonical run identifier; defaults to a generated UUID")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.execute:
        if args.evidence_file or args.run_id:
            raise ValueError("--evidence-file and --run-id require --execute")
        print(canonical_json_text(build_plan()))
        return 0
    run_id = args.run_id or f"capability-probe-{uuid4()}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,127}", run_id):
        raise ValueError("run id must be canonical lowercase text")
    filename = args.evidence_file or f"{run_id}.json"
    output_path = _safe_evidence_path(filename)
    reservation = reserve_new_evidence(output_path)
    try:
        evidence = execute_probe(run_id)
        reservation.publish(evidence)
    except BaseException:
        reservation.abandon()
        raise
    print(canonical_json_text(evidence))
    return 0 if evidence["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
