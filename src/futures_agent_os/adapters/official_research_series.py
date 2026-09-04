"""Governed unadjusted dominant-contract research series for sealed replay."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, cast

from futures_agent_os.reference_market_data import (
    DataQualityLevel,
    DatasetLayer,
    DatasetManifest,
    LicenseTerms,
    PointInTimeRecord,
    QualityReport,
    RevisionInfo,
    SourceProvenance,
    StoredDataset,
    TimeCoverage,
    sha256_digest,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

from .official_daily_bars import OfficialDailyBar, normalize_official_daily
from .official_daily_dataset import OFFICIAL_DAILY_DATASET_SCHEMA
from .official_exchange_daily import OfficialDailyRawFile, OfficialDailySource


OFFICIAL_RESEARCH_SERIES_NORMALIZER = "official-dominant-open-interest-series.v1"
OFFICIAL_RESEARCH_ROLL_POLICY = "daily-max-open-interest-unadjusted-tie-volume-contract.v1"
_SOURCE_ROOT: Mapping[OfficialDailySource, str] = MappingProxyType(
    {
        OfficialDailySource.SHFE: "https://www.shfe.com.cn/data/tradedata/future/dailydata/",
        OfficialDailySource.CZCE: "https://www.czce.com.cn/cn/DFSStaticFiles/Future/",
    }
)
_SOURCE_VARIETIES: Mapping[OfficialDailySource, frozenset[str]] = MappingProxyType(
    {
        OfficialDailySource.SHFE: frozenset({"AG", "CU"}),
        OfficialDailySource.CZCE: frozenset({"MA", "SR"}),
    }
)


@dataclass(frozen=True, slots=True)
class OfficialResearchSeriesBundle:
    raw: tuple[StoredDataset, ...]
    normalized_pit: StoredDataset
    records: tuple[PointInTimeRecord, ...]

    def __post_init__(self) -> None:
        if not self.raw or any(item.manifest.layer is not DatasetLayer.RAW for item in self.raw):
            raise ValueError("official research series requires RAW upstream datasets")
        if self.normalized_pit.manifest.layer is not DatasetLayer.NORMALIZED_PIT:
            raise ValueError("official research series requires a NORMALIZED_PIT dataset")
        if self.normalized_pit.manifest.upstream_manifest_ids != tuple(item.manifest.dataset_id for item in self.raw):
            raise ValueError("official research series must bind every ordered RAW upstream")
        self.normalized_pit.manifest.validate_point_in_time(self.records)


def materialize_official_research_series(
    raw_files: tuple[OfficialDailyRawFile, ...],
    *,
    varieties: tuple[str, ...],
    license_terms: LicenseTerms,
    raw_dataset_ids: tuple[EntityId, ...],
    normalized_dataset_id: EntityId,
    as_of: RecordedAt,
) -> OfficialResearchSeriesBundle:
    """Build one source-qualified, unadjusted dominant series dataset.

    This is explicitly a retrospective research representation. It preserves
    actual acquisition time on every record and never presents the selected
    component contract as a tradeable continuous instrument.
    """

    if not raw_files or len(raw_files) != len(raw_dataset_ids):
        raise ValueError("official research series requires one RAW identity per file")
    if any(type(item) is not OfficialDailyRawFile for item in raw_files):
        raise TypeError("official research series requires exact raw file inputs")
    if any(type(item) is not EntityId or item.namespace != "dataset" for item in raw_dataset_ids):
        raise ValueError("official research series requires dataset RAW identities")
    if type(normalized_dataset_id) is not EntityId or normalized_dataset_id.namespace != "dataset":
        raise ValueError("official research series requires a normalized dataset identity")
    if len(set((*raw_dataset_ids, normalized_dataset_id))) != len(raw_dataset_ids) + 1:
        raise ValueError("official research series dataset identities must be distinct")
    source = raw_files[0].source
    if any(item.source is not source for item in raw_files):
        raise ValueError("official research series cannot mix exchange sources")
    ordered = tuple(sorted(raw_files, key=lambda item: item.trading_date))
    if ordered != raw_files or len({item.trading_date for item in ordered}) != len(ordered):
        raise ValueError("official research raw files must be unique and chronologically ordered")
    requested = tuple(value.upper() for value in varieties)
    if not requested or requested != tuple(sorted(set(requested))) or not set(requested) <= _SOURCE_VARIETIES[source]:
        raise ValueError("official research varieties must be sorted, unique, and source-qualified")
    if type(as_of) is not RecordedAt or any(item.acquired_at.value > as_of.value for item in ordered):
        raise ValueError("official research as_of must follow every actual acquisition")

    raw_datasets: list[StoredDataset] = []
    series_records: list[PointInTimeRecord] = []
    for raw, dataset_id in zip(ordered, raw_dataset_ids, strict=True):
        bars = normalize_official_daily(raw)
        selected = tuple(_dominant(bars, variety) for variety in requested)
        raw_datasets.append(_raw_dataset(raw, dataset_id, selected, license_terms))
        series_records.extend(_series_record(raw, bar) for bar in selected)

    records = tuple(sorted(series_records, key=lambda item: (item.event_time.value, str(item.values["instrument_id"]))))
    content = canonical_json_text(tuple(_record_payload(record) for record in records)).encode()
    event_times = tuple(record.event_time for record in records)
    instruments = tuple(sorted({cast(str, record.values["instrument_id"]) for record in records}))
    revision_payload: JsonValue = tuple(
        {
            "trading_date": item.trading_date.isoformat(),
            "content_sha256": item.content_hash,
            "last_modified": (
                item.source_last_modified_at.to_dict()["recorded_at"] if item.source_last_modified_at else None
            ),
            "etag": item.source_etag,
        }
        for item in ordered
    )
    published = tuple(item.source_last_modified_at for item in ordered if item.source_last_modified_at is not None)
    manifest = DatasetManifest(
        normalized_dataset_id,
        DatasetLayer.NORMALIZED_PIT,
        _object_uri(content),
        sha256_digest(content),
        "official_dominant_open_interest_daily_pit",
        OFFICIAL_DAILY_DATASET_SCHEMA,
        TimeCoverage(min(event_times, key=lambda item: item.value), max(event_times, key=lambda item: item.value)),
        instruments,
        SourceProvenance(
            f"{source.value} official daily futures archive",
            _SOURCE_ROOT[source],
            as_of,
            max(published, key=lambda item: item.value) if published else None,
            canonical_sha256(revision_payload),
        ),
        license_terms,
        as_of,
        as_of,
        QualityReport(
            DataQualityLevel.Q2_RESEARCH,
            "Unadjusted daily dominant-contract research series; component rolls remain explicit.",
            as_of,
            ("retrospective sealed replay only", "not execution data", "roll discontinuities are unadjusted"),
        ),
        RevisionInfo(1, "initial governed retrospective research series", as_of),
        OFFICIAL_RESEARCH_SERIES_NORMALIZER,
        tuple(raw_dataset_ids),
    )
    return OfficialResearchSeriesBundle(tuple(raw_datasets), StoredDataset(manifest, content), records)


def _dominant(bars: tuple[OfficialDailyBar, ...], variety: str) -> OfficialDailyBar:
    candidates = tuple(item for item in bars if item.variety == variety)
    if not candidates:
        raise ValueError(f"official daily response is missing research variety {variety}")
    return min(candidates, key=lambda item: (-item.open_interest, -item.volume, item.contract))


def _series_record(raw: OfficialDailyRawFile, bar: OfficialDailyBar) -> PointInTimeRecord:
    source = raw.source.value
    return PointInTimeRecord(
        bar.to_point_in_time().event_time,
        raw.acquired_at,
        MappingProxyType(
            {
                "instrument_id": f"{source}.{bar.variety}.DOMINANT_OI",
                "component_instrument": bar.instrument,
                "variety": bar.variety,
                "trading_date": bar.trading_date,
                "open": _text(bar.open),
                "high": _text(bar.high),
                "low": _text(bar.low),
                "close": _text(bar.close),
                "settle": _text(bar.settle),
                "pre_settle": _text(bar.pre_settle),
                "volume": bar.volume,
                "open_interest": bar.open_interest,
                "turnover": str(bar.turnover),
                "price_unit": "CNY/contract_quote_unit",
                "volume_unit": "contracts",
                "open_interest_unit": "contracts",
                "raw_content_hash": raw.content_hash,
                "source_last_modified_at": (
                    raw.source_last_modified_at.to_dict()["recorded_at"] if raw.source_last_modified_at else None
                ),
                "source_etag": raw.source_etag,
                "roll_policy": OFFICIAL_RESEARCH_ROLL_POLICY,
            }
        ),
    )


def _raw_dataset(
    raw: OfficialDailyRawFile,
    dataset_id: EntityId,
    bars: tuple[OfficialDailyBar, ...],
    license_terms: LicenseTerms,
) -> StoredDataset:
    event_times = tuple(item.to_point_in_time().event_time for item in bars)
    manifest = DatasetManifest(
        dataset_id,
        DatasetLayer.RAW,
        _object_uri(raw.content),
        raw.content_hash,
        "official_exchange_daily_raw",
        OFFICIAL_DAILY_DATASET_SCHEMA,
        TimeCoverage(min(event_times, key=lambda item: item.value), max(event_times, key=lambda item: item.value)),
        tuple(sorted(item.instrument for item in bars)),
        SourceProvenance(
            f"{raw.source.value} official daily futures",
            raw.final_url,
            raw.acquired_at,
            raw.source_last_modified_at,
            f"etag={raw.source_etag};content={raw.content_hash}" if raw.source_etag else raw.content_hash,
        ),
        license_terms,
        raw.acquired_at,
        raw.acquired_at,
        QualityReport(DataQualityLevel.Q2_RESEARCH, "Exact official exchange daily response bytes.", raw.acquired_at),
        RevisionInfo(1, "initial exact official daily acquisition", raw.acquired_at),
    )
    return StoredDataset(manifest, raw.content)


def _record_payload(record: PointInTimeRecord) -> JsonValue:
    return {
        "event_time": record.event_time.to_dict()["recorded_at"],
        "available_time": record.available_time.to_dict()["recorded_at"],
        "values": cast(JsonValue, dict(record.values)),
    }


def _object_uri(content: bytes) -> str:
    return f"objects/{sha256_digest(content).removeprefix('sha256:')}"


def _text(value: object | None) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "OFFICIAL_RESEARCH_ROLL_POLICY",
    "OFFICIAL_RESEARCH_SERIES_NORMALIZER",
    "OfficialResearchSeriesBundle",
    "materialize_official_research_series",
]
