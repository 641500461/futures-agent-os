"""Collect one post-Pivot official trading day into the signed forward chain."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from futures_agent_os.adapters import (
    OFFICIAL_RESEARCH_SERIES_NORMALIZER,
    OfficialDailySource,
    OfficialExchangeDailyClient,
    UrlLibReadOnlyTransport,
    materialize_official_research_series,
    normalize_official_daily,
)
from futures_agent_os.reference_market_data import (
    DatasetLayer,
    LicenseTerms,
    LocalFileDataStore,
    dataset_manifest_sha256,
)
from futures_agent_os.research_experiment import (
    DatasetAuthorizationAuthority,
    ForwardAcquiredRecord,
    ForwardCollectionAuthority,
    ForwardDailyAcquisition,
    PIVOT_FORWARD_LABEL_BARS,
    PIVOT_FORWARD_PIVOT_DATE,
    PIVOT_FORWARD_ROSTER_SIZE,
    PIVOT_FORWARD_UNIVERSE,
)
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import RecordedAt, TradingDate, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "datasets" / "mvp-r-001" / "forward"
MASTER_SECRET_PATH = ROOT / "datasets" / "mvp-r-001" / ".governance-master-key"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_VARIETIES = {
    OfficialDailySource.SHFE: ("AG", "CU"),
    OfficialDailySource.CZCE: ("MA", "SR"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-date", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    trading_date = args.trading_date or datetime.now(_SHANGHAI).date()
    if args.plan_only:
        print(json.dumps(_status(args.output, trading_date), ensure_ascii=False, indent=2))
        return
    if trading_date <= PIVOT_FORWARD_PIVOT_DATE.value:
        raise SystemExit("forward trading date must be later than the 2026-08-30 Pivot decision")
    if trading_date > datetime.now(_SHANGHAI).date():
        raise SystemExit("forward collector cannot acquire a future trading date")

    master = _master_secret()
    collection_authority = ForwardCollectionAuthority(
        "mvp-r.pivot-forward-collection",
        _key(master, "pivot-forward-collection"),
    )
    previous = _load_chain(args.output, collection_authority)
    expected_date = _next_weekday(
        previous.trading_date.value if previous is not None else PIVOT_FORWARD_PIVOT_DATE.value
    )
    if trading_date != expected_date:
        raise SystemExit(
            "forward acquisition cannot skip a weekday; an official closure attestation is required before advancing"
        )

    client = OfficialExchangeDailyClient(
        UrlLibReadOnlyTransport(),
        timeout_seconds=20,
        maximum_bytes=20_000_000,
    )
    raw_by_source = {}
    try:
        for source in OfficialDailySource:
            acquired_at = RecordedAt.from_datetime(datetime.now(UTC))
            raw = client.fetch(source, trading_date, acquired_at=acquired_at)
            bars = normalize_official_daily(raw)
            missing = tuple(
                variety for variety in _VARIETIES[source] if not any(item.variety == variety for item in bars)
            )
            if missing:
                raise ValueError(f"official daily response is missing frozen varieties: {missing}")
            raw_by_source[source] = raw
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise SystemExit(
            f"official forward acquisition failed without mutating the chain: {type(error).__name__}"
        ) from error

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
        raw = raw_by_source[source]
        raw_id = semantic_entity_id(
            "dataset",
            {
                "task": "MVP-R-001-PIVOT-FORWARD",
                "layer": "RAW",
                "source": source.value,
                "trading_date": trading_date.isoformat(),
                "content_sha256": raw.content_hash,
                "acquired_at": raw.acquired_at.to_dict()["recorded_at"],
            },
        )
        normalized_id = semantic_entity_id(
            "dataset",
            {
                "task": "MVP-R-001-PIVOT-FORWARD",
                "layer": "NORMALIZED_PIT",
                "source": source.value,
                "raw_dataset_id": str(raw_id),
                "trading_date": trading_date.isoformat(),
                "acquired_at": raw.acquired_at.to_dict()["recorded_at"],
            },
        )
        bundle = materialize_official_research_series(
            (raw,),
            varieties=_VARIETIES[source],
            license_terms=license_terms,
            raw_dataset_ids=(raw_id,),
            normalized_dataset_id=normalized_id,
            as_of=raw.acquired_at,
        )
        raw_store.put(bundle.raw[0])
        normalized_store.put(bundle.normalized_pit)
        bundles.append(bundle)

    manifest_contracts = {
        dataset_manifest_sha256(bundle.normalized_pit.manifest): canonical_sha256(
            {
                "task": "MVP-R-001-PIVOT-FORWARD",
                "source_uri": bundle.normalized_pit.manifest.provenance.source_uri,
                "source_revision": bundle.normalized_pit.manifest.provenance.source_revision,
                "trading_date": trading_date.isoformat(),
                "purpose": "sealed-forward-holdout-only",
            }
        )
        for bundle in bundles
    }
    data_authority = DatasetAuthorizationAuthority(
        "mvp-r.pivot-forward-data",
        _key(master, "pivot-forward-data"),
        manifest_contracts,
        frozenset({"sha256:" + "0" * 64}),
        frozenset({OFFICIAL_RESEARCH_SERIES_NORMALIZER}),
    )
    artifacts = []
    dataset_evidence = []
    for bundle in bundles:
        manifest_sha256 = dataset_manifest_sha256(bundle.normalized_pit.manifest)
        dataset_ref = data_authority.authorize(
            bundle.normalized_pit,
            provider_contract_sha256=manifest_contracts[manifest_sha256],
            records=bundle.records,
        )
        dataset_evidence.append(dataset_ref.to_dict())
        artifacts.extend(
            data_authority.issue_artifact(dataset_ref, str(record.values["instrument_id"]), record)
            for record in bundle.records
        )
    recorded_at = RecordedAt.from_datetime(datetime.now(UTC))
    acquisition = collection_authority.record_day(
        previous=previous,
        trading_date=TradingDate(trading_date),
        recorded_at=recorded_at,
        artifacts=tuple(artifacts),
    )
    envelope: dict[str, JsonValue] = {
        "task": "MVP-R-001-PIVOT",
        "mode": "POST_PIVOT_FORWARD_ACQUISITION",
        "acquisition": {**acquisition.unsigned_payload(), "signature_sha256": acquisition.signature_sha256},
        "dataset_evidence": tuple(dataset_evidence),
        "holdout_progress": _progress(acquisition.sequence_number),
    }
    payload: dict[str, JsonValue] = {**envelope, "envelope_sha256": canonical_sha256(envelope)}
    path = args.output / "acquisitions" / f"{trading_date.isoformat()}.json"
    _write_once(path, (canonical_json_text(payload) + "\n").encode())
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _status(output: Path, trading_date: date) -> dict[str, object]:
    files = tuple(sorted((output / "acquisitions").glob("*.json"))) if (output / "acquisitions").exists() else ()
    signed_days = len(files)
    chain_tip_date = date.fromisoformat(files[-1].stem) if files else PIVOT_FORWARD_PIVOT_DATE.value
    expected_date = _next_weekday(chain_tip_date)
    eligible_date = trading_date == expected_date
    return {
        "task": "MVP-R-001-PIVOT",
        "mode": "PLAN_ONLY_NO_NETWORK_NO_WRITE",
        "requested_trading_date": trading_date.isoformat(),
        "expected_next_weekday": expected_date.isoformat(),
        "eligible_post_pivot_date": eligible_date,
        "signed_acquisition_days": signed_days,
        "maximum_future_blind_commitments": signed_days * len(PIVOT_FORWARD_UNIVERSE),
        "minimum_commitments_before_roster_freeze": PIVOT_FORWARD_ROSTER_SIZE,
        "label_bars_after_cutoff": PIVOT_FORWARD_LABEL_BARS,
        "future_reveal_locked": True,
        "blocker": "REQUESTED_DATE_IS_NOT_NEXT_CHAIN_DAY" if not eligible_date else "OFFICIAL_DAY_NOT_YET_ACQUIRED",
    }


def _progress(signed_days: int) -> dict[str, JsonValue]:
    return {
        "signed_acquisition_days": signed_days,
        "maximum_future_blind_commitments": signed_days * len(PIVOT_FORWARD_UNIVERSE),
        "minimum_commitments_before_roster_freeze": PIVOT_FORWARD_ROSTER_SIZE,
        "future_reveal_locked": True,
    }


def _load_chain(
    output: Path,
    authority: ForwardCollectionAuthority,
) -> ForwardDailyAcquisition | None:
    paths = tuple(sorted((output / "acquisitions").glob("*.json"))) if (output / "acquisitions").exists() else ()
    previous = None
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        acquisition = _hydrate_acquisition(payload["acquisition"])
        authority.verify_acquisition(acquisition)
        if previous is None:
            if acquisition.sequence_number != 1 or acquisition.previous_acquisition_sha256 != "0" * 64:
                raise ValueError("forward acquisition chain has an invalid genesis")
        elif (
            acquisition.sequence_number != previous.sequence_number + 1
            or acquisition.previous_acquisition_sha256 != previous.content_sha256
        ):
            raise ValueError("forward acquisition chain is not contiguous")
        previous = acquisition
    return previous


def _hydrate_acquisition(value: object) -> ForwardDailyAcquisition:
    if not isinstance(value, dict):
        raise ValueError("stored forward acquisition must be an object")
    records = value.get("records")
    if not isinstance(records, list):
        raise ValueError("stored forward acquisition records must be an array")
    return ForwardDailyAcquisition(
        str(value["collection_authority_id"]),
        str(value["protocol"]),
        int(value["sequence_number"]),
        TradingDate.parse(str(value["trading_date"])),
        RecordedAt.parse(str(value["recorded_at"])),
        str(value["previous_acquisition_sha256"]),
        tuple(
            ForwardAcquiredRecord(
                str(item["instrument_id"]),
                str(item["dataset_manifest_sha256"]),
                str(item["record_sha256"]),
                RecordedAt.parse(str(item["event_time"])),
                RecordedAt.parse(str(item["available_time"])),
            )
            for item in records
            if isinstance(item, dict)
        ),
        str(value["signature_sha256"]),
    )


def _master_secret() -> bytes:
    if MASTER_SECRET_PATH.exists():
        secret = MASTER_SECRET_PATH.read_bytes()
        if len(secret) != 32:
            raise ValueError("local governance master key has invalid length")
        return secret
    MASTER_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    descriptor = os.open(MASTER_SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(secret)
    return secret


def _key(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("immutable forward acquisition already exists with different content") from None
        return
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)


def _next_weekday(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


if __name__ == "__main__":
    main()
