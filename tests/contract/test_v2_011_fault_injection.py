from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json

import pytest

from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.accounting_settlement import DurableAuditLog, SimulationAccount
from futures_agent_os.execution_simulation import SimulationEngine
from futures_agent_os.execution_simulation import (
    DurableOrderCommandProcessor,
    FaultInjector,
    L1Bar,
    OrderCommandProcessor,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_fault_injector_rejects_duplicate_and_no_liquidity() -> None:
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    injector = FaultInjector()
    seen: set[str] = set()
    assert injector.duplicate_command("cmd-1", seen).accepted
    assert not injector.duplicate_command("cmd-1", seen).accepted
    decision = injector.no_liquidity(
        order, L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("0"))
    )
    assert decision.triggered and decision.reason == "NO_LIQUIDITY" and decision.filled_quantity == Decimal("0")


def test_fault_injector_recovers_command_state_and_rejects_clock_rule_and_gap_faults() -> None:
    order = Order(
        EntityId.deterministic("order", "fault-order"),
        EntityId.deterministic("execution_plan", "fault-plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.CREATED,
    )
    processor = OrderCommandProcessor()
    processor.register(order)
    accepted = processor.transition("cmd-1", str(order.order_id), OrderStatus.ACCEPTED)
    assert accepted.accepted
    recovered, result = FaultInjector().process_crash(processor.snapshot())
    assert recovered is not None and result.recovered and recovered.last_event_sequence == 1
    replay = recovered.transition("cmd-1", str(order.order_id), OrderStatus.ACCEPTED)
    assert replay == accepted

    injector = FaultInjector()
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    assert injector.clock_skew(now, RecordedAt.from_datetime(now.value + timedelta(seconds=31))).reason == "CLOCK_SKEW"
    assert injector.missing_rule(None).reason == "MISSING_RULE"
    assert injector.event_gap(2, 3).reason == "EVENT_GAP"


def test_durable_order_processor_persists_committed_commands_and_replays_once(tmp_path) -> None:
    """A returned command survives a new process and cannot create a second effect."""
    order = Order(
        EntityId.deterministic("order", "durable-rpo-order"),
        EntityId.deterministic("execution_plan", "durable-rpo-plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        OrderStatus.CREATED,
        created_at=RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC)),
    )
    path = tmp_path / "orders.json"
    processor = DurableOrderCommandProcessor(path)
    processor.register(order)
    assert processor.transition("cmd-accept", str(order.order_id), OrderStatus.ACCEPTED).accepted
    assert processor.transition("cmd-work", str(order.order_id), OrderStatus.WORKING).accepted
    committed = processor.apply_fill("cmd-fill", str(order.order_id), Decimal("1"))
    assert committed.accepted and committed.event_sequence == 3

    restarted = DurableOrderCommandProcessor(path)
    replay = restarted.apply_fill("cmd-fill", str(order.order_id), Decimal("1"))
    assert replay == committed
    assert restarted.get(str(order.order_id)) is not None
    assert restarted.get(str(order.order_id)).filled_quantity == Decimal("1")  # type: ignore[union-attr]
    assert restarted.last_event_sequence == 3


def test_durable_order_processor_rejects_corrupt_restart(tmp_path) -> None:
    order = Order(
        EntityId.deterministic("order", "durable-corrupt-order"),
        EntityId.deterministic("execution_plan", "durable-corrupt-plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.CREATED,
    )
    path = tmp_path / "orders.json"
    processor = DurableOrderCommandProcessor(path)
    processor.register(order)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"]["last_event_sequence"] = 9
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot load"):
        DurableOrderCommandProcessor(path)


def test_cross_module_crash_recovery_replays_fill_once(tmp_path) -> None:
    """A process crash between execution and restart cannot duplicate accounting."""
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "fault-golden")
    order = Order(
        EntityId.deterministic("order", "fault-golden"),
        EntityId.deterministic("execution_plan", "fault-golden"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
        created_at=now,
    )
    processor = DurableOrderCommandProcessor(tmp_path / "orders.json")
    processor.register(order)
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    result = SimulationEngine().execute_l1(
        order, L1Bar(Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1")), account, now=now
    )
    assert result.fill is not None
    assert processor.apply_fill("fill-command", str(order.order_id), result.fill.quantity).accepted
    audit = DurableAuditLog(tmp_path / "audit.json")
    audit.append("FILL", account_id, result.fill, now)
    restarted = DurableOrderCommandProcessor(tmp_path / "orders.json")
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    DurableAuditLog(tmp_path / "audit.json").replay(replayed, account_id=account_id)
    replay = restarted.apply_fill("fill-command", str(order.order_id), result.fill.quantity)
    assert replay.accepted and replay == processor.apply_fill("fill-command", str(order.order_id), result.fill.quantity)
    assert replayed.state == account.state


def test_subprocess_crash_recovery_keeps_committed_order_command(tmp_path) -> None:
    order = Order(
        EntityId.deterministic("order", "subprocess-crash"),
        EntityId.deterministic("execution_plan", "subprocess-crash"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.CREATED,
        created_at=RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC)),
    )
    path = tmp_path / "subprocess-orders.json"
    DurableOrderCommandProcessor(path).register(order)
    result = FaultInjector().process_crash_subprocess(
        str(path), command_id="subprocess-accept", order_id=str(order.order_id), target="ACCEPTED"
    )
    assert result.recovered and result.reason == "SUBPROCESS_RECOVERED"
