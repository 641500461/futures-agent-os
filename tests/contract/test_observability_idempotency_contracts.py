"""V0-010 contracts for trace propagation, idempotency, audit, and alerts."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Lock, Thread

import pytest

from futures_agent_os.agent_orchestration import ToolAuthorizer, ToolCallRequest, ToolScope
from futures_agent_os.governance_registry import TOOL_REGISTRY, TOOL_REGISTRY_VERSION, ToolRef
from futures_agent_os.observability import (
    AlertEvaluator,
    AlertPolicy,
    AlertRecord,
    AlertStatus,
    InMemoryTelemetry,
    LogSeverity,
    MetricKind,
    MetricSample,
    StructuredLogRecord,
    TraceSpan,
)
from futures_agent_os.shared_kernel import (
    AppendOnlyAuditLog,
    AuditDraft,
    AuditVerificationStatus,
    BusinessEffect,
    CommandEffectRegistry,
    EntityId,
    IdempotencyOutcome,
    IdempotentCommand,
    RecordedAt,
    TraceContext,
    canonical_sha256,
    SchemaVersion,
)


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 18, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _trace() -> TraceContext:
    return TraceContext(EntityId.new("correlation"), EntityId.new("trace"))


def _effect(effect_type: str = "hypothesis_created") -> BusinessEffect:
    payload = {"effect_type": effect_type}
    return BusinessEffect(EntityId.new("effect"), effect_type, canonical_sha256(payload))


def test_request_tool_and_domain_facts_share_correlation_and_preserve_immediate_causation() -> None:
    request_id = EntityId.new("request")
    tool_call_id = EntityId.new("tool_call")
    domain_event_id = EntityId.new("domain_event")
    request_trace = _trace().caused_by(request_id)
    tool_trace = request_trace.caused_by(tool_call_id)
    domain_trace = tool_trace
    tool_request = ToolCallRequest(
        call_id=tool_call_id, agent_role_id="main", node_id="agent_worker_a",
        catalog_version=SchemaVersion(1, 0), registry_version=TOOL_REGISTRY_VERSION,
        tool_ref=ToolRef("request_authorization_preflight", SchemaVersion(1, 0)), scope=ToolScope(),
        called_at=_at(1), correlation_id=request_trace.correlation_id, trace=tool_trace,
    )
    tool_decision = ToolAuthorizer(TOOL_REGISTRY, ()).authorize(tool_request)

    telemetry = InMemoryTelemetry()
    telemetry.emit_span(TraceSpan(EntityId.new("span"), "gateway.request", request_trace, _at(), _at(1), {}))
    telemetry.emit_span(TraceSpan(EntityId.new("span"), "tool.request_authorization_preflight", tool_request.trace, _at(1), _at(2), {}))
    telemetry.emit_log(StructuredLogRecord("DOMAIN_EVENT_RECORDED", LogSeverity.INFO, domain_trace, _at(2), {"event_id": str(domain_event_id)}))

    assert {span.trace.correlation_id for span in telemetry.spans} == {request_trace.correlation_id}
    assert telemetry.logs[0].trace.correlation_id == request_trace.correlation_id
    assert tool_decision.trace == tool_request.trace
    assert telemetry.spans[1].trace.causation_id == tool_call_id
    assert telemetry.logs[0].trace.causation_id == tool_call_id


def test_same_idempotency_key_replays_one_effect_and_conflicting_payload_fails_closed() -> None:
    registry = CommandEffectRegistry()
    trace = _trace()
    command = IdempotentCommand(EntityId.new("command"), "request-17", {"action": "create", "value": 1}, trace)
    effects: list[BusinessEffect] = []

    def create_effect() -> BusinessEffect:
        effect = _effect()
        effects.append(effect)
        return effect

    first = registry.execute(command, create_effect)
    replay = registry.execute(replace(command, command_id=EntityId.new("command")), create_effect)
    conflict = registry.execute(
        IdempotentCommand(EntityId.new("command"), "request-17", {"action": "create", "value": 2}, trace), create_effect,
    )

    assert first.outcome is IdempotencyOutcome.EXECUTED
    assert replay.outcome is IdempotencyOutcome.REPLAYED and replay.effect == first.effect
    assert conflict.outcome is IdempotencyOutcome.CONFLICT and conflict.effect is None
    assert len(effects) == registry.effect_count == 1


def test_idempotent_command_snapshots_mutable_request_and_captures_a_stable_hash() -> None:
    request = {"action": "create", "nested": {"value": 1}}
    command = IdempotentCommand(EntityId.new("command"), "request-snapshot", request, _trace())
    request["nested"]["value"] = 2

    assert command.request == {"action": "create", "nested": {"value": 1}}
    assert command.request_sha256 == canonical_sha256({"action": "create", "nested": {"value": 1}})
    with pytest.raises(TypeError):
        command.request["nested"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        command.request["nested"]["value"] = 2  # type: ignore[index]


def test_concurrent_duplicate_commands_create_exactly_one_effect() -> None:
    registry = CommandEffectRegistry()
    command = IdempotentCommand(EntityId.new("command"), "concurrent-request", {"action": "create"}, _trace())
    start = Barrier(3)
    created: list[BusinessEffect] = []
    created_lock = Lock()
    decisions = []

    def create_effect() -> BusinessEffect:
        with created_lock:
            effect = _effect()
            created.append(effect)
            return effect

    def execute() -> None:
        start.wait()
        decisions.append(registry.execute(command, create_effect))

    workers = (Thread(target=execute), Thread(target=execute))
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join()

    assert {decision.outcome for decision in decisions} == {IdempotencyOutcome.EXECUTED, IdempotencyOutcome.REPLAYED}
    assert len(created) == registry.effect_count == 1


def test_audit_hash_chain_detects_changed_historical_record() -> None:
    audit = AppendOnlyAuditLog()
    trace = _trace()
    audit.append(AuditDraft(EntityId.new("audit_event"), "service:gateway", "REQUEST_ACCEPTED", "inbox", trace, "operational", _at(), {"source": "test"}))
    audit.append(AuditDraft(EntityId.new("audit_event"), "service:worker", "EFFECT_CREATED", "hypothesis", trace, "long_term", _at(1), {"idempotency_key": "k-1"}))

    assert AppendOnlyAuditLog.verify(audit.events).status is AuditVerificationStatus.VALID
    tampered = (audit.events[0], replace(audit.events[1], audit_sha256="0" * 64))
    verification = AppendOnlyAuditLog.verify(tampered)
    assert verification.status is AuditVerificationStatus.INVALID
    assert verification.invalid_sequence == 2


def test_audit_draft_snapshots_details_and_rejects_duplicate_event_ids() -> None:
    audit = AppendOnlyAuditLog()
    details = {"input": {"status": "accepted"}}
    draft = AuditDraft(
        EntityId.new("audit_event"), "service:gateway", "REQUEST_ACCEPTED", "inbox", _trace(),
        "operational", _at(), details,
    )
    details["input"]["status"] = "mutated"
    event = audit.append(draft)

    assert event.draft.details == {"input": {"status": "accepted"}}
    assert event.audit_sha256 == canonical_sha256(event.payload_for_hash())
    with pytest.raises(TypeError):
        event.draft.details["input"] = {}  # type: ignore[index]
    with pytest.raises(ValueError, match="unique"):
        audit.append(draft)


def test_concurrent_audit_appends_preserve_one_contiguous_hash_chain() -> None:
    audit = AppendOnlyAuditLog()
    start = Barrier(3)

    def append(action: str) -> None:
        start.wait()
        audit.append(AuditDraft(
            EntityId.new("audit_event"), "service:test", action, "test", _trace(), "operational", _at(), {},
        ))

    workers = (Thread(target=append, args=("FIRST",)), Thread(target=append, args=("SECOND",)))
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join()

    assert tuple(event.sequence for event in audit.events) == (1, 2)
    assert AppendOnlyAuditLog.verify(audit.events).status is AuditVerificationStatus.VALID


def test_structured_logs_are_redacted_and_alerts_cover_threshold_and_absence() -> None:
    trace = _trace()
    telemetry = InMemoryTelemetry()
    telemetry.emit_log(StructuredLogRecord("TOOL_CALL_FAILED", LogSeverity.ERROR, trace, _at(), {"api_key": "not-for-logs", "message": "Bearer secret-token"}))
    sample = MetricSample.create(
        metric_id=EntityId.new("metric"), name="outbox_backlog", kind=MetricKind.GAUGE,
        value=Decimal("12"), recorded_at=_at(), trace=trace,
    )
    telemetry.emit_metric(sample)

    threshold = AlertEvaluator.evaluate(
        AlertPolicy("outbox-backlog", "outbox_backlog", LogSeverity.ERROR, "runbook://outbox-backlog", ("sim-users",), threshold=Decimal("10")),
        telemetry.metrics, _at(1), EntityId.new("alert"),
    )
    absence = AlertEvaluator.evaluate(
        AlertPolicy("market-freshness", "market_freshness", LogSeverity.CRITICAL, "runbook://market-freshness", ("sim-users", "operators"), absence_after=timedelta(minutes=2)),
        telemetry.metrics, _at(3), EntityId.new("alert"),
    )

    assert telemetry.logs[0].fields == {"api_key": "[REDACTED]", "message": "Bearer [REDACTED]"}
    assert threshold.status is AlertStatus.FIRING and threshold.observed_value == Decimal("12")
    assert threshold.correlation_id == trace.correlation_id
    assert threshold.runbook_ref == "runbook://outbox-backlog" and threshold.impact_scope == ("sim-users",)
    assert absence.status is AlertStatus.FIRING and absence.observed_value is None
    assert absence.runbook_ref == "runbook://market-freshness" and absence.impact_scope == ("sim-users", "operators")


def test_telemetry_detaches_nested_fields_and_metric_labels_are_immutable() -> None:
    trace = _trace()
    fields = {"context": {"token": "do-not-store", "values": ["a", "b"]}}
    attributes = {"request": {"authorization": "Bearer secret-token"}}
    log = StructuredLogRecord("REQUEST_RECEIVED", LogSeverity.INFO, trace, _at(), fields)
    span = TraceSpan(EntityId.new("span"), "gateway.request", trace, _at(), _at(1), attributes)
    fields["context"]["values"].append("changed")
    attributes["request"]["authorization"] = "changed"

    assert log.fields == {"context": {"token": "[REDACTED]", "values": ("a", "b")}}
    assert span.attributes == {"request": {"authorization": "[REDACTED]"}}
    with pytest.raises(TypeError):
        log.fields["context"]["values"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        MetricSample(EntityId.new("metric"), "queue_depth", MetricKind.GAUGE, Decimal("1"), _at(), [("queue", "main")])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        MetricSample(EntityId.new("metric"), "queue_depth", MetricKind.GAUGE, Decimal("1"), _at(), (("queue", "main"), ("queue", "retry")))


def test_alert_and_telemetry_runtime_contracts_fail_closed_for_invalid_values() -> None:
    with pytest.raises(ValueError, match="runbook"):
        AlertPolicy("queue", "queue_depth", LogSeverity.ERROR, "https://runbook", ("sim-users",), threshold=Decimal("1"))
    with pytest.raises(TypeError, match="impact_scope"):
        AlertPolicy("queue", "queue_depth", LogSeverity.ERROR, "runbook://queue", ["sim-users"], threshold=Decimal("1"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="impact_scope"):
        AlertPolicy("queue", "queue_depth", LogSeverity.ERROR, "runbook://queue", (), threshold=Decimal("1"))
    with pytest.raises(ValueError, match="runbook"):
        AlertRecord(
            EntityId.new("alert"), "queue", AlertStatus.FIRING, LogSeverity.ERROR, _at(), Decimal("1"),
            "invalid", ("sim-users",),
        )
    with pytest.raises(TypeError, match="telemetry can emit"):
        InMemoryTelemetry().emit_log("not-a-log")  # type: ignore[arg-type]
