from decimal import Decimal

from hypothesis import given, strategies as st

from futures_agent_os.shared_kernel import Money, Price, Quantity


@st.composite
def fixed_decimal_strings(draw: st.DrawFn, scale: int) -> str:
    units = draw(st.integers(min_value=-1_000_000, max_value=1_000_000))
    fraction = draw(st.integers(min_value=0, max_value=(10**scale) - 1))
    sign = "-" if units < 0 else ""
    return f"{sign}{abs(units)}.{fraction:0{scale}d}"


@given(scale=st.integers(min_value=0, max_value=6), data=st.data())
def test_exact_values_round_trip_at_their_declared_scale(scale: int, data: st.DataObject) -> None:
    value = data.draw(fixed_decimal_strings(scale))
    expected = Decimal(value).quantize(Decimal(1).scaleb(-scale))

    money = Money(value, "CNY", scale)
    price = Price(value, "CNY", "CNY/kg", scale)
    quantity = Quantity(value, "contract", scale)

    assert money.amount == price.amount == quantity.amount == expected
    assert money.to_dict()["amount"] == price.to_dict()["amount"] == quantity.to_dict()["amount"]
