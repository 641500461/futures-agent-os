"""Local, deterministic correlation, idempotency, and audit primitives.

These contracts are deliberately in-memory.  They define the semantics that a
PostgreSQL application service will apply in one transaction; they do not send
telemetry or mutate a business aggregate themselves.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import TypeAlias
from types import MappingProxyType

from .ids import EntityId
from .time import RecordedAt


JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
_GENESIS_AUDIT_SHA256 = "0" * 64


def _immutable_json_snapshot(value: JsonValue) -> JsonValue:
    """Validate and detach a finite JSON value from its caller-owned objects."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, tuple):
        return tuple(_immutable_json_snapshot(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        # A tuple of pairs is immutable, but JSON objects must remain mappings for
        # canonical serialization and the public request/details contract.
        return MappingProxyType({key: _immutable_json_snapshot(item) for key, item in value.items()})
    raise ValueError("value must be finite JSON-compatible data")


def canonical_sha256(value: JsonValue) -> str:
    """Hash canonical JSON so replay comparisons do not depend on key order."""

    try:
        encoded = json.dumps(_canonical_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("value must be finite JSON-compatible data") from error
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_json_value(value: JsonValue) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, tuple):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _canonical_json_value(item) for key, item in value.items()}
    raise ValueError("value must be finite JSON-compatible data")


@dataclass(frozen=True, slots=True)
class TraceContext:
    """The correlation and causation identifiers carried by every journey fact."""

    correlation_id: EntityId
    trace_id: EntityId
    causation_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, EntityId) or not isinstance(self.trace_id, EntityId):
            raise TypeError("trace contexts require correlation and trace EntityIds")
        if self.causation_id is not None and not isinstance(self.causation_id, EntityId):
            raise TypeError("trace context causation ids must be EntityIds")

    def caused_by(self, fact_id: EntityId) -> TraceContext:
        """Carry the journey identifiers forward while naming the immediate cause."""

        return TraceContext(self.correlation_id, self.trace_id, fact_id)


@dataclass(frozen=True, slots=True)
class IdempotentCommand:
    """A side-effecting command represented only by its immutable request hash."""

    command_id: EntityId
    idempotency_key: str
    request: JsonValue
    trace: TraceContext
    request_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip() or len(self.idempotency_key) > 255:
            raise ValueError("idempotency key must be non-empty and at most 255 characters")
        if not isinstance(self.trace, TraceContext):
            raise TypeError("idempotent commands require a TraceContext")
        # Freeze and hash together at ingress.  A frozen dataclass alone would
        # still retain a caller-owned nested dict and turn a validated replay
        # into a different command later.
        request = _immutable_json_snapshot(self.request)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "request_sha256", canonical_sha256(request))


@dataclass(frozen=True, slots=True)
class BusinessEffect:
    """The one durable business effect created for a successful command key."""

    effect_id: EntityId
    effect_type: str
    effect_sha256: str

    def __post_init__(self) -> None:
        if not self.effect_type:
            raise ValueError("business effects require an effect type")
        if len(self.effect_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.effect_sha256):
            raise ValueError("business effect hash must be a lowercase SHA-256 digest")


class IdempotencyOutcome(StrEnum):
    EXECUTED = "EXECUTED"
    REPLAYED = "REPLAYED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class CommandEffectDecision:
    """An executed/replayed effect or a fail-closed conflict with no effect."""

    outcome: IdempotencyOutcome
    effect: BusinessEffect | None

    def __post_init__(self) -> None:
        if self.outcome is IdempotencyOutcome.CONFLICT and self.effect is not None:
            raise ValueError("idempotency conflicts must not return a business effect")
        if self.outcome is not IdempotencyOutcome.CONFLICT and self.effect is None:
            raise ValueError("executed and replayed commands require their original business effect")


@dataclass(frozen=True, slots=True)
class _EffectRegistryEntry:
    request_sha256: str
    effect: BusinessEffect


