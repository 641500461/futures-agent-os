"""Exact, unit-bearing numeric values for cross-context contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TypeAlias


DecimalInput: TypeAlias = Decimal | int | str
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_UNIT = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]*$")


def _decimal(value: DecimalInput) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("binary float is not accepted; use Decimal, int, or str")
    if not isinstance(value, (Decimal, int, str)):
        raise TypeError("value must be Decimal, int, or str")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("value must be a decimal number") from error
    if not result.is_finite():
        raise ValueError("value must be finite")
    return result


def _fixed(value: DecimalInput, scale: int) -> Decimal:
    if isinstance(scale, bool) or not isinstance(scale, int) or not 0 <= scale <= 18:
        raise ValueError("scale must be an integer from 0 through 18")
    amount = _decimal(value)
    try:
        quantized = amount.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as error:
        raise ValueError("value cannot be represented at the declared fixed-point scale") from error
    if amount != quantized:
        raise ValueError("value exceeds the declared fixed-point scale")
    return quantized


def _currency(value: str) -> str:
    if not _CURRENCY.fullmatch(value):
        raise ValueError("currency must be an ISO 4217 uppercase code")
    return value


def _unit(value: str) -> str:
    if not _UNIT.fullmatch(value):
        raise ValueError("unit must be a stable non-empty token")
    return value


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in an explicit currency and declared decimal scale."""

    amount: DecimalInput
    currency: str
    scale: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _fixed(self.amount, self.scale))
        object.__setattr__(self, "currency", _currency(self.currency))

    def to_dict(self) -> dict[str, str | int]:
        return {"amount": f"{self.amount:.{self.scale}f}", "currency": self.currency, "scale": self.scale}


@dataclass(frozen=True, slots=True)
class Price:
    """An exact quoted price with its quote currency and economic unit."""

    amount: DecimalInput
    currency: str
    unit: str
    scale: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _fixed(self.amount, self.scale))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "unit", _unit(self.unit))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "amount": f"{self.amount:.{self.scale}f}",
            "currency": self.currency,
            "unit": self.unit,
            "scale": self.scale,
        }


@dataclass(frozen=True, slots=True)
class Quantity:
    """An exact quantity with an explicit economic unit and decimal scale."""

    amount: DecimalInput
    unit: str
    scale: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _fixed(self.amount, self.scale))
        object.__setattr__(self, "unit", _unit(self.unit))

    def to_dict(self) -> dict[str, str | int]:
        return {"amount": f"{self.amount:.{self.scale}f}", "unit": self.unit, "scale": self.scale}
