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
