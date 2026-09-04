from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Mapping

import pytest

from futures_agent_os.adapters.iwencai_openapi import (
    IwencaiHttpResult,
    IwencaiOpenApiClient,
    IwencaiRequest,
    IwencaiSkill,
)
from futures_agent_os.adapters.official_exchange_daily import (
    HttpReadResult,
    OfficialDailyRawFile,
    OfficialDailySource,
    OfficialExchangeDailyClient,
    official_daily_url,
)
from futures_agent_os.shared_kernel import RecordedAt


NOW = RecordedAt.parse("2026-08-28T06:00:00Z")


@dataclass
class FakeReadTransport:
    result: HttpReadResult
    call: tuple[str, float, int] | None = None

    def get(self, url: str, *, timeout_seconds: float, maximum_bytes: int) -> HttpReadResult:
        self.call = (url, timeout_seconds, maximum_bytes)
        return self.result


def test_official_exchange_client_uses_fixed_read_only_urls_and_hashes_exact_bytes() -> None:
    cases = (
        (OfficialDailySource.SHFE, "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat"),
        (
            OfficialDailySource.CZCE,
            "https://www.czce.com.cn/cn/DFSStaticFiles/Future/2024/20240102/FutureDataDaily.txt",
        ),
    )
    for source, expected_url in cases:
        transport = FakeReadTransport(HttpReadResult(expected_url, "application/octet-stream", b"exact raw bytes"))
        raw = OfficialExchangeDailyClient(transport).fetch(source, date(2024, 1, 2), acquired_at=NOW)

        assert raw.requested_url == expected_url == official_daily_url(source, date(2024, 1, 2))
        assert raw.content == b"exact raw bytes"
        assert raw.content_hash == "sha256:77930ed46720b8933079a3b4d8ff7fda9b6f33b40a0736ad7b21d674626a7770"
        assert transport.call == (expected_url, 30.0, 20_000_000)


def test_official_exchange_client_preserves_source_revision_headers_without_backdating_acquisition() -> None:
    url = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat"
    transport = FakeReadTransport(
        HttpReadResult(
            url,
            "application/json",
            b"exact raw bytes",
            "Wed, 20 Mar 2024 09:17:27 GMT",
            '"65faa9a7-20ba6"',
        )
    )

    raw = OfficialExchangeDailyClient(transport).fetch(OfficialDailySource.SHFE, date(2024, 1, 2), acquired_at=NOW)

    assert raw.source_last_modified_at == RecordedAt.parse("2024-03-20T09:17:27Z")
    assert raw.source_etag == '"65faa9a7-20ba6"'
    assert raw.acquired_at == NOW


def test_official_exchange_client_rejects_invalid_or_future_last_modified() -> None:
    url = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat"
    with pytest.raises(ValueError, match="valid HTTP date"):
        OfficialExchangeDailyClient(FakeReadTransport(HttpReadResult(url, "text/plain", b"x", "bad"))).fetch(
            OfficialDailySource.SHFE, date(2024, 1, 2), acquired_at=NOW
        )
    with pytest.raises(ValueError, match="cannot follow acquisition"):
        OfficialExchangeDailyClient(
            FakeReadTransport(HttpReadResult(url, "text/plain", b"x", "Sat, 29 Aug 2026 00:00:00 GMT"))
        ).fetch(OfficialDailySource.SHFE, date(2024, 1, 2), acquired_at=NOW)


def test_official_exchange_client_rejects_cross_origin_redirects() -> None:
    transport = FakeReadTransport(HttpReadResult("https://attacker.invalid/file", "text/plain", b"payload"))
    with pytest.raises(ValueError, match="allowlisted source boundary"):
        OfficialExchangeDailyClient(transport).fetch(OfficialDailySource.SHFE, date(2024, 1, 2), acquired_at=NOW)


