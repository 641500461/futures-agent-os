"""Normalization of allowlisted official SHFE and CZCE daily futures files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

from futures_agent_os.adapters.official_exchange_daily import OfficialDailyRawFile, OfficialDailySource
from futures_agent_os.reference_market_data.data_lake import PointInTimeRecord
from futures_agent_os.shared_kernel import RecordedAt


_CONTRACT = re.compile(r"^[A-Z]{1,3}[0-9]{3,4}$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class OfficialDailyBar:
    source: OfficialDailySource
    contract: str
    variety: str
    trading_date: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    settle: Decimal | None
    pre_settle: Decimal | None
    volume: int
    open_interest: int
    turnover: Decimal
    available_time: RecordedAt
    raw_content_hash: str

    def __post_init__(self) -> None:
        if not _CONTRACT.fullmatch(self.contract) or not self.contract.startswith(self.variety):
            raise ValueError("official daily bar requires a canonical futures contract")
        if any(value < 0 for value in (self.volume, self.open_interest, self.turnover)):
            raise ValueError("official daily bar volume, open interest, and turnover cannot be negative")
        object.__setattr__(self, "variety", self.variety.upper())

    @property
    def instrument(self) -> str:
        return f"{self.source.value}.{self.contract}"

    def to_point_in_time(self) -> PointInTimeRecord:
        local_close = datetime.combine(datetime.fromisoformat(self.trading_date).date(), time(15), _SHANGHAI)
        event_time = RecordedAt.from_datetime(local_close.astimezone(UTC))
        return PointInTimeRecord(
            event_time=event_time,
            available_time=self.available_time,
            values=MappingProxyType(
                {
                    "instrument": self.instrument,
                    "trading_date": self.trading_date,
                    "open": _text(self.open),
                    "high": _text(self.high),
                    "low": _text(self.low),
                    "close": _text(self.close),
                    "settle": _text(self.settle),
                    "pre_settle": _text(self.pre_settle),
                    "volume": self.volume,
                    "open_interest": self.open_interest,
                    "turnover": str(self.turnover),
                    "raw_content_hash": self.raw_content_hash,
                }
            ),
        )


def normalize_official_daily(raw: OfficialDailyRawFile) -> tuple[OfficialDailyBar, ...]:
    if raw.source is OfficialDailySource.SHFE:
        rows = _shfe_rows(raw.content)
    elif raw.source is OfficialDailySource.CZCE:
        rows = _czce_rows(raw.content)
    else:  # pragma: no cover - closed enum defense
        raise ValueError("unsupported official daily source")
    return tuple(_bar(raw, row) for row in rows)


def _shfe_rows(content: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        payload = json.loads(content)
        rows = payload["o_curinstrument"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("invalid SHFE daily JSON") from error
    if not isinstance(rows, list):
        raise ValueError("invalid SHFE daily row collection")
    normalized: list[Mapping[str, object]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("invalid SHFE daily row")
        delivery = str(item.get("DELIVERYMONTH", "")).strip()
        variety = str(item.get("PRODUCTGROUPID") or item.get("PRODUCTID") or "").split("_")[0].strip().upper()
        contract = f"{variety}{delivery}"
        if not _CONTRACT.fullmatch(contract):
            continue
        normalized.append(
            {
                "contract": contract,
                "variety": variety,
                "open": item.get("OPENPRICE"),
                "high": item.get("HIGHESTPRICE"),
                "low": item.get("LOWESTPRICE"),
                "close": item.get("CLOSEPRICE"),
                "settle": item.get("SETTLEMENTPRICE"),
                "pre_settle": item.get("PRESETTLEMENTPRICE"),
                "volume": item.get("VOLUME", 0),
                "open_interest": item.get("OPENINTEREST", 0),
                "turnover": item.get("TURNOVER", 0),
            }
        )
    return tuple(normalized)


def _czce_rows(content: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("invalid CZCE daily UTF-8 text") from error
    normalized: list[Mapping[str, object]] = []
    for line in text.splitlines():
        columns = [value.strip() for value in line.split("|")]
        if len(columns) < 13:
            continue
        contract = columns[0].upper()
        if not _CONTRACT.fullmatch(contract):
            continue
        variety_match = re.match(r"^[A-Z]+", contract)
        assert variety_match is not None
        normalized.append(
            {
                "contract": contract,
                "variety": variety_match.group(),
                "pre_settle": columns[1],
                "open": columns[2],
                "high": columns[3],
                "low": columns[4],
                "close": columns[5],
                "settle": columns[6],
                "volume": columns[9],
                "open_interest": columns[10],
                "turnover": columns[12],
            }
        )
    return tuple(normalized)


def _bar(raw: OfficialDailyRawFile, row: Mapping[str, object]) -> OfficialDailyBar:
    return OfficialDailyBar(
        source=raw.source,
        contract=str(row["contract"]),
        variety=str(row["variety"]),
        trading_date=raw.trading_date.isoformat(),
        open=_decimal(row.get("open"), optional=True),
        high=_decimal(row.get("high"), optional=True),
        low=_decimal(row.get("low"), optional=True),
        close=_decimal(row.get("close"), optional=True),
        settle=_decimal(row.get("settle"), optional=True),
        pre_settle=_decimal(row.get("pre_settle"), optional=True),
        volume=_integer(row.get("volume")),
        open_interest=_integer(row.get("open_interest")),
        turnover=_decimal(row.get("turnover"), optional=False) or Decimal(0),
        available_time=raw.acquired_at,
        raw_content_hash=raw.content_hash,
    )


def _decimal(value: object, *, optional: bool) -> Decimal | None:
    cleaned = str(value if value is not None else "").replace(",", "").strip()
    if cleaned in {"", "-", "None"}:
        return None if optional else Decimal(0)
    try:
        result = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError("official daily numeric field is invalid") from error
    if not result.is_finite():
        raise ValueError("official daily numeric field must be finite")
    return result


def _integer(value: object) -> int:
    number = _decimal(value, optional=False) or Decimal(0)
    if number != number.to_integral_value():
        raise ValueError("official daily integer field is fractional")
    return int(number)


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
