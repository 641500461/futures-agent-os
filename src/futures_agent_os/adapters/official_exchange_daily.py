"""Bounded, read-only acquisition of official exchange daily futures files.

The adapter deliberately stops at immutable raw bytes.  Publication-time and
license decisions belong to a governed dataset manifest and must not be
invented by a network client.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Mapping, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from futures_agent_os.shared_kernel import RecordedAt


class OfficialDailySource(StrEnum):
    SHFE = "SHFE"
    CZCE = "CZCE"


_SOURCE_HOSTS: Mapping[OfficialDailySource, str] = {
    OfficialDailySource.SHFE: "www.shfe.com.cn",
    OfficialDailySource.CZCE: "www.czce.com.cn",
}
_SOURCE_PATH_PREFIXES: Mapping[OfficialDailySource, str] = {
    OfficialDailySource.SHFE: "/data/tradedata/future/dailydata/",
    OfficialDailySource.CZCE: "/cn/DFSStaticFiles/Future/",
}


@dataclass(frozen=True, slots=True)
class HttpReadResult:
    final_url: str
    media_type: str
    content: bytes
    last_modified: str | None = None
    etag: str | None = None


class ReadOnlyHttpTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: float, maximum_bytes: int) -> HttpReadResult: ...


@dataclass(frozen=True, slots=True)
class OfficialDailyRawFile:
    source: OfficialDailySource
    trading_date: date
    requested_url: str
    final_url: str
    media_type: str
    acquired_at: RecordedAt
    content: bytes
    source_last_modified_at: RecordedAt | None = None
    source_etag: str | None = None

    def __post_init__(self) -> None:
        if type(self.trading_date) is not date:
            raise TypeError("official exchange raw file requires a date, not a timestamp")
        if not self.content:
            raise ValueError("official exchange response cannot be empty")
        _validate_source_url(self.source, self.requested_url)
        _validate_source_url(self.source, self.final_url)
        if self.source_last_modified_at is not None:
            if type(self.source_last_modified_at) is not RecordedAt:
                raise TypeError("official exchange Last-Modified requires RecordedAt")
            if self.source_last_modified_at.value > self.acquired_at.value:
                raise ValueError("official exchange Last-Modified cannot follow acquisition")
        if self.source_etag is not None and (not self.source_etag.strip() or "\n" in self.source_etag):
            raise ValueError("official exchange ETag must be non-empty single-line text")

    @property
    def content_hash(self) -> str:
        return f"sha256:{hashlib.sha256(self.content).hexdigest()}"


class UrlLibReadOnlyTransport:
    """Small GET-only transport with a hard response-size limit."""

    def get(self, url: str, *, timeout_seconds: float, maximum_bytes: int) -> HttpReadResult:
        request = Request(url, headers={"User-Agent": "futures-agent-os/0.0.1"}, method="GET")
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is allowlisted by caller
            content = response.read(maximum_bytes + 1)
            if len(content) > maximum_bytes:
                raise ValueError("official exchange response exceeds maximum_bytes")
            return HttpReadResult(
                final_url=response.geturl(),
                media_type=response.headers.get_content_type(),
                content=content,
                last_modified=response.headers.get("Last-Modified"),
                etag=response.headers.get("ETag"),
            )


class OfficialExchangeDailyClient:
    """Fetch one exchange-owned daily file without normalizing its semantics."""

    def __init__(
        self,
        transport: ReadOnlyHttpTransport,
        *,
        timeout_seconds: float = 30.0,
        maximum_bytes: int = 20_000_000,
    ) -> None:
        if timeout_seconds <= 0 or maximum_bytes < 1:
            raise ValueError("official exchange client requires positive limits")
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._maximum_bytes = maximum_bytes

    def fetch(
        self, source: OfficialDailySource, trading_date: date, *, acquired_at: RecordedAt
    ) -> OfficialDailyRawFile:
        if not isinstance(source, OfficialDailySource) or type(trading_date) is not date:
            raise TypeError("official exchange fetch requires typed source and trading_date")
        url = official_daily_url(source, trading_date)
        result = self._transport.get(
            url,
            timeout_seconds=self._timeout_seconds,
            maximum_bytes=self._maximum_bytes,
        )
        last_modified = _http_date(result.last_modified) if result.last_modified is not None else None
        return OfficialDailyRawFile(
            source=source,
            trading_date=trading_date,
            requested_url=url,
            final_url=result.final_url,
            media_type=result.media_type,
            acquired_at=acquired_at,
            content=result.content,
            source_last_modified_at=last_modified,
            source_etag=result.etag,
        )


def official_daily_url(source: OfficialDailySource, trading_date: date) -> str:
    stamp = trading_date.strftime("%Y%m%d")
    year = trading_date.strftime("%Y")
    if source is OfficialDailySource.SHFE:
        return f"https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{stamp}.dat"
    if source is OfficialDailySource.CZCE:
        return f"https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{stamp}/FutureDataDaily.txt"
    raise ValueError("unsupported official daily source")


def _validate_source_url(source: OfficialDailySource, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("official exchange URL must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("official exchange URL cannot contain credentials, query, or fragment")
    if parsed.hostname != _SOURCE_HOSTS[source] or not parsed.path.startswith(_SOURCE_PATH_PREFIXES[source]):
        raise ValueError("official exchange redirect left the allowlisted source boundary")


def _http_date(value: str) -> RecordedAt:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError("official exchange Last-Modified is not a valid HTTP date") from error
    if parsed.tzinfo is None:
        raise ValueError("official exchange Last-Modified must include a timezone")
    return RecordedAt.from_datetime(parsed)
