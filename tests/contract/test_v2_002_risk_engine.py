from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_agent_os.decision import ProtectionIntent, TradeAction, TradeDirection, TradePlan, RiskDecisionOutcome
from futures_agent_os.portfolio_risk import RiskConstitution, RiskEngine
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_risk_engine_sizes_and_modifies_plan() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    plan = TradePlan(
        EntityId.new("trade_plan"),
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        "strategy:test",
        TradeAction.OPEN,
        TradeDirection.LONG,
        Decimal("20"),
        Decimal("100"),
        ProtectionIntent(Decimal("95"), Decimal("50")),
        "thesis",
        "invalid",
        ("a" * 64,),
        "snapshot:test",
        RecordedAt.from_datetime(now.value + timedelta(hours=1)),
    )
    constitution = RiskConstitution(
        "risk:test", 1, "b" * 64, Decimal("50"), Decimal("1000"), Decimal("10"), Decimal("0.1")
    )
    decision = RiskEngine(constitution).decide(plan, decision_id=EntityId.new("risk_decision"), now=now)
    assert decision.outcome is RiskDecisionOutcome.MODIFY and decision.approved_quantity == Decimal("10")


def test_kill_switch_fails_closed_with_stable_code() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    plan = TradePlan(
        EntityId.new("trade_plan"),
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        "strategy:test",
        TradeAction.OPEN,
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        ProtectionIntent(Decimal("95"), Decimal("50")),
        "thesis",
        "invalid",
        ("a" * 64,),
        "snapshot:test",
        RecordedAt.from_datetime(now.value + timedelta(hours=1)),
    )
    constitution = RiskConstitution(
        "risk:test", 1, "b" * 64, Decimal("50"), Decimal("1000"), Decimal("10"), Decimal("0.1"), kill_switch=True
    )
    decision = RiskEngine(constitution).decide(plan, decision_id=EntityId.new("risk_decision"), now=now)
    assert decision.outcome is RiskDecisionOutcome.REJECT and decision.rule_refs == ("KILL_SWITCH",)


def test_quality_concentration_and_delivery_gates_fail_closed() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    plan = TradePlan(
        EntityId.new("trade_plan"),
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        "strategy:test",
        TradeAction.OPEN,
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        ProtectionIntent(Decimal("95"), Decimal("50")),
        "thesis",
        "invalid",
        ("a" * 64,),
        "snapshot:test",
        RecordedAt.from_datetime(now.value + timedelta(hours=1)),
    )
    constitution = RiskConstitution(
        "risk:test",
        1,
        "b" * 64,
        Decimal("50"),
        Decimal("1000"),
        Decimal("10"),
        Decimal("0.1"),
        max_concentration=Decimal("5"),
        min_data_quality=Decimal("0.9"),
        delivery_horizon_days=3,
    )
    engine = RiskEngine(constitution)
    for quality, concentration, expected_code in (
        (None, None, "DATA_QUALITY_UNAVAILABLE"),
        (Decimal("1"), None, "CONCENTRATION_UNAVAILABLE"),
        (Decimal("1"), Decimal("1"), "DELIVERY_HORIZON_UNAVAILABLE"),
    ):
        decision = engine.decide(
            plan,
            decision_id=EntityId.new("risk_decision"),
            now=now,
            data_quality=quality,
            concentration=concentration,
        )
        assert decision.outcome is RiskDecisionOutcome.REJECT
        assert decision.approved_quantity == 0
        assert decision.rule_refs == (expected_code,)
        assert decision.plan_hash == plan.plan_hash
    assert engine.decide(
        plan, decision_id=EntityId.new("risk_decision"), now=now, data_quality=Decimal("0.8")
    ).rule_refs == ("DATA_QUALITY_INSUFFICIENT",)
    assert engine.decide(
        plan, decision_id=EntityId.new("risk_decision"), now=now, data_quality=Decimal("1"), concentration=Decimal("6")
    ).rule_refs == ("CONCENTRATION_LIMIT",)
    assert engine.decide(
        plan,
        decision_id=EntityId.new("risk_decision"),
        now=now,
        data_quality=Decimal("1"),
        concentration=Decimal("1"),
        days_to_delivery=2,
    ).rule_refs == ("DELIVERY_TOO_NEAR",)
