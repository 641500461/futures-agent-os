import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from futures_agent_os.shared_kernel import (
    EntityId,
    Failure,
    Money,
    Price,
    Quantity,
    ReasonCode,
    RecordedAt,
    SchemaVersion,
    ShanghaiTimestamp,
    TradingDate,
)


def test_cross_context_identifiers_are_immutable_canonical_and_serializable() -> None:
    identifier = EntityId.new("trade_plan")

    assert identifier.namespace == "trade_plan"
    assert identifier.value.version == 7
    assert EntityId.parse(str(identifier)) == identifier
    assert json.loads(json.dumps(identifier.to_dict())) == {"id": str(identifier)}

    with pytest.raises(ValueError, match="namespace"):
        EntityId.new("Trade Plan")

    with pytest.raises(ValueError, match="canonical"):
        EntityId.parse(f"trade_plan_{str(identifier.value).upper()}")


@pytest.mark.parametrize(
    ("value_type", "arguments"),
    [
        (Money, (1.25, "CNY", 2)),
        (Price, (1.25, "CNY", "CNY/tonne", 2)),
        (Quantity, (1.25, "lot", 2)),
    ],
)
def test_decimal_value_objects_reject_binary_float(value_type: type[object], arguments: tuple[object, ...]) -> None:
    with pytest.raises(TypeError, match="float"):
        value_type(*arguments)


def test_money_price_and_quantity_are_fixed_point_and_serializable() -> None:
    money = Money(Decimal("123.40"), "CNY", 2)
    price = Price(Decimal("731.5"), "CNY", "CNY/tonne", 1)
    quantity = Quantity("3", "lot", 0)

    assert money.amount == Decimal("123.40")
    assert price.amount == Decimal("731.5")
    assert quantity.amount == Decimal("3")
    assert json.loads(json.dumps(money.to_dict())) == {
        "amount": "123.40",
        "currency": "CNY",
        "scale": 2,
    }

    with pytest.raises(ValueError, match="scale"):
        Money("123.456", "CNY", 2)

    with pytest.raises(ValueError, match="0 through 18"):
        Quantity("1", "lot", 19)

    with pytest.raises(ValueError, match="cannot be represented"):
        Money("1" + "0" * 1_000_000, "CNY", 2)


def test_recorded_at_is_normalized_to_utc_and_trading_date_is_not_inferred() -> None:
    source_time = datetime(2026, 8, 18, 21, 5, tzinfo=timezone(timedelta(hours=8)))
    recorded_at = RecordedAt.from_datetime(source_time)
    trading_date = TradingDate(date(2026, 8, 19))

    assert recorded_at.value == datetime(2026, 8, 18, 13, 5, tzinfo=UTC)
    assert recorded_at.to_dict() == {"recorded_at": "2026-08-18T13:05:00Z"}
    assert trading_date.to_dict() == {"trading_date": "2026-08-19"}

    with pytest.raises(ValueError, match="UTC"):
        RecordedAt(source_time)


def test_shanghai_timestamp_requires_the_iana_market_timezone() -> None:
    market_time = ShanghaiTimestamp.from_iso("2026-08-18T21:05:00+08:00")

    assert market_time.to_dict() == {"market_time": "2026-08-18T21:05:00+08:00"}

    with pytest.raises(ValueError, match="Asia/Shanghai"):
        ShanghaiTimestamp.from_datetime(datetime(2026, 8, 18, tzinfo=UTC))


def test_schema_versions_and_reason_codes_have_stable_machine_forms() -> None:
    version = SchemaVersion.parse("1.0")

    assert str(version) == "1.0"
    assert version.to_dict() == {"schema_version": "1.0"}
    assert ReasonCode.DATA_STALE.value == "DATA_STALE"
    assert ReasonCode.RULE_MISSING.value == "RULE_MISSING"

    with pytest.raises(ValueError, match="major.minor"):
        SchemaVersion.parse("v1")


def test_failure_serialization_keeps_the_stable_reason_code_separate_from_message() -> None:
    failure = Failure(reason_code=ReasonCode.RULE_MISSING, message="contract rule unavailable")
    terse_failure = Failure(reason_code=ReasonCode.DATA_STALE)

    assert json.loads(json.dumps(failure.to_dict())) == {
        "reason_code": "RULE_MISSING",
        "message": "contract rule unavailable",
    }
    assert terse_failure.to_dict() == {"reason_code": "DATA_STALE"}
