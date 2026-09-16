from decimal import Decimal

from hypothesis import given, strategies as st

from futures_agent_os.execution_simulation.advanced_algorithms import ExecutionAlgorithm, schedule


@given(quantity=st.integers(1, 500), slices=st.integers(1, 25))
def test_twap_children_exactly_conserve_integer_lots(quantity: int, slices: int) -> None:
    children = schedule(ExecutionAlgorithm.TWAP, Decimal(quantity), slices, lot_size=Decimal("1"))
    assert sum((child.quantity for child in children), Decimal("0")) == Decimal(quantity)
    assert all(child.quantity > 0 for child in children)


@given(
    quantity=st.integers(1, 500),
    volumes=st.lists(st.integers(1, 100), min_size=1, max_size=12),
)
def test_vwap_children_never_exceed_or_lose_parent(quantity: int, volumes: list[int]) -> None:
    profile = tuple(Decimal(volume) for volume in volumes)
    children = schedule(
        ExecutionAlgorithm.VWAP,
        Decimal(quantity),
        len(profile),
        volumes=profile,
        lot_size=Decimal("1"),
    )
    assert sum((child.quantity for child in children), Decimal("0")) == Decimal(quantity)
    assert all(Decimal("0") < child.quantity <= Decimal(quantity) for child in children)
