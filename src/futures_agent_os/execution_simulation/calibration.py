"""Deterministic backtest/paper fill calibration."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class FillCalibration:
    sample_count: int
    mean_error: Decimal
    max_error: Decimal
    error_low: Decimal
    error_high: Decimal
    applicable_scope: str
    prohibited_extrapolation: str


def calibrate(
    backtest: tuple[Decimal, ...], paper: tuple[Decimal, ...], *, scope: str, prohibited_extrapolation: str
) -> FillCalibration:
    if not backtest or len(backtest) != len(paper) or not scope.strip() or not prohibited_extrapolation.strip():
        raise ValueError("calibration requires paired samples and scope")
    errors = tuple(actual - expected for expected, actual in zip(backtest, paper))
    if any(not value.is_finite() for value in errors):
        raise ValueError("calibration values must be finite")
    absolute = tuple(abs(value) for value in errors)
    return FillCalibration(
        len(errors),
        sum(errors, Decimal("0")) / len(errors),
        max(absolute),
        min(errors),
        max(errors),
        scope,
        prohibited_extrapolation,
    )
