from datetime import date
from decimal import Decimal

import pytest

from futures_agent_os.adapters import OfficialDailyRawFile, OfficialDailySource, normalize_official_daily
from futures_agent_os.shared_kernel import RecordedAt


ACQUIRED = RecordedAt.parse("2026-08-28T06:00:00Z")


def raw(source: OfficialDailySource, content: bytes) -> OfficialDailyRawFile:
    if source is OfficialDailySource.SHFE:
        url = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat"
    else:
        url = "https://www.czce.com.cn/cn/DFSStaticFiles/Future/2024/20240102/FutureDataDaily.txt"
    return OfficialDailyRawFile(source, date(2024, 1, 2), url, url, "text/plain", ACQUIRED, content)


def test_normalizes_shfe_futures_and_skips_aggregate_rows() -> None:
    content = """{"o_curinstrument":[
      {"PRODUCTGROUPID":"cu ","DELIVERYMONTH":"2401","PRESETTLEMENTPRICE":69070,
       "OPENPRICE":68920,"HIGHESTPRICE":69150,"LOWESTPRICE":68800,"CLOSEPRICE":69020,
       "SETTLEMENTPRICE":68980,"VOLUME":123,"OPENINTEREST":456,"TURNOVER":789.5},
      {"PRODUCTGROUPID":"cu ","DELIVERYMONTH":"小计","VOLUME":999}
    ]}""".encode()

    bars = normalize_official_daily(raw(OfficialDailySource.SHFE, content))

    assert len(bars) == 1
    bar = bars[0]
    assert (bar.instrument, bar.variety, bar.close) == ("SHFE.CU2401", "CU", Decimal("69020"))
    assert bar.to_point_in_time().available_time == ACQUIRED
    assert bar.to_point_in_time().values["raw_content_hash"] == raw(OfficialDailySource.SHFE, content).content_hash


def test_normalizes_czce_futures_and_preserves_missing_prices() -> None:
    content = (
        "\t\t\u90d1\u5dde\u5546\u54c1\u4ea4\u6613\u6240\u671f\u8d27\u6bcf\u65e5\u884c\u60c5\u8868\n"
        "\u5408\u7ea6\u4ee3\u7801|\u6628\u7ed3\u7b97|\u4eca\u5f00\u76d8|\u6700\u9ad8\u4ef7|\u6700\u4f4e\u4ef7|\u4eca\u6536\u76d8|\u4eca\u7ed3\u7b97|\u6da8\u8dcc1|\u6da8\u8dcc2|\u6210\u4ea4\u91cf|\u6301\u4ed3\u91cf|\u589e\u51cf\u91cf|\u6210\u4ea4\u989d\n"
        "MA405|2,450|2,460|2,480|2,440|2,470|2,465|20|15|12,345|67,890|1|9,876.5\n"
        "SR405|6,000|-|-|-|-|6,010|10|10|0|123|0|0\n"
    ).encode()

    bars = normalize_official_daily(raw(OfficialDailySource.CZCE, content))

    assert [bar.instrument for bar in bars] == ["CZCE.MA405", "CZCE.SR405"]
    assert bars[0].volume == 12345 and bars[0].turnover == Decimal("9876.5")
    assert bars[1].open is None and bars[1].close is None


def test_normalizer_rejects_malformed_or_fractional_integer_fields() -> None:
    with pytest.raises(ValueError, match="invalid SHFE daily JSON"):
        normalize_official_daily(raw(OfficialDailySource.SHFE, b"not-json"))
    fractional = "MA405|1|1|1|1|1|1|0|0|1.5|2|0|3\n".encode()
    with pytest.raises(ValueError, match="fractional"):
        normalize_official_daily(raw(OfficialDailySource.CZCE, fractional))
