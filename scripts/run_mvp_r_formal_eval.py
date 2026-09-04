"""Freeze and run the post-R-005 formal 30/50 MVP-R automated evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import cast

import run_mvp_r_005 as r005
from futures_agent_os.adapters import OfficialCodexAppServerTransport
from futures_agent_os.reference_market_data import StoredDataset, dataset_manifest_sha256
from futures_agent_os.research_experiment import EpisodePhase, stratified_replay_candidates
from futures_agent_os.research_experiment.mvp_r_003 import StructuredModelConfig
from futures_agent_os.research_experiment.mvp_r_005 import (
    FormalEvalPhase,
    MvpR005ModelWorkloads,
    assess_correction_v5_episode,
    build_predecessor_hash_manifest,
    compute_formal_automated_gate,
    freeze_blind_selection,
    predecessor_hashes_match,
)
from futures_agent_os.research_experiment.mvp_r_005.evidence import (
    load_predecessor_hash_manifest,
    write_predecessor_hash_manifest,
)
from futures_agent_os.research_experiment.mvp_replay import ReplayEpisodeCandidate
from futures_agent_os.shared_kernel import RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
FORMAL_ROOT = ROOT / "evidence" / "mvp-r-formal-eval"
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
PREREG_PATH = ROOT / "docs" / "MVP-R-FORMAL-EVAL-PREREGISTRATION.md"
BASELINE_PATH = FORMAL_ROOT / "predecessor-hash-baseline.json"
CRITICAL_PATH = FORMAL_ROOT / "critical-checks.json"
BLIND_SEED = "mvp-r-formal-shadow-v1"
LOGGER = logging.getLogger("mvp-r-formal-eval")
EVAL_REVISION = "v1"
EXPECTED_PROVIDER_LABEL = "openai"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-rosters", action="store_true")
    parser.add_argument("--phase", choices=("diagnostic", "holdout"))
    parser.add_argument("--episode")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-completed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--research-model", default="gpt-5.6-terra")
    parser.add_argument("--critic-model", default="gpt-5.6-sol")
    parser.add_argument("--feedback-model", default="gpt-5.6-terra")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="xhigh")
    parser.add_argument("--revision", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    _configure_revision(args.revision)

    if args.freeze_rosters:
        if args.phase:
            raise SystemExit("--freeze-rosters freezes both phases; do not pass --phase")
        print(canonical_json_text(_freeze(_freeze_rosters())))
        return
    if not args.phase:
        raise SystemExit("--phase is required unless --freeze-rosters is used")

    phase = FormalEvalPhase(args.phase)
    _configure_r005(phase)
    roster = r005._load_roster()
    if phase is FormalEvalPhase.HOLDOUT:
        _assert_diagnostic_passed()
    if args.summarize_only:
        print(canonical_json_text(_freeze({"scorecard": str(_write_scorecard(roster, phase))})))
        return

    issued, result_port, validation_config = r005._issue_episodes(roster)
    if args.episode:
        issued = tuple(item for item in issued if item.contract.episode_id == args.episode)
        if not issued:
            raise SystemExit("requested episode is not in the frozen formal roster")
    if args.skip_completed:
        issued = tuple(item for item in issued if not _already_attempted(item.contract.episode_id, phase))
    if _failure_count(roster, phase) > phase.episode_count - phase.minimum_complete:
        scorecard = _write_scorecard(roster, phase)
        print(canonical_json_text({"scorecard": str(scorecard), "decision": _scorecard_decision(scorecard)}))
        return
    if args.plan_only:
        print(
            canonical_json_text(
                {
                    "phase": phase.value,
                    "roster_sha256": cast(str, roster["content_sha256"]),
                    "episode_count": len(issued),
                    "episodes": tuple(item.contract.episode_id for item in issued),
                }
            )
        )
        return

    workloads = MvpR005ModelWorkloads(OfficialCodexAppServerTransport())
    failures = _failure_count(roster, phase)
    for item in issued:
        LOGGER.info("starting formal %s episode %s", phase.value, item.contract.episode_id)
        try:
            r005._run_episode(
                item,
                validation_config,
                result_port,
                workloads,
                StructuredModelConfig(
                    args.research_model, args.effort, expected_provider=EXPECTED_PROVIDER_LABEL, timeout_seconds=180
                ),
                StructuredModelConfig(
                    args.critic_model, args.effort, expected_provider=EXPECTED_PROVIDER_LABEL, timeout_seconds=180
                ),
                StructuredModelConfig(
                    args.feedback_model, args.effort, expected_provider=EXPECTED_PROVIDER_LABEL, timeout_seconds=180
                ),
            )
            LOGGER.info("completed formal episode %s", item.contract.episode_id)
        except Exception as error:  # formal failures are retained and the batch continues
            LOGGER.error("failed closed formal episode %s: %s", item.contract.episode_id, error)
            r005._write_failure(item.contract.episode_id, error)
            failures += 1
            if failures > phase.episode_count - phase.minimum_complete:
                LOGGER.error("stopping formal %s after mathematical failure threshold", phase.value)
                break
    scorecard = _write_scorecard(roster, phase)
    print(canonical_json_text({"scorecard": str(scorecard), "decision": _scorecard_decision(scorecard)}))


def _freeze_rosters() -> dict[str, object]:
    diagnostic_path = FORMAL_ROOT / "diagnostic" / "roster.json"
    holdout_path = FORMAL_ROOT / "holdout" / "roster.json"
    if diagnostic_path.exists() or holdout_path.exists() or BASELINE_PATH.exists():
        raise RuntimeError("formal rosters or predecessor baseline already exist; refusing to overwrite")
    if "frozen" not in PREREG_PATH.read_text(encoding="utf-8").lower():
        raise RuntimeError("formal preregistration is not frozen")

    stored = r005._stored_datasets()
    records = tuple(record for dataset in stored for record in r005._records(dataset))
    candidates = stratified_replay_candidates(
        records,
        cutoff_start=RecordedAt.parse("2026-03-01T00:00:00Z"),
        cutoff_end=RecordedAt.parse("2026-08-20T23:59:59Z"),
        candidates_per_cell=10,
    )
    prior = _all_pre_formal_keys()
    by_cell: dict[tuple[str, str], list[ReplayEpisodeCandidate]] = {}
    for candidate in candidates:
        key = (
            candidate.instrument_id,
            candidate.stratum.value,
            candidate.market_cutoff.to_dict()["recorded_at"],
        )
        if key not in prior:
            by_cell.setdefault((candidate.instrument_id, candidate.stratum.value), []).append(candidate)
    for values in by_cell.values():
        values.sort(key=lambda item: item.market_cutoff.to_dict()["recorded_at"])

    ordered: list[ReplayEpisodeCandidate] = []
    cells = sorted(by_cell)
    for offset in range(10):
        for cell in cells:
            values = by_cell[cell]
            if offset < len(values):
                ordered.append(values[offset])
    if len(ordered) < 80:
        raise RuntimeError(f"formal eval requires 80 unused candidates, found {len(ordered)}")

    diagnostic = _roster(FormalEvalPhase.DIAGNOSTIC, tuple(ordered[:30]), stored)
    holdout = _roster(FormalEvalPhase.HOLDOUT, tuple(ordered[30:80]), stored)
    if r005._roster_keys(diagnostic) & r005._roster_keys(holdout):
        raise RuntimeError("formal diagnostic and holdout rosters overlap")

    write_predecessor_hash_manifest(BASELINE_PATH, build_predecessor_hash_manifest(ROOT))
    _write_json(diagnostic_path, diagnostic)
    _write_json(holdout_path, holdout)
    return {
        "diagnostic_roster": str(diagnostic_path),
        "diagnostic_sha256": diagnostic["content_sha256"],
        "holdout_roster": str(holdout_path),
        "holdout_sha256": holdout["content_sha256"],
        "predecessor_baseline": str(BASELINE_PATH),
    }


def _roster(
    phase: FormalEvalPhase,
    candidates: tuple[ReplayEpisodeCandidate, ...],
    stored: tuple[StoredDataset, ...],
) -> dict[str, object]:
    episodes = tuple(
        {
            "episode_id": f"formal-{phase.value}-{index:03d}",
            "instrument": candidate.instrument_id,
            "stratum": candidate.stratum.value,
            "market_cutoff": candidate.market_cutoff.to_dict()["recorded_at"],
        }
        for index, candidate in enumerate(candidates, start=1)
    )
    payload: dict[str, object] = {
        "schema_version": "mvp-r.formal-roster.v1",
        "task": "MVP-R-FORMAL-EVAL",
        "phase": phase.value,
        "frozen_before_formal_model_calls": True,
        "preregistration_sha256": hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest(),
        "selection_rule": (
            "deterministic round-robin over sorted AG/CU/MA/SR market-state cells from "
            "candidates_per_cell=10; exclude every R-003/R-004/R-005 roster triple; freeze "
            "30 diagnostic then the next 50 disjoint sealed holdout candidates"
        ),
        "manifests": tuple(
            {
                "manifest_sha256": dataset_manifest_sha256(item.manifest),
                "source_revision": item.manifest.provenance.source_revision,
                "source_uri": item.manifest.provenance.source_uri,
            }
            for item in stored
        ),
        "episodes": episodes,
    }
    payload["content_sha256"] = canonical_sha256(_freeze({k: v for k, v in payload.items()}))
    return payload


def _configure_r005(phase: FormalEvalPhase) -> None:
    phase_root = FORMAL_ROOT / phase.value
    r005.EVIDENCE_ROOT = phase_root
    run_prefix = "mvp-r-formal" if EVAL_REVISION == "v1" else "mvp-r-formal-v2"
    r005.RUN_ROOT = DATA_ROOT / "runs" / f"{run_prefix}-{phase.value}"
    r005.ROSTER_PATH = phase_root / "roster.json"
    r005.SCORECARD_PATH = phase_root / "scorecard.json"
    r005.WP_PATH = phase_root / "wp-evidence.json"
    r005.CODE_REF = f"mvp-r-formal-{phase.value}-{EVAL_REVISION}"
    r005.REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-FORMAL-EVAL", "phase": phase.value})
    r005.LOGGER = LOGGER
    r005.CORRECTION_V2 = False
    r005.CORRECTION_V3 = True
    r005.CORRECTION_V4 = False
    r005.CORRECTION_V5 = False
    r005.CANDIDATES_PER_CELL = 10
    r005.ACTIVE_TASK = "MVP-R-FORMAL-EVAL"
    r005.ACTIVE_PHASE_NAME = phase.value
    r005.ACTIVE_EPISODE_PHASE = EpisodePhase.DIAGNOSTIC if phase is FormalEvalPhase.DIAGNOSTIC else EpisodePhase.HOLDOUT
    r005.ACTIVE_EXECUTION_MODE = f"FORMAL_{phase.value.upper()}_EXECUTED"
    r005.DATA_HMAC_LABEL = f"mvp-r-formal-{phase.value}-data"
    r005.RESULT_HMAC_LABEL = f"mvp-r-formal-{phase.value}-results"
    r005.EXTRA_FORBIDDEN_KEYS = frozenset(_all_pre_formal_keys() | _other_formal_keys(phase))


def _configure_revision(revision: str) -> None:
    global FORMAL_ROOT, PREREG_PATH, BASELINE_PATH, CRITICAL_PATH, BLIND_SEED
    global EVAL_REVISION, EXPECTED_PROVIDER_LABEL
    if revision == "v1":
        FORMAL_ROOT = ROOT / "evidence" / "mvp-r-formal-eval"
        PREREG_PATH = ROOT / "docs" / "MVP-R-FORMAL-EVAL-PREREGISTRATION.md"
        EVAL_REVISION = "v1"
        EXPECTED_PROVIDER_LABEL = "openai"
        BLIND_SEED = "mvp-r-formal-shadow-v1"
    else:
        FORMAL_ROOT = ROOT / "evidence" / "mvp-r-formal-eval-v2"
        PREREG_PATH = ROOT / "docs" / "MVP-R-FORMAL-EVAL-V2-PREREGISTRATION.md"
        EVAL_REVISION = "v2"
        EXPECTED_PROVIDER_LABEL = "custom"
        BLIND_SEED = "mvp-r-formal-shadow-v2"
    BASELINE_PATH = FORMAL_ROOT / "predecessor-hash-baseline.json"
    CRITICAL_PATH = FORMAL_ROOT / "critical-checks.json"


def _write_scorecard(roster: dict[str, object], phase: FormalEvalPhase) -> Path:
    config = r005._validation_config()
    forbidden = r005._predecessor_keys()
    outcomes = []
    episodes = []
    total_tokens = 0
    wall_time_ms = 0
    completed_ids: list[str] = []
    for raw in cast(list[object], roster["episodes"]):
        item = cast(dict[str, object], raw)
        episode_id = cast(str, item["episode_id"])
        directory = r005.RUN_ROOT / episode_id
        agent = r005._read_json(directory / "research_agent_loop.json")
        single = r005._read_json(directory / "single_prompt_analyst.json")
        agent_md = (directory / "research_agent_loop.md").read_text(encoding="utf-8") if agent else ""
        single_md = (directory / "single_prompt_analyst.md").read_text(encoding="utf-8") if single else ""
        key = (cast(str, item["instrument"]), cast(str, item["stratum"]), cast(str, item["market_cutoff"]))
        outcome = assess_correction_v5_episode(
            roster_item=item,
            agent_payload=agent,
            single_payload=single,
            agent_markdown=agent_md,
            single_markdown=single_md,
            overlapping_predecessor=key in forbidden,
            config=config,
        )
        outcomes.append(outcome)
        if outcome.complete:
            completed_ids.append(episode_id)
        for payload in (agent, single):
            if not payload:
                continue
            receipts = payload.get("model_receipts")
            if type(receipts) not in (list, tuple):
                continue
            for receipt in cast(list[object] | tuple[object, ...], receipts):
                if type(receipt) is dict:
                    total_tokens += int(receipt.get("input_tokens", 0)) + int(receipt.get("output_tokens", 0))
                    wall_time_ms += int(receipt.get("latency_ms", 0))
        episodes.append(
            {
                "episode_id": episode_id,
                "instrument": outcome.instrument,
                "stratum": outcome.stratum,
                "market_cutoff": outcome.market_cutoff,
                "complete": outcome.complete,
                "raw_packet_to_view_lineage": outcome.raw_packet_to_view_lineage,
                "predicate_metric_binding": outcome.predicate_metric_binding,
                "verdict_predicate_congruent": outcome.verdict_predicate_congruent,
                "four_block_report": outcome.four_block_report,
                "stopped_folds_invisible": outcome.stopped_folds_invisible,
                "treatment_view_bound": outcome.treatment_view_bound,
                "pre_experiment_critic_gate": outcome.pre_experiment_critic_gate,
                "critic_blocked_experiment": outcome.critic_blocked_experiment,
                "overlapping_predecessor": outcome.overlapping_predecessor,
                "arm_verdicts": {
                    "research_agent_loop": outcome.agent_verdict,
                    "single_prompt_analyst": outcome.single_prompt_verdict,
                },
            }
        )

    current = build_predecessor_hash_manifest(ROOT)
    hashes_match = predecessor_hashes_match(load_predecessor_hash_manifest(BASELINE_PATH), current)
    critical = _critical_count()
    gate = compute_formal_automated_gate(
        tuple(outcomes),
        phase=phase,
        total_tokens=total_tokens,
        model_wall_time_ms=wall_time_ms,
        critical_fail_closed=critical,
        predecessor_hashes_match=hashes_match,
    )
    scorecard = {
        "schema_version": f"mvp-r.formal-scorecard.{EVAL_REVISION}",
        "task": "MVP-R-FORMAL-EVAL",
        "phase": phase.value,
        "preregistration_path": PREREG_PATH.relative_to(ROOT).as_posix(),
        "preregistration_sha256": hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest(),
        "roster_sha256": roster["content_sha256"],
        "product_models": (
            {
                "research": "gpt-5.6-sol/high",
                "feedback": "gpt-5.6-sol/high",
                "single_prompt": "gpt-5.6-sol/high",
                "shadow_critic": "gpt-5.6-sol/high",
                "expected_app_server_provider_label": EXPECTED_PROVIDER_LABEL,
            }
            if EVAL_REVISION == "v2"
            else {
                "research": "gpt-5.6-terra/xhigh",
                "feedback": "gpt-5.6-terra/xhigh",
                "single_prompt": "gpt-5.6-terra/xhigh",
                "shadow_critic": "gpt-5.6-sol/xhigh",
            }
        ),
        "episodes": tuple(episodes),
        "gate": gate,
        "independent_real_user_validation": False,
        "go": False,
        "approve_v1_011": False,
    }
    _write_json(r005.SCORECARD_PATH, scorecard)
    _write_json(
        r005.WP_PATH,
        {
            "schema_version": f"mvp-r.formal-wp-evidence.{EVAL_REVISION}",
            "task": "MVP-R-FORMAL-EVAL",
            "phase": phase.value,
            "executor": "Codex",
            "implementation_model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "expected_app_server_provider_label": EXPECTED_PROVIDER_LABEL,
            "status": gate["decision"],
            "roster_sha256": roster["content_sha256"],
            "gate": gate,
        },
    )
    if phase is FormalEvalPhase.HOLDOUT and gate["decision"] == phase.pass_decision:
        _write_blind_packets(tuple(completed_ids))
    return r005.SCORECARD_PATH


def _write_blind_packets(completed_ids: tuple[str, ...]) -> None:
    selections = freeze_blind_selection(completed_ids, seed=BLIND_SEED)
    blind_root = FORMAL_ROOT / "shadow"
    packets_root = blind_root / "packets"
    packets_root.mkdir(parents=True, exist_ok=True)
    public = []
    for index, selection in enumerate(selections, start=1):
        run_prefix = "mvp-r-formal" if EVAL_REVISION == "v1" else "mvp-r-formal-v2"
        source = DATA_ROOT / "runs" / f"{run_prefix}-holdout" / selection.episode_id
        agent = (source / "research_agent_loop.md").read_text(encoding="utf-8")
        single = (source / "single_prompt_analyst.md").read_text(encoding="utf-8")
        a = agent if selection.agent_label == "A" else single
        b = single if selection.agent_label == "A" else agent
        packet = f"# 正式 MVP-R 盲评 {index:02d}\n\n## A\n\n{a}\n\n## B\n\n{b}\n"
        path = packets_root / f"{index:02d}.md"
        path.write_text(packet, encoding="utf-8")
        public.append({"case": index, "packet": path.relative_to(ROOT).as_posix()})
    _write_json(blind_root / "blind-roster.json", {"schema_version": "mvp-r.formal-blind-roster.v1", "cases": public})
    _write_json(
        blind_root / "blind-mapping.json",
        {
            "schema_version": "mvp-r.formal-blind-mapping.v1",
            "seed_sha256": hashlib.sha256(BLIND_SEED.encode()).hexdigest(),
            "opened_before_user_scores": False,
            "selections": tuple(item.to_dict() for item in selections),
        },
    )


def _all_pre_formal_keys() -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for path in (
        ROOT / "evidence/mvp-r-003/discovery/roster.json",
        ROOT / "evidence/mvp-r-004/canary/roster.json",
        ROOT / "evidence/mvp-r-004/discovery/roster.json",
        ROOT / "evidence/mvp-r-005/roster.json",
        ROOT / "evidence/mvp-r-formal-eval/diagnostic/roster.json",
        ROOT / "evidence/mvp-r-formal-eval/holdout/roster.json",
    ):
        if path.exists():
            keys |= r005._roster_keys(cast(dict[str, object], json.loads(path.read_text(encoding="utf-8"))))
    return keys


def _other_formal_keys(phase: FormalEvalPhase) -> set[tuple[str, str, str]]:
    other = FormalEvalPhase.HOLDOUT if phase is FormalEvalPhase.DIAGNOSTIC else FormalEvalPhase.DIAGNOSTIC
    path = FORMAL_ROOT / other.value / "roster.json"
    if not path.exists():
        return set()
    return r005._roster_keys(cast(dict[str, object], json.loads(path.read_text(encoding="utf-8"))))


def _already_attempted(episode_id: str, phase: FormalEvalPhase) -> bool:
    run_prefix = "mvp-r-formal" if EVAL_REVISION == "v1" else "mvp-r-formal-v2"
    directory = DATA_ROOT / "runs" / f"{run_prefix}-{phase.value}" / episode_id
    if (directory / "research_agent_loop.md").exists() and (directory / "single_prompt_analyst.md").exists():
        return True
    return any((FORMAL_ROOT / phase.value).glob(f"{episode_id}-attempt-*-failure.json"))


def _failure_count(roster: dict[str, object], phase: FormalEvalPhase) -> int:
    count = 0
    for raw in cast(list[object], roster["episodes"]):
        episode_id = cast(dict[str, object], raw)["episode_id"]
        if any((FORMAL_ROOT / phase.value).glob(f"{episode_id}-attempt-*-failure.json")):
            count += 1
    return count


def _assert_diagnostic_passed() -> None:
    path = FORMAL_ROOT / "diagnostic" / "scorecard.json"
    if not path.exists() or _scorecard_decision(path) != FormalEvalPhase.DIAGNOSTIC.pass_decision:
        raise RuntimeError("formal diagnostic must pass before holdout")


def _critical_count() -> int:
    if not CRITICAL_PATH.exists():
        return 0
    payload = json.loads(CRITICAL_PATH.read_text(encoding="utf-8"))
    return 4 if payload.get("decision") == "CRITICAL_4_OF_4_PASS" else 0


def _scorecard_decision(path: Path) -> str:
    return cast(str, json.loads(path.read_text(encoding="utf-8"))["gate"]["decision"])


def _freeze(value: object) -> JsonValue:
    if value is None or type(value) in (str, int, bool, float):
        return cast(JsonValue, value)
    if isinstance(value, dict):
        return {str(key): _freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    raise TypeError(f"unsupported formal evidence value {type(value).__name__}")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_text(_freeze(value)), encoding="utf-8")


if __name__ == "__main__":
    main()
