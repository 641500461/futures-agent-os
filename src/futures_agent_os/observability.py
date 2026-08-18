"""Local structured metrics, logs, traces, and alert evaluation contracts.

V0 keeps collected records in memory.  It intentionally has no exporter,
network client, or remote telemetry dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from math import isfinite
import re
from types import MappingProxyType
from typing import TypeAlias

from futures_agent_os.security import redact_log_fields
from futures_agent_os.shared_kernel import EntityId, RecordedAt, TraceContext


TelemetryScalar: TypeAlias = str | int | float | bool | None
TelemetryValue: TypeAlias = TelemetryScalar | tuple["TelemetryValue", ...] | Mapping[str, "TelemetryValue"]
_RUNBOOK_REF = re.compile(r"^runbook://[A-Za-z0-9][A-Za-z0-9._/@:-]*$")
_IMPACT_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")


class LogSeverity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class MetricKind(StrEnum):
    COUNTER = "COUNTER"
    GAUGE = "GAUGE"
    HISTOGRAM = "HISTOGRAM"


class AlertStatus(StrEnum):
    FIRING = "FIRING"
    OK = "OK"


def _labels(labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(labels, Mapping):
        raise TypeError("metric labels must be a mapping when created from labels")
    if any(not isinstance(key, str) or not isinstance(value, str) or not key or not value for key, value in labels.items()):
        raise ValueError("metric labels must have non-empty names and values")
    return tuple(sorted(labels.items()))


def _mutable_telemetry_snapshot(value: object) -> object:
    """Detach supported telemetry values before redaction and freezing."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("telemetry fields must not contain non-finite floats")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("telemetry field names must be strings")
        return {key: _mutable_telemetry_snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_mutable_telemetry_snapshot(item) for item in value)
    raise TypeError("telemetry fields must be JSON-compatible values")


def _freeze_telemetry_value(value: object) -> TelemetryValue:
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_telemetry_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_telemetry_value(item) for item in value)
    raise TypeError("telemetry fields must be JSON-compatible values")


def _redacted_immutable_fields(fields: Mapping[str, TelemetryValue]) -> Mapping[str, TelemetryValue]:
    if not isinstance(fields, Mapping):
        raise TypeError("telemetry fields must be mappings")
    snapshot = _mutable_telemetry_snapshot(fields)
    assert isinstance(snapshot, dict)
    redacted = redact_log_fields(snapshot)
    frozen = _freeze_telemetry_value(redacted)
    assert isinstance(frozen, Mapping)
    return frozen


@dataclass(frozen=True, slots=True)
class StructuredLogRecord:
    event_code: str
    severity: LogSeverity
    trace: TraceContext
    recorded_at: RecordedAt
    fields: Mapping[str, TelemetryValue]

    def __post_init__(self) -> None:
        if not isinstance(self.event_code, str) or not self.event_code:
            raise ValueError("structured logs require an event code")
        if not isinstance(self.severity, LogSeverity) or not isinstance(self.trace, TraceContext) or not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("structured logs require severity, trace, and recorded-at contract values")
        # A log record is safe to persist only after recursive security redaction
        # and detachment from any caller-owned nested collection.
        object.__setattr__(self, "fields", _redacted_immutable_fields(self.fields))


