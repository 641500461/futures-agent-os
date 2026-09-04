"""Governed materialization of official daily files into data-lake objects."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, cast

from futures_agent_os.adapters.official_daily_bars import OfficialDailyBar, normalize_official_daily
from futures_agent_os.adapters.official_exchange_daily import OfficialDailyRawFile, OfficialDailySource
from futures_agent_os.reference_market_data.data_lake import (
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
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_json_text
from futures_agent_os.shared_kernel.observability import JsonValue


OFFICIAL_DAILY_DATASET_SCHEMA = SchemaVersion(1, 0)
OFFICIAL_DAILY_NORMALIZER = "official-daily-normalizer.v1"
_ALLOWED_VARIETIES: Mapping[OfficialDailySource, frozenset[str]] = MappingProxyType(
    {
        OfficialDailySource.SHFE: frozenset({"AG", "CU"}),
        OfficialDailySource.CZCE: frozenset({"MA", "SR"}),
    }
)


@dataclass(frozen=True, slots=True)
class OfficialDailyDatasetBundle:
    raw: StoredDataset
    normalized_pit: StoredDataset
    records: tuple[PointInTimeRecord, ...]

    def __post_init__(self) -> None:
        if self.raw.manifest.layer is not DatasetLayer.RAW:
            raise ValueError("official daily bundle requires a RAW dataset")
        if self.normalized_pit.manifest.layer is not DatasetLayer.NORMALIZED_PIT:
            raise ValueError("official daily bundle requires a NORMALIZED_PIT dataset")
        self.normalized_pit.manifest.validate_point_in_time(self.records)


def materialize_official_daily_datasets(
    raw: OfficialDailyRawFile,
    normalized_bars: tuple[OfficialDailyBar, ...],
    *,
    varieties: tuple[str, ...],
    license_terms: LicenseTerms,
    raw_dataset_id: EntityId,
    normalized_dataset_id: EntityId,
    as_of: RecordedAt,
) -> OfficialDailyDatasetBundle:
    """Create immutable raw and normalized datasets from one exact response.

    ``as_of`` must equal the actual acquisition time.  This deliberately
    prevents a historical exchange filename from being presented as if it had
    been acquired or visible at that historical date.
    """

    if type(raw) is not OfficialDailyRawFile or type(normalized_bars) is not tuple:
        raise TypeError("official daily materialization requires exact raw and tuple bar inputs")
    if type(license_terms) is not LicenseTerms or type(as_of) is not RecordedAt:
        raise TypeError("official daily materialization requires typed governance inputs")
    if any(type(item) is not OfficialDailyBar for item in normalized_bars):
        raise TypeError("official daily materialization requires exact OfficialDailyBar records")
    if any(
        type(value) is not EntityId or value.namespace != "dataset" for value in (raw_dataset_id, normalized_dataset_id)
    ):
        raise ValueError("official daily materialization requires dataset identities")
    if raw_dataset_id == normalized_dataset_id:
        raise ValueError("raw and normalized datasets require distinct identities")
    if as_of != raw.acquired_at:
        raise ValueError("official daily as_of must equal actual acquisition time")

    requested = tuple(value.upper() for value in varieties)
    if not requested or len(set(requested)) != len(requested) or requested != tuple(sorted(requested)):
        raise ValueError("official daily varieties must be non-empty, unique, and sorted")
    if not set(requested) <= _ALLOWED_VARIETIES[raw.source]:
        raise ValueError("official daily varieties are outside the source-qualified MVP universe")

    expected = normalize_official_daily(raw)
    if normalized_bars != expected:
        raise ValueError("normalized bars do not match the exact official raw response")
    selected = tuple(bar for bar in normalized_bars if bar.variety in requested)
    if {bar.variety for bar in selected} != set(requested):
        raise ValueError("official daily response is missing a requested variety")
    _validate_selected(raw, selected)

    records = tuple(bar.to_point_in_time() for bar in selected)
    event_times = tuple(record.event_time for record in records)
    coverage = TimeCoverage(
        min(event_times, key=lambda value: value.value), max(event_times, key=lambda value: value.value)
    )
    instruments = tuple(sorted({bar.instrument for bar in selected}))
    provenance = SourceProvenance(
        source_name=f"{raw.source.value} official daily futures",
        source_uri=raw.final_url,
        acquired_at=raw.acquired_at,
        source_published_at=raw.source_last_modified_at,
        source_revision=_source_revision(raw),
    )
    raw_manifest = _manifest(
        dataset_id=raw_dataset_id,
        layer=DatasetLayer.RAW,
        content=raw.content,
        schema_name="official_exchange_daily_raw",
        coverage=coverage,
        instruments=instruments,
        provenance=provenance,
        license_terms=license_terms,
        as_of=as_of,
        generated_by=None,
        upstream=(),
    )
    normalized_content = _normalized_bytes(records)
    normalized_manifest = _manifest(
        dataset_id=normalized_dataset_id,
        layer=DatasetLayer.NORMALIZED_PIT,
        content=normalized_content,
        schema_name="official_futures_daily_bar_pit",
        coverage=coverage,
        instruments=instruments,
        provenance=provenance,
        license_terms=license_terms,
        as_of=as_of,
        generated_by=OFFICIAL_DAILY_NORMALIZER,
        upstream=(raw_dataset_id,),
    )
    bundle = OfficialDailyDatasetBundle(
        raw=StoredDataset(raw_manifest, raw.content),
        normalized_pit=StoredDataset(normalized_manifest, normalized_content),
        records=records,
    )
    return bundle


def _validate_selected(raw: OfficialDailyRawFile, selected: tuple[OfficialDailyBar, ...]) -> None:
    expected_date = raw.trading_date.isoformat()
    for bar in selected:
        if (
            bar.source is not raw.source
            or bar.trading_date != expected_date
            or bar.available_time != raw.acquired_at
            or bar.raw_content_hash != raw.content_hash
        ):
            raise ValueError("official daily bar lineage does not match the raw response")


def _source_revision(raw: OfficialDailyRawFile) -> str:
    if raw.source_etag is None:
        return raw.content_hash
    return f"etag={raw.source_etag};content={raw.content_hash}"


def _normalized_bytes(records: tuple[PointInTimeRecord, ...]) -> bytes:
    payload = tuple(
        {
            "event_time": record.event_time.to_dict()["recorded_at"],
            "available_time": record.available_time.to_dict()["recorded_at"],
            "values": cast(JsonValue, dict(record.values)),
        }
        for record in records
    )
    return canonical_json_text(payload).encode("utf-8")


def _manifest(
    *,
    dataset_id: EntityId,
    layer: DatasetLayer,
    content: bytes,
    schema_name: str,
    coverage: TimeCoverage,
    instruments: tuple[str, ...],
    provenance: SourceProvenance,
    license_terms: LicenseTerms,
    as_of: RecordedAt,
    generated_by: str | None,
    upstream: tuple[EntityId, ...],
) -> DatasetManifest:
    content_hash = sha256_digest(content)
    return DatasetManifest(
        dataset_id=dataset_id,
        layer=layer,
        object_uri=f"objects/{content_hash.removeprefix('sha256:')}",
        content_hash=content_hash,
        schema_name=schema_name,
        schema_version=OFFICIAL_DAILY_DATASET_SCHEMA,
        coverage=coverage,
        instrument_universe=instruments,
        provenance=provenance,
        license=license_terms,
        as_of=as_of,
        ingested_at=as_of,
        quality=QualityReport(
            DataQualityLevel.Q2_RESEARCH,
            "Exact official daily bytes normalized for research; no execution-fidelity claim.",
            as_of,
        ),
        revision=RevisionInfo(1, "initial exact official daily acquisition", as_of),
        generated_by=generated_by,
        upstream_manifest_ids=upstream,
    )
