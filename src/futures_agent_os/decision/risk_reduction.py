"""Decision-owned reduction intent for existing exposure.

The intent is a proposal owned by Decision.  Execution consumes this value,
performs T4-SAFE validation, and is the only context that can issue a
ProtectiveRiskAction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from decimal import Decimal

from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


RISK_REDUCTION_SCHEMA = SchemaVersion(1, 0)


class ProtectionTriggerKind(StrEnum):
    INITIAL_STOP = "INITIAL_STOP"
    THESIS_INVALIDATION = "THESIS_INVALIDATION"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    PORTFOLIO_STOP = "PORTFOLIO_STOP"
    KILL_SWITCH = "KILL_SWITCH"


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
    schema_version: SchemaVersion = RISK_REDUCTION_SCHEMA
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
        if (
            not isinstance(self.source_ref, str)
            or not self.source_ref.strip()
            or any(c.isspace() for c in self.source_ref)
        ):
            raise ValueError("source_ref must be canonical text")
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


__all__ = ["ProtectionTriggerKind", "RiskReductionRequest", "RISK_REDUCTION_SCHEMA"]
