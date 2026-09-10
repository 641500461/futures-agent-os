from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import pytest

from futures_agent_os.operations import (
    AdmissionDecision,
    CapacityController,
    CapacityLimit,
    CapacityProfile,
    CircuitBreaker,
    CircuitBreakerPolicy,
    CircuitState,
    RecoveryDrillEvidence,
    RecoveryMode,
    SloMeasurementWindow,
    SloObjective,
    SloStatus,
    WorkloadClass,
    standard_recovery_policy,
    standard_slo_objectives,
)
from futures_agent_os.observability import MetricKind, MetricSample
from futures_agent_os.shared_kernel import EntityId, RecordedAt


AT = RecordedAt.parse("2026-09-11T00:00:00Z")


def _window(metric: str, values: tuple[Decimal, ...]) -> SloMeasurementWindow:
    return SloMeasurementWindow(
        f"window:{metric}",
        AT,
        AT,
        tuple(
            MetricSample(EntityId.deterministic("metric", f"{metric}:{index}"), metric, MetricKind.HISTOGRAM, value, AT)
            for index, value in enumerate(values)
        ),
    )


def _capacity_profile() -> CapacityProfile:
    return CapacityProfile(
        "sim-prod-capacity:v1",
        total_in_flight=8,
        reserved_critical_slots=3,
        limits=tuple(
            CapacityLimit(
                workload,
                max_in_flight=4 if workload is WorkloadClass.RESEARCH else 3,
                max_backlog=10,
                rate_per_second=Decimal("2") if workload is WorkloadClass.RESEARCH else Decimal("10"),
                burst=Decimal("5"),
            )
            for workload in WorkloadClass
        ),
    )


def test_critical_slo_catalog_has_measured_thresholds_alerts_and_runbooks() -> None:
    objectives = standard_slo_objectives()
    assert {objective.metric_name for objective in objectives} == {
        "gateway_ack_ms",
        "risk_reservation_ms",
        "final_receipt_gate_ms",
        "risk_constitution_ms",
        "protection_loop_ms",
        "critical_outbox_write_ms",
        "ledger_reconciliation_difference",
    }
    for objective in objectives:
        passing = objective.evaluate(_window(objective.metric_name, (objective.threshold,) * objective.minimum_samples))
        assert passing.status is SloStatus.PASS and not passing.alert_required
        breach = objective.evaluate(
            _window(objective.metric_name, (objective.threshold + Decimal(1),) * objective.minimum_samples)
        )
        assert breach.status is SloStatus.ALERT and breach.alert_required
        assert breach.objective.runbook_ref.startswith("runbook://v5-010/")
        insufficient = objective.evaluate(_window(objective.metric_name, ()))
        assert insufficient.status is SloStatus.INSUFFICIENT_DATA and insufficient.alert_required


def test_slo_uses_nearest_rank_percentile_not_average() -> None:
    objective = SloObjective("latency-p95", "latency_ms", 95, Decimal("100"), 20, "runbook://latency", ("user",))
    samples = (Decimal("1"),) * 19 + (Decimal("101"),)
    report = objective.evaluate(_window("latency_ms", samples))
    assert report.observed_percentile == Decimal("1") and report.status is SloStatus.PASS
    p100 = replace(objective, percentile=100).evaluate(_window("latency_ms", samples))
    assert p100.observed_percentile == Decimal("101") and p100.status is SloStatus.ALERT


def test_background_capacity_cannot_consume_reserved_critical_slots() -> None:
    controller = CapacityController(_capacity_profile())
    for workload in (WorkloadClass.RESEARCH,) * 4 + (WorkloadClass.AGENT,):
        assert controller.admit(workload, now_ms=0).decision is AdmissionDecision.ADMIT
    deferred = controller.admit(WorkloadClass.RESEARCH, now_ms=0)
    assert deferred.decision is AdmissionDecision.DEFER and deferred.reason_code == "CRITICAL_RESERVE"
    for workload in (WorkloadClass.PROTECTION, WorkloadClass.SETTLEMENT, WorkloadClass.OUTBOX):
        assert controller.admit(workload, now_ms=0).decision is AdmissionDecision.ADMIT


