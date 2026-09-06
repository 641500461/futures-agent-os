"""Deterministic position protection and T4-SAFE reduction validation."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, cast

from futures_agent_os.decision import PositionLot, StopPolicy, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256


PROTECTION_CONTRACT_SCHEMA = SchemaVersion(1, 0)


def _now_recorded() -> RecordedAt:
    return RecordedAt.from_datetime(datetime.now(UTC))


def _source(value: str, label: str = "source_ref") -> None:
    if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be canonical text")


class ProtectionTriggerKind(StrEnum):
    INITIAL_STOP = "INITIAL_STOP"
    THESIS_INVALIDATION = "THESIS_INVALIDATION"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    PORTFOLIO_STOP = "PORTFOLIO_STOP"
    KILL_SWITCH = "KILL_SWITCH"


class ValidationOutcome(StrEnum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class ThesisInvalidationSpec:
    """Explicit, replayable predicate for a strategy thesis failure."""

    metric: str
    operator: str
    threshold: Decimal
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.metric, str) or not self.metric.strip() or any(c.isspace() for c in self.metric):
            raise ValueError("thesis metric must be canonical text")
        if self.operator not in {"LT", "LTE", "GT", "GTE", "EQ"}:
            raise ValueError("unsupported thesis predicate operator")
        if not isinstance(self.threshold, Decimal) or not self.threshold.is_finite():
            raise ValueError("thesis threshold must be finite")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("thesis spec version must be positive")

    @property
    def spec_hash(self) -> str:
        return canonical_sha256(
            {
                "metric": self.metric,
                "operator": self.operator,
                "threshold": str(self.threshold),
                "version": self.version,
            }
        )

    def invalidated(self, observations: dict[str, Decimal]) -> bool:
        value = observations.get(self.metric)
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("thesis observation is missing or invalid")
        return {
            "LT": value < self.threshold,
            "LTE": value <= self.threshold,
            "GT": value > self.threshold,
            "GTE": value >= self.threshold,
            "EQ": value == self.threshold,
        }[self.operator]


@dataclass(frozen=True, slots=True)
class RiskReductionRequest:
    request_id: EntityId
    position_id: EntityId
    expected_position_version: int
    target_quantity: Decimal
    target_stop_price: Decimal | None
    trigger: ProtectionTriggerKind
    idempotency_key: str
    requested_at: RecordedAt
    version: int = 1
    schema_version: SchemaVersion = PROTECTION_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.request_id, self.position_id)):
            raise TypeError("reduction request requires typed identifiers")
        if self.request_id.namespace != "reduction_request" or self.position_id.namespace != "position_lot":
            raise ValueError("reduction request references must use canonical id namespaces")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("reduction request version must be positive")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("reduction request schema_version must be a SchemaVersion")
        _source(self.source_ref)
        if (
            isinstance(self.expected_position_version, bool)
            or not isinstance(self.expected_position_version, int)
            or self.expected_position_version < 1
        ):
            raise ValueError("expected position version must be positive")
        if (
            not isinstance(self.target_quantity, Decimal)
            or not self.target_quantity.is_finite()
            or self.target_quantity < 0
        ):
            raise ValueError("target quantity must be non-negative")
        if self.target_stop_price is not None and (
            not isinstance(self.target_stop_price, Decimal)
            or not self.target_stop_price.is_finite()
            or self.target_stop_price <= 0
        ):
            raise ValueError("target stop price must be positive")
        if not isinstance(self.trigger, ProtectionTriggerKind) or not isinstance(self.requested_at, RecordedAt):
            raise TypeError("trigger and timestamp must be typed")
        if (
            not isinstance(self.idempotency_key, str)
            or not self.idempotency_key.strip()
            or any(c.isspace() for c in self.idempotency_key)
        ):
            raise ValueError("idempotency key must be canonical text")


@dataclass(frozen=True, slots=True)
class RiskReductionValidation:
    request_id: EntityId
    outcome: ValidationOutcome
    reason: str
    validated_at: RecordedAt
    validation_id: EntityId = field(default_factory=lambda: EntityId.new("reduction_validation"))
    version: int = 1
    schema_version: SchemaVersion = PROTECTION_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not isinstance(self.validation_id, EntityId) or self.validation_id.namespace != "reduction_validation":
            raise ValueError("validation requires a reduction_validation id")
        if not isinstance(self.request_id, EntityId) or self.request_id.namespace != "reduction_request":
            raise ValueError("validation must reference a reduction request")
        if not isinstance(self.outcome, ValidationOutcome):
            raise TypeError("validation outcome must be typed")
        if not isinstance(self.reason, str) or not self.reason.strip() or any(c.isspace() for c in self.reason):
            raise ValueError("validation reason must be canonical text")
        if not isinstance(self.validated_at, RecordedAt):
            raise TypeError("validation requires a timestamp")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("validation version must be positive")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("validation schema_version must be a SchemaVersion")
        _source(self.source_ref)


@dataclass(frozen=True, slots=True)
class ProtectiveRiskAction:
    action_id: EntityId
    request_id: EntityId
    position_id: EntityId
    target_quantity: Decimal
    target_stop_price: Decimal | None
    created_at: RecordedAt
    validation_id: EntityId | None = None
    version: int = 1
    schema_version: SchemaVersion = PROTECTION_CONTRACT_SCHEMA
    source_ref: str = "source:v2"

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, EntityId) or self.action_id.namespace != "protective_action":
            raise ValueError("protective action requires a protective_action id")
        if not isinstance(self.request_id, EntityId) or self.request_id.namespace != "reduction_request":
            raise ValueError("protective action must reference a reduction request")
        if not isinstance(self.position_id, EntityId) or self.position_id.namespace != "position_lot":
            raise ValueError("protective action must reference a position lot")
        if self.validation_id is not None and (
            not isinstance(self.validation_id, EntityId) or self.validation_id.namespace != "reduction_validation"
        ):
            raise ValueError("protective action validation must use a reduction_validation id")
        if (
            not isinstance(self.target_quantity, Decimal)
            or not self.target_quantity.is_finite()
            or self.target_quantity < 0
        ):
            raise ValueError("protective action quantity must be finite and non-negative")
        if self.target_stop_price is not None and (
            not isinstance(self.target_stop_price, Decimal)
            or not self.target_stop_price.is_finite()
            or self.target_stop_price <= 0
        ):
            raise ValueError("protective action stop must be positive")
        if not isinstance(self.created_at, RecordedAt):
            raise TypeError("protective action requires a timestamp")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("protective action version must be positive")
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("protective action schema_version must be a SchemaVersion")
        _source(self.source_ref)


class ProtectionValidator:
    """Validates only monotonic reductions; it never increases exposure."""

    def validate(
        self,
        request: RiskReductionRequest,
        lot: PositionLot,
        policy: StopPolicy,
        *,
        position_version: int,
        now: RecordedAt,
    ) -> RiskReductionValidation:
        if request.position_id != lot.lot_id or policy.position_id != lot.lot_id:
            return RiskReductionValidation(request.request_id, ValidationOutcome.REJECTED, "POSITION_MISMATCH", now)
        if request.expected_position_version != position_version:
            return RiskReductionValidation(request.request_id, ValidationOutcome.STALE, "POSITION_VERSION_STALE", now)
        if request.target_quantity > lot.quantity:
            return RiskReductionValidation(request.request_id, ValidationOutcome.REJECTED, "EXPOSURE_INCREASE", now)
        if request.target_stop_price is not None:
            tighter = (
                request.target_stop_price >= policy.stop_price
                if lot.direction is TradeDirection.LONG
                else request.target_stop_price <= policy.stop_price
            )
            if not tighter:
                return RiskReductionValidation(
                    request.request_id, ValidationOutcome.REJECTED, "PROTECTION_RELAXATION", now
                )
        return RiskReductionValidation(request.request_id, ValidationOutcome.VALIDATED, "MONOTONIC_REDUCTION", now)

    def action(
        self, request: RiskReductionRequest, validation: RiskReductionValidation, *, now: RecordedAt
    ) -> ProtectiveRiskAction:
        if validation.outcome is not ValidationOutcome.VALIDATED:
            raise ValueError("only validated requests create protective actions")
        return ProtectiveRiskAction(
            EntityId.deterministic(
                "protective_action",
                f"{request.idempotency_key}:{request.request_id}:{validation.validation_id}",
            ),
            request.request_id,
            request.position_id,
            request.target_quantity,
            request.target_stop_price,
            now,
            validation.validation_id,
        )


class ProtectionTriggerEvaluator:
    """Create reductions from deterministic stop, time, portfolio and kill facts."""

    def price_stop(
        self, lot: PositionLot, policy: StopPolicy, price: Decimal, now: RecordedAt
    ) -> RiskReductionRequest | None:
        hit = price <= policy.stop_price if lot.direction is TradeDirection.LONG else price >= policy.stop_price
        if not hit:
            return None
        return self._request(lot, ProtectionTriggerKind.INITIAL_STOP, now)

    def trigger(self, lot: PositionLot, kind: ProtectionTriggerKind, now: RecordedAt) -> RiskReductionRequest:
        return self._request(lot, kind, now)

    def thesis_invalidation(
        self,
        lot: PositionLot,
        now: RecordedAt,
        *,
        spec: ThesisInvalidationSpec | None = None,
        observations: dict[str, Decimal] | None = None,
    ) -> RiskReductionRequest | None:
        """Evaluate an explicit strategy predicate before requesting reduction."""
        if spec is not None:
            if observations is None or not spec.invalidated(observations):
                return None
        return self.trigger(lot, ProtectionTriggerKind.THESIS_INVALIDATION, now)

    def time_stop(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.TIME_STOP, now)

    def portfolio_stop(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.PORTFOLIO_STOP, now)

    def kill_switch(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.KILL_SWITCH, now)

    @staticmethod
    def is_unprotected_open(lot: PositionLot, policy: StopPolicy | None) -> bool:
        """Return the highest-severity fault for a non-zero lot without active protection."""
        return lot.quantity > 0 and (policy is None or not policy.active)

    def trailing_stop(
        self, lot: PositionLot, policy: StopPolicy, price: Decimal, now: RecordedAt
    ) -> RiskReductionRequest | None:
        hit = price <= policy.stop_price if lot.direction is TradeDirection.LONG else price >= policy.stop_price
        return self._request(lot, ProtectionTriggerKind.TRAILING_STOP, now) if hit else None

    @staticmethod
    def _request(lot: PositionLot, kind: ProtectionTriggerKind, now: RecordedAt) -> RiskReductionRequest:
        return RiskReductionRequest(
            EntityId.deterministic("reduction_request", f"{lot.lot_id}:{kind.value}:{now.to_dict()['recorded_at']}"),
            lot.lot_id,
            lot.version,
            Decimal("0"),
            None,
            kind,
            f"{lot.lot_id}:{kind.value}:{now.to_dict()['recorded_at']}",
            now,
        )


class ProtectiveActionRegistry:
    """Idempotent in-memory action sink; database adapter can preserve its key."""

    def __init__(self) -> None:
        self._actions: dict[str, ProtectiveRiskAction] = {}
        self._lock = RLock()

    def issue(
        self, request: RiskReductionRequest, validation: RiskReductionValidation, *, now: RecordedAt
    ) -> ProtectiveRiskAction:
        with self._lock:
            if request.idempotency_key in self._actions:
                existing = self._actions[request.idempotency_key]
                if (
                    existing.request_id != request.request_id
                    or existing.position_id != request.position_id
                    or existing.target_quantity != request.target_quantity
                    or existing.target_stop_price != request.target_stop_price
                ):
                    raise ValueError("protective action idempotency key conflict")
                return existing
            action = ProtectionValidator().action(request, validation, now=now)
            self._actions[request.idempotency_key] = action
            return action

    def snapshot(self) -> tuple[tuple[str, ProtectiveRiskAction], ...]:
        """Return a durable-ready key/action snapshot for crash recovery."""
        with self._lock:
            return tuple(self._actions.items())

    @classmethod
    def restore(cls, snapshot: tuple[tuple[str, ProtectiveRiskAction], ...]) -> ProtectiveActionRegistry:
        registry = cls()
        for key, action in snapshot:
            if not isinstance(key, str) or not isinstance(action, ProtectiveRiskAction):
                raise TypeError("invalid protective action snapshot")
            if key in registry._actions:
                raise ValueError("duplicate protective action snapshot key")
            registry._actions[key] = action
        return registry


def _action_to_payload(action: ProtectiveRiskAction) -> dict[str, object]:
    return {
        "action_id": str(action.action_id),
        "request_id": str(action.request_id),
        "position_id": str(action.position_id),
        "target_quantity": str(action.target_quantity),
        "target_stop_price": str(action.target_stop_price) if action.target_stop_price is not None else None,
        "created_at": action.created_at.to_dict()["recorded_at"],
        "validation_id": str(action.validation_id) if action.validation_id is not None else None,
        "version": action.version,
        "schema_version": str(action.schema_version),
        "source_ref": action.source_ref,
    }


def _action_from_payload(value: object) -> ProtectiveRiskAction:
    if not isinstance(value, dict):
        raise ValueError("protective action state must be an object")
    required = {
        "action_id",
        "request_id",
        "position_id",
        "target_quantity",
        "target_stop_price",
        "created_at",
        "validation_id",
        "version",
        "schema_version",
        "source_ref",
    }
    if set(value) != required:
        raise ValueError("protective action state fields are not exact")
    return ProtectiveRiskAction(
        EntityId.parse(str(value["action_id"])),
        EntityId.parse(str(value["request_id"])),
        EntityId.parse(str(value["position_id"])),
        Decimal(str(value["target_quantity"])),
        Decimal(str(value["target_stop_price"])) if value["target_stop_price"] is not None else None,
        RecordedAt.parse(str(value["created_at"])),
        EntityId.parse(str(value["validation_id"])) if value["validation_id"] is not None else None,
        int(str(value["version"])),
        SchemaVersion.parse(str(value["schema_version"])),
        str(value["source_ref"]),
    )


def _tupleize(value: object) -> object:
    if isinstance(value, list):
        return tuple(_tupleize(item) for item in value)
    if isinstance(value, dict):
        return {key: _tupleize(item) for key, item in value.items()}
    return value


class DurableProtectiveActionRegistry:
    """Atomic local persistence adapter for deterministic protection actions."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._registry = ProtectiveActionRegistry()
        self._lock = RLock()
        if self.path.exists():
            self._load()

    def issue(
        self, request: RiskReductionRequest, validation: RiskReductionValidation, *, now: RecordedAt
    ) -> ProtectiveRiskAction:
        with self._lock:
            action = self._registry.issue(request, validation, now=now)
            self._persist()
            return action

    def snapshot(self) -> tuple[tuple[str, ProtectiveRiskAction], ...]:
        with self._lock:
            return self._registry.snapshot()

    def _payload(self) -> list[dict[str, object]]:
        return [
            {"idempotency_key": key, "action": _action_to_payload(action)} for key, action in self._registry.snapshot()
        ]

    def _persist(self) -> None:
        payload = self._payload()
        envelope = {
            "schema": "v2.protection-action.1",
            "payload": payload,
            "digest": canonical_sha256(cast(Any, _tupleize(payload))),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self) -> None:
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or set(envelope) != {"schema", "payload", "digest"}:
                raise ValueError("protective action envelope is invalid")
            payload = envelope["payload"]
            digest = envelope["digest"]
            if envelope["schema"] != "v2.protection-action.1" or not isinstance(payload, list):
                raise ValueError("protective action schema is invalid")
            if not isinstance(digest, str) or digest != canonical_sha256(cast(Any, _tupleize(payload))):
                raise ValueError("protective action digest mismatch")
            entries: list[tuple[str, ProtectiveRiskAction]] = []
            for item in payload:
                if not isinstance(item, dict) or set(item) != {"idempotency_key", "action"}:
                    raise ValueError("protective action entry is invalid")
                key = item["idempotency_key"]
                if not isinstance(key, str) or not key.strip() or not isinstance(item["action"], dict):
                    raise ValueError("protective action entry is invalid")
                entries.append((key, _action_from_payload(item["action"])))
            self._registry = ProtectiveActionRegistry.restore(tuple(entries))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("cannot load durable protective action state") from error


__all__ = [
    "ProtectionTriggerKind",
    "ValidationOutcome",
    "RiskReductionRequest",
    "RiskReductionValidation",
    "ProtectiveRiskAction",
    "ProtectionValidator",
    "ProtectionTriggerEvaluator",
    "ProtectiveActionRegistry",
    "DurableProtectiveActionRegistry",
]
