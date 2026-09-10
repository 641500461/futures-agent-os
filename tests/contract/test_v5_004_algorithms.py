from decimal import Decimal
import pytest
from futures_agent_os.execution_simulation.advanced_algorithms import ExecutionAlgorithm, schedule


def test_twap_conserves_quantity():
    out = schedule(ExecutionAlgorithm.TWAP, Decimal("10"), 4)
    assert sum(x.quantity for x in out) == Decimal("10")


def test_vwap_uses_volume_weights():
    out = schedule(ExecutionAlgorithm.VWAP, Decimal("10"), 2, volumes=(Decimal("1"), Decimal("3")))
    assert out[0].quantity == Decimal("2.5") and out[1].quantity == Decimal("7.5")


def test_vwap_requires_complete_volume():
    with pytest.raises(ValueError):
        schedule(ExecutionAlgorithm.VWAP, Decimal("1"), 2, volumes=(Decimal("1"),))
