"""Reproducible synthetic golden data for Reference & Market Data contracts.

These fixtures are intentionally low-frequency observations.  They exercise
data-quality and point-in-time semantics; they are not tick, order-book, or
execution-fidelity evidence.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Any

from futures_agent_os.reference_market_data.data_lake import (
    DataQualityLevel,
    DatasetLayer,
    DatasetManifest,
    LicenseTerms,
    PointInTimeRecord,
    QualityReport,
    RevisionInfo,
    SourceProvenance,
    TimeCoverage,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


DATASET_VERSION = "v0-012.1"
DATASET_ID = "dataset_018f9b16-9a00-7abd-8000-000000000013"
BUNDLE_ID = "dataset_bundle_018f9b16-9a00-7abe-8000-000000000014"
BUNDLE_VERSION = "golden-bundle-v0-012.1"
BUNDLE_REVISION = 1
SCHEMA_NAME = "futures_agent_os.synthetic_golden_market_event"
UNIVERSE = ("AG", "CU", "RB", "JM", "I", "MA", "SA", "M", "P", "SR", "SC", "JD")
REQUIRED_CASES = frozenset(
    {"night_session", "rule_change", "price_limit", "gap", "no_liquidity", "out_of_order", "missing_data"}
)


def _at(value: str) -> str:
    """Normalize a fixed ISO-8601 timestamp to the repository's UTC spelling."""
    return RecordedAt.from_datetime(datetime.fromisoformat(value.replace("Z", "+00:00"))).to_dict()["recorded_at"]


def _event(
    case_id: str,
    sequence: int,
    variety: str,
    contract: str,
    event_time: str,
    available_time: str,
    trading_date: str,
    *,
    open_price: str | None,
    high_price: str | None,
    low_price: str | None,
    close_price: str | None,
    volume: int | None,
    rule_version: str,
    quality_flags: tuple[str, ...] = (),
    **extra: object,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "sequence": sequence,
        "variety": variety,
        "instrument": contract,
        "event_time": _at(event_time),
        "available_time": _at(available_time),
        "trading_date": trading_date,
        "observation_kind": "bar_1m",
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "rule_version": rule_version,
        "quality_flags": list(quality_flags),
        **extra,
    }


