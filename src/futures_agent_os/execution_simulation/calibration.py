"""Deterministic replay/paper calibration across execution and PnL metrics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.shared_kernel import canonical_sha256


def _finite(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{label} must be finite Decimal")


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty canonical text")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


@dataclass(frozen=True, slots=True)
class FillCalibration:
    """Compatibility view for one scalar paired calibration."""

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
    if not backtest or len(backtest) != len(paper):
        raise ValueError("calibration requires paired samples and scope")
    _text(scope, "scope")
    _text(prohibited_extrapolation, "prohibited_extrapolation")
    errors = tuple(actual - expected for expected, actual in zip(backtest, paper))
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in (*backtest, *paper, *errors)):
        raise ValueError("calibration values must be finite Decimal")
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


class CalibrationMetric(StrEnum):
    FILL_QUANTITY = "FILL_QUANTITY"
    SLIPPAGE_BPS = "SLIPPAGE_BPS"
    PNL = "PNL"
    CAPACITY = "CAPACITY"


REQUIRED_METRICS = tuple(CalibrationMetric)


@dataclass(frozen=True, slots=True)
class MetricPair:
    metric: CalibrationMetric
    replay_value: Decimal
    paper_value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.metric, CalibrationMetric):
            raise TypeError("metric must be CalibrationMetric")
        _finite(self.replay_value, "replay value")
        _finite(self.paper_value, "paper value")
        if self.metric in {CalibrationMetric.FILL_QUANTITY, CalibrationMetric.CAPACITY} and (
            self.replay_value < 0 or self.paper_value < 0
        ):
            raise ValueError("fill and capacity values cannot be negative")


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    sample_id: str
    fill_model: str
    model_version: str
    applicable_scope: str
    replay_evidence_ref: str
    paper_evidence_ref: str
    metrics: tuple[MetricPair, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.sample_id, "sample_id"),
            (self.fill_model, "fill_model"),
            (self.model_version, "model_version"),
            (self.applicable_scope, "applicable_scope"),
            (self.replay_evidence_ref, "replay_evidence_ref"),
            (self.paper_evidence_ref, "paper_evidence_ref"),
        ):
            _text(value, label)
        if (
            not isinstance(self.metrics, tuple)
            or any(not isinstance(pair, MetricPair) for pair in self.metrics)
            or tuple(pair.metric for pair in self.metrics) != REQUIRED_METRICS
        ):
            raise ValueError("sample must contain all calibration metrics in canonical order")

    def payload(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "fill_model": self.fill_model,
            "model_version": self.model_version,
            "applicable_scope": self.applicable_scope,
            "replay_evidence_ref": self.replay_evidence_ref,
            "paper_evidence_ref": self.paper_evidence_ref,
            "metrics": tuple(
                {
                    "metric": pair.metric.value,
                    "replay": _decimal_text(pair.replay_value),
                    "paper": _decimal_text(pair.paper_value),
                }
                for pair in self.metrics
            ),
        }


@dataclass(frozen=True, slots=True)
class MetricCalibration:
    metric: CalibrationMetric
    mean_bias: Decimal
    mean_absolute_error: Decimal
    root_mean_square_error: Decimal
    error_low: Decimal
    error_high: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.metric, CalibrationMetric):
            raise TypeError("metric calibration requires CalibrationMetric")
        for value in (
            self.mean_bias,
            self.mean_absolute_error,
            self.root_mean_square_error,
            self.error_low,
            self.error_high,
        ):
            _finite(value, "calibration statistic")
        if self.mean_absolute_error < 0 or self.root_mean_square_error < 0 or self.error_low > self.error_high:
            raise ValueError("invalid calibration statistics")


@dataclass(frozen=True, slots=True)
class FillModelCalibration:
    fill_model: str
    model_version: str
    sample_count: int
    applicable_scope: str
    prohibited_extrapolation: tuple[str, ...]
    calibration_data_refs: tuple[str, ...]
    metrics: tuple[MetricCalibration, ...]
    dataset_digest: str
    calibration_digest: str

    def __post_init__(self) -> None:
        _text(self.fill_model, "fill_model")
        _text(self.model_version, "model_version")
        _text(self.applicable_scope, "applicable_scope")
        if self.sample_count < 1 or tuple(metric.metric for metric in self.metrics) != REQUIRED_METRICS:
            raise ValueError("calibration report requires samples and all metrics")
        if (
            not self.prohibited_extrapolation
            or len(set(self.prohibited_extrapolation)) != len(self.prohibited_extrapolation)
            or len(self.calibration_data_refs) != self.sample_count * 2
        ):
            raise ValueError("calibration requires data refs and prohibited extrapolation")
        for digest in (self.dataset_digest, self.calibration_digest):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("calibration digests must be lowercase SHA-256")


def _sqrt(value: Decimal) -> Decimal:
    return value.sqrt()


def calibrate_fill_model(
    samples: tuple[CalibrationSample, ...], *, prohibited_extrapolation: tuple[str, ...]
) -> FillModelCalibration:
    if not samples or any(not isinstance(sample, CalibrationSample) for sample in samples):
        raise ValueError("fill model calibration requires typed paired samples")
    first = samples[0]
    if any(
        (sample.fill_model, sample.model_version, sample.applicable_scope)
        != (first.fill_model, first.model_version, first.applicable_scope)
        for sample in samples
    ):
        raise ValueError("calibration samples must bind one model version and scope")
    if len({sample.sample_id for sample in samples}) != len(samples):
        raise ValueError("calibration sample IDs must be unique")
    if (
        not isinstance(prohibited_extrapolation, tuple)
        or not prohibited_extrapolation
        or any(not isinstance(item, str) or not item.strip() for item in prohibited_extrapolation)
    ):
        raise ValueError("prohibited extrapolation must be explicit")
    metric_reports: list[MetricCalibration] = []
    for index, metric in enumerate(REQUIRED_METRICS):
        errors = tuple(sample.metrics[index].paper_value - sample.metrics[index].replay_value for sample in samples)
        mean = sum(errors, Decimal("0")) / len(errors)
        mae = sum((abs(error) for error in errors), Decimal("0")) / len(errors)
        rmse = _sqrt(sum((error * error for error in errors), Decimal("0")) / len(errors))
        metric_reports.append(MetricCalibration(metric, mean, mae, rmse, min(errors), max(errors)))
    dataset_digest = canonical_sha256(cast(Any, tuple(sample.payload() for sample in samples)))
    refs = tuple(
        reference for sample in samples for reference in (sample.replay_evidence_ref, sample.paper_evidence_ref)
    )
    digest = canonical_sha256(
        cast(
            Any,
            {
                "fill_model": first.fill_model,
                "model_version": first.model_version,
                "scope": first.applicable_scope,
                "dataset": dataset_digest,
                "prohibited": prohibited_extrapolation,
                "metrics": tuple(
                    {
                        "metric": report.metric.value,
                        "mean_bias": _decimal_text(report.mean_bias),
                        "mae": _decimal_text(report.mean_absolute_error),
                        "rmse": _decimal_text(report.root_mean_square_error),
                        "low": _decimal_text(report.error_low),
                        "high": _decimal_text(report.error_high),
                    }
                    for report in metric_reports
                ),
            },
        )
    )
    return FillModelCalibration(
        first.fill_model,
        first.model_version,
        len(samples),
        first.applicable_scope,
        prohibited_extrapolation,
        refs,
        tuple(metric_reports),
        dataset_digest,
        digest,
    )


class FillModelCalibrationRegistry:
    def __init__(self) -> None:
        self._reports: dict[tuple[str, str, str], FillModelCalibration] = {}

    def register(self, report: FillModelCalibration) -> None:
        if not isinstance(report, FillModelCalibration):
            raise TypeError("registry requires FillModelCalibration")
        key = (report.fill_model, report.model_version, report.applicable_scope)
        existing = self._reports.get(key)
        if existing is not None and existing.calibration_digest != report.calibration_digest:
            raise ValueError("calibration key already has different evidence")
        self._reports[key] = report

    def require(self, fill_model: str, model_version: str, applicable_scope: str) -> FillModelCalibration:
        report = self._reports.get((fill_model, model_version, applicable_scope))
        if report is None:
            raise ValueError("FILL_MODEL_CALIBRATION_MISSING_OR_EXTRAPOLATED")
        return report

    def require_all(self, models: tuple[tuple[str, str, str], ...]) -> tuple[FillModelCalibration, ...]:
        if not models:
            raise ValueError("required FillModel set cannot be empty")
        return tuple(self.require(*model) for model in models)


__all__ = [
    "CalibrationMetric",
    "CalibrationSample",
    "FillCalibration",
    "FillModelCalibration",
    "FillModelCalibrationRegistry",
    "MetricCalibration",
    "MetricPair",
    "REQUIRED_METRICS",
    "calibrate",
    "calibrate_fill_model",
]
