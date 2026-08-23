"""Property checks for point-in-time contract rule resolution."""

from datetime import UTC, date, datetime, time

from hypothesis import given, strategies as st

from futures_agent_os.reference_market_data import (
    ContractFee,
    ContractRuleRegistry,
    ContractRuleResolver,
    ContractRuleVersion,
    DeliveryRestrictions,
    Exchange,
    FeeBasis,
    FeeSchedule,
    Instrument,
    MarginRequirements,
    OffsetRules,
    PositionTradingLimits,
    PriceLimitRange,
    Rate,
    ReferenceProvenance,
    RuleEffectiveInterval,
    TradingSession,
    Variety,
    contract_rule_registry_content_sha256,
)
from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    Money,
    Price,
    Quantity,
    ReasonCode,
    RecordedAt,
    TradingDate,
)


def fixture_rule(*, version: int = 1, effective: RuleEffectiveInterval | None = None) -> ContractRuleVersion:
    contract = Instrument(Variety(Exchange.SHFE, "AG", "synthetic silver"), "2606")
    recorded_at = RecordedAt(datetime(2026, 8, 23, tzinfo=UTC))
    return ContractRuleVersion(
        EntityId.new("contract_rule"),
        contract,
        effective or RuleEffectiveInterval(TradingDate(date(2026, 8, 1)), TradingDate(date(2026, 8, 31))),
        version,
        ReferenceProvenance("test://synthetic", recorded_at, recorded_at, "v1"),
        Quantity("15", "tonne/lot", 0),
        Price("1.0", "CNY", "CNY/tonne", 1),
        Quantity("1", "lot", 0),
        MarginRequirements(Rate("0.12", 2), Rate("0.10", 2)),
        FeeSchedule(
            ContractFee(FeeBasis.PER_LOT, per_lot=Money("1.00", "CNY", 2)),
            ContractFee(FeeBasis.PER_LOT, per_lot=Money("1.00", "CNY", 2)),
            ContractFee(FeeBasis.PER_LOT, per_lot=Money("2.00", "CNY", 2)),
        ),
        PriceLimitRange(Price("5000.0", "CNY", "CNY/tonne", 1), Price("7000.0", "CNY", "CNY/tonne", 1)),
        (TradingSession("DAY", time(9), time(15)),),
        TradingDate(date(2026, 8, 30)),
        DeliveryRestrictions(TradingDate(date(2026, 8, 25)), TradingDate(date(2026, 8, 27))),
        PositionTradingLimits(Quantity("100", "lot", 0), Quantity("50", "lot", 0), Quantity("100", "lot", 0)),
        OffsetRules(True, True, True),
    )


def registry(*rules: ContractRuleVersion) -> ContractRuleRegistry:
    typed_rules = tuple(rules)
    return ContractRuleRegistry(
        EntityId.new("contract_rule_registry"),
        1,
        typed_rules,
        contract_rule_registry_content_sha256(typed_rules),
    )


@given(day=st.integers(min_value=1, max_value=30))
def test_one_rule_is_resolved_for_every_trading_date_inside_its_half_open_interval(day: int) -> None:
    fixture = fixture_rule(
        effective=RuleEffectiveInterval(TradingDate(date(2026, 8, 1)), TradingDate(date(2026, 8, 31)))
    )
    outcome = ContractRuleResolver(registry(fixture)).resolve(
        fixture.instrument, TradingDate(date(2026, 8, day)), RecordedAt(datetime(2026, 8, 23, tzinfo=UTC))
    )
    assert not isinstance(outcome, Failure)
    assert outcome.rule == fixture


@given(day=st.integers(min_value=1, max_value=30))
def test_any_two_overlapping_versions_fail_closed_instead_of_selecting_latest(day: int) -> None:
    first = fixture_rule()
    second = fixture_rule(version=2)
    outcome = ContractRuleResolver(registry(first, second)).resolve(
        first.instrument, TradingDate(date(2026, 8, day)), RecordedAt(datetime(2026, 8, 23, tzinfo=UTC))
    )
    assert outcome == Failure(
        ReasonCode.RULE_CONFLICT, "multiple visible contract rules apply to instrument and trading_date"
    )