def golden_events() -> tuple[dict[str, object], ...]:
    """Return canonical records in source-arrival order, including bad-order cases."""
    return tuple(
        sorted(
            (
                _event(
                    "night_session",
                    1,
                    "AG",
                    "SHFE.AG2602",
                    "2026-01-05T13:01:00Z",
                    "2026-01-05T13:01:05Z",
                    "2026-01-06",
                    open_price="7421",
                    high_price="7424",
                    low_price="7418",
                    close_price="7422",
                    volume=128,
                    rule_version="SHFE.AG.2026-01",
                    quality_flags=("NIGHT_SESSION",),
                    market_time="2026-01-05T21:01:00+08:00",
                ),
                _event(
                    "rule_change",
                    1,
                    "CU",
                    "SHFE.CU2603",
                    "2026-01-06T01:00:00Z",
                    "2026-01-06T01:00:03Z",
                    "2026-01-06",
                    open_price="68120",
                    high_price="68160",
                    low_price="68100",
                    close_price="68140",
                    volume=91,
                    rule_version="SHFE.CU.2026-01",
                    rule_effective_from="2026-01-01T00:00:00Z",
                    margin_rate="0.12",
                ),
                _event(
                    "rule_change",
                    2,
                    "CU",
                    "SHFE.CU2603",
                    "2026-01-07T01:00:00Z",
                    "2026-01-07T01:00:04Z",
                    "2026-01-07",
                    open_price="67940",
                    high_price="67980",
                    low_price="67900",
                    close_price="67920",
                    volume=103,
                    rule_version="SHFE.CU.2026-02",
                    rule_effective_from="2026-01-07T00:00:00Z",
                    margin_rate="0.14",
                    quality_flags=("RULE_VERSION_CHANGED",),
                ),
                _event(
                    "price_limit",
                    1,
                    "RB",
                    "SHFE.RB2605",
                    "2026-01-08T01:00:00Z",
                    "2026-01-08T01:00:02Z",
                    "2026-01-08",
                    open_price="3330",
                    high_price="3420",
                    low_price="3328",
                    close_price="3420",
                    volume=811,
                    rule_version="SHFE.RB.2026-01",
                    price_limit_upper="3420",
                    price_limit_lower="3180",
                    quality_flags=("AT_UPPER_LIMIT",),
                ),
                _event(
                    "price_limit",
                    2,
                    "RB",
                    "SHFE.RB2605",
                    "2026-01-08T01:01:00Z",
                    "2026-01-08T01:01:06Z",
                    "2026-01-08",
                    open_price="3210",
                    high_price="3212",
                    low_price="3180",
                    close_price="3180",
                    volume=627,
                    rule_version="SHFE.RB.2026-01",
                    price_limit_upper="3420",
                    price_limit_lower="3180",
                    quality_flags=("AT_LOWER_LIMIT",),
                ),
                _event(
                    "gap",
                    1,
                    "JM",
                    "DCE.JM2605",
                    "2026-01-08T01:00:00Z",
                    "2026-01-08T01:00:02Z",
                    "2026-01-08",
                    open_price="1190",
                    high_price="1202",
                    low_price="1186",
                    close_price="1195",
                    volume=344,
                    rule_version="DCE.JM.2026-01",
                    previous_close="1120",
                    gap_pct="0.0625",
                    quality_flags=("GAP_OPEN",),
                ),
                _event(
                    "no_liquidity",
                    1,
                    "I",
                    "DCE.I2605",
                    "2026-01-08T01:00:00Z",
                    "2026-01-08T01:00:04Z",
                    "2026-01-08",
                    open_price=None,
                    high_price=None,
                    low_price=None,
                    close_price=None,
                    volume=0,
                    rule_version="DCE.I.2026-01",
                    quality_flags=("NO_LIQUIDITY", "NO_QUOTE"),
                    best_bid=None,
                    best_ask=None,
                ),
                _event(
                    "out_of_order",
                    2,
                    "MA",
                    "CZCE.MA605",
                    "2026-01-08T01:02:00Z",
                    "2026-01-08T01:02:03Z",
                    "2026-01-08",
                    open_price="2281",
                    high_price="2284",
                    low_price="2279",
                    close_price="2280",
                    volume=51,
                    rule_version="CZCE.MA.2026-01",
                    quality_flags=("SOURCE_ARRIVAL_OUT_OF_ORDER",),
                ),
                _event(
                    "out_of_order",
                    1,
                    "MA",
                    "CZCE.MA605",
                    "2026-01-08T01:01:00Z",
                    "2026-01-08T01:03:00Z",
                    "2026-01-08",
                    open_price="2278",
                    high_price="2282",
                    low_price="2277",
                    close_price="2281",
                    volume=64,
                    rule_version="CZCE.MA.2026-01",
                    quality_flags=("SOURCE_ARRIVAL_OUT_OF_ORDER", "LATE_EVENT"),
                ),
                _event(
                    "missing_data",
                    1,
                    "SA",
                    "CZCE.SA605",
                    "2026-01-08T01:00:00Z",
                    "2026-01-08T01:05:00Z",
                    "2026-01-08",
                    open_price=None,
                    high_price=None,
                    low_price=None,
                    close_price=None,
                    volume=None,
                    rule_version="CZCE.SA.2026-01",
                    quality_flags=("MISSING_BAR", "LATE_PUBLICATION"),
                    missing_interval_start="2026-01-08T01:00:00Z",
                    missing_interval_end="2026-01-08T01:04:00Z",
                ),
                _event(
                    "margin_change",
                    1,
                    "M",
                    "DCE.M2605",
                    "2026-01-08T01:00:00Z",
                    "2026-01-08T01:00:03Z",
                    "2026-01-08",
                    open_price="2831",
                    high_price="2836",
                    low_price="2828",
                    close_price="2834",
                    volume=451,
                    rule_version="DCE.M.2026-02",
                    margin_rate="0.15",
                    quality_flags=("RULE_VERSION_CHANGED", "MARGIN_CHANGED"),
                ),
                _event(
                    "close_today_fee",
                    1,
                    "P",
                    "DCE.P2605",
                    "2026-01-08T01:00:00Z",
                    "2026-01-08T01:00:03Z",
                    "2026-01-08",
                    open_price="8750",
                    high_price="8772",
                    low_price="8746",
                    close_price="8760",
                    volume=226,
                    rule_version="DCE.P.2026-01",
                    close_today_fee="0.0005",
                ),
                _event(
                    "near_delivery",
                    1,
                    "SR",
                    "CZCE.SR603",
                    "2026-02-20T01:00:00Z",
                    "2026-02-20T01:00:02Z",
                    "2026-02-20",
                    open_price="5701",
                    high_price="5710",
                    low_price="5696",
                    close_price="5705",
                    volume=39,
                    rule_version="CZCE.SR.2026-02",
                    days_to_delivery=8,
                    quality_flags=("NEAR_DELIVERY",),
                ),
                _event(
                    "abnormal_settlement",
                    1,
                    "SC",
                    "INE.SC2603",
                    "2026-02-20T07:00:00Z",
                    "2026-02-20T07:00:08Z",
                    "2026-02-20",
                    open_price="510.2",
                    high_price="513.8",
                    low_price="509.1",
                    close_price="512.6",
                    volume=587,
                    rule_version="INE.SC.2026-01",
                    settlement_price="498.0",
                    quality_flags=("ABNORMAL_SETTLEMENT",),
                ),
                _event(
                    "correlation_spike",
                    1,
                    "JD",
                    "DCE.JD2605",
                    "2026-02-20T01:00:00Z",
                    "2026-02-20T01:00:03Z",
                    "2026-02-20",
                    open_price="3550",
                    high_price="3571",
                    low_price="3548",
                    close_price="3568",
                    volume=119,
                    rule_version="DCE.JD.2026-01",
                    correlation_to_M="0.93",
                    quality_flags=("CORRELATION_SPIKE",),
                ),
            ),
            key=lambda event: str(event["available_time"]),
        )
    )


