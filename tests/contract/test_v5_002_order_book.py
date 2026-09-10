from decimal import Decimal
import pytest
from futures_agent_os.execution_simulation.order_book_replay import BookLevel, BookSide, BookUpdate, consume, replay


def test_depth_consumption_partial_and_impact():
    result = consume(
        (BookLevel(Decimal("101"), Decimal("2")), BookLevel(Decimal("102"), Decimal("1"))), Decimal("4"), Decimal("100")
    )
    assert result.quantity == Decimal("3")
    assert result.remaining == Decimal("1")
    assert result.notional == Decimal("304")

def test_queue_ahead_reduces_available_depth_and_gap_is_rejected():
    result = replay((BookUpdate(1, BookSide.ASK, Decimal("101"), Decimal("3"), Decimal("1")), BookUpdate(2, BookSide.ASK, Decimal("102"), Decimal("2"))), Decimal("3"), Decimal("100"), side=BookSide.ASK)
    assert result.quantity == Decimal("3") and result.consumed_depth == Decimal("3")
    with pytest.raises(ValueError, match="BOOK_SEQUENCE_GAP"):
        replay((BookUpdate(1, BookSide.ASK, Decimal("101"), Decimal("1")), BookUpdate(3, BookSide.ASK, Decimal("102"), Decimal("1"))), Decimal("1"), Decimal("100"), side=BookSide.ASK)
