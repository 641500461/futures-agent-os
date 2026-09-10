"""Deterministic, proposal-free execution schedules for V5-004."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ExecutionAlgorithm(StrEnum):
    TWAP = "TWAP"
    VWAP = "VWAP"
    ICEBERG = "ICEBERG"


@dataclass(frozen=True, slots=True)
class ChildSlice:
    index: int
    quantity: Decimal
    participation: Decimal


def schedule(
    algorithm: ExecutionAlgorithm,
    quantity: Decimal,
    slices: int,
    *,
    volumes: tuple[Decimal, ...] = (),
    display_quantity: Decimal | None = None,
) -> tuple[ChildSlice, ...]:
    if not isinstance(algorithm, ExecutionAlgorithm) or not quantity.is_finite() or quantity <= 0 or slices <= 0:
        raise ValueError("invalid execution schedule")
    if algorithm is ExecutionAlgorithm.VWAP:
        if len(volumes) != slices or any(not v.is_finite() or v <= 0 for v in volumes):
            raise ValueError("VWAP requires positive volume for each slice")
        total = sum(volumes, Decimal("0"))
        weights = tuple(v / total for v in volumes)
    elif algorithm is ExecutionAlgorithm.ICEBERG:
        if display_quantity is None or not display_quantity.is_finite() or display_quantity <= 0:
            raise ValueError("ICEBERG requires display_quantity")
        weights = tuple(
            min(display_quantity, quantity - sum((min(display_quantity, quantity) for _ in range(i)), Decimal("0")))
            / quantity
            for i in range(slices)
        )
    else:
        weights = tuple(Decimal("1") / slices for _ in range(slices))
    result = tuple(ChildSlice(i, quantity * w, w) for i, w in enumerate(weights))
    if sum((x.quantity for x in result), Decimal("0")) > quantity:
        raise ValueError("schedule exceeds parent quantity")
    return result