def golden_case_catalog() -> tuple[dict[str, object], ...]:
    """Explain each product's fixture role and expected handling boundary."""
    return (
        {
            "case_id": "night_session",
            "variety": "AG",
            "product_reason": "Adds SHFE precious-metal night-session coverage not supplied by the daytime DCE/CZCE fixtures; the synthetic night_session case is only AG's acceptance fixture.",
            "expected_disposition": "retain explicit trading_date; never infer it from calendar date.",
        },
        {
            "case_id": "rule_change",
            "variety": "CU",
            "product_reason": "Adds a second SHFE metal whose mutable margin rule is distinct from AG's calendar case; the synthetic rule_change case is only CU's acceptance fixture.",
            "expected_disposition": "select the rule version effective at the observation.",
        },
        {
            "case_id": "price_limit",
            "variety": "RB",
            "product_reason": "Adds ferrous SHFE price-limit mechanics rather than duplicating non-ferrous metals; the synthetic price_limit case is only RB's acceptance fixture.",
            "expected_disposition": "flag either limit state; do not assume executable liquidity.",
        },
        {
            "case_id": "gap",
            "variety": "JM",
            "product_reason": "Adds DCE coal-chain exposure and a discontinuous-open regime distinct from metals and oils; the synthetic gap case is only JM's acceptance fixture.",
            "expected_disposition": "preserve the prior-close reference and gap flag.",
        },
        {
            "case_id": "no_liquidity",
            "variety": "I",
            "product_reason": "Adds DCE ferrous raw-material coverage with an unavailable quote boundary distinct from RB's limit state; the synthetic no_liquidity case is only I's acceptance fixture.",
            "expected_disposition": "treat as unavailable for decision/execution use.",
        },
        {
            "case_id": "out_of_order",
            "variety": "MA",
            "product_reason": "Adds CZCE chemical coverage and delayed-event ingestion behavior not represented by DCE or SHFE cases; the synthetic out_of_order case is only MA's acceptance fixture.",
            "expected_disposition": "retain event and availability times; do not silently reorder source evidence.",
        },
        {
            "case_id": "missing_data",
            "variety": "SA",
            "product_reason": "Adds a second CZCE chemical with explicit missing-bar quality semantics, complementary to MA's late event; the synthetic missing_data case is only SA's acceptance fixture.",
            "expected_disposition": "surface Q1-style quality flags; no fabricated bar.",
        },
        {
            "case_id": "margin_change",
            "variety": "M",
            "product_reason": "Adds DCE oilseed-meal agricultural coverage and a margin-change field distinct from CU's metal rule revision; the synthetic margin_change case is only M's acceptance fixture.",
            "expected_disposition": "bind calculations to the recorded rule version.",
        },
        {
            "case_id": "close_today_fee",
            "variety": "P",
            "product_reason": "Adds DCE edible-oil coverage and close-today fee semantics distinct from M's oilseed-meal contract; the synthetic close_today_fee case is only P's acceptance fixture.",
            "expected_disposition": "preserve fee semantics for later simulation contracts.",
        },
        {
            "case_id": "near_delivery",
            "variety": "SR",
            "product_reason": "Adds CZCE soft-commodity delivery-window coverage outside the chemical fixtures; the synthetic near_delivery case is only SR's acceptance fixture.",
            "expected_disposition": "surface delivery proximity rather than treating it as ordinary liquidity.",
        },
        {
            "case_id": "abnormal_settlement",
            "variety": "SC",
            "product_reason": "Adds INE energy and separate settlement-reference behavior absent from domestic commodity cases; the synthetic abnormal_settlement case is only SC's acceptance fixture.",
            "expected_disposition": "keep settlement reference distinct from intraday close.",
        },
        {
            "case_id": "correlation_spike",
            "variety": "JD",
            "product_reason": "Adds DCE livestock coverage and a cross-variety correlation stress marker not duplicated by price-only cases; the synthetic correlation_spike case is only JD's acceptance fixture.",
            "expected_disposition": "preserve the evidence flag; no portfolio conclusion is encoded.",
        },
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def event_content() -> bytes:
    return b"".join(_json_bytes(event) for event in golden_events())


def case_catalog_content() -> bytes:
    return _json_bytes({"dataset_version": DATASET_VERSION, "cases": golden_case_catalog()})


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _recorded_at(value: str) -> RecordedAt:
    return RecordedAt.parse(value)


def manifest_for(content: bytes) -> DatasetManifest:
    events = golden_events()
    event_times = tuple(_recorded_at(str(event["event_time"])) for event in events)
    return DatasetManifest(
        dataset_id=EntityId.parse(DATASET_ID),
        layer=DatasetLayer.NORMALIZED_PIT,
        object_uri="datasets/v0-012/golden_market_events.jsonl",
        content_hash=_sha256(content),
        schema_name=SCHEMA_NAME,
        schema_version=SchemaVersion(1, 0),
        coverage=TimeCoverage(
            min(event_times, key=lambda value: value.value), max(event_times, key=lambda value: value.value)
        ),
        instrument_universe=UNIVERSE,
        provenance=SourceProvenance(
            "futures-agent-os synthetic scenario generator",
            "synthetic://futures-agent-os/v0-012",
            _recorded_at("2026-02-21T00:00:00Z"),
            source_revision=DATASET_VERSION,
        ),
        license=LicenseTerms(
            "CC0-1.0",
            "research and simulation",
            "repository lifetime",
            "redistribution permitted",
            "development and CI only",
        ),
        as_of=_recorded_at("2026-02-21T00:00:00Z"),
        ingested_at=_recorded_at("2026-02-21T00:00:00Z"),
        quality=QualityReport(
            DataQualityLevel.Q2_RESEARCH,
            "Intentional edge cases are flagged per record; not execution-fidelity data.",
            _recorded_at("2026-02-21T00:00:00Z"),
            tuple(sorted(REQUIRED_CASES)),
        ),
        revision=RevisionInfo(
            1,
            "initial deterministic synthetic golden dataset release",
            _recorded_at("2026-02-21T00:00:00Z"),
        ),
        generated_by="futures_agent_os.reference_market_data.golden_datasets/v0-012.1",
    )


def bundle_manifest_content(events: bytes, event_manifest: bytes, catalog: bytes) -> bytes:
    """Bind independently distributable events and catalog bytes into one release."""
    return _json_bytes(
        {
            "bundle_id": BUNDLE_ID,
            "dataset_id": DATASET_ID,
            "dataset_version": DATASET_VERSION,
            "bundle_version": BUNDLE_VERSION,
            "schema_name": "futures_agent_os.synthetic_golden_bundle",
            "schema_version": "1.0",
            "provenance": {
                "source_name": "futures-agent-os synthetic scenario generator",
                "source_uri": "synthetic://futures-agent-os/v0-012",
                "generated_at": "2026-02-21T00:00:00Z",
                "source_revision": BUNDLE_VERSION,
            },
            "revision": {
                "revision": BUNDLE_REVISION,
                "supersedes_bundle_id": None,
            },
            "members": {
                "events": {
                    "object_uri": "datasets/v0-012/golden_market_events.jsonl",
                    "content_hash": _sha256(events),
                },
                "events_manifest": {
                    "object_uri": "datasets/v0-012/golden_market_events.manifest.json",
                    "content_hash": _sha256(event_manifest),
                },
                "catalog": {
                    "object_uri": "datasets/v0-012/cases.json",
                    "content_hash": _sha256(catalog),
                },
            },
        }
    )


def manifest_content(content: bytes) -> bytes:
    manifest = manifest_for(content)
    return _json_bytes(
        {
            "dataset_id": str(manifest.dataset_id),
            "layer": manifest.layer.value,
            "object_uri": manifest.object_uri,
            "content_hash": manifest.content_hash,
            "schema_name": manifest.schema_name,
            "schema_version": str(manifest.schema_version),
            "coverage": {
                "start": manifest.coverage.start.to_dict()["recorded_at"],
                "end": manifest.coverage.end.to_dict()["recorded_at"],
            },
            "instrument_universe": list(manifest.instrument_universe),
            "provenance": {
                "source_name": manifest.provenance.source_name,
                "source_uri": manifest.provenance.source_uri,
                "acquired_at": manifest.provenance.acquired_at.to_dict()["recorded_at"],
                "source_published_at": None,
                "source_revision": manifest.provenance.source_revision,
            },
            "license": {
                "license_name": manifest.license.license_name,
                "allowed_use": manifest.license.allowed_use,
                "retention_policy": manifest.license.retention_policy,
                "redistribution_policy": manifest.license.redistribution_policy,
                "environment_restriction": manifest.license.environment_restriction,
            },
            "as_of": manifest.as_of.to_dict()["recorded_at"],
            "ingested_at": manifest.ingested_at.to_dict()["recorded_at"],
            "quality": {
                "level": manifest.quality.level.value,
                "summary": manifest.quality.summary,
                "checked_at": manifest.quality.checked_at.to_dict()["recorded_at"],
                "issues": list(manifest.quality.issues),
            },
            "revision": {
                "revision": manifest.revision.revision,
                "reason": manifest.revision.reason,
                "revised_at": manifest.revision.revised_at.to_dict()["recorded_at"],
                "supersedes_dataset_id": str(manifest.revision.supersedes_dataset_id)
                if manifest.revision.supersedes_dataset_id
                else None,
            },
            "generated_by": manifest.generated_by,
            "upstream_manifest_ids": [],
        }
    )


def write_golden_dataset(root: Path) -> None:
    """Write only deterministic, reviewable fixture files under *root*."""
    root.mkdir(parents=True, exist_ok=True)
    events = event_content()
    event_manifest = manifest_content(events)
    catalog = case_catalog_content()
    (root / "golden_market_events.jsonl").write_bytes(events)
    (root / "golden_market_events.manifest.json").write_bytes(event_manifest)
    (root / "cases.json").write_bytes(catalog)
    (root / "golden_bundle.manifest.json").write_bytes(bundle_manifest_content(events, event_manifest, catalog))


def validate_golden_dataset(root: Path) -> None:
    """Validate reproducibility, manifest lineage, PIT timing, and boundary cases."""
    expected_content = event_content()
    expected_catalog = case_catalog_content()
    expected_event_manifest = manifest_content(expected_content)
    expected_files = {
        "golden_market_events.jsonl": expected_content,
        "golden_market_events.manifest.json": expected_event_manifest,
        "cases.json": expected_catalog,
        "golden_bundle.manifest.json": bundle_manifest_content(
            expected_content, expected_event_manifest, expected_catalog
        ),
    }
    for name, expected in expected_files.items():
        if (root / name).read_bytes() != expected:
            raise ValueError(f"golden dataset file is not reproducible: {name}")

    events = tuple(json.loads(line) for line in expected_content.splitlines())
    manifest = manifest_for(expected_content)
    manifest.validate_point_in_time(
        tuple(
            PointInTimeRecord(_recorded_at(event["event_time"]), _recorded_at(event["available_time"]), event)
            for event in events
        )
    )
    if {event["variety"] for event in events} != set(UNIVERSE):
        raise ValueError("golden dataset does not represent the complete acceptance universe")
    bundle = json.loads((root / "golden_bundle.manifest.json").read_bytes())
    if bundle["members"]["events"]["content_hash"] != _sha256(expected_content):
        raise ValueError("golden bundle does not bind event content")
    if bundle["members"]["events_manifest"]["content_hash"] != _sha256(expected_event_manifest):
        raise ValueError("golden bundle does not bind event manifest content")
    if bundle["members"]["catalog"]["content_hash"] != _sha256(expected_catalog):
        raise ValueError("golden bundle does not bind catalog content")
    cases = json.loads(expected_catalog)["cases"]
    if len(cases) != len(UNIVERSE) or {case["variety"] for case in cases} != set(UNIVERSE):
        raise ValueError("golden catalog must contain each acceptance-universe variety exactly once")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("golden catalog case identifiers must be unique")
    if any(
        not isinstance(case["product_reason"], str)
        or not case["product_reason"].strip()
        or "synthetic" not in case["product_reason"].lower()
        or not isinstance(case["expected_disposition"], str)
        or not case["expected_disposition"].strip()
        for case in cases
    ):
        raise ValueError("golden catalog requires non-empty fixture-scoped product reasons and dispositions")
    case_ids = {case["case_id"] for case in cases}
    if not REQUIRED_CASES <= case_ids:
        raise ValueError("golden dataset does not cover required boundary cases")

    by_case: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_case.setdefault(event["case_id"], []).append(event)
    if [event["available_time"] for event in events] != sorted(event["available_time"] for event in events):
        raise ValueError("golden events must be globally ordered by source-arrival availability")
    night = by_case["night_session"][0]
    if night["trading_date"] == night["market_time"][:10]:
        raise ValueError("night-session sample must prove an explicit non-calendar trading date")
    rules = by_case["rule_change"]
    if (
        len(rules) != 2
        or [record["rule_effective_from"] for record in rules]
        != sorted(record["rule_effective_from"] for record in rules)
        or any(
            _recorded_at(record["rule_effective_from"]).value > _recorded_at(record["event_time"]).value
            for record in rules
        )
        or len({record["rule_version"] for record in rules}) != 2
        or len({Decimal(str(record["margin_rate"])) for record in rules}) != 2
    ):
        raise ValueError("rule-change sample must preserve effective-time, version, and margin-rate changes")
    limits = by_case["price_limit"]
    has_upper = any(
        record["high"] == record["close"] == record["price_limit_upper"] and "AT_UPPER_LIMIT" in record["quality_flags"]
        for record in limits
    )
    has_lower = any(
        record["low"] == record["close"] == record["price_limit_lower"] and "AT_LOWER_LIMIT" in record["quality_flags"]
        for record in limits
    )
    if not has_upper or not has_lower:
        raise ValueError("price-limit sample must include upper and lower limit semantics")
    gap = by_case["gap"][0]
    calculated_gap = (Decimal(str(gap["open"])) - Decimal(str(gap["previous_close"]))) / Decimal(
        str(gap["previous_close"])
    )
    if calculated_gap != Decimal(str(gap["gap_pct"])) or calculated_gap <= Decimal("0.05"):
        raise ValueError("gap sample must contain a materially discontinuous, exact Decimal gap")
    illiquid = by_case["no_liquidity"][0]
    if (
        any(illiquid[field] is not None for field in ("open", "high", "low", "close"))
        or illiquid["volume"] != 0
        or illiquid["best_bid"] is not None
        or illiquid["best_ask"] is not None
        or not {"NO_LIQUIDITY", "NO_QUOTE"} <= set(illiquid["quality_flags"])
    ):
        raise ValueError("no-liquidity sample is incomplete")
    unordered = by_case["out_of_order"]
    if [record["available_time"] for record in unordered] != sorted(record["available_time"] for record in unordered):
        raise ValueError("out-of-order sample must retain ascending source-arrival availability")
    if [record["event_time"] for record in unordered] == sorted(record["event_time"] for record in unordered):
        raise ValueError("out-of-order sample must have event-time disorder")
    missing = by_case["missing_data"][0]
    if (
        any(missing[field] is not None for field in ("open", "high", "low", "close", "volume"))
        or _recorded_at(missing["missing_interval_start"]).value > _recorded_at(missing["missing_interval_end"]).value
        or _recorded_at(missing["available_time"]).value <= _recorded_at(missing["missing_interval_end"]).value
        or not {"MISSING_BAR", "LATE_PUBLICATION"} <= set(missing["quality_flags"])
    ):
        raise ValueError("missing-data sample must not fabricate a bar")


def repository_dataset_root() -> Path:
    return Path(__file__).resolve().parents[3] / "datasets" / "v0-012"
