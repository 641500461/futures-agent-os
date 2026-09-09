"""JSON snapshot persistence using only installed market value constructors."""

from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Mapping
from uuid import UUID
from zoneinfo import ZoneInfo

from futures_agent_os import reference_market_data, shared_kernel
from futures_agent_os.reference_market_data import MarketSnapshot
from futures_agent_os.shared_kernel.observability import JsonValue

_TYPES: dict[str, type[Any]] = {
    f"{value.__module__}.{value.__name__}": value
    for module in (reference_market_data, shared_kernel)
    for value in vars(module).values()
    if isinstance(value, type) and (is_dataclass(value) or issubclass(value, Enum))
}


def _encode(value: Any) -> JsonValue:
    kind = f"{type(value).__module__}.{type(value).__name__}"
    if isinstance(value, Enum) and kind in _TYPES:
        return {"type": kind, "value": value.value}
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, datetime):
        return {
            "type": "datetime",
            "value": value.isoformat(),
            "zone": value.tzinfo.key if isinstance(value.tzinfo, ZoneInfo) else None,
            "fold": value.fold,
        }
    if isinstance(value, (Decimal, UUID, date, time)):
        return {"type": type(value).__name__, "value": str(value)}
    if isinstance(value, timedelta):
        return {"type": "timedelta", "value": (value.days * 86400 + value.seconds) * 1000000 + value.microseconds}
    if isinstance(value, (tuple, list)):
        return tuple(_encode(item) for item in value)
    if kind in _TYPES and is_dataclass(value):
        return {
            "type": kind,
            "fields": {field.name: _encode(getattr(value, field.name)) for field in fields(value) if field.init},
        }
    raise ValueError(f"unsupported snapshot value: {kind}")


def _decode(value: Any) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, (tuple, list)):
        return tuple(_decode(item) for item in value)
    if not isinstance(value, Mapping):
        raise ValueError("invalid snapshot value")
    kind = value["type"]
    scalar: dict[str, Callable[..., Any]] = {
        "Decimal": Decimal,
        "UUID": UUID,
        "date": date.fromisoformat,
        "time": time.fromisoformat,
    }
    if kind in scalar:
        return scalar[kind](value["value"])
    if kind == "datetime":
        result = datetime.fromisoformat(value["value"])
        if value["zone"] is not None:
            result = result.astimezone(ZoneInfo(value["zone"]))
        return result.replace(fold=value["fold"])
    if kind == "timedelta":
        return timedelta(microseconds=value["value"])
    cls = _TYPES.get(kind)
    if cls is None:
        raise ValueError("unknown snapshot type")
    if issubclass(cls, Enum):
        return cls(value["value"])
    expected = {field.name for field in fields(cls) if field.init}
    if set(value["fields"]) != expected:
        raise ValueError("snapshot fields do not match versioned type")
    return cls(**{name: _decode(item) for name, item in value["fields"].items()})


def snapshot_to_json(snapshot: MarketSnapshot) -> dict[str, JsonValue]:
    if type(snapshot) is not MarketSnapshot:
        raise TypeError("snapshot requires MarketSnapshot")
    return {"schema": "market-snapshot-envelope.v1", "snapshot": _encode(snapshot)}


def snapshot_from_json(value: Mapping[str, object]) -> MarketSnapshot:
    if value["schema"] != "market-snapshot-envelope.v1":
        raise ValueError("unsupported snapshot envelope version")
    snapshot = _decode(value["snapshot"])
    if type(snapshot) is not MarketSnapshot:
        raise ValueError("envelope requires MarketSnapshot")
    return snapshot