def test_backlog_is_shed_and_token_bucket_rate_limits_then_recovers() -> None:
    controller = CapacityController(_capacity_profile())
    controller.set_backlog(WorkloadClass.RESEARCH, 10)
    shed = controller.admit(WorkloadClass.RESEARCH, now_ms=0)
    assert shed.decision is AdmissionDecision.SHED and shed.reason_code == "BACKLOG_LIMIT"

    rate_limited = CapacityController(_capacity_profile())
    for _ in range(5):
        outcome = rate_limited.admit(WorkloadClass.RESEARCH, now_ms=0)
        assert outcome.decision is AdmissionDecision.ADMIT
        rate_limited.complete(WorkloadClass.RESEARCH)
    deferred = rate_limited.admit(WorkloadClass.RESEARCH, now_ms=0)
    assert deferred.reason_code == "RATE_LIMIT" and deferred.retry_after_ms == 500
    assert rate_limited.admit(WorkloadClass.RESEARCH, now_ms=500).decision is AdmissionDecision.ADMIT


def test_concurrent_admission_never_exceeds_workload_limit() -> None:
    controller = CapacityController(_capacity_profile())
    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = tuple(pool.map(lambda _: controller.admit(WorkloadClass.RESEARCH, now_ms=0), range(100)))
    admitted = tuple(outcome for outcome in outcomes if outcome.decision is AdmissionDecision.ADMIT)
    assert len(admitted) == 4 and controller.in_flight(WorkloadClass.RESEARCH) == 4


def test_dependency_circuit_breaker_opens_probes_and_closes() -> None:
    breaker = CircuitBreaker(CircuitBreakerPolicy("paper-connector", 2, 1000, 1))
    assert breaker.allow_call(0)
    breaker.record_failure(1)
    assert breaker.allow_call(2)
    breaker.record_failure(3)
    assert breaker.state is CircuitState.OPEN and not breaker.allow_call(999)
    assert breaker.allow_call(1003) and breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow_call(1003)
    breaker.record_success(1004)
    assert breaker.state is CircuitState.CLOSED and breaker.allow_call(1004)


def test_failed_half_open_probe_reopens_circuit() -> None:
    breaker = CircuitBreaker(CircuitBreakerPolicy("model-provider", 1, 10, 1))
    breaker.record_failure(0)
    assert breaker.allow_call(10)
    breaker.record_failure(11)
    assert breaker.state is CircuitState.OPEN and not breaker.allow_call(20)


def test_recovery_policy_is_fail_closed_and_drill_binds_rpo_rto_reconciliation() -> None:
    policy = standard_recovery_policy()
    assert policy.accepted_command_rpo_seconds == 0
    assert policy.recovery_mode is RecoveryMode.PROTECT_ONLY
    evidence = RecoveryDrillEvidence(
        "drill:pitr:v1",
        "postgres-primary-loss",
        RecordedAt.parse("2026-09-11T00:00:00Z"),
        RecordedAt.parse("2026-09-11T00:20:00Z"),
        Decimal("0"),
        ("command:before-backup", "command:at-target"),
        ("command:after-target",),
        "0010_v3_009",
        "a" * 64,
        RecoveryMode.PROTECT_ONLY,
        policy.required_reconciliations,
        0,
    )
    assert evidence.passes(policy) and evidence.digest == replace(evidence).digest
    assert not replace(evidence, recovered_at=RecordedAt.parse("2026-09-11T01:00:01Z")).passes(policy)
    assert not replace(evidence, completed_reconciliations=("DATABASE",)).passes(policy)
    with pytest.raises(ValueError, match="cannot reuse receipts"):
        replace(evidence, old_receipts_reused=1)


def test_recovery_policy_rejects_nonzero_accepted_command_rpo() -> None:
    with pytest.raises(ValueError, match="RPO=0"):
        replace(standard_recovery_policy(), accepted_command_rpo_seconds=1)
