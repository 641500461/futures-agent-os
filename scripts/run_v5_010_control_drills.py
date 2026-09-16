#!/usr/bin/env python3
"""Run deterministic overload, rate-limit, circuit, and SLO alert drills."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import time

from futures_agent_os.observability import MetricKind, MetricSample
from futures_agent_os.operations import (
    AdmissionDecision,
    CapacityController,
    CircuitBreaker,
    CircuitBreakerPolicy,
    CircuitState,
    SloMeasurementWindow,
    SloStatus,
    WorkloadClass,
    standard_capacity_profile,
    standard_slo_objectives,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256


def _slo_alert_drill(now: RecordedAt) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    for objective in standard_slo_objectives():
        samples = tuple(
            MetricSample.create(
                metric_id=EntityId.deterministic("metric", f"{objective.objective_id}:{index}"),
                name=objective.metric_name,
                kind=MetricKind.HISTOGRAM,
                value=objective.threshold + Decimal(1),
                recorded_at=now,
                labels={"source": "v5-010-fault-injection"},
            )
            for index in range(objective.minimum_samples)
        )
        window = SloMeasurementWindow(f"drill:{objective.objective_id}", now, now, samples)
        report = objective.evaluate(window)
        if report.status is not SloStatus.ALERT or not report.alert_required:
            raise RuntimeError(f"SLO breach did not alert: {objective.objective_id}")
        reports.append(
            {
                "objective_id": objective.objective_id,
                "metric_name": objective.metric_name,
                "observed": str(report.observed_percentile),
                "threshold": str(objective.threshold),
                "status": report.status.value,
                "window_digest": report.window_digest,
                "runbook_ref": objective.runbook_ref,
                "impact_scope": objective.impact_scope,
            }
        )
    return {"status": "PASS", "alerts": tuple(reports)}


def _capacity_drill() -> dict[str, object]:
    profile = standard_capacity_profile()
    controller = CapacityController(profile)
    admitted: list[WorkloadClass] = []
    started = time.perf_counter_ns()
    for workload, count in (
        (WorkloadClass.TRADING, 32),
        (WorkloadClass.AGENT, 12),
        (WorkloadClass.RESEARCH, 4),
    ):
        for _ in range(count):
            outcome = controller.admit(workload, now_ms=0)
            if outcome.decision is not AdmissionDecision.ADMIT:
                raise RuntimeError(f"capacity setup failed for {workload}: {outcome.reason_code}")
            admitted.append(workload)
    background = controller.admit(WorkloadClass.RESEARCH, now_ms=0)
    if background.reason_code != "CRITICAL_RESERVE":
        raise RuntimeError("background work consumed critical reserve")
    critical_admitted = 0
    for _ in range(profile.reserved_critical_slots):
        outcome = controller.admit(WorkloadClass.PROTECTION, now_ms=0)
        if outcome.decision is not AdmissionDecision.ADMIT:
            raise RuntimeError("reserved protection capacity was unavailable")
        critical_admitted += 1
    elapsed_ms = Decimal(time.perf_counter_ns() - started) / Decimal(1_000_000)

    overloaded = CapacityController(profile)
    research_limit = next(limit for limit in profile.limits if limit.workload is WorkloadClass.RESEARCH)
    overloaded.set_backlog(WorkloadClass.RESEARCH, research_limit.max_backlog)
    shed = overloaded.admit(WorkloadClass.RESEARCH, now_ms=0)
    if shed.decision is not AdmissionDecision.SHED:
        raise RuntimeError("overloaded research backlog was not shed")

    rate_limited = CapacityController(profile)
    for _ in range(int(research_limit.burst)):
        if rate_limited.admit(WorkloadClass.RESEARCH, now_ms=0).decision is not AdmissionDecision.ADMIT:
            raise RuntimeError("research burst was rejected before its policy limit")
        rate_limited.complete(WorkloadClass.RESEARCH)
    rate = rate_limited.admit(WorkloadClass.RESEARCH, now_ms=0)
    if rate.reason_code != "RATE_LIMIT":
        raise RuntimeError("research rate limit did not engage")
    return {
        "status": "PASS",
        "profile_id": profile.profile_id,
        "background_ceiling": profile.total_in_flight - profile.reserved_critical_slots,
        "background_admitted": len(admitted),
        "background_overflow_decision": background.decision.value,
        "background_overflow_reason": background.reason_code,
        "critical_reserved_admitted": critical_admitted,
        "backlog_overflow_decision": shed.decision.value,
        "backlog_overflow_reason": shed.reason_code,
        "rate_overflow_decision": rate.decision.value,
        "rate_overflow_reason": rate.reason_code,
        "rate_retry_after_ms": rate.retry_after_ms,
        "control_decision_elapsed_ms": str(elapsed_ms),
    }


def _circuit_drill() -> dict[str, object]:
    breaker = CircuitBreaker(CircuitBreakerPolicy("paper-connector", 3, 1000, 1))
    for timestamp in range(3):
        if not breaker.allow_call(timestamp * 2):
            raise RuntimeError("circuit opened before its failure threshold")
        breaker.record_failure(timestamp * 2 + 1)
    if breaker.state is not CircuitState.OPEN or breaker.allow_call(999):
        raise RuntimeError("failed dependency circuit did not remain open")
    if not breaker.allow_call(1005) or breaker.state is not CircuitState.HALF_OPEN:
        raise RuntimeError("circuit did not enter a bounded half-open probe")
    breaker.record_success(1006)
    if breaker.state is not CircuitState.CLOSED:
        raise RuntimeError("successful dependency probe did not close circuit")
    return {
        "status": "PASS",
        "dependency_id": breaker.policy.dependency_id,
        "failure_threshold": breaker.policy.failure_threshold,
        "open_call_allowed": False,
        "half_open_probe_limit": breaker.policy.half_open_max_calls,
        "final_state": breaker.state.value,
        "fallback": "deterministic protection continues; new risk fails closed",
    }


def run_drills() -> dict[str, object]:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    result: dict[str, object] = {
        "schema": "futures-agent-os.v5-010.control-drills.v1",
        "recorded_at": now.to_dict()["recorded_at"],
        "slo_alert": _slo_alert_drill(now),
        "capacity_backpressure_rate_limit": _capacity_drill(),
        "dependency_circuit_breaker": _circuit_drill(),
        "status": "PASS",
    }
    result["digest"] = canonical_sha256(result)  # type: ignore[arg-type]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("refusing to overwrite immutable drill evidence")
    result = run_drills()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(arguments.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
