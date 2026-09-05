"""Deterministic V2 failure scenarios used by recovery tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .fill_model import FillDecision, FillOrderType, L1Bar, L1FillModel
from .l2_model import BookEvent, L2EventFillModel
from futures_agent_os.decision import Order


class FaultKind(StrEnum):
    DUPLICATE_COMMAND = "DUPLICATE_COMMAND"
    OUT_OF_ORDER_EVENT = "OUT_OF_ORDER_EVENT"
    NO_LIQUIDITY = "NO_LIQUIDITY"


@dataclass(frozen=True, slots=True)
class FaultResult:
    kind: FaultKind
    accepted: bool
    reason: str


class FaultInjector:
    def duplicate_command(self, command_id: str, seen: set[str]) -> FaultResult:
        if command_id in seen:
            return FaultResult(FaultKind.DUPLICATE_COMMAND, False, "DUPLICATE_COMMAND")
        seen.add(command_id)
        return FaultResult(FaultKind.DUPLICATE_COMMAND, True, "ACCEPTED")

    def out_of_order(self, order: Order, events: tuple[BookEvent, ...]) -> FaultResult:
        try:
            L2EventFillModel().simulate(order, events)
        except ValueError:
            return FaultResult(FaultKind.OUT_OF_ORDER_EVENT, False, "OUT_OF_ORDER_EVENT")
        return FaultResult(FaultKind.OUT_OF_ORDER_EVENT, True, "ACCEPTED")

    def no_liquidity(self, order: Order, bar: L1Bar) -> FillDecision:
        return L1FillModel().simulate(order, bar, order_type=FillOrderType.MARKET)
