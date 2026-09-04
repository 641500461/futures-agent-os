from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from futures_agent_os.adapters import (
    OFFICIAL_DAILY_NORMALIZER,
    OFFICIAL_RESEARCH_SERIES_NORMALIZER,
    OfficialDailyRawFile,
    OfficialDailySource,
    materialize_official_daily_datasets,
    materialize_official_research_series,
    normalize_official_daily,
)
from futures_agent_os.reference_market_data import (
    DatasetLayer,
    LicenseTerms,
    dataset_manifest_sha256,
    sha256_digest,
)
from futures_agent_os.research_experiment import DatasetAuthorizationAuthority
from futures_agent_os.shared_kernel import EntityId, RecordedAt


ACQUIRED = RecordedAt.parse("2026-08-28T06:00:00Z")
RAW_ID = EntityId.parse("dataset_0198f4d0-0000-7000-8000-000000000101")
PIT_ID = EntityId.parse("dataset_0198f4d0-0000-7000-8000-000000000102")
RAW_ID_2 = EntityId.parse("dataset_0198f4d0-0000-7000-8000-000000000103")
SERIES_ID = EntityId.parse("dataset_0198f4d0-0000-7000-8000-000000000104")


def license_terms() -> LicenseTerms:
    return LicenseTerms(
        "governance-authorized public exchange data",
        "personal non-commercial research and simulation",
        "local evidence retention",
        "no redistribution",
        "research environments only",
    )


def shfe_raw() -> OfficialDailyRawFile:
    url = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat"
    content = """{"o_curinstrument":[
      {"PRODUCTGROUPID":"ag","DELIVERYMONTH":"2402","PRESETTLEMENTPRICE":5900,
       "OPENPRICE":5910,"HIGHESTPRICE":5950,"LOWESTPRICE":5890,"CLOSEPRICE":5940,
       "SETTLEMENTPRICE":5925,"VOLUME":123,"OPENINTEREST":456,"TURNOVER":789},
      {"PRODUCTGROUPID":"cu","DELIVERYMONTH":"2402","PRESETTLEMENTPRICE":69000,
       "OPENPRICE":69100,"HIGHESTPRICE":69500,"LOWESTPRICE":68800,"CLOSEPRICE":69400,
       "SETTLEMENTPRICE":69250,"VOLUME":321,"OPENINTEREST":654,"TURNOVER":987},
      {"PRODUCTGROUPID":"rb","DELIVERYMONTH":"2402","PRESETTLEMENTPRICE":3900,
       "OPENPRICE":3910,"HIGHESTPRICE":3950,"LOWESTPRICE":3890,"CLOSEPRICE":3940,
       "SETTLEMENTPRICE":3925,"VOLUME":1,"OPENINTEREST":2,"TURNOVER":3}
    ]}""".encode()
    return OfficialDailyRawFile(
        OfficialDailySource.SHFE, date(2024, 1, 2), url, url, "application/json", ACQUIRED, content
    )


def materialize(raw: OfficialDailyRawFile | None = None, *, as_of: RecordedAt = ACQUIRED):
    source = raw or shfe_raw()
    return materialize_official_daily_datasets(
        source,
        normalize_official_daily(source),
        varieties=("AG", "CU"),
        license_terms=license_terms(),
        raw_dataset_id=RAW_ID,
        normalized_dataset_id=PIT_ID,
        as_of=as_of,
    )


def test_materializes_exact_raw_and_canonical_pit_with_lineage() -> None:
    bundle = materialize()

    assert bundle.raw.content == shfe_raw().content
    assert bundle.raw.manifest.layer is DatasetLayer.RAW
    assert bundle.raw.manifest.content_hash == sha256_digest(bundle.raw.content)
    assert bundle.normalized_pit.manifest.layer is DatasetLayer.NORMALIZED_PIT
    assert bundle.normalized_pit.manifest.upstream_manifest_ids == (RAW_ID,)
    assert bundle.normalized_pit.manifest.instrument_universe == ("SHFE.AG2402", "SHFE.CU2402")
    assert {record.values["instrument"] for record in bundle.records} == {"SHFE.AG2402", "SHFE.CU2402"}
    assert all(record.available_time == ACQUIRED for record in bundle.records)
    assert b"SHFE.RB2402" not in bundle.normalized_pit.content


def test_materialization_is_content_deterministic_but_keeps_manifest_identity_separate() -> None:
    first = materialize()
    second = materialize()

    assert first.raw.content == second.raw.content
    assert first.normalized_pit.content == second.normalized_pit.content
    assert first.normalized_pit.manifest.content_hash == second.normalized_pit.manifest.content_hash
    assert first.raw.manifest.dataset_id == RAW_ID and first.normalized_pit.manifest.dataset_id == PIT_ID


