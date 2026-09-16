"""Deterministic V5 multi-account portfolio exposure and capital aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} is required")


def _finite(value: Decimal, label: str, *, non_negative: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or (non_negative and value < 0):
        raise ValueError(f"{label} must be {'non-negative ' if non_negative else ''}finite Decimal")


@dataclass(frozen=True, slots=True)
class Exposure:
    account: str
    strategy: str
    instrument: str
    notional: Decimal
    currency: str = "USD"
    sector: str = "UNCLASSIFIED"
    maturity_bucket: str = "UNSPECIFIED"
    correlation_cluster: str = "UNCLUSTERED"
    spread_id: str | None = None
    rollover_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for value, label in (
            (self.account, "account"),
            (self.strategy, "strategy"),
            (self.instrument, "instrument"),
            (self.currency, "currency"),
            (self.sector, "sector"),
            (self.maturity_bucket, "maturity_bucket"),
            (self.correlation_cluster, "correlation_cluster"),
        ):
            _text(value, label)
        if self.spread_id is not None:
            _text(self.spread_id, "spread_id")
        _finite(self.notional, "notional")
        _finite(self.rollover_cost, "rollover_cost", non_negative=True)
        if self.notional == 0 and self.rollover_cost != 0:
            raise ValueError("zero exposure cannot carry rollover cost")


@dataclass(frozen=True, slots=True)
class SpreadSummary:
    spread_id: str
    legs: int
    maturities: tuple[str, ...]
    gross: Decimal
    net: Decimal
    balanced_directions: bool


@dataclass(frozen=True, slots=True)
class PortfolioLimits:
    gross: Decimal | None = None
    absolute_net: Decimal | None = None
    account_gross: Decimal | None = None
    strategy_gross: Decimal | None = None
    sector_gross: Decimal | None = None
    maturity_gross: Decimal | None = None
    cluster_gross: Decimal | None = None
    cluster_concentration: Decimal | None = None
    rollover_cost: Decimal | None = None

    def __post_init__(self) -> None:
        for value in (
            self.gross,
            self.absolute_net,
            self.account_gross,
            self.strategy_gross,
            self.sector_gross,
            self.maturity_gross,
            self.cluster_gross,
            self.rollover_cost,
        ):
            if value is not None:
                _finite(value, "portfolio limit", non_negative=True)
                if value == 0:
                    raise ValueError("portfolio limits must be positive")
        if self.cluster_concentration is not None:
            _finite(self.cluster_concentration, "cluster_concentration", non_negative=True)
            if not Decimal("0") < self.cluster_concentration <= Decimal("1"):
                raise ValueError("cluster_concentration must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    by_account: tuple[tuple[str, Decimal], ...]
    by_strategy: tuple[tuple[str, Decimal], ...]
    by_instrument: tuple[tuple[str, Decimal], ...]
    total: Decimal
    gross: Decimal = Decimal("0")
    gross_by_account: tuple[tuple[str, Decimal], ...] = ()
    gross_by_strategy: tuple[tuple[str, Decimal], ...] = ()
    gross_by_sector: tuple[tuple[str, Decimal], ...] = ()
    gross_by_maturity: tuple[tuple[str, Decimal], ...] = ()
    gross_by_correlation_cluster: tuple[tuple[str, Decimal], ...] = ()
    net_by_sector: tuple[tuple[str, Decimal], ...] = ()
    net_by_maturity: tuple[tuple[str, Decimal], ...] = ()
    net_by_correlation_cluster: tuple[tuple[str, Decimal], ...] = ()
    long_gross: Decimal = Decimal("0")
    short_gross: Decimal = Decimal("0")
    spreads: tuple[SpreadSummary, ...] = ()
    rollover_cost_by_account: tuple[tuple[str, Decimal], ...] = ()
    total_rollover_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if sum((value for _, value in self.by_account), Decimal("0")) != self.total:
            raise ValueError("account net exposure does not reconcile")
        if sum((value for _, value in self.by_strategy), Decimal("0")) != self.total:
            raise ValueError("strategy net exposure does not reconcile")
        if self.long_gross - self.short_gross != self.total or self.long_gross + self.short_gross != self.gross:
            raise ValueError("directional gross/net exposure does not reconcile")
        if sum((value for _, value in self.rollover_cost_by_account), Decimal("0")) != self.total_rollover_cost:
            raise ValueError("rollover costs do not reconcile")


def _add(mapping: dict[str, Decimal], key: str, value: Decimal) -> None:
    mapping[key] = mapping.get(key, Decimal("0")) + value


def _items(mapping: dict[str, Decimal]) -> tuple[tuple[str, Decimal], ...]:
    return tuple(sorted(mapping.items()))


def aggregate(
    exposures: tuple[Exposure, ...] | list[Exposure],
    *,
    concentration_limit: Decimal | None = None,
    limits: PortfolioLimits | None = None,
) -> ExposureSummary:
    """Aggregate all dimensions and enforce limits on gross sources, not netted disguises."""

    frozen = tuple(exposures)
    if any(not isinstance(item, Exposure) for item in frozen):
        raise TypeError("exposures must contain Exposure values")
    if limits is not None and not isinstance(limits, PortfolioLimits):
        raise TypeError("limits must be PortfolioLimits")
    net_maps: dict[str, dict[str, Decimal]] = {
        key: {} for key in ("account", "strategy", "instrument", "sector", "maturity", "cluster")
    }
    gross_maps: dict[str, dict[str, Decimal]] = {
        key: {} for key in ("account", "strategy", "sector", "maturity", "cluster")
    }
    rollover_by_account: dict[str, Decimal] = {}
    spread_legs: dict[str, list[Exposure]] = {}
    long_gross = Decimal("0")
    short_gross = Decimal("0")
    for item in frozen:
        dimensions = {
            "account": item.account,
            "strategy": item.strategy,
            "instrument": item.instrument,
            "sector": item.sector,
            "maturity": item.maturity_bucket,
            "cluster": item.correlation_cluster,
        }
        for dimension, key in dimensions.items():
            _add(net_maps[dimension], key, item.notional)
            if dimension in gross_maps:
                _add(gross_maps[dimension], key, abs(item.notional))
        _add(rollover_by_account, item.account, item.rollover_cost)
        if item.spread_id is not None:
            spread_legs.setdefault(item.spread_id, []).append(item)
        if item.notional > 0:
            long_gross += item.notional
        else:
            short_gross += abs(item.notional)
    total = sum((item.notional for item in frozen), Decimal("0"))
    gross = long_gross + short_gross
    spreads = tuple(
        SpreadSummary(
            spread_id,
            len(legs),
            tuple(sorted({leg.maturity_bucket for leg in legs})),
            sum((abs(leg.notional) for leg in legs), Decimal("0")),
            sum((leg.notional for leg in legs), Decimal("0")),
            any(leg.notional > 0 for leg in legs) and any(leg.notional < 0 for leg in legs),
        )
        for spread_id, legs in sorted(spread_legs.items())
    )
    total_rollover_cost = sum((item.rollover_cost for item in frozen), Decimal("0"))
    summary = ExposureSummary(
        _items(net_maps["account"]),
        _items(net_maps["strategy"]),
        _items(net_maps["instrument"]),
        total,
        gross,
        _items(gross_maps["account"]),
        _items(gross_maps["strategy"]),
        _items(gross_maps["sector"]),
        _items(gross_maps["maturity"]),
        _items(gross_maps["cluster"]),
        _items(net_maps["sector"]),
        _items(net_maps["maturity"]),
        _items(net_maps["cluster"]),
        long_gross,
        short_gross,
        spreads,
        _items(rollover_by_account),
        total_rollover_cost,
    )
    if concentration_limit is not None:
        _finite(concentration_limit, "concentration_limit", non_negative=True)
        if concentration_limit == 0:
            raise ValueError("concentration_limit must be positive")
        if any(abs(value) > concentration_limit for mapping in net_maps.values() for value in mapping.values()):
            raise ValueError("CONCENTRATION_LIMIT")
    if limits is not None:
        _enforce_limits(summary, limits)
    return summary


def _exceeds(items: tuple[tuple[str, Decimal], ...], limit: Decimal | None) -> bool:
    return limit is not None and any(value > limit for _, value in items)


def _enforce_limits(summary: ExposureSummary, limits: PortfolioLimits) -> None:
    checks = (
        (limits.gross is not None and summary.gross > limits.gross, "PORTFOLIO_GROSS_LIMIT"),
        (limits.absolute_net is not None and abs(summary.total) > limits.absolute_net, "PORTFOLIO_NET_LIMIT"),
        (_exceeds(summary.gross_by_account, limits.account_gross), "ACCOUNT_GROSS_LIMIT"),
        (_exceeds(summary.gross_by_strategy, limits.strategy_gross), "STRATEGY_GROSS_LIMIT"),
        (_exceeds(summary.gross_by_sector, limits.sector_gross), "SECTOR_GROSS_LIMIT"),
        (_exceeds(summary.gross_by_maturity, limits.maturity_gross), "MATURITY_GROSS_LIMIT"),
        (_exceeds(summary.gross_by_correlation_cluster, limits.cluster_gross), "CORRELATION_CLUSTER_LIMIT"),
        (
            limits.cluster_concentration is not None
            and summary.gross > 0
            and any(
                value / summary.gross > limits.cluster_concentration
                for _, value in summary.gross_by_correlation_cluster
            ),
            "CORRELATION_CONCENTRATION_LIMIT",
        ),
        (
            limits.rollover_cost is not None and summary.total_rollover_cost > limits.rollover_cost,
            "ROLLOVER_COST_LIMIT",
        ),
    )
    for failed, reason in checks:
        if failed:
            raise ValueError(reason)


@dataclass(frozen=True, slots=True)
class CapitalAllocation:
    account: str
    strategy: str
    capital: Decimal
    risk_budget: Decimal

    def __post_init__(self) -> None:
        _text(self.account, "account")
        _text(self.strategy, "strategy")
        _finite(self.capital, "capital", non_negative=True)
        _finite(self.risk_budget, "risk_budget", non_negative=True)
        if self.risk_budget > self.capital:
            raise ValueError("risk budget cannot exceed allocated capital")


@dataclass(frozen=True, slots=True)
class CapitalAllocationSummary:
    capital_by_account: tuple[tuple[str, Decimal], ...]
    capital_by_strategy: tuple[tuple[str, Decimal], ...]
    risk_by_account: tuple[tuple[str, Decimal], ...]
    risk_by_strategy: tuple[tuple[str, Decimal], ...]
    total_capital: Decimal
    total_risk_budget: Decimal


def aggregate_capital(
    allocations: tuple[CapitalAllocation, ...] | list[CapitalAllocation],
    *,
    account_capital: dict[str, Decimal],
    portfolio_capital: Decimal,
) -> CapitalAllocationSummary:
    frozen = tuple(allocations)
    if any(not isinstance(item, CapitalAllocation) for item in frozen):
        raise TypeError("allocations must contain CapitalAllocation values")
    _finite(portfolio_capital, "portfolio_capital", non_negative=True)
    capital_account: dict[str, Decimal] = {}
    capital_strategy: dict[str, Decimal] = {}
    risk_account: dict[str, Decimal] = {}
    risk_strategy: dict[str, Decimal] = {}
    for item in frozen:
        if item.account not in account_capital:
            raise ValueError("ACCOUNT_CAPITAL_UNKNOWN")
        _finite(account_capital[item.account], "account capital", non_negative=True)
        _add(capital_account, item.account, item.capital)
        _add(capital_strategy, item.strategy, item.capital)
        _add(risk_account, item.account, item.risk_budget)
        _add(risk_strategy, item.strategy, item.risk_budget)
    if any(value > account_capital[account] for account, value in capital_account.items()):
        raise ValueError("ACCOUNT_CAPITAL_OVERALLOCATED")
    total_capital = sum(capital_account.values(), Decimal("0"))
    if total_capital > portfolio_capital:
        raise ValueError("PORTFOLIO_CAPITAL_OVERALLOCATED")
    return CapitalAllocationSummary(
        _items(capital_account),
        _items(capital_strategy),
        _items(risk_account),
        _items(risk_strategy),
        total_capital,
        sum(risk_account.values(), Decimal("0")),
    )


__all__ = [
    "CapitalAllocation",
    "CapitalAllocationSummary",
    "Exposure",
    "ExposureSummary",
    "PortfolioLimits",
    "SpreadSummary",
    "aggregate",
    "aggregate_capital",
]
