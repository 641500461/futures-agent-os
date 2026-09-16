from dataclasses import replace
from decimal import Decimal

import pytest

from futures_agent_os.execution_simulation.calibration import (
    CalibrationMetric,
    CalibrationSample,
    FillModelCalibrationRegistry,
    MetricPair,
    calibrate,
    calibrate_fill_model,
)


def _sample(index: int, *, scope: str = "SHFE:AG:liquid", version: str = "l4-v1") -> CalibrationSample:
    shift = Decimal(index)
    return CalibrationSample(
        f"sample-{index}",
        "ORDER_BOOK_QUEUE",
        version,
        scope,
        f"replay:{index}",
        f"paper:{index}",
        (
            MetricPair(CalibrationMetric.FILL_QUANTITY, Decimal("10"), Decimal("9") + shift),
            MetricPair(CalibrationMetric.SLIPPAGE_BPS, Decimal("2"), Decimal("3") + shift),
            MetricPair(CalibrationMetric.PNL, Decimal("100"), Decimal("95") + shift),
            MetricPair(CalibrationMetric.CAPACITY, Decimal("20"), Decimal("18") + shift),
        ),
    )


def test_compatibility_calibration_reports_error_interval_and_scope() -> None:
    result = calibrate(
        (Decimal("100"), Decimal("101")),
        (Decimal("100.5"), Decimal("100.5")),
        scope="ES:2026",
        prohibited_extrapolation="not for illiquid contracts",
    )
    assert result.sample_count == 2
    assert result.error_low == Decimal("-0.5") and result.error_high == Decimal("0.5")


def test_fill_model_report_covers_fill_slippage_pnl_and_capacity_bias() -> None:
    report = calibrate_fill_model(
        (_sample(0), _sample(1), _sample(2)),
        prohibited_extrapolation=("illiquid", "other-instruments", "other-regimes"),
    )
    assert report.sample_count == 3 and len(report.metrics) == 4
    assert [metric.metric for metric in report.metrics] == list(CalibrationMetric)
    assert report.metrics[0].error_low == Decimal("-1") and report.metrics[0].error_high == Decimal("1")
    assert report.metrics[1].mean_bias == Decimal("2")
    assert len(report.calibration_data_refs) == 6
    assert len(report.dataset_digest) == len(report.calibration_digest) == 64


def test_same_samples_produce_same_content_addressed_report() -> None:
    samples = (_sample(0), _sample(1))
    first = calibrate_fill_model(samples, prohibited_extrapolation=("outside-scope",))
    second = calibrate_fill_model(samples, prohibited_extrapolation=("outside-scope",))
    assert first == second and first.calibration_digest == second.calibration_digest


def test_registry_requires_exact_model_version_and_scope_for_every_fill_model() -> None:
    registry = FillModelCalibrationRegistry()
    l3 = calibrate_fill_model(
        (replace(_sample(0), fill_model="TICK_REPLAY", model_version="l3-v1"),),
        prohibited_extrapolation=("not-order-book",),
    )
    l4 = calibrate_fill_model((_sample(0),), prohibited_extrapolation=("not-illiquid",))
    registry.register(l3)
    registry.register(l4)
    assert registry.require_all(
        (("TICK_REPLAY", "l3-v1", "SHFE:AG:liquid"), ("ORDER_BOOK_QUEUE", "l4-v1", "SHFE:AG:liquid"))
    ) == (l3, l4)
    with pytest.raises(ValueError, match="MISSING_OR_EXTRAPOLATED"):
        registry.require("ORDER_BOOK_QUEUE", "l4-v1", "SHFE:AG:illiquid")
    with pytest.raises(ValueError, match="MISSING_OR_EXTRAPOLATED"):
        registry.require("ORDER_BOOK_QUEUE", "l4-v2", "SHFE:AG:liquid")


def test_incomplete_metrics_mixed_scope_duplicates_and_nonfinite_values_fail_closed() -> None:
    sample = _sample(0)
    with pytest.raises(ValueError, match="all calibration metrics"):
        replace(sample, metrics=sample.metrics[:-1])
    with pytest.raises(ValueError, match="one model version and scope"):
        calibrate_fill_model((sample, _sample(1, scope="DCE:I")), prohibited_extrapolation=("outside",))
    with pytest.raises(ValueError, match="unique"):
        calibrate_fill_model((sample, sample), prohibited_extrapolation=("outside",))
    with pytest.raises(ValueError, match="finite"):
        replace(sample.metrics[0], paper_value=Decimal("NaN"))
    with pytest.raises(ValueError, match="prohibited extrapolation"):
        calibrate_fill_model((sample,), prohibited_extrapolation=())


def test_compatibility_calibration_requires_pairs() -> None:
    with pytest.raises(ValueError):
        calibrate((Decimal("1"),), (), scope="x", prohibited_extrapolation="y")
