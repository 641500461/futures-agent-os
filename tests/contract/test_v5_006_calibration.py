from decimal import Decimal
import pytest
from futures_agent_os.execution_simulation.calibration import calibrate

def test_calibration_reports_error_interval_and_scope():
    result = calibrate((Decimal("100"), Decimal("101")), (Decimal("100.5"), Decimal("100.5")), scope="ES:2026", prohibited_extrapolation="not for illiquid contracts")
    assert result.sample_count == 2
    assert result.error_low == Decimal("-0.5")
    assert result.error_high == Decimal("0.5")

def test_calibration_requires_pairs():
    with pytest.raises(ValueError):
        calibrate((Decimal("1"),), (), scope="x", prohibited_extrapolation="y")