class CommandEffectRegistry:
    """Process-local reference model for the database idempotency-effect registry.

    The lock is intentionally held while the callback creates its effect.  This
    makes the contract explicit for tests: a duplicate cannot slip between
    checking a key and recording the first effect.  Production work must use a
    matching unique constraint and transaction, not this in-memory object.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _EffectRegistryEntry] = {}
        self._lock = RLock()

    def execute(self, command: IdempotentCommand, create_effect: Callable[[], BusinessEffect]) -> CommandEffectDecision:
        with self._lock:
            existing = self._entries.get(command.idempotency_key)
            request_sha256 = command.request_sha256
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    return CommandEffectDecision(IdempotencyOutcome.CONFLICT, None)
                return CommandEffectDecision(IdempotencyOutcome.REPLAYED, existing.effect)

            effect = create_effect()
            if not isinstance(effect, BusinessEffect):
                raise TypeError("idempotent command callbacks must return a BusinessEffect")
            self._entries[command.idempotency_key] = _EffectRegistryEntry(request_sha256, effect)
            return CommandEffectDecision(IdempotencyOutcome.EXECUTED, effect)

    @property
    def effect_count(self) -> int:
        return len(self._entries)


@dataclass(frozen=True, slots=True)
class AuditDraft:
    """An auditable action before the append-only chain assigns its hash."""

    audit_event_id: EntityId
    actor_ref: str
    action: str
    object_type: str
    trace: TraceContext
    retention_class: str
    recorded_at: RecordedAt
    details: JsonValue
    object_id: EntityId | None = None
    object_version: int | None = None
    before_sha256: str | None = None
    after_sha256: str | None = None

    def __post_init__(self) -> None:
        if not all((self.actor_ref, self.action, self.object_type, self.retention_class)):
            raise ValueError("audit drafts require actor, action, object type, and retention class")
        if self.object_version is not None and self.object_version < 0:
            raise ValueError("audit object versions cannot be negative")
        for value in (self.before_sha256, self.after_sha256):
            if value is not None and (len(value) != 64 or any(character not in "0123456789abcdef" for character in value)):
                raise ValueError("audit state hashes must be lowercase SHA-256 digests")
        if not isinstance(self.trace, TraceContext):
            raise TypeError("audit drafts require a TraceContext")
        object.__setattr__(self, "details", _immutable_json_snapshot(self.details))


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A fully chained audit record; existing records are never edited."""

    sequence: int
    draft: AuditDraft
    previous_audit_sha256: str
    audit_sha256: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("audit event sequences must be positive")
        for value in (self.previous_audit_sha256, self.audit_sha256):
            if value and (len(value) != 64 or any(character not in "0123456789abcdef" for character in value)):
                raise ValueError("audit chain hashes must be lowercase SHA-256 digests")

    def payload_for_hash(self) -> JsonValue:
        return {
            "sequence": self.sequence,
            "audit_event_id": str(self.draft.audit_event_id),
            "actor_ref": self.draft.actor_ref,
            "action": self.draft.action,
            "object_type": self.draft.object_type,
            "object_id": str(self.draft.object_id) if self.draft.object_id else None,
            "object_version": self.draft.object_version,
            "before_sha256": self.draft.before_sha256,
            "after_sha256": self.draft.after_sha256,
            "correlation_id": str(self.draft.trace.correlation_id),
            "trace_id": str(self.draft.trace.trace_id),
            "causation_id": str(self.draft.trace.causation_id) if self.draft.trace.causation_id else None,
            "retention_class": self.draft.retention_class,
            "recorded_at": self.draft.recorded_at.to_dict()["recorded_at"],
            "details_sha256": canonical_sha256(self.draft.details),
            "previous_audit_sha256": self.previous_audit_sha256,
        }


class AuditVerificationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class AuditVerification:
    status: AuditVerificationStatus
    invalid_sequence: int | None = None


class AppendOnlyAuditLog:
    """An in-memory append-only hash-chain reference implementation."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._event_ids: set[EntityId] = set()
        self._lock = RLock()

    def append(self, draft: AuditDraft) -> AuditEvent:
        if not isinstance(draft, AuditDraft):
            raise TypeError("audit logs can append only AuditDraft records")
        with self._lock:
            if draft.audit_event_id in self._event_ids:
                raise ValueError("audit event ids must be unique")
            previous = self._events[-1].audit_sha256 if self._events else _GENESIS_AUDIT_SHA256
            sequence = len(self._events) + 1
            provisional = AuditEvent(sequence, draft, previous, "")
            event = AuditEvent(sequence, draft, previous, canonical_sha256(provisional.payload_for_hash()))
            self._events.append(event)
            self._event_ids.add(draft.audit_event_id)
            return event

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @staticmethod
    def verify(events: Sequence[AuditEvent]) -> AuditVerification:
        expected_previous = _GENESIS_AUDIT_SHA256
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence != expected_sequence or event.previous_audit_sha256 != expected_previous:
                return AuditVerification(AuditVerificationStatus.INVALID, event.sequence)
            expected_hash = canonical_sha256(event.payload_for_hash())
            if event.audit_sha256 != expected_hash:
                return AuditVerification(AuditVerificationStatus.INVALID, event.sequence)
            expected_previous = event.audit_sha256
        return AuditVerification(AuditVerificationStatus.VALID)
