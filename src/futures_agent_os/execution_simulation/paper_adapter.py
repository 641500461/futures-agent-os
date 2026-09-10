"""Paper trading reconciliation adapter; never treats unknown states as success."""

from dataclasses import dataclass
from enum import StrEnum


class ExternalStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExternalExecution:
    order_id: str
    status: ExternalStatus
    filled_quantity: int


@dataclass(frozen=True, slots=True)
class Reconciliation:
    order_id: str
    status: ExternalStatus
    matched: bool
    reason: str


class PaperTradingAdapter:
    def reconcile(self, local_order_id: str, local_filled_quantity: int, external: ExternalExecution) -> Reconciliation:
        if not local_order_id or external.order_id != local_order_id:
            return Reconciliation(local_order_id, external.status, False, "ORDER_ID_MISMATCH")
        if external.status is ExternalStatus.UNKNOWN:
            return Reconciliation(local_order_id, external.status, False, "UNKNOWN_EXTERNAL_STATE")
        if external.filled_quantity < 0 or external.filled_quantity != local_filled_quantity:
            return Reconciliation(local_order_id, external.status, False, "FILL_QUANTITY_MISMATCH")
        return Reconciliation(local_order_id, external.status, True, "MATCHED")
