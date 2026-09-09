from decimal import Decimal
from futures_agent_os.execution_simulation.order_book_replay import BookLevel, consume

def test_depth_consumption_partial_and_impact():
    result = consume((BookLevel(Decimal("101"), Decimal("2")), BookLevel(Decimal("102"), Decimal("1"))), Decimal("4"), Decimal("100"))
    assert result.quantity == Decimal("3")
    assert result.remaining == Decimal("1")
    assert result.notional == Decimal("304")