@dataclass(frozen=True, slots=True)
class MetricSample:
    metric_id: EntityId
    name: str
    kind: MetricKind
    value: Decimal
    recorded_at: RecordedAt
    labels: tuple[tuple[str, str], ...] = ()
    trace: TraceContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric_id, EntityId) or not isinstance(self.name, str) or not self.name:
            raise ValueError("metric samples require a name")
        if not isinstance(self.kind, MetricKind) or not isinstance(self.recorded_at, RecordedAt):
            raise TypeError("metric samples require metric kind and recorded-at contract values")
        if self.trace is not None and not isinstance(self.trace, TraceContext):
            raise TypeError("metric sample trace must be a TraceContext")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("metric values must be finite Decimals")
        if not isinstance(self.labels, tuple):
            raise TypeError("metric labels must be an immutable tuple of pairs")
        if any(not isinstance(pair, tuple) or len(pair) != 2 for pair in self.labels):
            raise TypeError("metric labels must be immutable name/value pairs")
        if any(not isinstance(key, str) or not isinstance(value, str) or not key or not value for key, value in self.labels):
            raise ValueError("metric labels must be unique non-empty pairs")
        if len({key for key, _ in self.labels}) != len(self.labels):
            raise ValueError("metric labels must be unique non-empty pairs")

    @classmethod
    def create(
        cls, *, metric_id: EntityId, name: str, kind: MetricKind, value: Decimal, recorded_at: RecordedAt,
        labels: Mapping[str, str] | None = None, trace: TraceContext | None = None,
    ) -> MetricSample:
        return cls(metric_id, name, kind, value, recorded_at, _labels(labels or {}), trace)


@dataclass(frozen=True, slots=True)
class TraceSpan:
    span_id: EntityId
    name: str
    trace: TraceContext
    started_at: RecordedAt
    finished_at: RecordedAt
    attributes: Mapping[str, TelemetryValue]

    def __post_init__(self) -> None:
        if not isinstance(self.span_id, EntityId) or not isinstance(self.name, str) or not self.name or not isinstance(self.trace, TraceContext):
            raise ValueError("trace spans require a name and TraceContext")
        if not isinstance(self.started_at, RecordedAt) or not isinstance(self.finished_at, RecordedAt):
            raise TypeError("trace spans require recorded-at contract values")
        if self.finished_at.value < self.started_at.value:
            raise ValueError("trace spans require a name and non-negative duration")
        object.__setattr__(self, "attributes", _redacted_immutable_fields(self.attributes))


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    """A minimal policy for either an upper threshold or missing signal."""

    policy_id: str
    metric_name: str
    severity: LogSeverity
    runbook_ref: str
    impact_scope: tuple[str, ...]
    threshold: Decimal | None = None
    absence_after: timedelta | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id or not isinstance(self.metric_name, str) or not self.metric_name:
            raise ValueError("alert policies require an id and metric name")
        if not isinstance(self.severity, LogSeverity):
            raise TypeError("alert policies require a LogSeverity")
        _validate_alert_context(self.runbook_ref, self.impact_scope)
        threshold_policy = self.threshold is not None
        absence_policy = self.absence_after is not None
        if threshold_policy == absence_policy:
            raise ValueError("an alert policy must define exactly one of threshold or absence_after")
        if self.threshold is not None:
            if not isinstance(self.threshold, Decimal) or not self.threshold.is_finite():
                raise ValueError("alert thresholds must be finite Decimals")
        if self.absence_after is not None:
            if not isinstance(self.absence_after, timedelta):
                raise TypeError("absence alerts require a timedelta")
            if self.absence_after <= timedelta(0):
                raise ValueError("absence alerts require a positive duration")


@dataclass(frozen=True, slots=True)
class AlertRecord:
    alert_id: EntityId
    policy_id: str
    status: AlertStatus
    severity: LogSeverity
    observed_at: RecordedAt
    observed_value: Decimal | None
    runbook_ref: str
    impact_scope: tuple[str, ...]
    correlation_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.alert_id, EntityId) or not isinstance(self.policy_id, str) or not self.policy_id:
            raise ValueError("alert records require an id and policy id")
        if not isinstance(self.status, AlertStatus) or not isinstance(self.severity, LogSeverity):
            raise TypeError("alert records require status and severity enums")
        if not isinstance(self.observed_at, RecordedAt):
            raise TypeError("alert records require a RecordedAt observation time")
        if self.observed_value is not None and (not isinstance(self.observed_value, Decimal) or not self.observed_value.is_finite()):
            raise ValueError("alert observed values must be finite Decimals when present")
        if self.correlation_id is not None and not isinstance(self.correlation_id, EntityId):
            raise TypeError("alert correlations must be EntityIds")
        _validate_alert_context(self.runbook_ref, self.impact_scope)