def test_rejects_tampered_normalization_and_lineage() -> None:
    raw = shfe_raw()
    bars = normalize_official_daily(raw)
    with pytest.raises(ValueError, match="exact official raw"):
        materialize_official_daily_datasets(
            raw,
            bars[:-1],
            varieties=("AG", "CU"),
            license_terms=license_terms(),
            raw_dataset_id=RAW_ID,
            normalized_dataset_id=PIT_ID,
            as_of=ACQUIRED,
        )
    tampered = (replace(bars[0], raw_content_hash="sha256:" + "0" * 64), *bars[1:])
    with pytest.raises(ValueError, match="exact official raw"):
        materialize_official_daily_datasets(
            raw,
            tampered,
            varieties=("AG", "CU"),
            license_terms=license_terms(),
            raw_dataset_id=RAW_ID,
            normalized_dataset_id=PIT_ID,
            as_of=ACQUIRED,
        )


def test_rejects_wrong_source_universe_missing_variety_and_historical_as_of() -> None:
    raw = shfe_raw()
    bars = normalize_official_daily(raw)
    common = dict(
        raw=raw,
        normalized_bars=bars,
        license_terms=license_terms(),
        raw_dataset_id=RAW_ID,
        normalized_dataset_id=PIT_ID,
        as_of=ACQUIRED,
    )
    with pytest.raises(ValueError, match="source-qualified"):
        materialize_official_daily_datasets(varieties=("MA",), **common)
    ag_only_content = raw.content.split(b',\n      {"PRODUCTGROUPID":"cu"', maxsplit=1)[0] + b"\n    ]}"
    ag_only = replace(raw, content=ag_only_content)
    with pytest.raises(ValueError, match="missing a requested variety"):
        materialize_official_daily_datasets(
            varieties=("AG", "CU"),
            **{**common, "raw": ag_only, "normalized_bars": normalize_official_daily(ag_only)},
        )
    with pytest.raises(ValueError, match="actual acquisition"):
        materialize(raw, as_of=RecordedAt.parse("2024-01-02T08:00:00Z"))


def test_bundle_collections_are_immutable() -> None:
    bundle = materialize()
    with pytest.raises(TypeError):
        bundle.records[0].values["close"] = "0"  # type: ignore[index]


def test_governance_authorizes_only_an_explicitly_approved_official_normalizer() -> None:
    bundle = materialize()
    manifest_sha256 = dataset_manifest_sha256(bundle.normalized_pit.manifest)
    provider_contract_sha256 = "c" * 64
    forbidden_content_sha256 = "sha256:" + "0" * 64
    common = dict(
        authority_id="mvp-r.official-data-governance",
        signing_key=bytes(range(32)),
        approved_manifest_contracts={manifest_sha256: provider_contract_sha256},
        forbidden_content_hashes=frozenset({forbidden_content_sha256}),
    )

    with pytest.raises(ValueError, match="normalizer is absent"):
        DatasetAuthorizationAuthority(**common).authorize(
            bundle.normalized_pit,
            provider_contract_sha256=provider_contract_sha256,
            records=bundle.records,
        )

    authority = DatasetAuthorizationAuthority(
        **common,
        approved_normalizer_ids=frozenset({OFFICIAL_DAILY_NORMALIZER}),
    )
    evidence = authority.authorize(
        bundle.normalized_pit,
        provider_contract_sha256=provider_contract_sha256,
        records=bundle.records,
    )

    authority.verify(evidence)
    assert evidence.manifest_sha256 == manifest_sha256


def test_materializes_multi_day_dominant_research_series_with_actual_acquisition_time() -> None:
    first = shfe_raw()
    second_url = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240103.dat"
    second = replace(first, trading_date=date(2024, 1, 3), requested_url=second_url, final_url=second_url)
    bundle = materialize_official_research_series(
        (first, second),
        varieties=("AG", "CU"),
        license_terms=license_terms(),
        raw_dataset_ids=(RAW_ID, RAW_ID_2),
        normalized_dataset_id=SERIES_ID,
        as_of=ACQUIRED,
    )

    assert len(bundle.raw) == 2
    assert len(bundle.records) == 4
    assert bundle.normalized_pit.manifest.instrument_universe == (
        "SHFE.AG.DOMINANT_OI",
        "SHFE.CU.DOMINANT_OI",
    )
    assert bundle.normalized_pit.manifest.generated_by == OFFICIAL_RESEARCH_SERIES_NORMALIZER
    assert bundle.normalized_pit.manifest.upstream_manifest_ids == (RAW_ID, RAW_ID_2)
    assert all(record.available_time == ACQUIRED for record in bundle.records)
    assert {record.values["component_instrument"] for record in bundle.records} == {
        "SHFE.AG2402",
        "SHFE.CU2402",
    }

    manifest_sha256 = dataset_manifest_sha256(bundle.normalized_pit.manifest)
    authority = DatasetAuthorizationAuthority(
        "mvp-r.series-data-governance",
        bytes(range(32)),
        {manifest_sha256: "d" * 64},
        frozenset({"sha256:" + "0" * 64}),
        frozenset({OFFICIAL_RESEARCH_SERIES_NORMALIZER}),
    )
    evidence = authority.authorize(
        bundle.normalized_pit,
        provider_contract_sha256="d" * 64,
        records=bundle.records,
    )
    authority.verify(evidence)
