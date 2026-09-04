"""Run the repaired eight-episode, four-arm MVP-R-004 Discovery batch.

Does not touch MVP-R-003 Evidence. Requires a passing canary and a frozen roster whose
(instrument, stratum, cutoff) triples differ from the R-003 v1 roster.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from futures_agent_os.adapters import OFFICIAL_RESEARCH_SERIES_NORMALIZER, OfficialCodexAppServerTransport
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
    DatasetEvidenceRef,
    EpisodeIssuer,
    EpisodeMode,
    EpisodePhase,
    EvaluationSuite,
    FrozenRuntimeIdentity,
    MVP_R_EPISODE_SELECTION_RULE,
    MVP_R_REQUIRED_BASELINES,
    MVP_R_TOOLSET_VERSION,
    RetrospectiveMarketWindow,
    RetrospectiveWindowIssuer,
    TrustedResearchToolsPort,
    ValidationConfig,
    frozen_mvp_tool_specs,
    stratified_replay_candidates,
)
from futures_agent_os.research_experiment.model_routing import (
    ModelActivationBinding,
    ModelAuthenticationMode,
    ModelCostAccountingMode,
    ModelProfileRevision,
    ModelProtocolFamily,
    ModelQualificationState,
    ModelRunnerCapabilities,
    ModelRunnerKind,
    ResolvedRunConfig,
    WorkloadId,
)
from futures_agent_os.research_experiment.mvp_r_003 import (
    ArtifactRef,
    CriticDecision,
    CriticReview,
    FinalVerdict,
    HypothesisSpec,
    MvpR003ExperimentAdapter,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
    SignalOperator,
    StructuredModelConfig,
)
from futures_agent_os.research_experiment.mvp_r_003.model_workloads import ModelWorkloadReceipt
from futures_agent_os.research_experiment.mvp_r_003.reporting import ResearchEpisodeReport
from futures_agent_os.research_experiment.mvp_r_004 import (
    DiscoveryEpisodeOutcome,
    LabeledCriticOutcome,
    MvpR004HypothesisValidator,
    MvpR004ModelWorkloads,
    ResearchEvidenceBundle,
    ValidationProtocolDigest,
    build_research_evidence_bundle,
    build_validation_protocol_digest,
    compute_discovery_gate,
    gold_cases,
)
from futures_agent_os.research_experiment.mvp_r_004.contracts import GoldLabel
from futures_agent_os.research_experiment.mvp_r_004.metrics import decimal_metrics
from futures_agent_os.research_experiment.mvp_replay import ReplayEpisodeCandidate
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
from futures_agent_os.research_experiment.mvp_validation import AgentEpisodeView, ModelRunConfig
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
R003_ROSTER_PATH = ROOT / "evidence" / "mvp-r-003" / "discovery" / "roster.json"
R003_SCORECARD = ROOT / "evidence" / "mvp-r-003" / "discovery" / "scorecard.json"
CANARY_SCORECARD = ROOT / "evidence" / "mvp-r-004" / "canary" / "scorecard.json"
ROSTER_PATH = ROOT / "evidence" / "mvp-r-004" / "discovery" / "roster.json"
EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-004" / "discovery"
RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-004-discovery"
SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
USER_BLIND_PATH = EVIDENCE_ROOT / "user-blind-eval.json"
MASTER_SECRET_PATH = DATA_ROOT / ".governance-master-key"
REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-004", "workload": "discovery"})
CODE_REF = "mvp-r-004-discovery-v1"
LOGGER = logging.getLogger("mvp-r-004-discovery")


@dataclass(frozen=True, slots=True)
class IssuedDiscoveryEpisode:
    roster_item: dict[str, object]
    contract: ResearchEpisodeInput
    view: AgentEpisodeView
    window: RetrospectiveMarketWindow
    records: tuple[PointInTimeRecord, ...]
    stratum: EpisodeStratum
    bundle: ResearchEvidenceBundle
    protocol: ValidationProtocolDigest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-roster", action="store_true")
    parser.add_argument("--episode")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-completed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--research-model", default="gpt-5.6-terra")
    parser.add_argument("--critic-model", default="gpt-5.6-sol")
    parser.add_argument("--feedback-model", default="gpt-5.6-terra")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="xhigh")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _assert_r003_evidence_untouched()
    _assert_canary_passed()
    if args.freeze_roster:
        path = _freeze_roster()
        print(canonical_json_text({"roster": str(path), "roster_sha256": cast(str, _load_roster()["content_sha256"])}))
        return
    roster = _load_roster()
    if args.summarize_only:
        print(canonical_json_text({"scorecard": str(_write_scorecard_from_disk(roster))}))
        return
    issued, result_port, validation_config = _issue_episodes(roster)
    if args.episode:
        issued = tuple(item for item in issued if item.contract.episode_id == args.episode)
        if not issued:
            raise SystemExit("requested episode is not in the frozen discovery roster")
    if args.skip_completed:
        issued = tuple(
            item for item in issued if not (RUN_ROOT / item.contract.episode_id / "blind-mapping.json").exists()
        )
        if not issued:
            print(canonical_json_text({"scorecard": str(_write_scorecard_from_disk(roster)), "skipped": True}))
            return
    if args.plan_only:
        print(
            canonical_json_text(
                {
                    "roster_sha256": cast(str, roster["content_sha256"]),
                    "episode_count": len(issued),
                    "episodes": tuple(item.contract.episode_id for item in issued),
                    "r003_evidence_untouched": True,
                    "distinct_from_r003_v1": True,
                }
            )
        )
        return
    workloads = MvpR004ModelWorkloads(OfficialCodexAppServerTransport())
    completed = 0
    for item in issued:
        LOGGER.info("starting episode %s", item.contract.episode_id)
        try:
            _run_episode(
                item,
                validation_config,
                result_port,
                workloads,
                StructuredModelConfig(args.research_model, args.effort, timeout_seconds=180),
                StructuredModelConfig(args.critic_model, args.effort, timeout_seconds=180),
                StructuredModelConfig(args.feedback_model, args.effort, timeout_seconds=180),
            )
            completed += 1
            LOGGER.info("completed episode %s", item.contract.episode_id)
        except Exception as error:
            LOGGER.info("failed closed episode %s: %s", item.contract.episode_id, error)
            _write_failure(item.contract.episode_id, error)
            raise
    scorecard_path = _write_scorecard_from_disk(roster)
    print(
        canonical_json_text(
            {
                "scorecard": str(scorecard_path),
                "decision": _read_decision(scorecard_path),
                "completed": completed,
            }
        )
    )


def _freeze_roster() -> Path:
    if ROSTER_PATH.exists():
        raise RuntimeError("discovery roster is already frozen; refusing to overwrite")
    v1 = cast(dict[str, object], json.loads(R003_ROSTER_PATH.read_text(encoding="utf-8")))
    v1_keys = {
        (
            cast(str, item["instrument"]),
            cast(str, item["stratum"]),
            cast(str, item["market_cutoff"]),
        )
        for item in cast(list[object], v1["episodes"])
        for item in (cast(dict[str, object], item),)
    }
    stored = _stored_datasets()
    all_records = tuple(record for dataset in stored for record in _records(dataset))
    candidates = stratified_replay_candidates(
        all_records,
        cutoff_start=RecordedAt.parse("2026-03-01T00:00:00Z"),
        cutoff_end=RecordedAt.parse("2026-08-20T23:59:59Z"),
        candidates_per_cell=2,
    )
    by_cell: dict[tuple[str, str], list[ReplayEpisodeCandidate]] = {}
    for candidate in candidates:
        by_cell.setdefault((candidate.instrument_id, candidate.stratum.value), []).append(candidate)
    episodes = []
    for raw in cast(list[object], v1["episodes"]):
        v1_item = cast(dict[str, object], raw)
        instrument = cast(str, v1_item["instrument"])
        stratum = cast(str, v1_item["stratum"])
        v1_cutoff = cast(str, v1_item["market_cutoff"])
        cell = by_cell[(instrument, stratum)]
        unused = [item for item in cell if item.market_cutoff.to_dict()["recorded_at"] != v1_cutoff]
        if len(unused) != 1:
            raise RuntimeError(f"expected exactly one non-v1 candidate for {instrument} {stratum}")
        chosen = unused[0]
        cutoff = chosen.market_cutoff.to_dict()["recorded_at"]
        key = (instrument, stratum, cutoff)
        if key in v1_keys:
            raise RuntimeError("R-004 discovery roster collided with an R-003 v1 window")
        v1_id = cast(str, v1_item["episode_id"])
        episodes.append(
            {
                "episode_id": f"r004-{v1_id.removeprefix('r003-')}",
                "instrument": instrument,
                "stratum": stratum,
                "market_cutoff": cutoff,
            }
        )
    roster = {
        "schema_version": "mvp-r-004.discovery-roster.v1",
        "task": "MVP-R-004",
        "phase": "discovery",
        "frozen_before_discovery_model_calls": True,
        "selection_rule": (
            "same eight AG/CU/MA/SR instrument-state cells as R-003 v1, using the other "
            "candidates_per_cell=2 window so (instrument, stratum, cutoff) differs from v1"
        ),
        "manifests": tuple(
            {
                "manifest_sha256": dataset_manifest_sha256(item.manifest),
                "source_revision": item.manifest.provenance.source_revision,
                "source_uri": item.manifest.provenance.source_uri,
            }
            for item in stored
        ),
        "episodes": tuple(episodes),
    }
    digest = canonical_sha256(_freeze(roster))
    payload = {**roster, "content_sha256": digest}
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    ROSTER_PATH.write_text(canonical_json_text(_freeze(payload)), encoding="utf-8")
    return ROSTER_PATH


def _run_episode(
    item: IssuedDiscoveryEpisode,
    config: ValidationConfig,
    result_port: TrustedResearchToolsPort,
    workloads: MvpR004ModelWorkloads,
    research_config: StructuredModelConfig,
    critic_config: StructuredModelConfig,
    feedback_config: StructuredModelConfig,
) -> None:
    episode_dir = RUN_ROOT / item.contract.episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)
    threshold = format(config.signal_threshold, "f")
    validator = MvpR004HypothesisValidator()
    adapter = MvpR003ExperimentAdapter()
    clean, bad = gold_cases(item.contract, threshold)
    clean_validation = validator.validate(item.contract, clean.hypothesis)
    bad_validation = validator.validate(item.contract, bad.hypothesis)
    if clean_validation.status.value != "EXECUTABLE":
        raise RuntimeError(f"{item.contract.episode_id} gold CLEAN hypothesis is not executable")
    if bad_validation.status.value == "EXECUTABLE":
        raise RuntimeError(f"{item.contract.episode_id} gold BAD hypothesis must not be executable")
    clean_review, clean_receipt = workloads.critique(
        item.contract, clean.hypothesis, item.bundle, item.protocol, critic_config
    )
    bad_review, bad_receipt = workloads.critique(
        item.contract, bad.hypothesis, item.bundle, item.protocol, critic_config
    )
    _write_json(
        episode_dir / "gold.json",
        {
            "schema_version": "mvp-r-004.discovery-gold.v1",
            "episode_id": item.contract.episode_id,
            "gold_clean": {
                "hypothesis_id": clean.hypothesis.hypothesis_id,
                "validation": clean_validation.to_dict(),
                "review": clean_review.to_dict(),
                "receipt": _receipt_payload(clean_receipt),
            },
            "gold_bad": {
                "hypothesis_id": bad.hypothesis.hypothesis_id,
                "validation": bad_validation.to_dict(),
                "review": bad_review.to_dict(),
                "receipt": _receipt_payload(bad_receipt),
            },
        },
    )

    deterministic = _template_hypothesis(item.contract, threshold)
    deterministic_validation = validator.validate(item.contract, deterministic)
    if deterministic_validation.status.value != "EXECUTABLE":
        raise RuntimeError(f"{item.contract.episode_id} template hypothesis is not executable")
    deterministic_plan = adapter.instantiate(item.contract, deterministic, config, code_ref=CODE_REF)
    deterministic_result = adapter.execute_replay(
        plan=deterministic_plan,
        episode=item.view,
        window=item.window,
        records=item.records,
        market_state=item.stratum,
        config=config,
        result_authority=result_port,
        hypothesis=deterministic,
    )
    deterministic_final = _deterministic_verdict(deterministic, deterministic_result)
    template_report = ResearchEpisodeReport(
        "DISCOVERY_EXECUTED",
        item.contract,
        (deterministic,),
        (deterministic_validation,),
        (),
        deterministic,
        deterministic_plan,
        deterministic_result,
        deterministic_final,
    )
    single_final, single_receipt = workloads.single_prompt_verdict(
        item.contract,
        deterministic,
        deterministic_result,
        item.bundle,
        item.protocol,
        feedback_config,
    )
    single_report = ResearchEpisodeReport(
        "DISCOVERY_EXECUTED",
        item.contract,
        (deterministic,),
        (deterministic_validation,),
        (),
        deterministic,
        deterministic_plan,
        deterministic_result,
        single_final,
        (single_receipt,),
    )

    hypotheses, generation_receipt = workloads.generate_hypotheses(
        item.contract, item.bundle, item.protocol, research_config
    )
    validations = tuple(validator.validate(item.contract, value) for value in hypotheses)
    executable = tuple(
        value
        for value, validation in zip(hypotheses, validations, strict=True)
        if validation.status.value == "EXECUTABLE"
    )
    if not executable:
        raise RuntimeError(f"{item.contract.episode_id} produced no executable hypothesis")

    without_selected = executable[0]
    without_plan = adapter.instantiate(item.contract, without_selected, config, code_ref=CODE_REF)
    without_result = adapter.execute_replay(
        plan=without_plan,
        episode=item.view,
        window=item.window,
        records=item.records,
        market_state=item.stratum,
        config=config,
        result_authority=result_port,
        hypothesis=without_selected,
    )
    without_final, without_receipt = workloads.final_verdict(without_selected, without_result, feedback_config)
    without_report = ResearchEpisodeReport(
        "DISCOVERY_EXECUTED",
        item.contract,
        hypotheses,
        validations,
        (),
        without_selected,
        without_plan,
        without_result,
        without_final,
        (generation_receipt, without_receipt),
    )

    reviews: list[CriticReview] = []
    review_receipts = []
    full_selected: HypothesisSpec | None = None
    for value in executable:
        review, receipt = workloads.critique(item.contract, value, item.bundle, item.protocol, critic_config)
        reviews.append(review)
        review_receipts.append(receipt)
        if full_selected is None and review.decision is CriticDecision.SELECT:
            full_selected = value

    base_arms = {
        "deterministic_template": template_report,
        "single_prompt_analyst": single_report,
        "research_without_critic": without_report,
    }
    if full_selected is None:
        for name, report in base_arms.items():
            _write_arm(episode_dir, name, report)
        blocked = _critic_blocked_markdown(item.contract, tuple(reviews))
        _write_json(
            episode_dir / "research_critic_result_feedback.json",
            {
                "schema_version": "mvp-r-004.critic-blocked.v1",
                "execution_mode": "DISCOVERY_EXECUTED",
                "episode": item.contract.to_dict(),
                "hypotheses": tuple(value.to_dict() for value in hypotheses),
                "validations": tuple(value.to_dict() for value in validations),
                "critic_reviews": tuple(value.to_dict() for value in reviews),
                "outcome": "NO_EXPERIMENT_CRITIC_SELECTED_NONE",
                "model_receipts": tuple(_receipt_payload(value) for value in (generation_receipt, *review_receipts)),
            },
        )
        (episode_dir / "research_critic_result_feedback.md").write_text(blocked, encoding="utf-8")
        _write_blind_reports(
            episode_dir,
            item.contract.episode_id,
            {
                **{name: _markdown(report) for name, report in base_arms.items()},
                "research_critic_result_feedback": blocked,
            },
        )
        return

    full_plan = adapter.instantiate(item.contract, full_selected, config, code_ref=CODE_REF)
    full_result = adapter.execute_replay(
        plan=full_plan,
        episode=item.view,
        window=item.window,
        records=item.records,
        market_state=item.stratum,
        config=config,
        result_authority=result_port,
        hypothesis=full_selected,
    )
    if not full_result.complete:
        raise RuntimeError(f"{item.contract.episode_id} selected experiment did not complete")
    full_final, full_receipt = workloads.final_verdict(full_selected, full_result, feedback_config)
    full_report = ResearchEpisodeReport(
        "DISCOVERY_EXECUTED",
        item.contract,
        hypotheses,
        validations,
        tuple(reviews),
        full_selected,
        full_plan,
        full_result,
        full_final,
        (generation_receipt, *review_receipts, full_receipt),
    )
    arms = {**base_arms, "research_critic_result_feedback": full_report}
    for name, report in arms.items():
        _write_arm(episode_dir, name, report)
    _write_blind_reports(
        episode_dir,
        item.contract.episode_id,
        {name: _markdown(report) for name, report in arms.items()},
    )


def _write_scorecard_from_disk(roster: dict[str, object]) -> Path:
    summaries = tuple(
        _disk_episode_summary(cast(dict[str, object], item)) for item in cast(list[object], roster["episodes"])
    )
    labeled = tuple(case for item in summaries for case in _labeled(item))
    outcomes = tuple(_outcome(item) for item in summaries)
    gate = compute_discovery_gate(outcomes, labeled, user_blind_eval=_user_blind_eval_status())
    slim = tuple(
        {
            "episode_id": item["episode_id"],
            "instrument": item["instrument"],
            "stratum": item["stratum"],
            "market_cutoff": item["market_cutoff"],
            "complete": item["complete"],
            "repaired": item["repaired"],
            "executable_count": item["executable_count"],
            "agent_hypothesis_count": item["agent_hypothesis_count"],
            "gold_clean_decision": item["gold_clean_decision"],
            "gold_bad_decision": item["gold_bad_decision"],
            "critic_decisions": item["critic_decisions"],
            "arm_verdicts": item["arm_verdicts"],
            "without_experiment_complete": item["without_experiment_complete"],
            "full_arm_complete": item["full_arm_complete"],
            "run_dir": f"datasets/mvp-r-001/runs/mvp-r-004-discovery/{item['episode_id']}",
        }
        for item in summaries
    )
    scorecard = {
        "schema_version": "mvp-r-004.discovery-scorecard.v1",
        "task": "MVP-R-004",
        "phase": "discovery",
        "roster_path": "evidence/mvp-r-004/discovery/roster.json",
        "roster_sha256": roster["content_sha256"],
        "r003_evidence_untouched": True,
        "canary_required": "CANARY_PASS",
        "episodes": slim,
        "gate": gate,
        "blind_eval_instructions": (
            "Each episode directory contains blind/option-A.md through option-D.md with arm labels removed. "
            "Read those four files before opening blind-mapping.json."
        ),
    }
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    (RUN_ROOT / "batch-summary.json").write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    return SCORECARD_PATH


def _disk_episode_summary(roster_item: dict[str, object]) -> dict[str, object]:
    episode_id = cast(str, roster_item["episode_id"])
    episode_dir = RUN_ROOT / episode_id
    gold = _read_json(episode_dir / "gold.json") or {}
    full = _read_json(episode_dir / "research_critic_result_feedback.json")
    without = _read_json(episode_dir / "research_without_critic.json")
    template = _read_json(episode_dir / "deterministic_template.json")
    single = _read_json(episode_dir / "single_prompt_analyst.json")
    source = without or full or {}
    reviews = tuple(
        cast(dict[str, object], item) for item in cast(list[object], (full or {}).get("critic_reviews") or ())
    )
    validations = tuple(cast(dict[str, object], item) for item in cast(list[object], source.get("validations") or ()))
    hypotheses = tuple(cast(dict[str, object], item) for item in cast(list[object], source.get("hypotheses") or ()))
    critic_decisions = tuple(cast(str, item["decision"]) for item in reviews)
    selected = sum(decision == "SELECT" for decision in critic_decisions)
    full_result = (full or {}).get("experiment_result")
    full_complete = type(full_result) is dict and bool(cast(dict[str, object], full_result).get("complete"))
    if (full or {}).get("schema_version") == "mvp-r-004.critic-blocked.v1":
        full_complete = False
    without_result = (without or {}).get("experiment_result")
    without_complete = type(without_result) is dict and bool(cast(dict[str, object], without_result).get("complete"))
    return {
        "episode_id": episode_id,
        "instrument": roster_item["instrument"],
        "stratum": roster_item["stratum"],
        "market_cutoff": roster_item["market_cutoff"],
        "complete": (episode_dir / "blind-mapping.json").exists(),
        "repaired": episode_id in _repaired_episode_ids(),
        "executable_count": sum(item.get("status") == "EXECUTABLE" for item in validations),
        "agent_hypothesis_count": len(hypotheses),
        "gold_clean_decision": _gold_decision(gold, "gold_clean"),
        "gold_bad_decision": _gold_decision(gold, "gold_bad"),
        "critic_decisions": critic_decisions,
        "critic_selected_agent": selected,
        "selected_experiments_run": int(full_complete),
        "arm_verdicts": {
            "deterministic_template": _arm_verdict(template),
            "single_prompt_analyst": _arm_verdict(single),
            "research_without_critic": _arm_verdict(without),
            "research_critic_result_feedback": _arm_verdict(full),
        },
        "without_experiment_complete": without_complete,
        "full_arm_complete": full_complete,
    }


def _gold_decision(payload: dict[str, object], field: str) -> str:
    block = payload.get(field)
    if type(block) is not dict:
        raise ValueError(f"{field} critic decision is missing")
    review = cast(dict[str, object], block).get("review")
    if type(review) is not dict:
        raise ValueError(f"{field} critic review is missing")
    decision = cast(dict[str, object], review).get("decision")
    if type(decision) is not str:
        raise ValueError(f"{field} critic decision is invalid")
    return decision


def _outcome(payload: dict[str, object]) -> DiscoveryEpisodeOutcome:
    verdicts = cast(dict[str, object], payload["arm_verdicts"])
    return DiscoveryEpisodeOutcome(
        cast(str, payload["episode_id"]),
        cast(str, payload["instrument"]),
        cast(str, payload["stratum"]),
        cast(str, payload["market_cutoff"]),
        bool(payload["repaired"]),
        bool(payload["complete"]),
        int(cast(int, payload["executable_count"])),
        cast(str, payload["gold_clean_decision"]),
        cast(str, payload["gold_bad_decision"]),
        bool(payload["without_experiment_complete"]),
        bool(payload["full_arm_complete"]),
        int(cast(int, payload["critic_selected_agent"])),
        int(cast(int, payload["selected_experiments_run"])),
        _optional_str(verdicts.get("deterministic_template")),
        _optional_str(verdicts.get("single_prompt_analyst")),
        _optional_str(verdicts.get("research_without_critic")),
        _optional_str(verdicts.get("research_critic_result_feedback")),
        int(cast(int, payload["agent_hypothesis_count"])),
    )


def _labeled(payload: dict[str, object]) -> tuple[LabeledCriticOutcome, LabeledCriticOutcome]:
    episode_id = cast(str, payload["episode_id"])
    return (
        LabeledCriticOutcome(episode_id, GoldLabel.CLEAN, "SELECT", cast(str, payload["gold_clean_decision"])),
        LabeledCriticOutcome(episode_id, GoldLabel.BAD, "REJECT", cast(str, payload["gold_bad_decision"])),
    )


def _optional_str(value: object) -> str | None:
    return value if type(value) is str else None


def _arm_verdict(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    if payload.get("schema_version") in {"mvp-r-003.critic-blocked.v1", "mvp-r-004.critic-blocked.v1"}:
        outcome = payload.get("outcome")
        return outcome if type(outcome) is str else None
    verdict = payload.get("final_verdict") or {}
    if type(verdict) is not dict:
        return None
    value = cast(dict[str, object], verdict).get("verdict")
    return value if type(value) is str else None


def _repaired_episode_ids() -> frozenset[str]:
    names = []
    for path in EVIDENCE_ROOT.glob("*-attempt-*-failure.json"):
        payload = _read_json(path)
        if payload and type(payload.get("episode_id")) is str:
            names.append(cast(str, payload["episode_id"]))
    return frozenset(names)


def _write_failure(episode_id: str, error: Exception) -> None:
    existing = list(EVIDENCE_ROOT.glob(f"{episode_id}-attempt-*-failure.json"))
    attempt = len(existing) + 1
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(
        EVIDENCE_ROOT / f"{episode_id}-attempt-{attempt}-failure.json",
        {
            "schema_version": "mvp-r-004.discovery-failure.v1",
            "episode_id": episode_id,
            "attempt": attempt,
            "completed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "FAILED_CLOSED",
            "failure": f"{type(error).__name__}: {error}",
            "tool_or_trading_side_effect": False,
            "manual_output_repair": False,
            "counts_as_completed_episode": False,
        },
    )


def _issue_episodes(
    roster: dict[str, object],
) -> tuple[tuple[IssuedDiscoveryEpisode, ...], TrustedResearchToolsPort, ValidationConfig]:
    stored = _stored_datasets()
    records_by_manifest = {dataset_manifest_sha256(item.manifest): _records(item) for item in stored}
    all_records = tuple(record for records in records_by_manifest.values() for record in records)
    master = _master_secret()
    contracts = {
        dataset_manifest_sha256(item.manifest): canonical_sha256(
            {
                "source_uri": item.manifest.provenance.source_uri,
                "source_revision": item.manifest.provenance.source_revision,
                "license": "personal-non-commercial-research-no-redistribution",
                "governance_authorized_at": "2026-08-28",
            }
        )
        for item in stored
    }
    authority = DatasetAuthorizationAuthority(
        "mvp-r-004.data-governance",
        _key(master, "mvp-r-004-data"),
        contracts,
        frozenset({sha256_digest(b"MVP-R known synthetic denylist sentinel")}),
        frozenset({OFFICIAL_RESEARCH_SERIES_NORMALIZER}),
    )
    dataset_refs = tuple(
        authority.authorize(
            item,
            provider_contract_sha256=contracts[dataset_manifest_sha256(item.manifest)],
            records=records_by_manifest[dataset_manifest_sha256(item.manifest)],
        )
        for item in stored
    )
    config = _validation_config()
    suite = _suite(dataset_refs, authority.authority_id)
    candidates = stratified_replay_candidates(
        all_records,
        cutoff_start=RecordedAt.parse("2026-03-01T00:00:00Z"),
        cutoff_end=RecordedAt.parse("2026-08-20T23:59:59Z"),
        candidates_per_cell=2,
    )
    by_key = {
        (item.instrument_id, item.stratum.value, item.market_cutoff.to_dict()["recorded_at"]): item
        for item in candidates
    }
    v1 = cast(dict[str, object], json.loads(R003_ROSTER_PATH.read_text(encoding="utf-8")))
    v1_keys = {
        (
            cast(str, item["instrument"]),
            cast(str, item["stratum"]),
            cast(str, item["market_cutoff"]),
        )
        for item in cast(list[object], v1["episodes"])
        for item in (cast(dict[str, object], item),)
    }
    ref_by_instrument = {instrument: ref for ref in dataset_refs for instrument in ref.instrument_universe}
    protocol = build_validation_protocol_digest(config, sample_count=40)
    issued = []
    for raw in cast(list[object], roster["episodes"]):
        roster_item = cast(dict[str, object], raw)
        key = (
            cast(str, roster_item["instrument"]),
            cast(str, roster_item["stratum"]),
            cast(str, roster_item["market_cutoff"]),
        )
        if key in v1_keys:
            raise RuntimeError("frozen R-004 discovery roster reused an R-003 v1 window")
        candidate = by_key[key]
        issued.append(
            _issue_one(
                candidate,
                roster_item,
                ref_by_instrument[key[0]],
                authority,
                suite,
                config,
                protocol,
            )
        )
    return tuple(issued), TrustedResearchToolsPort(_key(master, "mvp-r-004-results")), config


def _issue_one(
    candidate: ReplayEpisodeCandidate,
    roster_item: dict[str, object],
    dataset_ref: DatasetEvidenceRef,
    authority: DatasetAuthorizationAuthority,
    suite: EvaluationSuite,
    config: ValidationConfig,
    protocol: ValidationProtocolDigest,
) -> IssuedDiscoveryEpisode:
    artifacts = tuple(
        authority.issue_artifact(dataset_ref, candidate.instrument_id, record) for record in candidate.records
    )
    window = RetrospectiveWindowIssuer().issue(
        instrument_id=candidate.instrument_id,
        acquisition_as_of=candidate.records[-1].available_time,
        market_cutoff=candidate.market_cutoff,
        artifacts=artifacts,
    )
    episode = EpisodeIssuer().issue(
        suite=suite,
        episode_id=semantic_entity_id(
            "evaluation_episode", {"task": "MVP-R-004", "id": cast(str, roster_item["episode_id"])}
        ),
        phase=EpisodePhase.DIAGNOSTIC,
        mode=EpisodeMode.RETROSPECTIVE_SEALED_REPLAY,
        instrument_id=candidate.instrument_id,
        as_of=candidate.records[-1].available_time,
        market_cutoff=candidate.market_cutoff,
        future_reveal_at=candidate.future_record.event_time,
        artifacts=artifacts,
        retrospective_window=window,
    )
    contract = _contract_episode(roster_item, candidate, dataset_ref.manifest_sha256, window, config)
    bundle = build_research_evidence_bundle(
        episode_id=contract.episode_id,
        instrument=contract.instrument,
        market_cutoff=contract.market_cutoff,
        as_of=contract.as_of,
        market_state=contract.market_state,
        records=candidate.records,
    )
    return IssuedDiscoveryEpisode(
        roster_item,
        contract,
        episode.agent_view(),
        window,
        candidate.records,
        candidate.stratum,
        bundle,
        protocol,
    )


def _contract_episode(
    roster_item: dict[str, object],
    candidate: ReplayEpisodeCandidate,
    manifest_sha256: str,
    window: RetrospectiveMarketWindow,
    config: ValidationConfig,
) -> ResearchEpisodeInput:
    def ref(kind: str, uri: str, digest: str) -> ArtifactRef:
        return ArtifactRef(kind, uri, digest)

    feature_digest = canonical_sha256(
        {
            "instrument": candidate.instrument_id,
            "market_cutoff": cast(str, roster_item["market_cutoff"]),
            "stratum": candidate.stratum.value,
            "task": "MVP-R-004",
            "phase": "discovery",
        }
    )
    snapshot = ref("market_snapshot", f"market-snapshot://{window.content_sha256}", window.content_sha256)
    feature = ref("feature", f"feature://{feature_digest}", feature_digest)
    return ResearchEpisodeInput(
        episode_id=cast(str, roster_item["episode_id"]),
        instrument=candidate.instrument_id,
        as_of=candidate.records[-1].available_time.to_dict()["recorded_at"],
        market_cutoff=candidate.market_cutoff.to_dict()["recorded_at"],
        acquired_at=candidate.records[-1].available_time.to_dict()["recorded_at"],
        dataset_ref=ref("dataset", f"dataset://{manifest_sha256}", manifest_sha256),
        market_snapshot_ref=snapshot,
        feature_ref=feature,
        rule_ref=ref("rule", f"validation-config://{config.content_sha256}", config.content_sha256),
        cost_ref=ref("cost", f"cost://{config.content_sha256}", config.content_sha256),
        toolset_ref=ref("toolset", f"toolset://{MVP_R_TOOLSET_VERSION}", canonical_sha256(MVP_R_TOOLSET_VERSION)),
        signal_operators=(SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,),
        allowed_parameter_values=(
            ("direction", ("FOLLOW", "INVERT")),
            ("threshold", (format(config.signal_threshold, "f"),)),
        ),
        market_state=candidate.stratum.value,
        warnings=("dominant-contract component rolls are not back-adjusted",),
        unknowns=("future regime persistence", "intraday execution unavailable"),
        evidence_refs=(snapshot, feature),
        tradable=False,
        future_result_present=False,
    )


def _template_hypothesis(episode: ResearchEpisodeInput, threshold: str) -> HypothesisSpec:
    clean, _unused = gold_cases(episode, threshold)
    return replace(clean.hypothesis, hypothesis_id=f"{episode.episode_id}-template")


def _deterministic_verdict(hypothesis: HypothesisSpec, result) -> ResearchFinalVerdict:
    metrics = decimal_metrics(result)
    supported = (
        metrics.get("signal_accuracy", Decimal("-1")) > metrics.get("counterfactual_signal_accuracy", Decimal("1"))
        and metrics.get("stressed_net_return", Decimal("-1"))
        > metrics.get("counterfactual_stressed_net_return", Decimal("1"))
        and metrics.get("positive_fold_ratio", Decimal("0")) >= Decimal("0.5")
    )
    return ResearchFinalVerdict(
        verdict_id=f"{result.packet_id}-template-verdict",
        verdict=FinalVerdict.ACCEPT if supported else FinalVerdict.REJECT,
        hypothesis_ref=hypothesis.identity,
        falsification_condition=hypothesis.falsification_condition,
        result_refs=(result.identity,),
        rationale="All registered deterministic comparisons pass." if supported else "A registered comparison failed.",
    )


def _suite(dataset_refs: tuple[DatasetEvidenceRef, ...], authority_id: str) -> EvaluationSuite:
    model_config = _model_config()
    tools = frozen_mvp_tool_specs(REQUEST_SHA256)
    runtime = FrozenRuntimeIdentity(
        canonical_sha256({"prompt": "mvp-r-004-discovery"}),
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        canonical_sha256({"policy": "research-only-no-trading"}),
    )
    return EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": "MVP-R-004", "roster": "discovery-v1"}),
        1,
        model_config.content_sha256,
        runtime.agent_sha256,
        canonical_sha256(
            tuple(
                {"name": tool.name, "description": tool.description, "parameters_json": tool.parameters_json}
                for tool in tools
            )
        ),
        runtime.content_sha256,
        authority_id,
        "mvp-r-004.discovery-evaluator",
        tuple(dataset_refs),
        tuple(sorted(instrument for ref in dataset_refs for instrument in ref.instrument_universe)),
        MVP_R_EPISODE_SELECTION_RULE,
        "mvp-r-004.discovery.v1",
        ("gold_label_critic.v1", "result_packet_metric_map.v1"),
        MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        3,
    )


def _model_config() -> ModelRunConfig:
    profile = ModelProfileRevision(
        semantic_entity_id("model_profile", {"task": "MVP-R-004", "purpose": "discovery-issuer"}),
        1,
        WorkloadId("research.hypothesis_synthesis"),
        ModelProtocolFamily.MVP_R_001,
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        "high",
        "mvp-r-004.prompt.v1",
        "mvp-r-004.hypothesis.v1",
        MVP_R_TOOLSET_VERSION,
        ModelRunnerCapabilities(
            True,
            True,
            True,
            True,
            True,
            ModelCostAccountingMode.SUBSCRIPTION_UNAVAILABLE,
            True,
            "mvp-r.codex-app-server.v1",
        ),
        ModelQualificationState.QUALIFIED,
    )
    binding = ModelActivationBinding.activate(
        semantic_entity_id("model_activation", {"profile": profile.content_sha256}), profile
    )
    resolved = ResolvedRunConfig.resolve(binding, profile)
    return ModelRunConfig(
        semantic_entity_id("model_run_config", {"profile": profile.content_sha256}),
        1,
        resolved,
        "mvp-r-004.prompt.v1",
        "mvp-r-004.discovery",
        MVP_R_TOOLSET_VERSION,
        1,
        1,
        4_000,
        50_000,
        180,
        1_000_000,
        0,
        0,
        1,
        1,
        0,
    )


def _validation_config() -> ValidationConfig:
    return ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": "MVP-R-004", "revision": 1}),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.00010000"),
        Decimal("2.00000000"),
        Decimal("1.00000000"),
        (Decimal("1.00000000"), Decimal("2.00000000")),
        2,
    )


def _load_roster() -> dict[str, object]:
    roster = cast(dict[str, object], json.loads(ROSTER_PATH.read_text(encoding="utf-8")))
    content = {key: value for key, value in roster.items() if key != "content_sha256"}
    if canonical_sha256(_freeze(content)) != roster.get("content_sha256"):
        raise ValueError("discovery roster digest mismatch")
    return roster


def _assert_r003_evidence_untouched() -> None:
    if not R003_SCORECARD.exists():
        raise FileNotFoundError("R-003 v1 scorecard must remain on disk")
    payload = json.loads(R003_SCORECARD.read_text(encoding="utf-8"))
    if payload.get("gate", {}).get("decision") != "STOP/PIVOT":
        raise RuntimeError("R-004 must not rewrite the R-003 v1 scorecard decision")


def _assert_canary_passed() -> None:
    if not CANARY_SCORECARD.exists():
        raise FileNotFoundError("R-004 canary scorecard is required before discovery")
    payload = json.loads(CANARY_SCORECARD.read_text(encoding="utf-8"))
    if payload.get("gate", {}).get("decision") != "CANARY_PASS":
        raise RuntimeError("R-004 discovery cannot start until canary is CANARY_PASS")
    if payload.get("gate", {}).get("hardcoded") is not False:
        raise RuntimeError("canary gate must be computed, not hardcoded")


def _stored_datasets() -> tuple[StoredDataset, ...]:
    summary = json.loads((DATA_ROOT / "collection-summary.json").read_text(encoding="utf-8"))
    store = LocalFileDataStore(DATA_ROOT / "normalized", DatasetLayer.NORMALIZED_PIT)
    return tuple(store.get(EntityId.parse(item["normalized_dataset_id"])) for item in summary["sources"])


def _records(dataset: StoredDataset) -> tuple[PointInTimeRecord, ...]:
    return tuple(
        PointInTimeRecord(
            RecordedAt.parse(item["event_time"]),
            RecordedAt.parse(item["available_time"]),
            item["values"],
        )
        for item in json.loads(dataset.content)
    )


def _master_secret() -> bytes:
    if not MASTER_SECRET_PATH.exists():
        raise FileNotFoundError("existing local governance key is required")
    secret = MASTER_SECRET_PATH.read_bytes()
    if len(secret) != 32:
        raise ValueError("local governance key has invalid length")
    return secret


def _key(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()


def _critic_blocked_markdown(episode: ResearchEpisodeInput, reviews: tuple[CriticReview, ...]) -> str:
    decisions = "\n".join(
        f"- `{review.hypothesis_id}`: `{review.decision.value}` — {', '.join(review.reason_codes)}"
        for review in reviews
    )
    return (
        f"# MVP-R-004 Research Episode {episode.episode_id}\n\n"
        "Execution mode: `DISCOVERY_EXECUTED`\n\n"
        "This report is research and simulation only. No hypothesis was selected for experiment.\n\n"
        "## Experiment-pre judgment\n\n"
        "- Multiple bounded hypotheses passed deterministic executability validation.\n\n"
        "## Independent Critic\n\n"
        f"{decisions}\n\n"
        "## Deterministic experiment results\n\n"
        "- No experiment ran in this arm because the Critic selected no hypothesis.\n\n"
        "## Experiment-post judgment\n\n"
        "- Outcome: `NO_EXPERIMENT_CRITIC_SELECTED_NONE`\n"
        "- No ResultPacket or trading action was fabricated.\n\n"
        "## Limitations\n\n"
        "- This arm cannot support an empirical FinalVerdict without a selected experiment.\n"
    )


def _markdown(report: ResearchEpisodeReport) -> str:
    return report.render_markdown().replace("MVP-R-003 Research Episode", "MVP-R-004 Research Episode")


def _write_arm(episode_dir: Path, name: str, report: ResearchEpisodeReport) -> None:
    _write_json(episode_dir / f"{name}.json", report.to_dict())
    (episode_dir / f"{name}.md").write_text(_markdown(report), encoding="utf-8")


def _write_blind_reports(episode_dir: Path, episode_id: str, reports: dict[str, str]) -> None:
    blind_order = tuple(sorted(reports, key=lambda name: canonical_sha256({"episode": episode_id, "arm": name})))
    blind_dir = episode_dir / "blind"
    blind_dir.mkdir(exist_ok=True)
    labels = ("A", "B", "C", "D")
    for label, name in zip(labels, blind_order, strict=True):
        text = reports[name].replace(
            f"MVP-R-004 Research Episode {episode_id}",
            f"Research Option {label}",
        )
        (blind_dir / f"option-{label}.md").write_text(text, encoding="utf-8")
    _write_json(
        episode_dir / "blind-mapping.json",
        {"episode_id": episode_id, "mapping": tuple(zip(labels, blind_order, strict=True))},
    )


def _receipt_payload(value: ModelWorkloadReceipt) -> dict[str, object]:
    return {
        "workload": value.workload,
        "response_id": value.response_id,
        "model": value.model,
        "reasoning_effort": value.reasoning_effort,
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "reasoning_tokens": value.reasoning_tokens,
        "latency_ms": value.latency_ms,
        "request_sha256": value.request_sha256,
        "response_sha256": value.response_sha256,
        "receipt_sha256": value.content_sha256,
    }


def _user_blind_eval_status() -> str:
    payload = _read_json(USER_BLIND_PATH)
    if payload is None:
        return "NOT_STARTED"
    gate = payload.get("gate")
    if type(gate) is not dict:
        raise ValueError(f"{USER_BLIND_PATH} is missing a gate object")
    decision = gate.get("decision")
    if type(decision) is not str or not decision:
        raise ValueError(f"{USER_BLIND_PATH} is missing gate.decision")
    return decision


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError(f"{path} is not a JSON object")
    return cast(dict[str, object], payload)


def _read_decision(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return cast(str, cast(dict[str, object], payload["gate"])["decision"])


def _freeze(value: object) -> JsonValue:
    if value is None:
        return None
    if type(value) is str:
        return value
    if type(value) is int:
        return value
    if type(value) is bool:
        return value
    if type(value) in {tuple, list}:
        frozen_seq: tuple[JsonValue, ...] = tuple(
            _freeze(item) for item in cast(tuple[object, ...] | list[object], value)
        )
        return frozen_seq
    if type(value) is dict:
        frozen: dict[str, JsonValue] = {
            cast(str, key): _freeze(item) for key, item in cast(dict[object, object], value).items()
        }
        return frozen
    raise TypeError("scorecard must contain finite JSON")


def _write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json_text(_freeze(value)), encoding="utf-8")


if __name__ == "__main__":
    main()
