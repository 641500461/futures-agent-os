"""Deterministic V2 failure scenarios used by recovery tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import subprocess
import sys

from .fill_model import FillDecision, FillOrderType, L1Bar, L1FillModel
from .l2_model import BookEvent, L2EventFillModel
from futures_agent_os.decision import Order
from futures_agent_os.shared_kernel import RecordedAt
from .order_processor import OrderCommandProcessor, OrderProcessorSnapshot
from .order_processor import DurableOrderCommandProcessor


class FaultKind(StrEnum):
    DUPLICATE_COMMAND = "DUPLICATE_COMMAND"
    OUT_OF_ORDER_EVENT = "OUT_OF_ORDER_EVENT"
    NO_LIQUIDITY = "NO_LIQUIDITY"
    PROCESS_CRASH = "PROCESS_CRASH"
    DATABASE_RESTART = "DATABASE_RESTART"
    CLOCK_SKEW = "CLOCK_SKEW"
    MISSING_RULE = "MISSING_RULE"
    EVENT_GAP = "EVENT_GAP"


@dataclass(frozen=True, slots=True)
class FaultResult:
    kind: FaultKind
    accepted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    kind: FaultKind
    recovered: bool
    last_event_sequence: int
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

    def process_crash(self, snapshot: OrderProcessorSnapshot) -> tuple[OrderCommandProcessor | None, RecoveryResult]:
        """Restore command outcomes after a simulated process crash."""
        try:
            processor = OrderCommandProcessor.restore(snapshot)
        except (TypeError, ValueError) as error:
            return None, RecoveryResult(FaultKind.PROCESS_CRASH, False, 0, str(error))
        return processor, RecoveryResult(FaultKind.PROCESS_CRASH, True, processor.last_event_sequence, "RECOVERED")

    def database_restart(self, snapshot: OrderProcessorSnapshot) -> tuple[OrderCommandProcessor | None, RecoveryResult]:
        processor, result = self.process_crash(snapshot)
        return processor, RecoveryResult(
            FaultKind.DATABASE_RESTART, result.recovered, result.last_event_sequence, result.reason
        )

    def process_crash_subprocess(self, path: str, *, command_id: str, order_id: str, target: str) -> RecoveryResult:
        """Kill a child after a durable command, then recover in a new process.

        The child writes through ``DurableOrderCommandProcessor`` and exits
        without orderly shutdown. The parent only accepts recovery when the
        command is present exactly once after reconstructing the file.
        """
        script = (
            "from futures_agent_os.execution_simulation import DurableOrderCommandProcessor;"
            "from futures_agent_os.decision import OrderStatus; import os,sys;"
            "p=DurableOrderCommandProcessor(sys.argv[1]);"
            "p.transition(sys.argv[2],sys.argv[3],OrderStatus(sys.argv[4])); os._exit(137)"
        )
        child = subprocess.run(
            [sys.executable, "-c", script, path, command_id, order_id, target],
            check=False,
            capture_output=True,
            text=True,
        )
        recovered = DurableOrderCommandProcessor(path)
        order = recovered.get(order_id)
        if child.returncode != 137 or order is None or order.status.value != target:
            return RecoveryResult(
                FaultKind.PROCESS_CRASH, False, recovered.last_event_sequence, "CRASH_RECOVERY_FAILED"
            )
        return RecoveryResult(FaultKind.PROCESS_CRASH, True, recovered.last_event_sequence, "SUBPROCESS_RECOVERED")

    def database_restart_persisted(self, path: str) -> RecoveryResult:
        """Reopen the durable command store as a database-restart analogue."""
        recovered = DurableOrderCommandProcessor(path)
        return RecoveryResult(FaultKind.DATABASE_RESTART, True, recovered.last_event_sequence, "REOPENED")

    def clock_skew(
        self, recorded_at: RecordedAt, observed_at: RecordedAt, *, max_skew: timedelta = timedelta(seconds=30)
    ) -> FaultResult:
        if not isinstance(recorded_at, RecordedAt) or not isinstance(observed_at, RecordedAt):
            raise TypeError("clock skew requires RecordedAt values")
        skew = abs(observed_at.value - recorded_at.value)
        accepted = skew <= max_skew
        return FaultResult(FaultKind.CLOCK_SKEW, accepted, "ACCEPTED" if accepted else "CLOCK_SKEW")

    def missing_rule(self, rule_ref: str | None) -> FaultResult:
        accepted = isinstance(rule_ref, str) and bool(rule_ref.strip()) and not any(c.isspace() for c in rule_ref)
        return FaultResult(FaultKind.MISSING_RULE, accepted, "ACCEPTED" if accepted else "MISSING_RULE")

    def event_gap(self, expected_sequence: int, actual_sequence: int) -> FaultResult:
        accepted = actual_sequence == expected_sequence
        return FaultResult(FaultKind.EVENT_GAP, accepted, "ACCEPTED" if accepted else "EVENT_GAP")