def _validate_alert_context(runbook_ref: str, impact_scope: tuple[str, ...]) -> None:
    if not isinstance(runbook_ref, str) or not _RUNBOOK_REF.fullmatch(runbook_ref):
        raise ValueError("alert runbook_ref must be a canonical runbook:// reference")
    if not isinstance(impact_scope, tuple):
        raise TypeError("alert impact_scope must be an immutable tuple")
    if any(not isinstance(scope, str) or not _IMPACT_SCOPE.fullmatch(scope) for scope in impact_scope):
        raise ValueError("alert impact_scope must contain canonical user-impact selectors")
    if not impact_scope or len(set(impact_scope)) != len(impact_scope):
        raise ValueError("alert impact_scope must contain unique user-impact selectors")


class AlertEvaluator:
    """Deterministically evaluates the V0 alert policies over retained samples."""

    @staticmethod
    def evaluate(
        policy: AlertPolicy, samples: Iterable[MetricSample], now: RecordedAt, alert_id: EntityId,
    ) -> AlertRecord:
        if not isinstance(policy, AlertPolicy) or not isinstance(now, RecordedAt) or not isinstance(alert_id, EntityId):
            raise TypeError("alert evaluation requires policy, current time, and alert-id contract values")
        all_samples = tuple(samples)
        if any(not isinstance(sample, MetricSample) for sample in all_samples):
            raise TypeError("alert evaluation requires MetricSample values")
        matching = tuple(sample for sample in all_samples if sample.name == policy.metric_name and sample.recorded_at.value <= now.value)
        if policy.threshold is not None:
            observed = max((sample.value for sample in matching), default=None)
            status = AlertStatus.FIRING if observed is not None and observed >= policy.threshold else AlertStatus.OK
            correlated = next((sample.trace.correlation_id for sample in reversed(matching) if sample.trace is not None), None)
            return AlertRecord(
                alert_id, policy.policy_id, status, policy.severity, now, observed,
                policy.runbook_ref, policy.impact_scope, correlated,
            )

        assert policy.absence_after is not None
        cutoff = now.value - policy.absence_after
        recent = tuple(sample for sample in matching if sample.recorded_at.value >= cutoff)
        correlated = next((sample.trace.correlation_id for sample in reversed(recent) if sample.trace is not None), None)
        return AlertRecord(
            alert_id, policy.policy_id, AlertStatus.OK if recent else AlertStatus.FIRING,
            policy.severity, now, recent[-1].value if recent else None,
            policy.runbook_ref, policy.impact_scope, correlated,
        )


class InMemoryTelemetry:
    """A test double retaining structured, redacted local observability records."""

    def __init__(self) -> None:
        self._logs: list[StructuredLogRecord] = []
        self._metrics: list[MetricSample] = []
        self._spans: list[TraceSpan] = []
        self._alerts: list[AlertRecord] = []

    def emit_log(self, record: StructuredLogRecord) -> None:
        if not isinstance(record, StructuredLogRecord):
            raise TypeError("telemetry can emit only StructuredLogRecord values")
        self._logs.append(record)

    def emit_metric(self, sample: MetricSample) -> None:
        if not isinstance(sample, MetricSample):
            raise TypeError("telemetry can emit only MetricSample values")
        self._metrics.append(sample)

    def emit_span(self, span: TraceSpan) -> None:
        if not isinstance(span, TraceSpan):
            raise TypeError("telemetry can emit only TraceSpan values")
        self._spans.append(span)

    def record_alert(self, alert: AlertRecord) -> None:
        if not isinstance(alert, AlertRecord):
            raise TypeError("telemetry can record only AlertRecord values")
        self._alerts.append(alert)

    @property
    def logs(self) -> tuple[StructuredLogRecord, ...]:
        return tuple(self._logs)

    @property
    def metrics(self) -> tuple[MetricSample, ...]:
        return tuple(self._metrics)

    @property
    def spans(self) -> tuple[TraceSpan, ...]:
        return tuple(self._spans)

    @property
    def alerts(self) -> tuple[AlertRecord, ...]:
        return tuple(self._alerts)
