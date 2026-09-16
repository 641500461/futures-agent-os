"""L5 paper connector normalization and bidirectional reconciliation.

External venues are evidence sources, never accounting truth. Unknown,
degraded, unsupported, or internally inconsistent snapshots fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256

from .contracts import Fill


def _canonical_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical non-empty text")


def _quantity(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{label} must be a non-negative finite Decimal")


class ExternalStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class ConnectorHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ReconciliationOutcome(StrEnum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    DEGRADED = "DEGRADED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    name: str
    version: str
    supports_partial_fills: bool
    supports_cancel: bool
    limitations: tuple[str, ...]
    fidelity: str = "L5_PAPER"
    documentation_url: str = "local://paper-adapter"
    verified_at: str = "UNVERIFIED"

    def __post_init__(self) -> None:
        for value, label in (
            (self.name, "name"),
            (self.version, "version"),
            (self.fidelity, "fidelity"),
            (self.documentation_url, "documentation_url"),
            (self.verified_at, "verified_at"),
        ):
            _canonical_text(value, label)
        if self.fidelity != "L5_PAPER":
            raise ValueError("paper connector cannot claim L3/L4 fidelity")
        if not isinstance(self.limitations, tuple) or not self.limitations:
            raise ValueError("adapter capabilities require explicit limitations")
        if any(not isinstance(item, str) or not item.strip() for item in self.limitations):
            raise ValueError("adapter limitations must be non-empty text")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "name": self.name,
                    "version": self.version,
                    "supports_partial_fills": self.supports_partial_fills,
                    "supports_cancel": self.supports_cancel,
                    "limitations": self.limitations,
                    "fidelity": self.fidelity,
                    "documentation_url": self.documentation_url,
                    "verified_at": self.verified_at,
                },
            )
        )

    @classmethod
    def tqsim(cls, runtime_version: str) -> AdapterCapabilities:
        """Build a manifest without guessing the installed TqSdk version."""

        _canonical_text(runtime_version, "runtime_version")
        return cls(
            "TqSim",
            runtime_version,
            False,
            True,
            (
                "limit-orders-fill-at-order-price-after-crossing-opponent",
                "limit-orders-do-not-fill-without-opponent",
                "market-orders-auto-cancel-without-opponent",
                "all-or-none-simulated-fills-no-partial-fills",
                "not-L3-or-L4-high-fidelity-evidence",
            ),
            documentation_url="https://doc.shinnytech.com/tqsdk/latest/reference/tqsdk.sim.html",
            verified_at="2026-09-10",
        )


@dataclass(frozen=True, slots=True)
class ExternalFill:
    external_fill_id: str
    order_id: str
    instrument: str
    direction: TradeDirection
    quantity: Decimal
    price: Decimal
    fee: Decimal
    filled_at: RecordedAt

    def __post_init__(self) -> None:
        for value, label in (
            (self.external_fill_id, "external_fill_id"),
            (self.order_id, "order_id"),
            (self.instrument, "instrument"),
        ):
            _canonical_text(value, label)
        if not isinstance(self.direction, TradeDirection):
            raise TypeError("direction must be TradeDirection")
        _quantity(self.quantity, "fill quantity")
        if self.quantity == 0:
            raise ValueError("fill quantity must be positive")
        _quantity(self.price, "fill price")
        if self.price == 0:
            raise ValueError("fill price must be positive")
        _quantity(self.fee, "fill fee")
        if not isinstance(self.filled_at, RecordedAt):
            raise TypeError("filled_at must be RecordedAt")


@dataclass(frozen=True, slots=True)
class ExternalExecution:
    order_id: str
    status: ExternalStatus
    filled_quantity: Decimal
    quantity: Decimal | None = None
    fills: tuple[ExternalFill, ...] = ()
    observed_at: RecordedAt | None = None

    def __post_init__(self) -> None:
        _canonical_text(self.order_id, "external order_id")
        if not isinstance(self.status, ExternalStatus):
            raise TypeError("external status must be ExternalStatus")
        if isinstance(self.filled_quantity, int):
            object.__setattr__(self, "filled_quantity", Decimal(self.filled_quantity))
        if isinstance(self.quantity, int):
            object.__setattr__(self, "quantity", Decimal(self.quantity))
        _quantity(self.filled_quantity, "external filled_quantity")
        if self.quantity is not None:
            _quantity(self.quantity, "external quantity")
            if self.filled_quantity > self.quantity:
                raise ValueError("external fill cannot exceed order quantity")
        if not isinstance(self.fills, tuple) or any(not isinstance(fill, ExternalFill) for fill in self.fills):
            raise TypeError("external fills must be an immutable tuple")
        if self.observed_at is not None and not isinstance(self.observed_at, RecordedAt):
            raise TypeError("observed_at must be RecordedAt")


@dataclass(frozen=True, slots=True)
class PaperOrderIntent:
    """Connector-neutral outbound mapping; it is not a venue success fact."""

    local_order_id: EntityId
    external_client_order_id: str
    instrument: str
    direction: TradeDirection
    quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    idempotency_key: str
    manifest_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.local_order_id, EntityId) or self.local_order_id.namespace != "order":
            raise TypeError("local_order_id must be a typed order identifier")
        for value, label in (
            (self.external_client_order_id, "external_client_order_id"),
            (self.instrument, "instrument"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _canonical_text(value, label)
        if not isinstance(self.direction, TradeDirection):
            raise TypeError("direction must be TradeDirection")
        _quantity(self.quantity, "order quantity")
        if self.quantity == 0:
            raise ValueError("order quantity must be positive")
        for price in (self.limit_price, self.stop_price):
            if price is not None:
                _quantity(price, "order price")
                if price == 0:
                    raise ValueError("order price must be positive")
        if len(self.manifest_digest) != 64:
            raise ValueError("manifest_digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class Reconciliation:
    order_id: str
    status: ExternalStatus
    matched: bool
    reason: str
    outcome: ReconciliationOutcome = ReconciliationOutcome.MATCHED
    discrepancies: tuple[str, ...] = ()
    imported_fills: tuple[Fill, ...] = ()
    connector_health: ConnectorHealth = ConnectorHealth.HEALTHY
    can_assume_success: bool = True
    manifest_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExternalStatus) or not isinstance(self.outcome, ReconciliationOutcome):
            raise TypeError("reconciliation status and outcome must be typed")
        if self.matched != (self.outcome is ReconciliationOutcome.MATCHED):
            raise ValueError("matched flag must agree with reconciliation outcome")
        if self.can_assume_success != self.matched:
            raise ValueError("only a matched reconciliation may assume success")


_STATUS_MAP = {
    ExternalStatus.ACCEPTED: {OrderStatus.ACCEPTED, OrderStatus.WORKING},
    ExternalStatus.WORKING: {OrderStatus.WORKING},
    ExternalStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED},
    ExternalStatus.FILLED: {OrderStatus.FILLED},
    ExternalStatus.CANCELED: {OrderStatus.CANCELLED},
    ExternalStatus.REJECTED: {OrderStatus.REJECTED},
}


class PaperTradingAdapter:
    def __init__(self, capabilities: AdapterCapabilities | None = None) -> None:
        self.capabilities = capabilities or AdapterCapabilities("local-paper", "v1", True, True, ("simulation-only",))

    def prepare_order(self, order: Order, *, external_client_order_id: str, idempotency_key: str) -> PaperOrderIntent:
        """Map a local working Order outbound without claiming acceptance."""

        if not isinstance(order, Order):
            raise TypeError("paper order mapping requires canonical Order")
        if order.status not in {OrderStatus.CREATED, OrderStatus.ACCEPTED, OrderStatus.WORKING}:
            raise ValueError("only an unfilled live order can be mapped outbound")
        return PaperOrderIntent(
            order.order_id,
            external_client_order_id,
            order.instrument,
            order.direction,
            order.quantity,
            order.limit_price,
            order.stop_price,
            idempotency_key,
            self.capabilities.digest,
        )

    def reconcile(
        self, local_order_id: str, local_filled_quantity: int | Decimal, external: ExternalExecution
    ) -> Reconciliation:
        """Compatibility quantity check; UNKNOWN still fails closed."""

        local_quantity = Decimal(local_filled_quantity)
        if not local_order_id or external.order_id != local_order_id:
            return self._failure(local_order_id, external, ReconciliationOutcome.MISMATCH, "ORDER_ID_MISMATCH")
        if external.status is ExternalStatus.UNKNOWN:
            return self._failure(local_order_id, external, ReconciliationOutcome.UNKNOWN, "UNKNOWN_EXTERNAL_STATE")
        if external.filled_quantity != local_quantity:
            return self._failure(local_order_id, external, ReconciliationOutcome.MISMATCH, "FILL_QUANTITY_MISMATCH")
        return self._success(local_order_id, external)

    def reconcile_state(
        self,
        local_order: Order,
        local_fills: tuple[Fill, ...],
        external: ExternalExecution,
        *,
        external_order_id: str,
        health: ConnectorHealth = ConnectorHealth.HEALTHY,
    ) -> Reconciliation:
        """Compare local and external order/fill facts in both directions."""

        if not isinstance(local_order, Order) or any(not isinstance(fill, Fill) for fill in local_fills):
            raise TypeError("reconciliation requires canonical Order and Fill facts")
        if not isinstance(local_fills, tuple) or not isinstance(health, ConnectorHealth):
            raise TypeError("local fills and connector health must be typed")
        if health is not ConnectorHealth.HEALTHY:
            outcome = (
                ReconciliationOutcome.DEGRADED if health is ConnectorHealth.DEGRADED else ReconciliationOutcome.UNKNOWN
            )
            return self._failure(
                str(local_order.order_id), external, outcome, f"CONNECTOR_{health.value}", health=health
            )
        if external.status is ExternalStatus.UNKNOWN:
            return self._failure(
                str(local_order.order_id), external, ReconciliationOutcome.UNKNOWN, "UNKNOWN_EXTERNAL_STATE"
            )
        if external.order_id != external_order_id:
            return self._failure(
                str(local_order.order_id), external, ReconciliationOutcome.MISMATCH, "ORDER_ID_MAPPING_MISMATCH"
            )
        if external.quantity is None:
            return self._failure(
                str(local_order.order_id), external, ReconciliationOutcome.UNKNOWN, "EXTERNAL_ORDER_QUANTITY_UNKNOWN"
            )
        if not self.capabilities.supports_partial_fills and Decimal("0") < external.filled_quantity < external.quantity:
            return self._failure(
                str(local_order.order_id), external, ReconciliationOutcome.UNSUPPORTED, "UNSUPPORTED_PARTIAL_FILL"
            )
        discrepancies: list[str] = []
        if external.quantity != local_order.quantity:
            discrepancies.append("ORDER_QUANTITY_MISMATCH")
        if local_order.status not in _STATUS_MAP.get(external.status, set()):
            discrepancies.append("ORDER_STATUS_MISMATCH")
        local_fill_quantity = sum((fill.quantity for fill in local_fills), Decimal("0"))
        external_fill_quantity = sum((fill.quantity for fill in external.fills), Decimal("0"))
        if local_fill_quantity != local_order.filled_quantity:
            discrepancies.append("LOCAL_FILL_ORDER_MISMATCH")
        if external_fill_quantity != external.filled_quantity:
            discrepancies.append("EXTERNAL_FILL_ORDER_MISMATCH")
        if local_order.filled_quantity != external.filled_quantity:
            discrepancies.append("CROSS_SYSTEM_FILL_MISMATCH")
        if len({fill.fill_id for fill in local_fills}) != len(local_fills):
            discrepancies.append("DUPLICATE_LOCAL_FILL")
        for local_fill in local_fills:
            if local_fill.order_id != local_order.order_id:
                discrepancies.append("LOCAL_FILL_ORDER_ID_MISMATCH")
            if local_fill.instrument != local_order.instrument or local_fill.direction is not local_order.direction:
                discrepancies.append("LOCAL_FILL_CONTRACT_MISMATCH")
        if len({fill.external_fill_id for fill in external.fills}) != len(external.fills):
            discrepancies.append("DUPLICATE_EXTERNAL_FILL")
        for external_fill in external.fills:
            if external_fill.order_id != external.order_id:
                discrepancies.append("EXTERNAL_FILL_ORDER_ID_MISMATCH")
            if (
                external_fill.instrument != local_order.instrument
                or external_fill.direction is not local_order.direction
            ):
                discrepancies.append("EXTERNAL_FILL_CONTRACT_MISMATCH")
        imported = self.normalize_external_fills(local_order, external) if not discrepancies else ()
        if discrepancies:
            return self._failure(
                str(local_order.order_id),
                external,
                ReconciliationOutcome.MISMATCH,
                discrepancies[0],
                discrepancies=tuple(dict.fromkeys(discrepancies)),
            )
        return self._success(str(local_order.order_id), external, imported=imported)

    def validate_cancel_support(self) -> ReconciliationOutcome:
        return ReconciliationOutcome.MATCHED if self.capabilities.supports_cancel else ReconciliationOutcome.UNSUPPORTED

    def normalize_external_fills(self, order: Order, external: ExternalExecution) -> tuple[Fill, ...]:
        """Map a complete, known external fill set into canonical immutable Fill facts."""

        if not isinstance(order, Order) or not isinstance(external, ExternalExecution):
            raise TypeError("fill normalization requires canonical Order and ExternalExecution")
        if external.status is ExternalStatus.UNKNOWN:
            raise ValueError("UNKNOWN_EXTERNAL_STATE")
        if sum((fill.quantity for fill in external.fills), Decimal("0")) != external.filled_quantity:
            raise ValueError("EXTERNAL_FILL_ORDER_MISMATCH")
        if len({fill.external_fill_id for fill in external.fills}) != len(external.fills):
            raise ValueError("DUPLICATE_EXTERNAL_FILL")
        normalized: list[Fill] = []
        for external_fill in external.fills:
            if (
                external_fill.order_id != external.order_id
                or external_fill.instrument != order.instrument
                or external_fill.direction is not order.direction
            ):
                raise ValueError("EXTERNAL_FILL_CONTRACT_MISMATCH")
            seed = canonical_sha256(
                cast(
                    Any,
                    {
                        "manifest": self.capabilities.digest,
                        "external_fill_id": external_fill.external_fill_id,
                        "external_order_id": external.order_id,
                    },
                )
            )
            normalized.append(
                Fill(
                    EntityId.deterministic("fill", seed),
                    order.order_id,
                    order.instrument,
                    order.direction,
                    external_fill.quantity,
                    external_fill.price,
                    external_fill.fee,
                    external_fill.filled_at,
                    schema_version=order.schema_version,
                    source_ref=f"l5:{self.capabilities.name}:{self.capabilities.version}",
                )
            )
        return tuple(normalized)

    def _success(
        self, order_id: str, external: ExternalExecution, *, imported: tuple[Fill, ...] = ()
    ) -> Reconciliation:
        return Reconciliation(
            order_id,
            external.status,
            True,
            "MATCHED",
            imported_fills=imported,
            manifest_digest=self.capabilities.digest,
        )

    def _failure(
        self,
        order_id: str,
        external: ExternalExecution,
        outcome: ReconciliationOutcome,
        reason: str,
        *,
        discrepancies: tuple[str, ...] = (),
        health: ConnectorHealth = ConnectorHealth.HEALTHY,
    ) -> Reconciliation:
        return Reconciliation(
            order_id,
            external.status,
            False,
            reason,
            outcome,
            discrepancies or (reason,),
            connector_health=health,
            can_assume_success=False,
            manifest_digest=self.capabilities.digest,
        )


__all__ = [
    "AdapterCapabilities",
    "ConnectorHealth",
    "ExternalExecution",
    "ExternalFill",
    "ExternalStatus",
    "PaperOrderIntent",
    "PaperTradingAdapter",
    "Reconciliation",
    "ReconciliationOutcome",
]