def test_raw_file_rejects_query_credentials_and_empty_content() -> None:
    with pytest.raises(ValueError, match="credentials, query, or fragment"):
        OfficialDailyRawFile(
            OfficialDailySource.SHFE,
            date(2024, 1, 2),
            "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat?token=secret",
            "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat",
            "application/json",
            NOW,
            b"payload",
        )


class FakeIwencaiTransport:
    def __init__(self, result: IwencaiHttpResult) -> None:
        self.result = result
        self.url = ""
        self.headers: Mapping[str, str] = {}
        self.content = b""

    def post(
        self, url: str, *, headers: Mapping[str, str], content: bytes, timeout_seconds: float
    ) -> IwencaiHttpResult:
        assert timeout_seconds == 30.0
        self.url, self.headers, self.content = url, headers, content
        return self.result


@pytest.mark.parametrize("skill", tuple(IwencaiSkill))
def test_iwencai_client_is_bounded_versioned_and_keeps_credentials_out_of_evidence(skill: IwencaiSkill) -> None:
    raw_response = json.dumps({"datas": [{"合约代码": "CU2609"}], "code_count": 1}).encode()
    transport = FakeIwencaiTransport(IwencaiHttpResult(200, raw_response))
    client = IwencaiOpenApiClient(transport, api_key="credential-value")

    evidence = client.query(IwencaiRequest(skill, "沪铜期货资料"), acquired_at=NOW)

    assert transport.url == "https://openapi.iwencai.com/v1/query2data"
    assert transport.headers["X-Claw-Skill-Id"] == skill.value
    assert transport.headers["X-Claw-Skill-Version"] == "1.0.0"
    assert transport.headers["Authorization"] == "Bearer credential-value"
    assert len(transport.headers["X-Claw-Trace-Id"]) == 64
    assert json.loads(transport.content)["query"] == "沪铜期货资料"
    assert evidence.skill is skill and evidence.response["code_count"] == 1
    assert isinstance(evidence.response["datas"], tuple)
    assert "credential-value" not in repr(evidence)


def test_official_exchange_client_rejects_datetime_as_trading_date() -> None:
    transport = FakeReadTransport(HttpReadResult("https://www.shfe.com.cn/file", "text/plain", b"payload"))
    with pytest.raises(TypeError, match="date"):
        OfficialExchangeDailyClient(transport).fetch(
            OfficialDailySource.SHFE, datetime(2024, 1, 2, tzinfo=UTC), acquired_at=NOW
        )


def test_iwencai_client_fails_closed_on_bad_shape_or_status_and_bounds_requests() -> None:
    with pytest.raises(ValueError, match="1-500"):
        IwencaiRequest(IwencaiSkill.FUTURES_QUERY, "")
    with pytest.raises(ValueError, match="between 1 and 100"):
        IwencaiRequest(IwencaiSkill.FUTURES_QUERY, "query", limit=101)

    bad_status = IwencaiOpenApiClient(FakeIwencaiTransport(IwencaiHttpResult(401, b"{}")), api_key="x")
    with pytest.raises(RuntimeError, match="HTTP 401"):
        bad_status.query(IwencaiRequest(IwencaiSkill.BASICINFO_QUERY, "query"), acquired_at=NOW)

    bad_shape = IwencaiOpenApiClient(FakeIwencaiTransport(IwencaiHttpResult(200, b"[]")), api_key="x")
    with pytest.raises(ValueError, match="JSON object"):
        bad_shape.query(IwencaiRequest(IwencaiSkill.BASICINFO_QUERY, "query"), acquired_at=NOW)

    redirected = IwencaiOpenApiClient(
        FakeIwencaiTransport(IwencaiHttpResult(200, b"{}", "https://attacker.invalid/result")), api_key="x"
    )
    with pytest.raises(ValueError, match="fixed endpoint boundary"):
        redirected.query(IwencaiRequest(IwencaiSkill.BASICINFO_QUERY, "query"), acquired_at=NOW)
