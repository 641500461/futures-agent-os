from decimal import Decimal

from hypothesis import given, strategies as st

from futures_agent_os.execution_simulation.calibration import calibrate


@given(
    replay=st.lists(st.integers(-10000, 10000), min_size=1, max_size=50),
    deltas=st.lists(st.integers(-1000, 1000), min_size=1, max_size=50),
)
def test_empirical_error_interval_contains_every_paired_error(replay: list[int], deltas: list[int]) -> None:
    size = min(len(replay), len(deltas))
    expected = tuple(Decimal(value) for value in replay[:size])
    errors = tuple(Decimal(value) for value in deltas[:size])
    paper = tuple(value + error for value, error in zip(expected, errors))
    report = calibrate(expected, paper, scope="property", prohibited_extrapolation="outside-property")
    assert report.error_low == min(errors) and report.error_high == max(errors)
    assert all(report.error_low <= error <= report.error_high for error in errors)
    assert report.mean_error == sum(errors, Decimal("0")) / size
    assert report.max_error == max(abs(error) for error in errors)
