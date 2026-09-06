from datetime import UTC, datetime
from decimal import Decimal
from dataclasses import replace
from types import SimpleNamespace
import pytest

from futures_agent_os.accounting_settlement import (
    AccountingEvent,
    AccountingEventLog,
    DurableAuditLog,
    SimulationAccount,
    append_simulation_episode,
)
from futures_agent_os.decision import Fill, TradeDirection
from futures_agent_os.decision import Order, OrderStatus
from futures_agent_os.execution_simulation import BookEvent, L1Bar, SimulationEngine, run_manual_shadow_episode
from futures_agent_os.decision import StopPolicy
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_accounting_event_log_replays_in_order() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account_id = EntityId.new("simulation_account")
    fill = Fill(
        EntityId.new("fill"),
        EntityId.new("order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    log = AccountingEventLog()
    log.append(AccountingEvent(1, EntityId.new("accounting_event"), fill))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    log.replay(account, account_id=account_id)
    assert account.state.cash == Decimal("999")
    with pytest.raises(ValueError):
        log.append(AccountingEvent(3, EntityId.new("accounting_event"), fill))


def test_durable_audit_restarts_replays_and_reconciles(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "v2-010-account")
    fill = Fill(
        EntityId.deterministic("fill", "v2-010-fill"),
        EntityId.deterministic("order", "v2-010-order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    path = tmp_path / "audit.json"
    log = DurableAuditLog(path)
    first = log.append("FILL", account_id, fill, now)

    restarted = DurableAuditLog(path)
    projection = SimulationAccount(Decimal("1000"), account_id=account_id)
    restarted.replay(projection, account_id=account_id)
    assert projection.state.cash == Decimal("999")
    assert restarted.reconcile(projection, account_id=account_id).balanced

    correction = restarted.correction(
        first.event_id,
        {"reason": "exchange fee correction", "delta": "0"},
        now,
    )
    assert correction.correction_of == first.event_id
    assert DurableAuditLog(path).verify()
    assert tuple(event.event_type for event in DurableAuditLog(path).events) == ("FILL", "CORRECTION")


def test_durable_audit_fails_closed_on_corrupt_restart(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    path = tmp_path / "audit.json"
    log = DurableAuditLog(path)
    log.append("PLAN_VALIDATED", EntityId.new("trade_plan"), {"outcome": "VALID"}, now)
    data = path.read_text(encoding="utf-8")
    path.write_text(data.replace("VALID", "ALTERED"), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot load"):
        DurableAuditLog(path)


def test_durable_audit_rebuilds_open_close_settlement_chain_after_restart(tmp_path) -> None:
    """A complete simulated episode has one deterministic durable projection."""
    account_id = EntityId.deterministic("simulation_account", "v2-010-golden-account")
    order_open = EntityId.deterministic("order", "v2-010-golden-open")
    order_close = EntityId.deterministic("order", "v2-010-golden-close")
    open_at = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    close_at = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 5, tzinfo=UTC))
    settle_at = RecordedAt.from_datetime(datetime(2026, 9, 5, 15, 0, tzinfo=UTC))
    opened = Fill(
        EntityId.deterministic("fill", "v2-010-golden-open-fill"),
        order_open,
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        Decimal("100"),
        Decimal("1"),
        open_at,
    )
    closed = Fill(
        EntityId.deterministic("fill", "v2-010-golden-close-fill"),
        order_close,
        "SHFE_AG_2601",
        TradeDirection.SHORT,
        Decimal("1"),
        Decimal("110"),
        Decimal("1"),
        close_at,
    )
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    account.apply_fill(
        opened, lot_id=EntityId.deterministic("position_lot", str(opened.fill_id)), account_id=account_id
    )
    account.close(closed)
    settlement = account.mark_to_market(
        EntityId.deterministic("settlement", "v2-010-golden-settlement"),
        "2026-09-05",
        Decimal("110"),
        settle_at,
    )
    account.settle(settlement)
    account.assert_conservation()

    path = tmp_path / "golden-audit.json"
    log = DurableAuditLog(path)
    log.append("FILL", account_id, opened, open_at, source_ref="source:v2:golden")
    log.append("CLOSE_FILL", account_id, closed, close_at, source_ref="source:v2:golden")
    log.append("SETTLEMENT", account_id, settlement, settle_at, source_ref="source:v2:golden")
    assert log.reconcile(account, account_id=account_id).balanced

    restarted = DurableAuditLog(path)
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    restarted.replay(replayed, account_id=account_id)
    assert replayed.state == account.state
    assert replayed.conservation_residual() == Decimal("0")
    # Replaying the same source facts after restart is harmless and does not
    # alter cash, lots, or realized PnL.
    restarted.replay(replayed, account_id=account_id)
    assert replayed.state == account.state
    assert restarted.reconcile(replayed, account_id=account_id).balanced


def test_shared_l1_engine_emits_deterministic_fill_for_replay() -> None:
    account_id = EntityId.deterministic("simulation_account", "v2-010-engine-account")
    order = Order(
        EntityId.deterministic("order", "v2-010-engine-order"),
        EntityId.deterministic("execution_plan", "v2-010-engine-plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
        created_at=RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC)),
    )
    bar = L1Bar(Decimal("100"), Decimal("105"), Decimal("99"), Decimal("101"), Decimal("2"))
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 1, tzinfo=UTC))
    first = SimulationEngine().execute_l1(
        order, bar, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    second = SimulationEngine().execute_l1(
        order, bar, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    assert first.fill is not None and second.fill == first.fill
    assert first.order == second.order


def test_l2_engine_and_durable_audit_replay_same_account_state(tmp_path) -> None:
    account_id = EntityId.deterministic("simulation_account", "v2-010-l2-chain")
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    order = Order(
        EntityId.deterministic("order", "v2-010-l2-chain"),
        EntityId.deterministic("execution_plan", "v2-010-l2-chain"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        OrderStatus.WORKING,
    )
    events = (
        BookEvent(1, Decimal("99"), Decimal("1"), Decimal("101"), Decimal("1")),
        BookEvent(2, Decimal("100"), Decimal("2"), Decimal("102"), Decimal("1")),
    )
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    result = SimulationEngine().execute_l2(order, events, account, now=now)
    assert result.fill is not None
    audit = DurableAuditLog(tmp_path / "l2-audit.json")
    audit.append("FILL", account_id, result.fill, now, source_ref="source:v2:l2")
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    DurableAuditLog(tmp_path / "l2-audit.json").replay(replayed, account_id=account_id)
    assert replayed.state == account.state


def test_simulation_output_adapter_persists_and_replays_linked_episode(tmp_path) -> None:
    """Production-shaped shadow output is the source for the durable chain."""
    at = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "v2-010-adapter")
    plan_id = EntityId.deterministic("trade_plan", "v2-010-adapter")
    order = Order(
        EntityId.deterministic("order", "v2-010-adapter"),
        EntityId.deterministic("execution_plan", "v2-010-adapter"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
        created_at=at,
    )
    open_bar = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("2"))
    exit_bar = L1Bar(Decimal("100"), Decimal("101"), Decimal("90"), Decimal("95"), Decimal("2"))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    stop = StopPolicy(
        EntityId.deterministic("stop_policy", str(order.order_id)),
        EntityId.deterministic("position_lot", "placeholder"),
        Decimal("95"),
        Decimal("95"),
        created_at=at,
    )
    probe = SimulationAccount(Decimal("1000"), account_id=account_id)
    opened = SimulationEngine().execute_l1(order, open_bar, probe, now=at)
    assert opened.fill is not None
    stop = replace(stop, position_id=EntityId.deterministic("position_lot", str(opened.fill.fill_id)))
    report = run_manual_shadow_episode(order, account, open_bar=open_bar, exit_bar=exit_bar, stop_policy=stop, now=at)
    submission = SimpleNamespace(
        order=order,
        risk=SimpleNamespace(
            decision_id=EntityId.deterministic("risk_decision", "v2-010-adapter"),
            outcome=SimpleNamespace(value="APPROVE"),
            approved_quantity=Decimal("1"),
        ),
        receipt=SimpleNamespace(
            receipt_id=EntityId.deterministic("autonomy_gate_receipt", "v2-010-adapter"),
            execution_origin="MANUAL_TEST",
        ),
        protection=SimpleNamespace(
            mandate_id=EntityId.deterministic("protection_mandate", "v2-010-adapter"), stop_price=Decimal("95")
        ),
        execution_plan=SimpleNamespace(execution_plan_id=order.execution_plan_id),
    )
    plan = SimpleNamespace(plan_id=plan_id, plan_hash="a" * 64)
    path = tmp_path / "adapter-audit.json"
    log = DurableAuditLog(path)
    events = append_simulation_episode(
        log, correlation_id=plan_id, recorded_at=at, plan=plan, submission=submission, shadow_report=report
    )
    assert {event.event_type for event in events} == {
        "AUTHORIZATION",
        "RISK_DECISION",
        "EXECUTION_PLAN",
        "PROTECTION",
        "FILL",
        "CLOSE_FILL",
        "SETTLEMENT",
    }
    authorization_event = next(event for event in events if event.event_type == "AUTHORIZATION")
    assert authorization_event.payload["execution_origin"] == "MANUAL_TEST"
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    DurableAuditLog(path).replay_trade_episode(replayed, account_id=account_id, correlation_id=plan_id)
    assert replayed.state == account.state
    assert DurableAuditLog(path).reconcile(replayed, account_id=account_id).balanced


def test_durable_full_fact_correction_reconciles_to_corrected_projection(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    corrected_at = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 1, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "v2-010-correction-account")
    original = Fill(
        EntityId.deterministic("fill", "v2-010-correction-fill"),
        EntityId.deterministic("order", "v2-010-correction-order"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    corrected = Fill(
        original.fill_id,
        original.order_id,
        original.instrument,
        original.direction,
        original.quantity,
        original.price,
        Decimal("2"),
        original.filled_at,
    )
    path = tmp_path / "corrected-audit.json"
    log = DurableAuditLog(path)
    target = log.append("FILL", account_id, original, now)
    log.correct_fact(target.event_id, corrected, corrected_at)

    current = SimulationAccount(Decimal("1000"), account_id=account_id)
    current.apply_fill(
        corrected,
        lot_id=EntityId.deterministic("position_lot", str(corrected.fill_id)),
        account_id=account_id,
    )
    restarted = DurableAuditLog(path)
    report = restarted.reconcile(current, account_id=account_id)
    assert report.valid_chain and report.correction_count == 1 and report.balanced
    assert report.replay_cash == Decimal("998")

    wrong_identity = Fill(
        EntityId.deterministic("fill", "v2-010-correction-other-fill"),
        original.order_id,
        original.instrument,
        original.direction,
        original.quantity,
        original.price,
        Decimal("2"),
        original.filled_at,
    )
    with pytest.raises(ValueError, match="retain the accounting identity"):
        restarted.correct_fact(target.event_id, wrong_identity, corrected_at)


def test_durable_trade_episode_links_lifecycle_and_replays(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "v2-010-linked")
    correlation = EntityId.deterministic("trade_plan", "v2-010-linked")
    order_id = EntityId.deterministic("order", "v2-010-linked")
    fill = Fill(
        EntityId.deterministic("fill", "v2-010-linked"),
        order_id,
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("0"),
        now,
    )
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    account.apply_fill(fill, lot_id=EntityId.deterministic("position_lot", str(fill.fill_id)), account_id=account_id)
    settlement = account.mark_to_market(
        EntityId.deterministic("settlement", "v2-010-linked"), "2026-09-05", Decimal("100"), now
    )
    account.settle(settlement)
    log = DurableAuditLog(tmp_path / "linked.json")
    events = log.append_trade_episode(
        correlation_id=correlation,
        recorded_at=now,
        authorization={"basis_id": "basis", "plan_id": str(correlation)},
        risk={"decision_id": "risk", "plan_id": str(correlation)},
        execution={"execution_plan_id": "execution", "plan_id": str(correlation)},
        protection={"mandate_id": "protection", "plan_id": str(correlation)},
        fills=(fill,),
        settlement=settlement,
    )
    assert [event.event_type for event in events] == [
        "AUTHORIZATION",
        "RISK_DECISION",
        "EXECUTION_PLAN",
        "PROTECTION",
        "FILL",
        "SETTLEMENT",
    ]
    restarted = DurableAuditLog(tmp_path / "linked.json")
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    restarted.replay_trade_episode(replayed, account_id=account_id, correlation_id=correlation)
    assert replayed.state == account.state


def test_durable_replay_isolates_account_projection(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    account_one = EntityId.deterministic("simulation_account", "replay-one")
    account_two = EntityId.deterministic("simulation_account", "replay-two")
    log = DurableAuditLog(tmp_path / "multi-account.json")
    for index, account_id in enumerate((account_one, account_two)):
        fill = Fill(
            EntityId.deterministic("fill", f"multi-{index}"),
            EntityId.deterministic("order", f"multi-{index}"),
            "SHFE_AG_2601",
            TradeDirection.LONG,
            Decimal("1"),
            Decimal("100"),
            Decimal("1"),
            now,
        )
        log.append("FILL", account_id, fill, now)
    projection = SimulationAccount(Decimal("1000"), account_id=account_one)
    log.replay(projection, account_id=account_one)
    assert projection.state.cash == Decimal("999") and len(projection.state.lots) == 1


def test_linked_episode_replay_includes_targeted_correction(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "corrected-episode")
    correlation = EntityId.deterministic("trade_plan", "corrected-episode")
    order_id = EntityId.deterministic("order", "corrected-episode")
    original = Fill(
        EntityId.deterministic("fill", "corrected-episode"),
        order_id,
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        Decimal("1"),
        now,
    )
    log = DurableAuditLog(tmp_path / "corrected-episode.json")
    log.append_trade_episode(
        correlation_id=correlation,
        recorded_at=now,
        authorization={"basis_id": "basis"},
        risk={"decision_id": "risk"},
        execution={"execution_plan_id": "execution"},
        protection={"mandate_id": "protection"},
        fills=(original,),
        settlement=SimulationAccount(Decimal("1000"), account_id=account_id).mark_to_market(
            EntityId.deterministic("settlement", "corrected-episode"), "2026-09-05", Decimal("100"), now
        ),
    )
    corrected = replace(original, fee=Decimal("2"))
    target = next(event for event in log.events if event.event_type == "FILL")
    log.correct_fact(target.event_id, corrected, now)
    current = SimulationAccount(Decimal("1000"), account_id=account_id)
    restarted = DurableAuditLog(log.path)
    restarted.replay_trade_episode(current, account_id=account_id, correlation_id=correlation)
    assert current.state.cash == Decimal("998")


def test_manual_shadow_report_is_automatically_wired_to_durable_episode(tmp_path) -> None:
    """The real simulation result is sufficient to build and replay the audit chain."""
    account_id = EntityId.deterministic("simulation_account", "v2-010-production-bridge")
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    order = Order(
        EntityId.deterministic("order", "v2-010-production-bridge"),
        EntityId.deterministic("execution_plan", "v2-010-production-bridge"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
        created_at=now,
    )
    entry = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("2"))
    stop_exit = L1Bar(Decimal("95"), Decimal("96"), Decimal("90"), Decimal("92"), Decimal("2"))
    stop = StopPolicy(
        EntityId.deterministic("stop_policy", "v2-010-production-bridge"),
        EntityId.deterministic("position_lot", "v2-010-production-bridge"),
        Decimal("95"),
        Decimal("10"),
        created_at=now,
    )
    # run_manual_shadow_episode validates and binds the actual prospective lot;
    # derive that identity exactly as the engine does for this frozen input.
    probe = SimulationAccount(Decimal("1000"), account_id=account_id)
    opened = SimulationEngine().execute_l1(order, entry, probe, now=now)
    assert opened.fill is not None
    stop = replace(stop, position_id=EntityId.deterministic("position_lot", str(opened.fill.fill_id)))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    report = run_manual_shadow_episode(order, account, open_bar=entry, exit_bar=stop_exit, stop_policy=stop, now=now)
    assert report.settlement is not None and report.exit_fill is not None

    correlation = EntityId.deterministic("trade_plan", "v2-010-production-bridge")
    path = tmp_path / "production-bridge.json"
    audit = DurableAuditLog(path)
    events = audit.append_manual_shadow_episode(report, correlation_id=correlation, recorded_at=now)
    assert [event.event_type for event in events] == [
        "AUTHORIZATION",
        "RISK_DECISION",
        "EXECUTION_PLAN",
        "PROTECTION",
        "FILL",
        "CLOSE_FILL",
        "SETTLEMENT",
    ]
    restarted = DurableAuditLog(path)
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    restarted.replay_trade_episode(replayed, account_id=account_id, correlation_id=correlation)
    assert replayed.state == account.state
    assert restarted.reconcile(replayed, account_id=account_id).balanced
