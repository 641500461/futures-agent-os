from decimal import Decimal
import pytest
from futures_agent_os.portfolio_risk.exposure_aggregation import Exposure, aggregate

def test_aggregate_conserves_and_groups():
    out = aggregate((Exposure("a", "s1", "x", Decimal("2")), Exposure("a", "s2", "x", Decimal("-1"))))
    assert out.total == Decimal("1")
    assert out.by_account == (("a", Decimal("1")),)
    assert out.by_instrument == (("x", Decimal("1")),)

def test_concentration_limit_is_fail_closed():
    with pytest.raises(ValueError, match="CONCENTRATION_LIMIT"):
        aggregate((Exposure("a", "s", "x", Decimal("3")),), concentration_limit=Decimal("2"))
