"""Collect and freeze the official-data input for MVP-R sealed replay."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

from futures_agent_os.adapters import (
    OfficialDailySource,
    OfficialDailyRawFile,
    OfficialExchangeDailyClient,
    UrlLibReadOnlyTransport,
    materialize_official_research_series,
    normalize_official_daily,
)
from futures_agent_os.reference_market_data import DatasetLayer, LicenseTerms, LocalFileDataStore
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import RecordedAt, canonical_json_text, canonical_sha256


_VARIETIES = {
    OfficialDailySource.SHFE: ("AG", "CU"),
    OfficialDailySource.CZCE: ("MA", "SR"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=Path("datasets/mvp-r-001"))
    args = parser.parse_args()
    if args.end < args.start:
        raise SystemExit("--end must not precede --start")

    acquired_at = RecordedAt.from_datetime(datetime.now(UTC))
    client = OfficialExchangeDailyClient(UrlLibReadOnlyTransport(), timeout_seconds=15, maximum_bytes=20_000_000)
    collected: dict[OfficialDailySource, list[OfficialDailyRawFile]] = {source: [] for source in OfficialDailySource}
    attempted = 0
    for trading_date in _weekdays(args.start, args.end):
        for source in OfficialDailySource:
            attempted += 1
            try:
                raw = client.fetch(source, trading_date, acquired_at=acquired_at)
                bars = normalize_official_daily(raw)
                if not all(any(bar.variety == variety for bar in bars) for variety in _VARIETIES[source]):
                    continue
                collected[source].append(raw)
            except HTTPError, URLError, TimeoutError, ValueError:
                continue
        if attempted % 40 == 0:
            print(
                f"attempted={attempted} shfe={len(collected[OfficialDailySource.SHFE])} "
                f"czce={len(collected[OfficialDailySource.CZCE])}",
                flush=True,
            )

    license_terms = LicenseTerms(
        "project-governed public exchange research use",
        "personal non-commercial research and simulation",
        "local immutable evidence retention",
        "no raw redistribution",
        "research environments only",
    )
    raw_store = LocalFileDataStore(args.output / "raw", DatasetLayer.RAW)
    normalized_store = LocalFileDataStore(args.output / "normalized", DatasetLayer.NORMALIZED_PIT)
    bundles = []
    for source in OfficialDailySource:
        raw_files = tuple(collected[source])
        if len(raw_files) < 40:
            raise SystemExit(f"insufficient {source.value} trading days: {len(raw_files)}")
        raw_ids = tuple(
            semantic_entity_id(
                "dataset",
                {
                    "mvp": "MVP-R-001",
                    "layer": "RAW",
                    "source": source.value,
                    "trading_date": raw.trading_date.isoformat(),
                    "content_sha256": raw.content_hash,
                    "acquired_at": acquired_at.to_dict()["recorded_at"],
                },
            )
            for raw in raw_files
        )
        normalized_id = semantic_entity_id(
            "dataset",
            {
                "mvp": "MVP-R-001",
                "layer": "NORMALIZED_PIT",
                "source": source.value,
                "raw_dataset_ids": tuple(str(value) for value in raw_ids),
                "acquired_at": acquired_at.to_dict()["recorded_at"],
            },
        )
        bundle = materialize_official_research_series(
            raw_files,
            varieties=_VARIETIES[source],
            license_terms=license_terms,
            raw_dataset_ids=raw_ids,
            normalized_dataset_id=normalized_id,
            as_of=acquired_at,
        )
        for raw_dataset in bundle.raw:
            raw_store.put(raw_dataset)
        normalized_store.put(bundle.normalized_pit)
        bundles.append(bundle)

    summary = {
        "task": "MVP-R-001",
        "mode": "RETROSPECTIVE_SEALED_REPLAY",
        "acquired_at": acquired_at.to_dict()["recorded_at"],
        "requested_range": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "sources": tuple(
            {
                "source": source.value,
                "trading_days": len(collected[source]),
                "normalized_dataset_id": str(bundle.normalized_pit.manifest.dataset_id),
                "normalized_content_sha256": bundle.normalized_pit.manifest.content_hash,
                "record_count": len(bundle.records),
                "instrument_universe": bundle.normalized_pit.manifest.instrument_universe,
            }
            for source, bundle in zip(OfficialDailySource, bundles, strict=True)
        ),
    }
    envelope = {**summary, "summary_sha256": canonical_sha256(summary)}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "collection-summary.json").write_text(canonical_json_text(envelope) + "\n", encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2))


def _weekdays(start: date, end: date) -> tuple[date, ...]:
    values = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor += timedelta(days=1)
    return tuple(values)


if __name__ == "__main__":
    main()
