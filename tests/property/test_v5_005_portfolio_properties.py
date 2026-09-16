from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from futures_agent_os.portfolio_risk.exposure_aggregation import Exposure, PortfolioLimits, aggregate


def _exposure(index: int, value: int, *, cluster: str = "cluster", roll_cost: int = 0) -> Exposure:
    return Exposure(
        f"account-{index % 3}",
        f"strategy-{index % 4}",
        f"instrument-{index}",
        Decimal(value),
        sector=f"sector-{index % 2}",
        maturity_bucket=f"tenor-{index % 3}",
        correlation_cluster=cluster,
        rollover_cost=Decimal(roll_cost),
    )


@given(values=st.lists(st.integers(-1000, 1000), min_size=1, max_size=30))
def test_net_and_gross_reconcile_across_accounts_and_strategies(values: list[int]) -> None:
    summary = aggregate(tuple(_exposure(index, value) for index, value in enumerate(values)))
    expected_net = sum((Decimal(value) for value in values), Decimal("0"))
    expected_gross = sum((abs(Decimal(value)) for value in values), Decimal("0"))
    assert summary.total == expected_net and summary.gross == expected_gross
    assert sum((value for _, value in summary.by_account), Decimal("0")) == expected_net
    assert sum((value for _, value in summary.by_strategy), Decimal("0")) == expected_net
    assert summary.gross >= abs(summary.total)


@given(first=st.integers(1, 1000), second=st.integers(1, 1000))
def test_correlation_cluster_limit_uses_gross_even_when_net_is_small(first: int, second: int) -> None:
    exposures = (_exposure(0, first), _exposure(1, -second))
    gross = Decimal(first + second)
    with pytest.raises(ValueError, match="CORRELATION_CLUSTER_LIMIT"):
        aggregate(exposures, limits=PortfolioLimits(cluster_gross=gross - Decimal("1")))
    assert aggregate(exposures, limits=PortfolioLimits(cluster_gross=gross)).gross == gross


@given(costs=st.lists(st.integers(0, 100), min_size=1, max_size=20))
def test_rollover_costs_reconcile_and_limit_is_exact(costs: list[int]) -> None:
    exposures = tuple(_exposure(index, 1, roll_cost=cost) for index, cost in enumerate(costs))
    total = Decimal(sum(costs))
    summary = aggregate(exposures)
    assert summary.total_rollover_cost == total
    assert sum((value for _, value in summary.rollover_cost_by_account), Decimal("0")) == total
    if total > 0:
        with pytest.raises(ValueError, match="ROLLOVER_COST_LIMIT"):
            aggregate(exposures, limits=PortfolioLimits(rollover_cost=total - Decimal("0.5")))


@given(large=st.integers(1, 1000), small=st.integers(0, 1000))
def test_cluster_concentration_ratio_boundary(large: int, small: int) -> None:
    large, small = max(large, small), min(large, small)
    exposures = (
        _exposure(0, large, cluster="large"),
        _exposure(1, small, cluster="small"),
    )
    total = Decimal(large + small)
    ratio = Decimal(large) / total
    assert aggregate(exposures, limits=PortfolioLimits(cluster_concentration=ratio)).gross == total
    if ratio < 1:
        with pytest.raises(ValueError, match="CORRELATION_CONCENTRATION_LIMIT"):
            aggregate(exposures, limits=PortfolioLimits(cluster_concentration=ratio - Decimal("0.000001")))
