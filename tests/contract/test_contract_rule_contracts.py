"""Contracts for immutable, point-in-time futures contract rules."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from futures_agent_os.reference_market_data import (
    ContractFee,
    ContractRuleRegistry,
    ContractRuleResolver,
    ContractRuleVersion,
    DeliveryRestrictions,
    FeeBasis,
    FeeSchedule,
    MarginRequirements,
    OffsetRules,
    PositionTradingLimits,
    PriceLimitRange,
    Rate,
    ReferenceProvenance,
    RuleEffectiveInterval,
    RuleSetRef,
    TradingSession,
    Variety,
    contract_rule_content_sha256,
    contract_rule_registry_content_sha256,
)
from futures_agent_os.reference_market_data import Exchange, Instrument
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


def trading_day(day: int) -> TradingDate:
    return TradingDate(date(2026, 8, day))


def observed(hour: int) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 23, hour, tzinfo=UTC))


def provenance(acquired_at: RecordedAt | None = None) -> ReferenceProvenance:
    acquired = acquired_at or observed(0)
    return ReferenceProvenance("test://synthetic-contract-rule", acquired, observed(0), "notice-v1")


def instrument() -> Instrument:
    return Instrument(Variety(Exchange.SHFE, "AG", "synthetic silver"), "2606")


def rule(
    *,
    target: Instrument | None = None,
    effective: RuleEffectiveInterval | None = None,
    acquired_at: RecordedAt | None = None,
    version: int = 1,
) -> ContractRuleVersion:
    return ContractRuleVersion(
        rule_id=EntityId.new("contract_rule"),
        instrument=target or instrument(),
        effective=effective or RuleEffectiveInterval(trading_day(1), trading_day(31)),
        version=version,
        provenance=provenance(acquired_at),
        multiplier=Quantity("15", "tonne/lot", 0),
        tick_size=Price("1.0", "CNY", "CNY/tonne", 1),
        minimum_order_quantity=Quantity("1", "lot", 0),
        margin=MarginRequirements(Rate("0.12", 2), Rate("0.10", 2)),
        fees=FeeSchedule(
            open_fee=ContractFee(FeeBasis.PER_LOT, per_lot=Money("1.50", "CNY", 2)),
            close_fee=ContractFee(FeeBasis.PER_LOT, per_lot=Money("1.50", "CNY", 2)),
            close_today_fee=ContractFee(FeeBasis.PER_LOT, per_lot=Money("3.00", "CNY", 2)),
        ),
        price_limits=PriceLimitRange(
            lower_limit=Price("5000.0", "CNY", "CNY/tonne", 1),
            upper_limit=Price("7000.0", "CNY", "CNY/tonne", 1),
        ),
        sessions=(
            TradingSession("DAY", time(9), time(15)),
            TradingSession("NIGHT", time(21), time(2)),
        ),
        last_trading_date=trading_day(30),
        delivery_restrictions=DeliveryRestrictions(trading_day(25), trading_day(27)),
        limits=PositionTradingLimits(
            max_open_position=Quantity("100", "lot", 0),
            max_daily_open_quantity=Quantity("50", "lot", 0),
            max_daily_close_quantity=Quantity("100", "lot", 0),
        ),
        offset_rules=OffsetRules(open_allowed=True, close_allowed=True, close_today_allowed=True),
    )


def registry(*rules: ContractRuleVersion) -> ContractRuleRegistry:
    return ContractRuleRegistry(
        registry_id=EntityId.new("contract_rule_registry"),
        release_version=1,
        rules=rules,
        expected_content_sha256=contract_rule_registry_content_sha256(rules),
    )


def test_exactly_one_visible_rule_resolves_with_all_required_truth_and_evidence() -> None:
    fixture = rule()
    rule_registry = registry(fixture)
    resolver = ContractRuleResolver(rule_registry)

    outcome = resolver.resolve(fixture.instrument, trading_day(20), observed(1))

    assert not isinstance(outcome, Failure)
    assert outcome.rule == fixture
    assert outcome.provenance == fixture.provenance
    assert outcome.rule_content_sha256 == contract_rule_content_sha256(fixture)
    assert outcome.registry_id == rule_registry.registry_id
    assert outcome.registry_release_version == rule_registry.release_version
    assert outcome.registry_content_sha256 == rule_registry.expected_content_sha256
    assert outcome.rule_set_ref == RuleSetRef(
        rule_registry.registry_id,
        rule_registry.release_version,
        rule_registry.expected_content_sha256,
        fixture.rule_id,
        fixture.version,
        contract_rule_content_sha256(fixture),
    )
    assert outcome.trading_date == trading_day(20)
    assert outcome.as_of == observed(1)
    assert outcome.rule.multiplier.amount == Decimal("15")
    assert outcome.rule.tick_size.amount == Decimal("1.0")
    assert outcome.rule.margin.initial_ratio.value == Decimal("0.12")
    assert outcome.rule.fees.close_today_fee.per_lot == Money("3.00", "CNY", 2)
    assert outcome.rule.sessions[1].crosses_midnight is True
    assert outcome.rule.offset_rules.close_today_allowed is True


def test_missing_conflicting_expired_and_not_yet_visible_rules_fail_closed_with_stable_codes() -> None:
    fixture = rule()
    resolver = ContractRuleResolver(registry(fixture))
    other = Instrument(Variety(Exchange.DCE, "I", "synthetic iron ore"), "2609")

    assert resolver.resolve(other, trading_day(20), observed(1)) == Failure(
        ReasonCode.RULE_MISSING, "no contract rule applies to instrument and trading_date"
    )
    assert resolver.resolve(fixture.instrument, trading_day(31), observed(1)) == Failure(
        ReasonCode.RULE_MISSING, "no contract rule applies to instrument and trading_date"
    )

    future = rule(acquired_at=observed(2))
    assert ContractRuleResolver(registry(future)).resolve(future.instrument, trading_day(20), observed(1)) == Failure(
        ReasonCode.REFERENCE_NOT_YET_VISIBLE, "contract rule was not acquired at as_of"
    )

    conflicting = rule(version=2)
    assert ContractRuleResolver(registry(fixture, conflicting)).resolve(
        fixture.instrument, trading_day(20), observed(1)
    ) == Failure(ReasonCode.RULE_CONFLICT, "multiple visible contract rules apply to instrument and trading_date")


def test_rules_are_effective_by_trading_date_not_natural_date_and_boundary_is_half_open() -> None:
    first = rule(effective=RuleEffectiveInterval(trading_day(1), trading_day(15)), version=1)
    second = rule(effective=RuleEffectiveInterval(trading_day(15), trading_day(31)), version=2)
    resolver = ContractRuleResolver(registry(first, second))

    before = resolver.resolve(first.instrument, trading_day(14), observed(1))
    boundary = resolver.resolve(first.instrument, trading_day(15), observed(1))
    assert not isinstance(before, Failure) and before.rule == first
    assert not isinstance(boundary, Failure) and boundary.rule == second
    with pytest.raises(TypeError, match="TradingDate"):
        resolver.resolve(first.instrument, date(2026, 8, 15), observed(1))  # type: ignore[arg-type]


def test_instrument_scope_has_no_variety_or_exchange_fallback_and_never_merges_rule_fields() -> None:
    ag2606 = instrument()
    ag2607 = Instrument(ag2606.variety, "2607")
    first = rule(target=ag2606)
    partial_looking_second = replace(
        rule(target=ag2606, version=2),
        fees=FeeSchedule(
            ContractFee(FeeBasis.PER_LOT, per_lot=Money("9.00", "CNY", 2)),
            ContractFee(FeeBasis.PER_LOT, per_lot=Money("9.00", "CNY", 2)),
            ContractFee(FeeBasis.PER_LOT, per_lot=Money("18.00", "CNY", 2)),
        ),
    )
    resolver = ContractRuleResolver(registry(first, partial_looking_second))

    assert resolver.resolve(ag2607, trading_day(20), observed(1)) == Failure(
        ReasonCode.RULE_MISSING, "no contract rule applies to instrument and trading_date"
    )
    assert resolver.resolve(ag2606, trading_day(20), observed(1)) == Failure(
        ReasonCode.RULE_CONFLICT, "multiple visible contract rules apply to instrument and trading_date"
    )


def test_rule_values_are_exact_typed_complete_and_internally_coherent() -> None:
    fixture = rule()
    assert tuple(field.name for field in fields(PositionTradingLimits)) == (
        "max_open_position",
        "max_daily_open_quantity",
        "max_daily_close_quantity",
    )
    assert fixture.fees.open_fee.basis is FeeBasis.PER_LOT
    assert fixture.price_limits.lower_limit.amount < fixture.price_limits.upper_limit.amount
    assert fixture.minimum_order_quantity.unit == "lot"
    assert fixture.multiplier.unit == "tonne/lot"
    assert fixture.tick_size.unit == "CNY/tonne"
    assert fixture.price_limits.lower_limit.unit == "CNY/tonne"

    with pytest.raises(TypeError, match="binary float"):
        Rate(0.12, 2)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="maintenance"):
        MarginRequirements(Rate("0.10", 2), Rate("0.12", 2))
    with pytest.raises(ValueError, match="exactly one"):
        ContractFee(FeeBasis.PER_LOT, per_lot=Money("1.00", "CNY", 2), notional_rate=Rate("0.001", 3))
    with pytest.raises(ValueError, match="currency and unit"):
        PriceLimitRange(Price("1.0", "CNY", "CNY/tonne", 1), Price("2.0", "USD", "USD/tonne", 1))
    with pytest.raises(ValueError, match="canonical <underlying>/lot"):
        replace(fixture, multiplier=Quantity("15", "banana", 0))
    with pytest.raises(ValueError, match="canonical <underlying>/lot"):
        replace(fixture, multiplier=Quantity("15", "tonne//lot", 0))
    with pytest.raises(ValueError, match="canonical CNY/kg"):
        replace(fixture, multiplier=Quantity("15", "kg/lot", 0))
    with pytest.raises(ValueError, match="canonical CNY/tonne"):
        replace(fixture, tick_size=Price("1.0", "CNY", "CNY/kg", 1))
    with pytest.raises(ValueError, match="canonical CNY/tonne"):
        replace(
            fixture,
            price_limits=PriceLimitRange(Price("5000.0", "CNY", "CNY/kg", 1), Price("7000.0", "CNY", "CNY/kg", 1)),
        )
    with pytest.raises(ValueError, match="cannot be represented"):
        Rate("1E+999999999", 0)
    with pytest.raises(ValueError, match="last_trading_date"):
        replace(fixture, last_trading_date=TradingDate(date(2026, 7, 31)))
    with pytest.raises(ValueError, match="delivery restriction"):
        replace(fixture, delivery_restrictions=DeliveryRestrictions(trading_day(27), trading_day(25)))
    with pytest.raises(ValueError, match="unique"):
        replace(fixture, sessions=(fixture.sessions[0], fixture.sessions[0]))


def test_rule_snapshot_is_immutable_order_independent_and_concurrent_reads_are_identical() -> None:
    first = rule(effective=RuleEffectiveInterval(trading_day(1), trading_day(15)), version=1)
    second = rule(effective=RuleEffectiveInterval(trading_day(15), trading_day(31)), version=2)
    resolver = ContractRuleResolver(registry(first, second))
    assert contract_rule_content_sha256(first) == contract_rule_content_sha256(replace(first, rule_id=first.rule_id))
    assert contract_rule_registry_content_sha256((first, second)) == contract_rule_registry_content_sha256(
        (second, first)
    )

    with pytest.raises(FrozenInstanceError):
        first.version = 3  # type: ignore[misc]
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(
            executor.map(lambda _: resolver.resolve(first.instrument, trading_day(20), observed(1)), range(32))
        )
    assert all(outcome == outcomes[0] for outcome in outcomes)
    assert not isinstance(outcomes[0], Failure)


@pytest.mark.parametrize("invalid", ("2026-08-23", None, 1))
def test_rule_resolver_requires_typed_point_in_time_inputs(invalid: object) -> None:
    fixture = rule()
    resolver = ContractRuleResolver(registry(fixture))
    with pytest.raises(TypeError, match="RecordedAt"):
        resolver.resolve(fixture.instrument, trading_day(2), invalid)  # type: ignore[arg-type]
