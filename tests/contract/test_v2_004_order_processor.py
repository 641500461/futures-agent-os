from decimal import Decimal
from pathlib import Path
import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import DurableOrderCommandProcessor, OrderCommandProcessor
from futures_agent_os.shared_kernel import EntityId


def _order() -> Order:
    return Order(EntityId.new("order"), EntityId.new("execution_plan"), "SHFE:AG", TradeDirection.LONG, Decimal("1"))


def test_order_commands_are_idempotent_and_reject_invalid_transitions() -> None:
    order = _order()
    processor = OrderCommandProcessor()
    processor.register(order)
    accepted = processor.transition("c1", str(order.order_id), OrderStatus.ACCEPTED)
    assert accepted.accepted
    assert processor.transition("c1", str(order.order_id), OrderStatus.REJECTED) == accepted
    rejected = processor.transition("c2", str(order.order_id), OrderStatus.FILLED)
    assert not rejected.accepted and rejected.reason == "INVALID_TRANSITION"


def test_cancel_fill_race_is_resolved_by_event_sequence() -> None:
    order = _order()
    processor = OrderCommandProcessor()
    processor.register(order)
    assert processor.transition("accept", str(order.order_id), OrderStatus.ACCEPTED, event_sequence=1).accepted
    assert processor.transition("work", str(order.order_id), OrderStatus.WORKING, event_sequence=2).accepted
    # The cancel arrives first in the exchange stream.  A later fill cannot
    # revive the terminal order, even if it was generated concurrently.
    cancelled = processor.transition("cancel", str(order.order_id), OrderStatus.CANCELLED, event_sequence=3)
    assert cancelled.accepted
    raced_fill = processor.apply_fill("fill", str(order.order_id), Decimal("1"), event_sequence=4)
    assert not raced_fill.accepted and raced_fill.order is not None
    assert processor.get(str(order.order_id)).status is OrderStatus.CANCELLED


def test_fill_wins_when_it_precedes_cancel_and_snapshot_preserves_idempotency() -> None:
    order = _order()
    processor = OrderCommandProcessor()
    processor.register(order)
    processor.transition("accept", str(order.order_id), OrderStatus.ACCEPTED, event_sequence=1)
    processor.transition("work", str(order.order_id), OrderStatus.WORKING, event_sequence=2)
    fill = processor.apply_fill("fill", str(order.order_id), Decimal("1"), event_sequence=3)
    assert fill.accepted and fill.order is not None and fill.order.status is OrderStatus.FILLED
    # A cancel after a complete fill is rejected, while the duplicate fill is
    # replayed with exactly the original business result.
    cancel = processor.transition("cancel", str(order.order_id), OrderStatus.CANCELLED, event_sequence=4)
    assert not cancel.accepted and cancel.reason == "INVALID_TRANSITION"
    restored = OrderCommandProcessor.restore(processor.snapshot())
    assert restored.apply_fill("fill", str(order.order_id), Decimal("1"), event_sequence=3) == fill
    conflict = restored.apply_fill("fill", str(order.order_id), Decimal("0.5"), event_sequence=99)
    assert not conflict.accepted and conflict.reason == "COMMAND_ID_CONFLICT"


def test_event_sequence_gaps_are_retryable_and_command_ids_are_canonical() -> None:
    order = _order()
    processor = OrderCommandProcessor()
    processor.register(order)
    with pytest.raises(ValueError):
        processor.transition("bad id", str(order.order_id), OrderStatus.ACCEPTED)
    gap = processor.transition("accept", str(order.order_id), OrderStatus.ACCEPTED, event_sequence=2)
    assert not gap.accepted and gap.reason == "EVENT_SEQUENCE_GAP"
    accepted = processor.transition("accept", str(order.order_id), OrderStatus.ACCEPTED, event_sequence=1)
    assert accepted.accepted


def test_durable_processor_replays_duplicate_command_after_restart(tmp_path: Path) -> None:
    order = _order()
    path = tmp_path / "order.json"
    processor = DurableOrderCommandProcessor(path)
    processor.register(order)
    processor.transition("accept", str(order.order_id), OrderStatus.ACCEPTED, event_sequence=1)
    restored = DurableOrderCommandProcessor.restore(path)
    replayed = restored.transition("accept", str(order.order_id), OrderStatus.REJECTED, event_sequence=2)
    assert not replayed.accepted and replayed.reason == "COMMAND_ID_CONFLICT"
    assert restored.get(str(order.order_id)) == processor.get(str(order.order_id))
