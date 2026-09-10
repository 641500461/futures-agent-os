"""Deterministic multi-account and multi-strategy exposure aggregation."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Exposure:
    account: str
    strategy: str
    instrument: str
    notional: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not all(
            isinstance(x, str) and x.strip() for x in (self.account, self.strategy, self.instrument, self.currency)
        ):
            raise ValueError("exposure identifiers are required")
        if not isinstance(self.notional, Decimal) or not self.notional.is_finite():
            raise ValueError("notional must be finite")


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    by_account: tuple[tuple[str, Decimal], ...]
    by_strategy: tuple[tuple[str, Decimal], ...]
    by_instrument: tuple[tuple[str, Decimal], ...]
    total: Decimal


def aggregate(
    exposures: tuple[Exposure, ...] | list[Exposure], *, concentration_limit: Decimal | None = None
) -> ExposureSummary:
    maps: list[dict[str, Decimal]] = [{}, {}, {}]
    for item in exposures:
        for mapping, key in zip(maps, (item.account, item.strategy, item.instrument)):
            mapping[key] = mapping.get(key, Decimal("0")) + item.notional
    total = sum((x.notional for x in exposures), Decimal("0"))
    if concentration_limit is not None:
        if not concentration_limit.is_finite() or concentration_limit <= 0:
            raise ValueError("concentration_limit must be positive")
        for mapping in maps:
            if any(abs(value) > concentration_limit for value in mapping.values()):
                raise ValueError("CONCENTRATION_LIMIT")
    return ExposureSummary(
        tuple(sorted(maps[0].items())), tuple(sorted(maps[1].items())), tuple(sorted(maps[2].items())), total
    )
