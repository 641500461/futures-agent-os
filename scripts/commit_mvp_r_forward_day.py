"""Freeze four future-blind commitments for the latest signed forward day."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import hashlib
import hmac
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import collect_mvp_r_forward as collector

from futures_agent_os.adapters import OFFICIAL_RESEARCH_SERIES_NORMALIZER
from futures_agent_os.reference_market_data import (
    DatasetLayer,
    LocalFileDataStore,
    PointInTimeRecord,
    StoredDataset,
    dataset_manifest_sha256,
    sha256_digest,
)
from futures_agent_os.research_experiment import (
    DatasetAuthorizationAuthority,
    ForwardCollectionAuthority,
    PIVOT_FORWARD_UNIVERSE,
    PIVOT_FORWARD_WINDOW_BARS,
)
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
DEFAULT_FORWARD_ROOT = DATA_ROOT / "forward"
MASTER_SECRET_PATH = DATA_ROOT / ".governance-master-key"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-date", type=date.fromisoformat)
    parser.add_argument("--forward-root", type=Path, default=DEFAULT_FORWARD_ROOT)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    acquisition_paths = tuple(sorted((args.forward_root / "acquisitions").glob("*.json")))
    if not acquisition_paths:
        if args.plan_only:
            print(json.dumps(_plan(None, args.trading_date, args.forward_root), ensure_ascii=False, indent=2))
            return
        raise SystemExit("no signed forward acquisition exists")
    requested = args.trading_date or date.fromisoformat(acquisition_paths[-1].stem)
    acquisition_path = args.forward_root / "acquisitions" / f"{requested.isoformat()}.json"
    if args.plan_only:
        print(json.dumps(_plan(acquisition_path, requested, args.forward_root), ensure_ascii=False, indent=2))
        return
    if acquisition_path != acquisition_paths[-1]:
        raise SystemExit("only the immutable acquisition chain tip can be committed")
    if requested != datetime.now(_SHANGHAI).date():
        raise SystemExit("forward commitment must be created on the same Shanghai calendar day as acquisition")

    master = _master_secret()
    collection_authority = ForwardCollectionAuthority(
        "mvp-r.pivot-forward-collection",
        _key(master, "pivot-forward-collection"),
    )
    chain_tip = collector._load_chain(args.forward_root, collection_authority)
    if chain_tip is None or chain_tip.trading_date.value != requested:
        raise ValueError("forward acquisition chain tip does not match the requested date")
    stored, provider_contracts = _governed_datasets(args.forward_root)
    records_by_manifest = {dataset_manifest_sha256(item.manifest): _records(item) for item in stored}
    data_authority = DatasetAuthorizationAuthority(
        "mvp-r.pivot-forward-data",
        _key(master, "pivot-forward-data"),
        provider_contracts,
        frozenset({sha256_digest(b"MVP-R forward synthetic denylist sentinel")}),
        frozenset({OFFICIAL_RESEARCH_SERIES_NORMALIZER}),
    )
    artifacts_by_key = {}
    for dataset in stored:
        manifest_sha256 = dataset_manifest_sha256(dataset.manifest)
        records = records_by_manifest[manifest_sha256]
        dataset_ref = data_authority.authorize(
            dataset,
            provider_contract_sha256=provider_contracts[manifest_sha256],
            records=records,
        )
        for record in records:
            instrument = record.values.get("instrument_id")
            if type(instrument) is not str:
                raise ValueError("forward input record requires instrument_id")
            key = (instrument, record.event_time.to_dict()["recorded_at"])
            if key in artifacts_by_key:
                raise ValueError("forward input datasets contain a duplicate instrument event")
            artifacts_by_key[key] = data_authority.issue_artifact(dataset_ref, instrument, record)

    committed_at = RecordedAt.from_datetime(datetime.now(UTC))
    commitments = []
    for instrument in PIVOT_FORWARD_UNIVERSE:
        eligible = tuple(
            sorted(
                (
                    artifact
                    for (candidate_instrument, _), artifact in artifacts_by_key.items()
                    if candidate_instrument == instrument
                    and artifact.record.event_time.value
                    <= next(item for item in chain_tip.records if item.instrument_id == instrument).event_time.value
                    and artifact.record.available_time.value <= committed_at.value
                ),
                key=lambda item: item.record.event_time.value,
            )
        )
        if len(eligible) < PIVOT_FORWARD_WINDOW_BARS:
            raise ValueError(f"insufficient causal history for {instrument}")
        window = eligible[-PIVOT_FORWARD_WINDOW_BARS:]
        episode_id = semantic_entity_id(
            "evaluation_episode",
            {
                "task": "MVP-R-001-PIVOT-FORWARD",
                "instrument_id": instrument,
                "trading_date": requested.isoformat(),
                "acquisition_sha256": chain_tip.content_sha256,
            },
        )
        commitments.append(
            collection_authority.issue_commitment(
                episode_id=episode_id,
                acquisition=chain_tip,
                artifacts=window,
                committed_at=committed_at,
            )
        )
    envelope: dict[str, JsonValue] = {
        "task": "MVP-R-001-PIVOT",
        "mode": "POST_PIVOT_FORWARD_COMMITMENT",
        "trading_date": requested.isoformat(),
        "committed_at": committed_at.to_dict()["recorded_at"],
        "acquisition_sha256": chain_tip.content_sha256,
        "future_reveal_included": False,
        "commitments": tuple(
            {**item.unsigned_payload(), "signature_sha256": item.signature_sha256} for item in commitments
        ),
    }
    payload: dict[str, JsonValue] = {**envelope, "envelope_sha256": canonical_sha256(envelope)}
    output_path = args.forward_root / "commitments" / f"{requested.isoformat()}.json"
    collector._write_once(output_path, (canonical_json_text(payload) + "\n").encode())
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _plan(acquisition_path: Path | None, requested: date | None, forward_root: Path) -> dict[str, object]:
    commitment_files = tuple(sorted((forward_root / "commitments").glob("*.json")))
    return {
        "task": "MVP-R-001-PIVOT",
        "mode": "PLAN_ONLY_NO_WRITE",
        "requested_trading_date": requested.isoformat() if requested else None,
        "signed_acquisition_exists": bool(acquisition_path and acquisition_path.exists()),
        "is_chain_tip": bool(
            acquisition_path
            and acquisition_path.exists()
            and tuple(sorted((forward_root / "acquisitions").glob("*.json")))[-1] == acquisition_path
        ),
        "signed_commitment_days": len(commitment_files),
        "signed_commitments": len(commitment_files) * len(PIVOT_FORWARD_UNIVERSE),
        "future_reveal_included": False,
    }


def _governed_datasets(forward_root: Path) -> tuple[tuple[StoredDataset, ...], dict[str, str]]:
    historical_summary = json.loads((DATA_ROOT / "collection-summary.json").read_text(encoding="utf-8"))
    historical_store = LocalFileDataStore(DATA_ROOT / "normalized", DatasetLayer.NORMALIZED_PIT)
    stored = [
        historical_store.get(EntityId.parse(item["normalized_dataset_id"])) for item in historical_summary["sources"]
    ]
    contracts = {
        dataset_manifest_sha256(item.manifest): canonical_sha256(
            {
                "task": "MVP-R-001-PIVOT-FORWARD",
                "manifest_sha256": dataset_manifest_sha256(item.manifest),
                "purpose": "pre-pivot-input-context-only",
            }
        )
        for item in stored
    }
    forward_store = LocalFileDataStore(forward_root / "normalized", DatasetLayer.NORMALIZED_PIT)
    for acquisition_path in sorted((forward_root / "acquisitions").glob("*.json")):
        payload = json.loads(acquisition_path.read_text(encoding="utf-8"))
        for evidence in payload["dataset_evidence"]:
            dataset = forward_store.get(EntityId.parse(evidence["dataset_id"]))
            manifest_sha256 = dataset_manifest_sha256(dataset.manifest)
            if manifest_sha256 != evidence["manifest_sha256"]:
                raise ValueError("forward dataset evidence manifest digest mismatch")
            stored.append(dataset)
            contracts[manifest_sha256] = evidence["provider_contract_sha256"]
    if len({item.manifest.dataset_id for item in stored}) != len(stored):
        raise ValueError("forward governed dataset roster contains duplicates")
    return tuple(stored), contracts


def _records(dataset: StoredDataset) -> tuple[PointInTimeRecord, ...]:
    values = json.loads(dataset.content)
    return tuple(
        PointInTimeRecord(
            RecordedAt.parse(item["event_time"]),
            RecordedAt.parse(item["available_time"]),
            item["values"],
        )
        for item in values
    )


def _master_secret() -> bytes:
    secret = MASTER_SECRET_PATH.read_bytes()
    if len(secret) != 32:
        raise ValueError("local governance master key has invalid length")
    return secret


def _key(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()


if __name__ == "__main__":
    main()
