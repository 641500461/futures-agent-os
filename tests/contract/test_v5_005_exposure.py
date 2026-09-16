from decimal import Decimal

import pytest

from futures_agent_os.portfolio_risk.exposure_aggregation import (
    CapitalAllocation,
    Exposure,
    PortfolioLimits,
    aggregate,
    aggregate_capital,
)


def _exposure(
    account: str,
    strategy: str,
    instrument: str,
    notional: str,
    *,
    sector: str = "METALS",
    maturity: str = "FRONT",
    cluster: str = "CHINA-CYCLICAL",
    spread: str | None = None,
    roll_cost: str = "0",
) -> Exposure:
    return Exposure(
        account,
        strategy,
        instrument,
        Decimal(notional),
        "CNY",
        sector,
        maturity,
        cluster,
        spread,
        Decimal(roll_cost),
    )


def test_multi_account_strategy_and_dimension_aggregation_reconciles() -> None:
    summary = aggregate(
        (
            _exposure("a1", "trend", "SHFE:AG2610", "100"),
            _exposure("a1", "carry", "SHFE:AG2612", "-40", maturity="NEXT"),
            _exposure("a2", "trend", "DCE:I2701", "-30", sector="FERROUS", cluster="CHINA-GROWTH"),
        )
    )
    assert summary.total == Decimal("30") and summary.gross == Decimal("170")
    assert summary.by_account == (("a1", Decimal("60")), ("a2", Decimal("-30")))
    assert summary.by_strategy == (("carry", Decimal("-40")), ("trend", Decimal("70")))
    assert summary.long_gross == Decimal("100") and summary.short_gross == Decimal("70")
    assert sum((value for _, value in summary.by_account), Decimal("0")) == summary.total


def test_cross_maturity_spread_and_rollover_cost_are_explicit() -> None:
    summary = aggregate(
        (
            _exposure("a1", "calendar", "SHFE:AG2610", "50", spread="ag-roll", roll_cost="2"),
            _exposure("a1", "calendar", "SHFE:AG2612", "-45", maturity="NEXT", spread="ag-roll", roll_cost="3"),
        )
    )
    spread = summary.spreads[0]
    assert spread.spread_id == "ag-roll" and spread.legs == 2
    assert spread.maturities == ("FRONT", "NEXT") and spread.balanced_directions
    assert spread.gross == Decimal("95") and spread.net == Decimal("5")
    assert summary.total_rollover_cost == Decimal("5")
    assert summary.rollover_cost_by_account == (("a1", Decimal("5")),)


@pytest.mark.parametrize(
    ("limits", "reason"),
    (
        (PortfolioLimits(gross=Decimal("99")), "PORTFOLIO_GROSS_LIMIT"),
        (PortfolioLimits(absolute_net=Decimal("9")), "PORTFOLIO_NET_LIMIT"),
        (PortfolioLimits(account_gross=Decimal("99")), "ACCOUNT_GROSS_LIMIT"),
        (PortfolioLimits(strategy_gross=Decimal("99")), "STRATEGY_GROSS_LIMIT"),
        (PortfolioLimits(sector_gross=Decimal("99")), "SECTOR_GROSS_LIMIT"),
        (PortfolioLimits(maturity_gross=Decimal("99")), "MATURITY_GROSS_LIMIT"),
        (PortfolioLimits(cluster_gross=Decimal("99")), "CORRELATION_CLUSTER_LIMIT"),
        (PortfolioLimits(cluster_concentration=Decimal("0.9")), "CORRELATION_CONCENTRATION_LIMIT"),
        (PortfolioLimits(rollover_cost=Decimal("1")), "ROLLOVER_COST_LIMIT"),
    ),
)
def test_every_portfolio_boundary_fails_closed(limits: PortfolioLimits, reason: str) -> None:
    exposures = (
        _exposure("a1", "s1", "SHFE:AG", "60", roll_cost="1"),
        _exposure("a1", "s1", "SHFE:AU", "-50", roll_cost="1"),
    )
    with pytest.raises(ValueError, match=reason):
        aggregate(exposures, limits=limits)


def test_legacy_concentration_limit_uses_all_net_dimensions() -> None:
    with pytest.raises(ValueError, match="CONCENTRATION_LIMIT"):
        aggregate((_exposure("a", "s", "x", "3"),), concentration_limit=Decimal("2"))


def test_capital_allocation_rolls_up_and_cannot_overallocate_account_or_portfolio() -> None:
    allocations = (
        CapitalAllocation("a1", "trend", Decimal("60"), Decimal("10")),
        CapitalAllocation("a1", "carry", Decimal("40"), Decimal("8")),
        CapitalAllocation("a2", "trend", Decimal("50"), Decimal("9")),
    )
    summary = aggregate_capital(
        allocations, account_capital={"a1": Decimal("100"), "a2": Decimal("60")}, portfolio_capital=Decimal("160")
    )
    assert summary.capital_by_account == (("a1", Decimal("100")), ("a2", Decimal("50")))
    assert summary.capital_by_strategy == (("carry", Decimal("40")), ("trend", Decimal("110")))
    assert summary.total_capital == Decimal("150") and summary.total_risk_budget == Decimal("27")
    with pytest.raises(ValueError, match="ACCOUNT_CAPITAL_OVERALLOCATED"):
        aggregate_capital(
            allocations, account_capital={"a1": Decimal("90"), "a2": Decimal("60")}, portfolio_capital=Decimal("160")
        )
    with pytest.raises(ValueError, match="PORTFOLIO_CAPITAL_OVERALLOCATED"):
        aggregate_capital(
            allocations,
            account_capital={"a1": Decimal("100"), "a2": Decimal("60")},
            portfolio_capital=Decimal("140"),
        )
