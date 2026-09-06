from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_agent_os.accounting_settlement import AccountingEvent, AccountingEventLog, SimulationAccount
from futures_agent_os.decision import Order, OrderStatus, TradeDirection
from futures_agent_os.execution_simulation import (
    BookEvent,
    FrozenStrategySpecFixture,
    L1Bar,
    SimulationEngine,
    replay_v1_candidate_l2_matrix,
)
from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.research_experiment import stratified_replay_candidates
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_shared_engine_is_deterministic_for_same_l1_input() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    account_id = EntityId.new("simulation_account")
    order = Order(
        EntityId.new("order"),
        EntityId.new("execution_plan"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("2"))
    first = SimulationEngine().execute_l1(
        order, bar, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    second = SimulationEngine().execute_l1(
        order, bar, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    assert first.order.filled_quantity == second.order.filled_quantity == Decimal("2")
    assert first.account_cash == second.account_cash


def test_shared_engine_fill_can_be_replayed_into_same_account_projection() -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 6, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "v2-009-replay")
    order = Order(
        EntityId.deterministic("order", "v2-009-replay"),
        EntityId.deterministic("execution_plan", "v2-009-replay"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        OrderStatus.WORKING,
    )
    bar = L1Bar(Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))
    account = SimulationAccount(Decimal("1000"), account_id=account_id)
    result = SimulationEngine().execute_l1(order, bar, account, now=now)
    assert result.fill is not None
    assert result.account_cash == Decimal("1000")
    assert result.fill.price == Decimal("100")
    log = AccountingEventLog()
    log.append(AccountingEvent(1, EntityId.deterministic("accounting_event", "v2-009-replay"), result.fill))
    replayed = SimulationAccount(Decimal("1000"), account_id=account_id)
    log.replay(replayed, account_id=account_id)
    assert replayed.state == account.state
    assert replayed.state.lots[0].source_fill_id == result.fill.fill_id
    log.replay(replayed, account_id=account_id)
    assert replayed.state == account.state


def test_shared_engine_l2_replay_is_deterministic() -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 6, 8, 0, tzinfo=UTC))
    account_id = EntityId.deterministic("simulation_account", "v2-009-l2-engine")
    order = Order(
        EntityId.deterministic("order", "v2-009-l2-engine"),
        EntityId.deterministic("execution_plan", "v2-009-l2-engine"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        OrderStatus.WORKING,
    )
    events = (
        BookEvent(1, Decimal("99"), Decimal("1"), Decimal("101"), Decimal("1")),
        BookEvent(2, Decimal("100"), Decimal("2"), Decimal("102"), Decimal("1")),
    )
    first = SimulationEngine().execute_l2(
        order, events, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    second = SimulationEngine().execute_l2(
        order, events, SimulationAccount(Decimal("1000"), account_id=account_id), now=now
    )
    assert first.fill == second.fill and first.order == second.order


def test_frozen_strategy_fixture_replays_walk_forward_with_stable_manifest() -> None:
    fixture = FrozenStrategySpecFixture(
        "strategy-fixture-v2",
        1,
        (1, -1, 1, 1, -1, 1, -1, 1),
        (1, -1, -1, 1, -1, 1, 1, 1),
        (
            Decimal("0.01"),
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.03"),
            Decimal("0.01"),
            Decimal("-0.02"),
            Decimal("0.04"),
            Decimal("0.01"),
        ),
        tuple(f"2026-09-0{i + 1}" for i in range(8)),
        tuple(f"2026-09-{i + 2}" for i in range(8)),
        Decimal("0.001"),
        3,
        2,
        2,
        1,
    )
    assert fixture.replay() == fixture.replay()
    assert fixture.manifest() == fixture.manifest()
    assert all(fold.config_sha256 == fixture.fixture_hash for fold in fixture.replay())
    assert fixture.counterfactual_manifest() == fixture.counterfactual_manifest()
    assert fixture.stressed_manifest() == fixture.stressed_manifest()
    assert fixture.counterfactual_manifest() != fixture.manifest()
    assert fixture.stressed_manifest() != fixture.manifest()

    base = fixture.replay_l2()
    counterfactual = fixture.replay_l2(variant="counterfactual")
    stressed = fixture.replay_l2(variant="stress", cost_multiplier=Decimal("2"))
    assert base.replay_cash == base.ledger_cash
    assert counterfactual.replay_cash == counterfactual.ledger_cash
    assert stressed.replay_cash == stressed.ledger_cash
    assert base.result_hash != counterfactual.result_hash
    assert base.result_hash != stressed.result_hash
    assert base.order_ids and base.fill_ids
    matrix = fixture.replay_l2_matrix()
    assert len(matrix.variants) == 3
    assert matrix.matrix_hash == fixture.replay_l2_matrix().matrix_hash


def test_v1_mvp_candidate_bridges_real_pit_window_into_l2_matrix() -> None:
    """V1's sealed PIT records drive signals; V2 supplies executable facts."""
    first = datetime(2026, 7, 1, tzinfo=UTC)
    closes = tuple(100 + (index % 2) * 2 + index // 4 for index in range(58))
    records = tuple(
        PointInTimeRecord(
            RecordedAt.from_datetime(first + timedelta(days=index)),
            RecordedAt.from_datetime(first + timedelta(days=index, hours=1)),
            {"instrument_id": "SHFE.AG.DOMINANT_OI", "close": str(close), "trading_date": f"2026-07-{index + 1:02d}"},
        )
        for index, close in enumerate(closes)
    )
    candidates = stratified_replay_candidates(
        records,
        cutoff_start=records[39].event_time,
        cutoff_end=records[52].event_time,
        candidates_per_cell=2,
    )
    candidate = candidates[0]
    first_result = replay_v1_candidate_l2_matrix(candidate)
    second_result = replay_v1_candidate_l2_matrix(candidate)
    assert first_result == second_result
    assert first_result["v1_input_record_count"] == 40
    assert first_result["walk_forward_manifest"]
    assert first_result["counterfactual_manifest"] != first_result["walk_forward_manifest"]
    assert first_result["stress_manifest"] != first_result["walk_forward_manifest"]
    assert first_result["deterministic"] is True
    assert len(first_result["l2_result_hashes"]) == 3
    assert len(set(first_result["l2_result_hashes"])) == 3
