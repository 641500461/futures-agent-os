"""Explicit time boundaries; business-date attribution remains calendar-owned."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from dataclasses import dataclass
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _render(value: datetime) -> str:
    timespec = "seconds" if value.microsecond == 0 else "microseconds"
    return value.isoformat(timespec=timespec)


@dataclass(frozen=True, slots=True)
class TradingDate:
    """A date attributed by an exchange Trading Calendar, never inferred here."""

    value: date

    def __post_init__(self) -> None:
        if isinstance(self.value, datetime) or not isinstance(self.value, date):
            raise TypeError("trading_date must be a date, not a timestamp")

    @classmethod
    def parse(cls, text: str) -> TradingDate:
        return cls(date.fromisoformat(text))

    def __str__(self) -> str:
        return self.value.isoformat()

    def to_dict(self) -> dict[str, str]:
        return {"trading_date": str(self)}


@dataclass(frozen=True, slots=True)
class RecordedAt:
    """A persisted timestamp normalized to UTC."""

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() != timedelta(0):
            raise ValueError("recorded_at must be UTC and timezone-aware")
        object.__setattr__(self, "value", self.value.astimezone(UTC))

    @classmethod
    def from_datetime(cls, value: datetime) -> RecordedAt:
        if value.tzinfo is None:
            raise ValueError("recorded_at source must be timezone-aware")
        return cls(value.astimezone(UTC))

    @classmethod
    def parse(cls, text: str) -> RecordedAt:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return cls.from_datetime(parsed)

    def to_dict(self) -> dict[str, str]:
        return {"recorded_at": f"{_render(self.value).replace('+00:00', 'Z')}"}


@dataclass(frozen=True, slots=True)
class ShanghaiTimestamp:
    """A market-facing timestamp expressed in the Asia/Shanghai IANA timezone."""

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or getattr(self.value.tzinfo, "key", None) != SHANGHAI.key:
            raise ValueError("market time must use the Asia/Shanghai IANA timezone")

    @classmethod
    def from_datetime(cls, value: datetime) -> ShanghaiTimestamp:
        return cls(value)

    @classmethod
    def from_iso(cls, text: str) -> ShanghaiTimestamp:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            raise ValueError("market time must be timezone-aware")
        return cls(parsed.astimezone(SHANGHAI))

    def to_dict(self) -> dict[str, str]:
        return {"market_time": _render(self.value)}
