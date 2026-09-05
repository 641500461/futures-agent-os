"""Deterministic position protection and T4-SAFE reduction validation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.decision import PositionLot, StopPolicy, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt


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
class RiskReductionRequest:
    request_id: EntityId
    position_id: EntityId
    expected_position_version: int
    target_quantity: Decimal
    target_stop_price: Decimal | None
    trigger: ProtectionTriggerKind
    idempotency_key: str
    requested_at: RecordedAt

    def __post_init__(self) -> None:
        if not all(isinstance(value, EntityId) for value in (self.request_id, self.position_id)):
            raise TypeError("reduction request requires typed identifiers")
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


@dataclass(frozen=True, slots=True)
class ProtectiveRiskAction:
    action_id: EntityId
    request_id: EntityId
    position_id: EntityId
    target_quantity: Decimal
    target_stop_price: Decimal | None
    created_at: RecordedAt


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
            EntityId.new("protective_action"),
            request.request_id,
            request.position_id,
            request.target_quantity,
            request.target_stop_price,
            now,
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

    def thesis_invalidation(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.THESIS_INVALIDATION, now)

    def time_stop(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.TIME_STOP, now)

    def portfolio_stop(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.PORTFOLIO_STOP, now)

    def kill_switch(self, lot: PositionLot, now: RecordedAt) -> RiskReductionRequest:
        return self.trigger(lot, ProtectionTriggerKind.KILL_SWITCH, now)

    def trailing_stop(
        self, lot: PositionLot, policy: StopPolicy, price: Decimal, now: RecordedAt
    ) -> RiskReductionRequest | None:
        return self.price_stop(lot, policy, price, now)

    @staticmethod
    def _request(lot: PositionLot, kind: ProtectionTriggerKind, now: RecordedAt) -> RiskReductionRequest:
        return RiskReductionRequest(
            EntityId.new("reduction_request"),
            lot.lot_id,
            1,
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

    def issue(
        self, request: RiskReductionRequest, validation: RiskReductionValidation, *, now: RecordedAt
    ) -> ProtectiveRiskAction:
        if request.idempotency_key in self._actions:
            return self._actions[request.idempotency_key]
        action = ProtectionValidator().action(request, validation, now=now)
        self._actions[request.idempotency_key] = action
        return action

    def snapshot(self) -> tuple[tuple[str, ProtectiveRiskAction], ...]:
        """Return a durable-ready key/action snapshot for crash recovery."""
        return tuple(self._actions.items())

    @classmethod
    def restore(cls, snapshot: tuple[tuple[str, ProtectiveRiskAction], ...]) -> ProtectiveActionRegistry:
        registry = cls()
        for key, action in snapshot:
            if not isinstance(key, str) or not isinstance(action, ProtectiveRiskAction):
                raise TypeError("invalid protective action snapshot")
            registry._actions[key] = action
        return registry
