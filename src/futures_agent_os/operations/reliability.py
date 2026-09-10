"""Measured SLO, capacity, resilience, and recovery contracts for V5-010."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from enum import StrEnum
from threading import RLock

from futures_agent_os.observability import MetricSample
from futures_agent_os.shared_kernel import RecordedAt, canonical_sha256


def _canonical_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical non-empty text")


def _non_negative(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{label} must be a finite non-negative Decimal")


class WorkloadClass(StrEnum):
    PROTECTION = "PROTECTION"
    SETTLEMENT = "SETTLEMENT"
    GATEWAY = "GATEWAY"
    OUTBOX = "OUTBOX"
    TRADING = "TRADING"
    AGENT = "AGENT"
    RESEARCH = "RESEARCH"


_RESERVED_WORKLOADS = frozenset(
    {WorkloadClass.PROTECTION, WorkloadClass.SETTLEMENT, WorkloadClass.GATEWAY, WorkloadClass.OUTBOX}
)


class AdmissionDecision(StrEnum):
    ADMIT = "ADMIT"
    DEFER = "DEFER"
    SHED = "SHED"


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class SloStatus(StrEnum):
    PASS = "PASS"
    ALERT = "ALERT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RecoveryMode(StrEnum):
    PROTECT_ONLY = "PROTECT_ONLY"


@dataclass(frozen=True, slots=True)
class SloObjective:
    objective_id: str
    metric_name: str
    percentile: int
    threshold: Decimal
    minimum_samples: int
    runbook_ref: str
    impact_scope: tuple[str, ...]

    def __post_init__(self) -> None:
        _canonical_text(self.objective_id, "objective_id")
        _canonical_text(self.metric_name, "metric_name")
        _canonical_text(self.runbook_ref, "runbook_ref")
        if not self.runbook_ref.startswith("runbook://"):
            raise ValueError("SLO runbook_ref must use runbook://")
        if (
            isinstance(self.percentile, bool)
            or not isinstance(self.percentile, int)
            or not 50 <= self.percentile <= 100
        ):
            raise ValueError("SLO percentile must be an integer from 50 through 100")
        _non_negative(self.threshold, "threshold")
        if (
            isinstance(self.minimum_samples, bool)
            or not isinstance(self.minimum_samples, int)
            or self.minimum_samples < 1
        ):
            raise ValueError("SLO minimum_samples must be positive")
        if not self.impact_scope or len(set(self.impact_scope)) != len(self.impact_scope):
            raise ValueError("SLO requires unique impact scope")
        for scope in self.impact_scope:
            _canonical_text(scope, "impact_scope")

    def evaluate(self, window: SloMeasurementWindow) -> SloReport:
        if not isinstance(window, SloMeasurementWindow):
            raise TypeError("SLO evaluation requires a measured window")
        if any(sample.name != self.metric_name for sample in window.samples):
            raise ValueError("SLO window contains a metric outside the objective")
        values = tuple(sample.value for sample in window.samples)
        if len(values) < self.minimum_samples:
            return SloReport(self, window.digest, len(values), None, SloStatus.INSUFFICIENT_DATA, True)
        ordered = tuple(sorted(values))
        rank = int(
            (Decimal(self.percentile) * Decimal(len(ordered)) / Decimal(100)).to_integral_value(rounding=ROUND_CEILING)
        )
        observed = ordered[max(0, rank - 1)]
        status = SloStatus.PASS if observed <= self.threshold else SloStatus.ALERT
        return SloReport(self, window.digest, len(values), observed, status, status is not SloStatus.PASS)


@dataclass(frozen=True, slots=True)
class SloMeasurementWindow:
    window_id: str
    started_at: RecordedAt
    ended_at: RecordedAt
    samples: tuple[MetricSample, ...]

    def __post_init__(self) -> None:
        _canonical_text(self.window_id, "window_id")
        if not isinstance(self.started_at, RecordedAt) or not isinstance(self.ended_at, RecordedAt):
            raise TypeError("SLO window requires RecordedAt boundaries")
        if self.ended_at.value < self.started_at.value:
            raise ValueError("SLO window end cannot precede start")
        if not isinstance(self.samples, tuple) or any(not isinstance(sample, MetricSample) for sample in self.samples):
            raise TypeError("SLO window requires immutable MetricSample values")
        if any(
            sample.recorded_at.value < self.started_at.value or sample.recorded_at.value > self.ended_at.value
            for sample in self.samples
        ):
            raise ValueError("SLO sample lies outside its measurement window")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            {
                "window_id": self.window_id,
                "started_at": self.started_at.to_dict()["recorded_at"],
                "ended_at": self.ended_at.to_dict()["recorded_at"],
                "samples": tuple(
                    {
                        "metric_id": str(sample.metric_id),
                        "name": sample.name,
                        "kind": sample.kind.value,
                        "value": str(sample.value),
                        "recorded_at": sample.recorded_at.to_dict()["recorded_at"],
                        "labels": sample.labels,
                    }
                    for sample in self.samples
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class SloReport:
    objective: SloObjective
    window_digest: str
    sample_count: int
    observed_percentile: Decimal | None
    status: SloStatus
    alert_required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.objective, SloObjective) or not isinstance(self.status, SloStatus):
            raise TypeError("SLO report requires typed objective and status")
        if len(self.window_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.window_digest
        ):
            raise ValueError("SLO report requires measured window digest")
        if self.sample_count < 0:
            raise ValueError("SLO sample count cannot be negative")
        if self.observed_percentile is not None:
            _non_negative(self.observed_percentile, "observed_percentile")
        if self.alert_required is (self.status is SloStatus.PASS):
            raise ValueError("SLO alert flag must match status")


def standard_slo_objectives() -> tuple[SloObjective, ...]:
    """Return the measured critical SLO catalog; all thresholds are milliseconds."""

    specifications = (
        ("gateway-ack-p95", "gateway_ack_ms", 95, "2000", "gateway-ingress"),
        ("risk-reservation-p95", "risk_reservation_ms", 95, "200", "risk-budget"),
        ("final-gate-p95", "final_receipt_gate_ms", 95, "100", "new-risk"),
        ("risk-constitution-p95", "risk_constitution_ms", 95, "200", "risk-decision"),
        ("protection-loop-p99", "protection_loop_ms", 99, "1000", "open-positions"),
        ("outbox-write-p95", "critical_outbox_write_ms", 95, "2000", "operator-notifications"),
        ("ledger-difference-max", "ledger_reconciliation_difference", 100, "0", "simulation-ledger"),
    )
    return tuple(
        SloObjective(
            objective_id,
            metric,
            percentile,
            Decimal(threshold),
            20,
            f"runbook://v5-010/{objective_id}",
            (impact,),
        )
        for objective_id, metric, percentile, threshold, impact in specifications
    )


@dataclass(frozen=True, slots=True)
class CapacityLimit:
    workload: WorkloadClass
    max_in_flight: int
    max_backlog: int
    rate_per_second: Decimal
    burst: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.workload, WorkloadClass):
            raise TypeError("capacity limit requires typed workload")
        if self.max_in_flight < 1 or self.max_backlog < 1:
            raise ValueError("capacity concurrency and backlog must be positive")
        _non_negative(self.rate_per_second, "rate_per_second")
        _non_negative(self.burst, "burst")
        if self.rate_per_second == 0 or self.burst < 1:
            raise ValueError("capacity rate and burst must permit work")


@dataclass(frozen=True, slots=True)
class CapacityProfile:
    profile_id: str
    total_in_flight: int
    reserved_critical_slots: int
    limits: tuple[CapacityLimit, ...]

    def __post_init__(self) -> None:
        _canonical_text(self.profile_id, "profile_id")
        if self.total_in_flight < 1 or not 0 < self.reserved_critical_slots < self.total_in_flight:
            raise ValueError("capacity profile requires critical reserve below total capacity")
        if len(self.limits) != len(WorkloadClass) or {limit.workload for limit in self.limits} != set(WorkloadClass):
            raise ValueError("capacity profile requires exactly one limit per workload")


def standard_capacity_profile() -> CapacityProfile:
    """Conservative single-host profile validated by the V5-010 control drill."""

    settings = {
        WorkloadClass.PROTECTION: (16, 1_000, "1000", "100"),
        WorkloadClass.SETTLEMENT: (8, 100, "100", "20"),
        WorkloadClass.GATEWAY: (16, 1_000, "500", "100"),
        WorkloadClass.OUTBOX: (8, 1_000, "500", "100"),
        WorkloadClass.TRADING: (32, 500, "200", "50"),
        WorkloadClass.AGENT: (12, 100, "10", "12"),
        WorkloadClass.RESEARCH: (8, 50, "2", "8"),
    }
    return CapacityProfile(
        "single-host-simulation:v1",
        total_in_flight=64,
        reserved_critical_slots=16,
        limits=tuple(
            CapacityLimit(workload, concurrency, backlog, Decimal(rate), Decimal(burst))
            for workload, (concurrency, backlog, rate, burst) in settings.items()
        ),
    )


@dataclass(frozen=True, slots=True)
class AdmissionOutcome:
    decision: AdmissionDecision
    reason_code: str
    workload: WorkloadClass
    retry_after_ms: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, AdmissionDecision) or not isinstance(self.workload, WorkloadClass):
            raise TypeError("admission outcome requires typed decision and workload")
        _canonical_text(self.reason_code, "reason_code")
        if self.retry_after_ms is not None and self.retry_after_ms < 1:
            raise ValueError("retry_after_ms must be positive when present")
        if (self.decision is AdmissionDecision.DEFER) != (self.retry_after_ms is not None):
            raise ValueError("only deferred work carries retry_after_ms")


@dataclass(slots=True)
class _Bucket:
    tokens: Decimal
    last_seen_ms: int


class CapacityController:
    """Priority admission with critical reserve, bounded queues, and token buckets."""

    def __init__(self, profile: CapacityProfile) -> None:
        if not isinstance(profile, CapacityProfile):
            raise TypeError("capacity controller requires CapacityProfile")
        self.profile = profile
        self._limits = {limit.workload: limit for limit in profile.limits}
        self._in_flight = {workload: 0 for workload in WorkloadClass}
        self._backlog = {workload: 0 for workload in WorkloadClass}
        self._buckets = {workload: _Bucket(limit.burst, 0) for workload, limit in self._limits.items()}
        self._lock = RLock()

    def set_backlog(self, workload: WorkloadClass, count: int) -> None:
        if (
            not isinstance(workload, WorkloadClass)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise ValueError("backlog requires typed workload and non-negative count")
        with self._lock:
            self._backlog[workload] = count

    def admit(self, workload: WorkloadClass, *, now_ms: int, cost: Decimal = Decimal(1)) -> AdmissionOutcome:
        if (
            not isinstance(workload, WorkloadClass)
            or isinstance(now_ms, bool)
            or not isinstance(now_ms, int)
            or now_ms < 0
        ):
            raise ValueError("admission requires typed workload and monotonic non-negative time")
        _non_negative(cost, "cost")
        if cost == 0:
            raise ValueError("admission cost must be positive")
        with self._lock:
            limit = self._limits[workload]
            if self._backlog[workload] >= limit.max_backlog:
                return AdmissionOutcome(AdmissionDecision.SHED, "BACKLOG_LIMIT", workload, None)
            total = sum(self._in_flight.values())
            background_ceiling = self.profile.total_in_flight - self.profile.reserved_critical_slots
            if workload not in _RESERVED_WORKLOADS and total >= background_ceiling:
                return AdmissionOutcome(AdmissionDecision.DEFER, "CRITICAL_RESERVE", workload, 1000)
            if total >= self.profile.total_in_flight or self._in_flight[workload] >= limit.max_in_flight:
                return AdmissionOutcome(AdmissionDecision.DEFER, "CONCURRENCY_LIMIT", workload, 100)
            bucket = self._buckets[workload]
            if now_ms < bucket.last_seen_ms:
                raise ValueError("rate limiter time cannot move backwards")
            elapsed = Decimal(now_ms - bucket.last_seen_ms) / Decimal(1000)
            bucket.tokens = min(limit.burst, bucket.tokens + elapsed * limit.rate_per_second)
            bucket.last_seen_ms = now_ms
            if bucket.tokens < cost:
                missing = cost - bucket.tokens
                retry = int((missing * Decimal(1000) / limit.rate_per_second).to_integral_value(rounding=ROUND_CEILING))
                return AdmissionOutcome(AdmissionDecision.DEFER, "RATE_LIMIT", workload, max(1, retry))
            bucket.tokens -= cost
            self._in_flight[workload] += 1
            return AdmissionOutcome(AdmissionDecision.ADMIT, "CAPACITY_AVAILABLE", workload, None)

    def complete(self, workload: WorkloadClass) -> None:
        if not isinstance(workload, WorkloadClass):
            raise ValueError("cannot complete work that is not in flight")
        with self._lock:
            if self._in_flight[workload] < 1:
                raise ValueError("cannot complete work that is not in flight")
            self._in_flight[workload] -= 1

    def in_flight(self, workload: WorkloadClass) -> int:
        if not isinstance(workload, WorkloadClass):
            raise TypeError("in_flight requires typed workload")
        with self._lock:
            return self._in_flight[workload]


@dataclass(frozen=True, slots=True)
class CircuitBreakerPolicy:
    dependency_id: str
    failure_threshold: int
    recovery_timeout_ms: int
    half_open_max_calls: int

    def __post_init__(self) -> None:
        _canonical_text(self.dependency_id, "dependency_id")
        if self.failure_threshold < 1 or self.recovery_timeout_ms < 1 or self.half_open_max_calls < 1:
            raise ValueError("circuit-breaker limits must be positive")


class CircuitBreaker:
    """Deterministic closed/open/half-open dependency circuit breaker."""

    def __init__(self, policy: CircuitBreakerPolicy) -> None:
        if not isinstance(policy, CircuitBreakerPolicy):
            raise TypeError("circuit breaker requires CircuitBreakerPolicy")
        self.policy = policy
        self.state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at_ms: int | None = None
        self._half_open_calls = 0
        self._last_seen_ms = 0
        self._lock = RLock()

    def allow_call(self, now_ms: int) -> bool:
        with self._lock:
            self._check_time(now_ms)
            if self.state is CircuitState.OPEN:
                assert self._opened_at_ms is not None
                if now_ms - self._opened_at_ms < self.policy.recovery_timeout_ms:
                    return False
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
            if self.state is CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.policy.half_open_max_calls:
                    return False
                self._half_open_calls += 1
            return True

    def record_success(self, now_ms: int) -> None:
        with self._lock:
            self._check_time(now_ms)
            self.state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at_ms = None
            self._half_open_calls = 0

    def record_failure(self, now_ms: int) -> None:
        with self._lock:
            self._check_time(now_ms)
            if self.state is CircuitState.HALF_OPEN:
                self._open(now_ms)
                return
            self._failures += 1
            if self._failures >= self.policy.failure_threshold:
                self._open(now_ms)

    def _open(self, now_ms: int) -> None:
        self.state = CircuitState.OPEN
        self._opened_at_ms = now_ms
        self._half_open_calls = 0

    def _check_time(self, now_ms: int) -> None:
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < self._last_seen_ms:
            raise ValueError("circuit-breaker time must be monotonic and non-negative")
        self._last_seen_ms = now_ms


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    policy_id: str
    accepted_command_rpo_seconds: int
    database_rpo_seconds: int
    restart_rto_seconds: int
    disaster_rto_seconds: int
    recovery_mode: RecoveryMode
    required_reconciliations: tuple[str, ...]

    def __post_init__(self) -> None:
        _canonical_text(self.policy_id, "policy_id")
        if self.accepted_command_rpo_seconds != 0:
            raise ValueError("accepted simulation commands require RPO=0")
        if min(self.database_rpo_seconds, self.restart_rto_seconds, self.disaster_rto_seconds) < 1:
            raise ValueError("recovery objectives must be positive")
        if self.restart_rto_seconds > self.disaster_rto_seconds:
            raise ValueError("single-node restart RTO cannot exceed disaster RTO")
        if self.recovery_mode is not RecoveryMode.PROTECT_ONLY:
            raise ValueError("recovery must start in PROTECT_ONLY")
        if not self.required_reconciliations or len(set(self.required_reconciliations)) != len(
            self.required_reconciliations
        ):
            raise ValueError("recovery policy requires unique reconciliation gates")


def standard_recovery_policy() -> RecoveryPolicy:
    return RecoveryPolicy(
        "sim-prod-recovery:v1",
        accepted_command_rpo_seconds=0,
        database_rpo_seconds=300,
        restart_rto_seconds=60,
        disaster_rto_seconds=3600,
        recovery_mode=RecoveryMode.PROTECT_ONLY,
        required_reconciliations=("DATABASE", "LEDGER", "OPEN_ORDERS", "POSITIONS", "CONNECTOR"),
    )


@dataclass(frozen=True, slots=True)
class RecoveryDrillEvidence:
    drill_id: str
    scenario_id: str
    started_at: RecordedAt
    recovered_at: RecordedAt
    recovery_point_lag_seconds: Decimal
    restored_command_ids: tuple[str, ...]
    excluded_post_target_command_ids: tuple[str, ...]
    restored_schema_revision: str
    backup_manifest_sha256: str
    recovered_mode: RecoveryMode
    completed_reconciliations: tuple[str, ...]
    old_receipts_reused: int

    def __post_init__(self) -> None:
        _canonical_text(self.drill_id, "drill_id")
        _canonical_text(self.scenario_id, "scenario_id")
        if not isinstance(self.started_at, RecordedAt) or not isinstance(self.recovered_at, RecordedAt):
            raise TypeError("recovery drill requires RecordedAt timestamps")
        if self.recovered_at.value < self.started_at.value:
            raise ValueError("recovery cannot precede drill start")
        _non_negative(self.recovery_point_lag_seconds, "recovery_point_lag_seconds")
        if len(self.backup_manifest_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.backup_manifest_sha256
        ):
            raise ValueError("backup manifest requires lowercase SHA-256")
        _canonical_text(self.restored_schema_revision, "restored_schema_revision")
        if not self.restored_command_ids or not self.excluded_post_target_command_ids:
            raise ValueError("PITR drill must prove both restored and post-target-excluded commands")
        if len(set(self.restored_command_ids)) != len(self.restored_command_ids) or len(
            set(self.excluded_post_target_command_ids)
        ) != len(self.excluded_post_target_command_ids):
            raise ValueError("recovery command evidence must be unique")
        if set(self.restored_command_ids) & set(self.excluded_post_target_command_ids):
            raise ValueError("restored and excluded command sets must be disjoint")
        if self.recovered_mode is not RecoveryMode.PROTECT_ONLY or self.old_receipts_reused != 0:
            raise ValueError("recovery must be PROTECT_ONLY and cannot reuse receipts")
        if not self.completed_reconciliations or len(set(self.completed_reconciliations)) != len(
            self.completed_reconciliations
        ):
            raise ValueError("completed reconciliations must be unique")

    def passes(self, policy: RecoveryPolicy) -> bool:
        if not isinstance(policy, RecoveryPolicy):
            raise TypeError("drill evaluation requires RecoveryPolicy")
        duration = Decimal(str((self.recovered_at.value - self.started_at.value).total_seconds()))
        return (
            self.recovery_point_lag_seconds <= Decimal(policy.database_rpo_seconds)
            and duration <= Decimal(policy.disaster_rto_seconds)
            and set(self.completed_reconciliations) == set(policy.required_reconciliations)
            and self.recovered_mode is policy.recovery_mode
            and self.old_receipts_reused == 0
        )

    @property
    def digest(self) -> str:
        return canonical_sha256(
            {
                "drill_id": self.drill_id,
                "scenario_id": self.scenario_id,
                "started_at": self.started_at.to_dict()["recorded_at"],
                "recovered_at": self.recovered_at.to_dict()["recorded_at"],
                "rpo_seconds": str(self.recovery_point_lag_seconds),
                "restored": self.restored_command_ids,
                "excluded": self.excluded_post_target_command_ids,
                "schema": self.restored_schema_revision,
                "backup": self.backup_manifest_sha256,
                "mode": self.recovered_mode.value,
                "reconciliations": self.completed_reconciliations,
                "old_receipts_reused": self.old_receipts_reused,
            }
        )
