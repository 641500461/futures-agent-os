"""Freeze the final fifty-entry Pivot roster from future-blind commitments only."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path

import collect_mvp_r_forward as collector

from futures_agent_os.research_experiment import (
    EpisodeStratum,
    ForwardCollectionAuthority,
    ForwardEpisodeCommitment,
    ForwardRosterAuthority,
    ForwardStratumScore,
    PIVOT_FORWARD_ROSTER_SIZE,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, TradingDate, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORWARD_ROOT = ROOT / "datasets" / "mvp-r-001" / "forward"
MASTER_SECRET_PATH = ROOT / "datasets" / "mvp-r-001" / ".governance-master-key"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward-root", type=Path, default=DEFAULT_FORWARD_ROOT)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    commitment_paths = tuple(sorted((args.forward_root / "commitments").glob("*.json")))
    if args.plan_only:
        print(json.dumps(_plan(commitment_paths), ensure_ascii=False, indent=2))
        return
    if len(commitment_paths) * 4 < PIVOT_FORWARD_ROSTER_SIZE:
        raise SystemExit("forward roster cannot freeze before fifty signed commitments exist")

    master = _master_secret()
    collection_authority = ForwardCollectionAuthority(
        "mvp-r.pivot-forward-collection",
        _key(master, "pivot-forward-collection"),
    )
    commitments = tuple(
        commitment for path in commitment_paths for commitment in _commitments(path, collection_authority)
    )
    roster_authority = ForwardRosterAuthority(
        "mvp-r.pivot-forward-roster",
        _key(master, "pivot-forward-roster"),
        collection_authority,
    )
    roster = roster_authority.freeze(
        commitments,
        frozen_at=RecordedAt.from_datetime(datetime.now(UTC)),
    )
    roster_authority.verify(roster)
    envelope: dict[str, JsonValue] = {
        "task": "MVP-R-001-PIVOT",
        "mode": "POST_PIVOT_FORWARD_ROSTER_FREEZE",
        "future_reveal_read": False,
        "roster": {**roster.unsigned_payload(), "signature_sha256": roster.signature_sha256},
        "selected_commitments": tuple(
            {
                **entry.commitment.unsigned_payload(),
                "signature_sha256": entry.commitment.signature_sha256,
                "selected_stratum": entry.stratum.value,
            }
            for entry in roster.entries
        ),
    }
    payload: dict[str, JsonValue] = {**envelope, "envelope_sha256": canonical_sha256(envelope)}
    collector._write_once(
        args.forward_root / "rosters" / "final.json",
        (canonical_json_text(payload) + "\n").encode(),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _plan(paths: tuple[Path, ...]) -> dict[str, object]:
    commitments = len(paths) * 4
    return {
        "task": "MVP-R-001-PIVOT",
        "mode": "PLAN_ONLY_COMMITMENTS_ONLY",
        "signed_commitment_days": len(paths),
        "signed_commitments": commitments,
        "required_commitments": PIVOT_FORWARD_ROSTER_SIZE,
        "ready_to_freeze": commitments >= PIVOT_FORWARD_ROSTER_SIZE,
        "future_reveal_read": False,
        "blocker": None if commitments >= PIVOT_FORWARD_ROSTER_SIZE else "FEWER_THAN_FIFTY_COMMITMENTS",
    }


def _commitments(
    path: Path,
    authority: ForwardCollectionAuthority,
) -> tuple[ForwardEpisodeCommitment, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("future_reveal_included") is not False:
        raise PermissionError("forward roster input must explicitly exclude future reveal")
    values = payload.get("commitments")
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError("forward commitment day must contain exactly four commitments")
    commitments = tuple(_hydrate_commitment(value) for value in values)
    for commitment in commitments:
        authority.verify_commitment(commitment)
    return commitments


def _hydrate_commitment(value: object) -> ForwardEpisodeCommitment:
    if not isinstance(value, dict):
        raise ValueError("stored forward commitment must be an object")
    scores = value.get("stratum_scores")
    if not isinstance(scores, list):
        raise ValueError("stored forward stratum scores must be an array")
    return ForwardEpisodeCommitment(
        str(value["collection_authority_id"]),
        str(value["protocol"]),
        EntityId.parse(str(value["episode_id"])),
        str(value["instrument_id"]),
        TradingDate.parse(str(value["cutoff_trading_date"])),
        RecordedAt.parse(str(value["cutoff_event_time"])),
        RecordedAt.parse(str(value["committed_at"])),
        str(value["acquisition_sha256"]),
        tuple(str(item) for item in value["input_manifest_sha256s"]),
        tuple(str(item) for item in value["input_record_sha256s"]),
        tuple(str(item) for item in value["family_screen_sha256s"]),
        tuple(
            ForwardStratumScore(EpisodeStratum(str(item["stratum"])), str(item["score"]))
            for item in scores
            if isinstance(item, dict)
        ),
        str(value["signature_sha256"]),
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
