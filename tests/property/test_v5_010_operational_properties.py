from decimal import Decimal

from hypothesis import given, strategies as st

from futures_agent_os.observability import MetricKind, MetricSample
from futures_agent_os.operations import SloMeasurementWindow, SloObjective, SloStatus
from futures_agent_os.shared_kernel import EntityId, RecordedAt


AT = RecordedAt.parse("2026-09-11T00:00:00Z")


def _window(identifier: str, values: list[int]) -> SloMeasurementWindow:
    return SloMeasurementWindow(
        identifier,
        AT,
        AT,
        tuple(
            MetricSample(
                EntityId.deterministic("metric", f"{identifier}:{index}"),
                "latency_ms",
                MetricKind.HISTOGRAM,
                Decimal(value),
                AT,
            )
            for index, value in enumerate(values)
        ),
    )


@given(values=st.lists(st.integers(min_value=0, max_value=10_000), min_size=20, max_size=100))
def test_slo_result_is_monotone_when_every_observation_worsens(values: list[int]) -> None:
    objective = SloObjective("property-p95", "latency_ms", 95, Decimal("500"), 20, "runbook://property", ("sim",))
    original = objective.evaluate(_window("original", values))
    worsened = objective.evaluate(_window("worsened", [value + 1 for value in values]))
    assert worsened.observed_percentile is not None and original.observed_percentile is not None
    assert worsened.observed_percentile >= original.observed_percentile
    if original.status is SloStatus.ALERT:
        assert worsened.status is SloStatus.ALERT
