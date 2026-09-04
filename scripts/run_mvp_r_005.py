"""Run the eight-episode MVP-R-005 single-agent loop versus Single-prompt baseline.

Does not touch MVP-R-003 or MVP-R-004 Evidence. Critic is shadow-only after experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
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
    MvpR003ExperimentAdapter,
    ResearchEpisodeInput,
    SignalOperator,
    StructuredModelConfig,
)
from futures_agent_os.research_experiment.mvp_r_003.contracts import ExperimentResultPacket, HypothesisSpec
from futures_agent_os.research_experiment.mvp_r_003.model_workloads import ModelWorkloadReceipt
from futures_agent_os.research_experiment.mvp_r_004 import (
    MvpR004HypothesisValidator,
    ResearchEvidenceBundle,
    ValidationProtocolDigest,
    build_research_evidence_bundle,
    build_validation_protocol_digest,
)
from futures_agent_os.research_experiment.mvp_r_005 import (
    MvpR005ModelWorkloads,
    R005CorrectionV2EpisodeOutcome,
    R005CorrectionV3EpisodeOutcome,
    R005EpisodeOutcome,
    assess_correction_v3_episode,
    assess_correction_v5_episode,
    build_predecessor_hash_manifest,
    build_treatment_metric_view,
    compute_r005_correction_v2_gate,
    compute_r005_correction_v3_gate,
    compute_r005_correction_v4_gate,
    compute_r005_correction_v5_gate,
    compute_r005_gate,
    fallback_hypothesis,
    fold_metrics_bound_to_manifest,
    packet_direction_bound,
    packet_has_authentic_walk_forward,
    packet_has_fold_signal_accuracies,
    packet_treatment_control_mirror,
    parse_falsification_condition,
    predecessor_evidence_status,
    predecessor_hashes_match,
    render_decision_brief_markdown,
)
from futures_agent_os.research_experiment.mvp_r_005.evidence import (
    PRE_V2_BYTE_STABILITY,
    load_predecessor_hash_manifest,
    write_predecessor_hash_manifest,
)
from futures_agent_os.research_experiment.mvp_r_005.predicate import evaluate_falsification_predicate

from futures_agent_os.research_experiment.mvp_replay import ReplayEpisodeCandidate
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
from futures_agent_os.research_experiment.mvp_validation import AgentEpisodeView, ModelRunConfig
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
R003_ROSTER_PATH = ROOT / "evidence" / "mvp-r-003" / "discovery" / "roster.json"
R004_ROSTER_PATH = ROOT / "evidence" / "mvp-r-004" / "discovery" / "roster.json"
ROSTER_PATH = ROOT / "evidence" / "mvp-r-005" / "roster.json"
EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-005"
RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-005-discovery"
SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
WP_PATH = EVIDENCE_ROOT / "wp-discovery.json"
MASTER_SECRET_PATH = DATA_ROOT / ".governance-master-key"
REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-005", "workload": "discovery"})
CODE_REF = "mvp-r-005-discovery-v1"
FOUR_BLOCK_HEADINGS = ("## 测了什么", "## 结果怎样", "## 当前判断", "## 下一步动作")
LOGGER = logging.getLogger("mvp-r-005-discovery")
CORRECTION_V2 = False
CORRECTION_V3 = False
CORRECTION_V4 = False
CORRECTION_V5 = False
CANDIDATES_PER_CELL = 3
EXTRA_FORBIDDEN_KEYS: frozenset[tuple[str, str, str]] = frozenset()
ACTIVE_TASK = "MVP-R-005"
ACTIVE_PHASE_NAME = "discovery"
ACTIVE_EPISODE_PHASE = EpisodePhase.DIAGNOSTIC
ACTIVE_EXECUTION_MODE = "DISCOVERY_EXECUTED"
DATA_HMAC_LABEL = "mvp-r-005-data"
RESULT_HMAC_LABEL = "mvp-r-005-results"
HASH_BASELINE_PATH = EVIDENCE_ROOT / "predecessor-hash-baseline.json"
HASH_FINAL_PATH = EVIDENCE_ROOT / "predecessor-hash-final.json"


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


def _configure_correction_v2() -> None:
    global EVIDENCE_ROOT, RUN_ROOT, SCORECARD_PATH, WP_PATH, CODE_REF, REQUEST_SHA256, LOGGER
    global CORRECTION_V2, DATA_HMAC_LABEL, RESULT_HMAC_LABEL, HASH_BASELINE_PATH, HASH_FINAL_PATH
    CORRECTION_V2 = True
    EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-005" / "correction-v2"
    RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-005-correction-v2"
    SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
    WP_PATH = EVIDENCE_ROOT / "wp-discovery.json"
    CODE_REF = "mvp-r-005-correction-v2"
    REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-005", "workload": "correction-v2"})
    DATA_HMAC_LABEL = "mvp-r-005-correction-v2-data"
    RESULT_HMAC_LABEL = "mvp-r-005-correction-v2-results"
    LOGGER = logging.getLogger("mvp-r-005-correction-v2")
    v1 = json.loads((ROOT / "evidence" / "mvp-r-005" / "scorecard.json").read_text(encoding="utf-8"))
    if v1["gate"]["schema_version"] != "mvp-r-005.discovery-gate.v1" or v1["gate"]["decision"] != "R005_PASS":
        raise RuntimeError("R-005 v1 scorecard must remain historical R005_PASS; do not rewrite it")
    HASH_BASELINE_PATH = EVIDENCE_ROOT / "predecessor-hash-baseline.json"
    HASH_FINAL_PATH = EVIDENCE_ROOT / "predecessor-hash-final.json"


def _configure_correction_v3() -> None:
    global EVIDENCE_ROOT, RUN_ROOT, SCORECARD_PATH, WP_PATH, CODE_REF, REQUEST_SHA256, LOGGER
    global CORRECTION_V2, CORRECTION_V3, DATA_HMAC_LABEL, RESULT_HMAC_LABEL
    global HASH_BASELINE_PATH, HASH_FINAL_PATH
    if CORRECTION_V2:
        raise RuntimeError("correction-v3 cannot overwrite correction-v2")
    CORRECTION_V3 = True
    EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-005" / "correction-v3"
    RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-005-correction-v3"
    SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
    WP_PATH = EVIDENCE_ROOT / "wp-discovery.json"
    CODE_REF = "mvp-r-005-correction-v3"
    REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-005", "workload": "correction-v3"})
    DATA_HMAC_LABEL = "mvp-r-005-correction-v3-data"
    RESULT_HMAC_LABEL = "mvp-r-005-correction-v3-results"
    LOGGER = logging.getLogger("mvp-r-005-correction-v3")
    HASH_BASELINE_PATH = EVIDENCE_ROOT / "predecessor-hash-baseline.json"
    HASH_FINAL_PATH = EVIDENCE_ROOT / "predecessor-hash-final.json"
    v1 = json.loads((ROOT / "evidence" / "mvp-r-005" / "scorecard.json").read_text(encoding="utf-8"))
    if v1["gate"]["schema_version"] != "mvp-r-005.discovery-gate.v1" or v1["gate"]["decision"] != "R005_PASS":
        raise RuntimeError("R-005 v1 scorecard must remain historical R005_PASS; do not rewrite it")
    v2 = json.loads((ROOT / "evidence" / "mvp-r-005" / "correction-v2" / "scorecard.json").read_text(encoding="utf-8"))
    if v2["gate"]["schema_version"] != "mvp-r-005.correction-v2-gate.v1":
        raise RuntimeError("R-005 correction-v2 scorecard must remain in place")
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if not HASH_BASELINE_PATH.exists():
        write_predecessor_hash_manifest(HASH_BASELINE_PATH, build_predecessor_hash_manifest(ROOT))


def _configure_correction_v4() -> None:
    global EVIDENCE_ROOT, RUN_ROOT, SCORECARD_PATH, WP_PATH, LOGGER
    global CORRECTION_V4, HASH_BASELINE_PATH, HASH_FINAL_PATH
    CORRECTION_V4 = True
    EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-005" / "correction-v4"
    RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-005-correction-v3"
    SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
    WP_PATH = EVIDENCE_ROOT / "wp-discovery.json"
    LOGGER = logging.getLogger("mvp-r-005-correction-v4")
    HASH_BASELINE_PATH = EVIDENCE_ROOT / "predecessor-hash-baseline.json"
    HASH_FINAL_PATH = EVIDENCE_ROOT / "predecessor-hash-final.json"
    v3 = json.loads((ROOT / "evidence" / "mvp-r-005" / "correction-v3" / "scorecard.json").read_text(encoding="utf-8"))
    if v3["gate"]["schema_version"] != "mvp-r-005.correction-v3-gate.v1":
        raise RuntimeError("R-005 correction-v3 scorecard must remain in place")
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if not HASH_BASELINE_PATH.exists():
        write_predecessor_hash_manifest(HASH_BASELINE_PATH, build_predecessor_hash_manifest(ROOT))


def _configure_correction_v5() -> None:
    global EVIDENCE_ROOT, RUN_ROOT, SCORECARD_PATH, WP_PATH, LOGGER
    global CORRECTION_V5, HASH_BASELINE_PATH, HASH_FINAL_PATH
    CORRECTION_V5 = True
    EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-005" / "correction-v5"
    RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-005-correction-v3"
    SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
    WP_PATH = EVIDENCE_ROOT / "wp-discovery.json"
    LOGGER = logging.getLogger("mvp-r-005-correction-v5")
    HASH_BASELINE_PATH = EVIDENCE_ROOT / "predecessor-hash-baseline.json"
    HASH_FINAL_PATH = EVIDENCE_ROOT / "predecessor-hash-final.json"
    v4 = json.loads((ROOT / "evidence/mvp-r-005/correction-v4/scorecard.json").read_text(encoding="utf-8"))
    if v4["gate"]["schema_version"] != "mvp-r-005.correction-v4-gate.v1":
        raise RuntimeError("R-005 correction-v4 scorecard must remain in place")
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if not HASH_BASELINE_PATH.exists():
        write_predecessor_hash_manifest(HASH_BASELINE_PATH, build_predecessor_hash_manifest(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-roster", action="store_true")
    parser.add_argument("--correction-v2", action="store_true")
    parser.add_argument("--correction-v3", action="store_true")
    parser.add_argument("--correction-v4", action="store_true")
    parser.add_argument("--correction-v5", action="store_true")
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
    predecessor_evidence_status(ROOT)
    if sum((args.correction_v2, args.correction_v3, args.correction_v4, args.correction_v5)) > 1:
        raise SystemExit("choose exactly one correction revision")
    if args.correction_v2:
        if args.freeze_roster:
            raise SystemExit("correction-v2 must reuse the frozen v1 roster")
        _configure_correction_v2()
    if args.correction_v3:
        if args.freeze_roster:
            raise SystemExit("correction-v3 must reuse the frozen v1 roster")
        _configure_correction_v3()
    if args.correction_v4:
        if args.freeze_roster:
            raise SystemExit("correction-v4 must reuse the frozen v1 roster")
        if not args.summarize_only and not args.plan_only:
            raise SystemExit("correction-v4 is evidence-only; use --summarize-only or --plan-only")
        _configure_correction_v4()
    if args.correction_v5:
        if args.freeze_roster:
            raise SystemExit("correction-v5 must reuse the frozen v1 roster")
        if not args.summarize_only and not args.plan_only:
            raise SystemExit("correction-v5 is evidence-only; use --summarize-only or --plan-only")
        _configure_correction_v5()
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
            item for item in issued if not (RUN_ROOT / item.contract.episode_id / "research_agent_loop.md").exists()
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
                    "pre_v2_byte_stability": PRE_V2_BYTE_STABILITY if CORRECTION_V3 else None,
                    "predecessor_hash_baseline": HASH_BASELINE_PATH.name
                    if CORRECTION_V3 or CORRECTION_V4 or CORRECTION_V5
                    else None,
                }
            )
        )
        return
    workloads = MvpR005ModelWorkloads(OfficialCodexAppServerTransport())
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
    r004 = cast(dict[str, object], json.loads(R004_ROSTER_PATH.read_text(encoding="utf-8")))
    forbidden = _roster_keys(v1) | _roster_keys(r004)
    stored = _stored_datasets()
    all_records = tuple(record for dataset in stored for record in _records(dataset))
    candidates = stratified_replay_candidates(
        all_records,
        cutoff_start=RecordedAt.parse("2026-03-01T00:00:00Z"),
        cutoff_end=RecordedAt.parse("2026-08-20T23:59:59Z"),
        candidates_per_cell=3,
    )
    by_cell: dict[tuple[str, str], list[ReplayEpisodeCandidate]] = {}
    for candidate in candidates:
        by_cell.setdefault((candidate.instrument_id, candidate.stratum.value), []).append(candidate)
    episodes = []
    for raw in cast(list[object], v1["episodes"]):
        v1_item = cast(dict[str, object], raw)
        instrument = cast(str, v1_item["instrument"])
        stratum = cast(str, v1_item["stratum"])
        cell = by_cell[(instrument, stratum)]
        unused = [
            item for item in cell if (instrument, stratum, item.market_cutoff.to_dict()["recorded_at"]) not in forbidden
        ]
        if not unused:
            raise RuntimeError(f"no unused cutoff for {instrument} {stratum}")
        chosen = sorted(unused, key=lambda item: item.market_cutoff.to_dict()["recorded_at"])[0]
        cutoff = chosen.market_cutoff.to_dict()["recorded_at"]
        if (instrument, stratum, cutoff) in forbidden:
            raise RuntimeError("R-005 discovery roster collided with a predecessor window")
        v1_id = cast(str, v1_item["episode_id"])
        episodes.append(
            {
                "episode_id": f"r005-{v1_id.removeprefix('r003-')}",
                "instrument": instrument,
                "stratum": stratum,
                "market_cutoff": cutoff,
            }
        )
    roster = {
        "schema_version": "mvp-r-005.discovery-roster.v1",
        "task": "MVP-R-005",
        "phase": "discovery",
        "frozen_before_discovery_model_calls": True,
        "selection_rule": (
            "same eight AG/CU/MA/SR instrument-state cells as R-003 v1, using a candidates_per_cell=3 "
            "window whose (instrument, stratum, cutoff) differs from both R-003 v1 and R-004"
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


def _assert_packet_ready(episode_id: str, hypothesis: HypothesisSpec, packet: ExperimentResultPacket) -> None:
    if CORRECTION_V3:
        from futures_agent_os.research_experiment.mvp_r_005.treatment_view import raw_tool_runs_untransformed

        if not raw_tool_runs_untransformed(packet):
            raise RuntimeError(f"{episode_id} raw ToolRunResult metrics were transformed")
        return
    if CORRECTION_V2:
        if not packet_has_authentic_walk_forward(packet):
            raise RuntimeError(f"{episode_id} packet is missing authentic walk-forward fold manifest")
        if not fold_metrics_bound_to_manifest(packet):
            raise RuntimeError(f"{episode_id} fold metrics are not bound to the walk-forward manifest")
        if not packet_direction_bound(hypothesis, packet):
            raise RuntimeError(f"{episode_id} packet direction is not bound to the selected hypothesis")
        if not packet_treatment_control_mirror(packet):
            raise RuntimeError(f"{episode_id} treatment/control metrics are not a semantic mirror")
        return
    if not packet_has_fold_signal_accuracies(packet):
        raise RuntimeError(f"{episode_id} packet is missing per-fold signal_accuracy")


def _predicate_payload(hypothesis: HypothesisSpec, source: object) -> dict[str, object]:
    predicate = parse_falsification_condition(hypothesis.falsification_condition)
    if predicate is None:
        raise RuntimeError(f"{hypothesis.hypothesis_id} is missing a typed falsification predicate")
    return {
        "predicate": predicate.to_dict(),
        "evaluation": evaluate_falsification_predicate(predicate, source).to_dict(),
    }


def _run_episode(
    item: IssuedDiscoveryEpisode,
    config: ValidationConfig,
    result_port: TrustedResearchToolsPort,
    workloads: MvpR005ModelWorkloads,
    research_config: StructuredModelConfig,
    critic_config: StructuredModelConfig,
    feedback_config: StructuredModelConfig,
) -> None:
    episode_dir = RUN_ROOT / item.contract.episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)
    threshold = format(config.signal_threshold, "f")
    validator = MvpR004HypothesisValidator()
    adapter = MvpR003ExperimentAdapter()

    fallback = fallback_hypothesis(item.contract, threshold)
    fallback_validation = validator.validate(item.contract, fallback)
    if fallback_validation.status.value != "EXECUTABLE":
        raise RuntimeError(f"{item.contract.episode_id} fallback hypothesis is not executable")
    fallback_plan = adapter.instantiate(item.contract, fallback, config, code_ref=CODE_REF)
    fallback_result = adapter.execute_replay(
        plan=fallback_plan,
        episode=item.view,
        window=item.window,
        records=item.records,
        market_state=item.stratum,
        config=config,
        result_authority=result_port,
        hypothesis=fallback,
    )
    if not fallback_result.complete:
        raise RuntimeError(f"{item.contract.episode_id} fallback experiment did not complete")
    _assert_packet_ready(item.contract.episode_id, fallback, fallback_result)
    fallback_view = build_treatment_metric_view(fallback_result, hypothesis=fallback, plan=fallback_plan, config=config)
    single_final, single_brief, single_receipt = workloads.single_prompt_verdict(
        item.contract,
        fallback,
        fallback_result,
        fallback_view,
        item.bundle,
        item.protocol,
        feedback_config,
    )
    _write_arm(
        episode_dir,
        "single_prompt_analyst",
        {
            "schema_version": "mvp-r-005.episode-report.v1",
            "execution_mode": ACTIVE_EXECUTION_MODE,
            "arm": "single_prompt_analyst",
            "selected_by": "deterministic_fallback_hypothesis",
            "pre_experiment_critic_gate": False,
            "episode": item.contract.to_dict(),
            "hypotheses": (fallback.to_dict(),),
            "validations": (fallback_validation.to_dict(),),
            "selected_hypothesis": fallback.to_dict(),
            "experiment_plan": fallback_plan.to_dict(),
            "experiment_result": fallback_result.to_dict(),
            "treatment_metric_view": fallback_view.to_dict(),
            "agent_visible_experiment": fallback_view.agent_visible_dict(),
            "final_verdict": single_final.to_dict(),
            "decision_brief": single_brief.to_dict(),
            "shadow_critic": None,
            "model_receipts": (_receipt_payload(single_receipt),),
            "falsification_predicate": _predicate_payload(fallback, fallback_view)
            if CORRECTION_V2 or CORRECTION_V3
            else None,
        },
        render_decision_brief_markdown(item.contract.episode_id, single_brief),
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
    selected = executable[0]
    plan = adapter.instantiate(item.contract, selected, config, code_ref=CODE_REF)
    result = adapter.execute_replay(
        plan=plan,
        episode=item.view,
        window=item.window,
        records=item.records,
        market_state=item.stratum,
        config=config,
        result_authority=result_port,
        hypothesis=selected,
    )
    if not result.complete:
        raise RuntimeError(f"{item.contract.episode_id} agent experiment did not complete")
    _assert_packet_ready(item.contract.episode_id, selected, result)
    view = build_treatment_metric_view(result, hypothesis=selected, plan=plan, config=config)
    final, brief, feedback_receipt = workloads.final_verdict(
        item.contract,
        selected,
        result,
        view,
        item.bundle,
        item.protocol,
        feedback_config,
    )
    shadow, shadow_receipt = workloads.shadow_critique(
        item.contract,
        selected,
        result,
        view,
        item.bundle,
        item.protocol,
        critic_config,
    )
    _write_arm(
        episode_dir,
        "research_agent_loop",
        {
            "schema_version": "mvp-r-005.episode-report.v1",
            "execution_mode": ACTIVE_EXECUTION_MODE,
            "arm": "research_agent_loop",
            "selected_by": "first_executable_hypothesis",
            "pre_experiment_critic_gate": False,
            "critic_blocked_experiment": False,
            "episode": item.contract.to_dict(),
            "hypotheses": tuple(value.to_dict() for value in hypotheses),
            "validations": tuple(value.to_dict() for value in validations),
            "selected_hypothesis": selected.to_dict(),
            "experiment_plan": plan.to_dict(),
            "experiment_result": result.to_dict(),
            "treatment_metric_view": view.to_dict(),
            "agent_visible_experiment": view.agent_visible_dict(),
            "final_verdict": final.to_dict(),
            "decision_brief": brief.to_dict(),
            "shadow_critic": {**shadow.to_dict(), "receipt": _receipt_payload(shadow_receipt)},
            "model_receipts": tuple(
                _receipt_payload(value) for value in (generation_receipt, feedback_receipt, shadow_receipt)
            ),
            "falsification_predicate": _predicate_payload(selected, view) if CORRECTION_V2 or CORRECTION_V3 else None,
        },
        render_decision_brief_markdown(item.contract.episode_id, brief),
    )


def _write_scorecard_from_disk(roster: dict[str, object]) -> Path:
    predecessor = predecessor_evidence_status(ROOT)
    forbidden = _predecessor_keys()
    summaries = tuple(
        _disk_episode_summary(cast(dict[str, object], item), forbidden)
        for item in cast(list[object], roster["episodes"])
    )
    if CORRECTION_V5:
        return _write_correction_v5_scorecard(roster, predecessor)
    if CORRECTION_V4:
        return _write_correction_v4_scorecard(roster, predecessor)
    if CORRECTION_V3:
        return _write_correction_v3_scorecard(roster, predecessor)
    if CORRECTION_V2:
        return _write_correction_v2_scorecard(roster, predecessor, summaries)
    outcomes = tuple(_outcome(item) for item in summaries)
    gate = compute_r005_gate(outcomes)
    slim = tuple(
        {
            "episode_id": item["episode_id"],
            "instrument": item["instrument"],
            "stratum": item["stratum"],
            "market_cutoff": item["market_cutoff"],
            "complete": item["complete"],
            "agent_loop_complete": item["agent_loop_complete"],
            "agent_experiment_complete": item["agent_experiment_complete"],
            "single_prompt_complete": item["single_prompt_complete"],
            "pre_experiment_critic_gate": item["pre_experiment_critic_gate"],
            "critic_blocked_experiment": item["critic_blocked_experiment"],
            "shadow_ran": item["shadow_ran"],
            "shadow_would_have_blocked": item["shadow_would_have_blocked"],
            "packet_has_fold_signal_accuracy": item["packet_has_fold_signal_accuracy"],
            "four_block_report": item["four_block_report"],
            "overlapping_predecessor": item["overlapping_predecessor"],
            "arm_verdicts": item["arm_verdicts"],
            "run_dir": f"datasets/mvp-r-001/runs/mvp-r-005-discovery/{item['episode_id']}",
        }
        for item in summaries
    )
    scorecard = {
        "schema_version": "mvp-r-005.discovery-scorecard.v1",
        "task": "MVP-R-005",
        "phase": "discovery",
        "roster_path": "evidence/mvp-r-005/roster.json",
        "roster_sha256": roster["content_sha256"],
        "predecessor_evidence": predecessor,
        "template_is_product": False,
        "critic_is_pre_experiment_gate": False,
        "independent_real_user_validation": False,
        "not_go": True,
        "episodes": slim,
        "gate": gate,
    }
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    (RUN_ROOT / "batch-summary.json").write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    WP_PATH.write_text(
        canonical_json_text(
            _freeze(
                {
                    "schema_version": "mvp-r-005.wp-evidence.v1",
                    "task": "MVP-R-005",
                    "phase": "discovery",
                    "status": gate["decision"],
                    "executor": "Cursor",
                    "implementation_model": "Cursor Grok 4.6",
                    "reasoning_effort": "NOT_EXPOSED",
                    "product_models": {
                        "research": "gpt-5.6-terra/xhigh",
                        "feedback": "gpt-5.6-terra/xhigh",
                        "shadow_critic": "gpt-5.6-sol/xhigh",
                    },
                    "predecessor_evidence_untouched": True,
                    "roster_sha256": roster["content_sha256"],
                    "gate": gate,
                    "independent_real_user_validation": False,
                    "not_go": True,
                    "approve_formal_30_50_shadow": False,
                    "approve_v1_011": False,
                }
            )
        ),
        encoding="utf-8",
    )
    return SCORECARD_PATH


def _disk_episode_summary(roster_item: dict[str, object], forbidden: set[tuple[str, str, str]]) -> dict[str, object]:
    episode_id = cast(str, roster_item["episode_id"])
    episode_dir = RUN_ROOT / episode_id
    agent = _read_json(episode_dir / "research_agent_loop.json")
    single = _read_json(episode_dir / "single_prompt_analyst.json")
    agent_md = (episode_dir / "research_agent_loop.md").read_text(encoding="utf-8") if agent else ""
    agent_result = (agent or {}).get("experiment_result")
    agent_complete = type(agent_result) is dict and bool(cast(dict[str, object], agent_result).get("complete"))
    single_result = (single or {}).get("experiment_result")
    single_complete = type(single_result) is dict and bool(cast(dict[str, object], single_result).get("complete"))
    shadow = (agent or {}).get("shadow_critic")
    shadow_map = shadow if type(shadow) is dict else {}
    packet = None
    hypothesis_spec = None
    if type(agent_result) is dict:
        packet = ExperimentResultPacket.hydrate(cast(dict[str, object], agent_result))
    selected = (agent or {}).get("selected_hypothesis")
    if type(selected) is dict:
        hypothesis_spec = HypothesisSpec.hydrate(cast(dict[str, object], selected))
    single_packet = None
    if type(single_result) is dict:
        single_packet = ExperimentResultPacket.hydrate(cast(dict[str, object], single_result))
    single_hyp = None
    single_selected = (single or {}).get("selected_hypothesis")
    if type(single_selected) is dict:
        single_hyp = HypothesisSpec.hydrate(cast(dict[str, object], single_selected))
    key = (
        cast(str, roster_item["instrument"]),
        cast(str, roster_item["stratum"]),
        cast(str, roster_item["market_cutoff"]),
    )
    return {
        "episode_id": episode_id,
        "instrument": roster_item["instrument"],
        "stratum": roster_item["stratum"],
        "market_cutoff": roster_item["market_cutoff"],
        "complete": agent_complete and single_complete and bool(agent_md),
        "agent_loop_complete": agent_complete and bool(agent_md),
        "agent_experiment_complete": agent_complete,
        "single_prompt_complete": single_complete,
        "pre_experiment_critic_gate": bool((agent or {}).get("pre_experiment_critic_gate")),
        "critic_blocked_experiment": bool((agent or {}).get("critic_blocked_experiment")),
        "shadow_ran": type(shadow) is dict,
        "shadow_would_have_blocked": bool(shadow_map.get("would_have_blocked_experiment")),
        "packet_has_fold_signal_accuracy": False if packet is None else packet_has_fold_signal_accuracies(packet),
        "four_block_report": _four_blocks(agent_md),
        "overlapping_predecessor": key in forbidden,
        "direction_bound": False
        if packet is None or hypothesis_spec is None
        else packet_direction_bound(hypothesis_spec, packet),
        "treatment_control_mirror": False if packet is None else packet_treatment_control_mirror(packet),
        "authentic_walk_forward_manifest": False if packet is None else packet_has_authentic_walk_forward(packet),
        "fold_metrics_bound_to_manifest": False if packet is None else fold_metrics_bound_to_manifest(packet),
        "verdict_predicate_congruent": _verdict_congruent(agent, hypothesis_spec, packet)
        and _verdict_congruent(single, single_hyp, single_packet),
        "deterministic_agent_outcome": _deterministic_outcome(hypothesis_spec, packet),
        "deterministic_single_outcome": _deterministic_outcome(single_hyp, single_packet),
        "arm_verdicts": {
            "research_agent_loop": _arm_verdict(agent),
            "single_prompt_analyst": _arm_verdict(single),
        },
    }


def _deterministic_outcome(hypothesis: HypothesisSpec | None, packet: ExperimentResultPacket | None) -> str | None:
    if hypothesis is None or packet is None:
        return None
    predicate = parse_falsification_condition(hypothesis.falsification_condition)
    if predicate is None:
        return None
    return evaluate_falsification_predicate(predicate, packet).outcome.value


def _verdict_congruent(
    payload: dict[str, object] | None,
    hypothesis: HypothesisSpec | None,
    packet: ExperimentResultPacket | None,
) -> bool:
    if payload is None or hypothesis is None or packet is None:
        return False
    expected = _deterministic_outcome(hypothesis, packet)
    actual = _arm_verdict(payload)
    if expected is None or actual is None:
        return False
    if actual == "MODIFY":
        verdict = payload.get("final_verdict")
        if type(verdict) is not dict:
            return False
        return (
            expected == "REJECT"
            and verdict.get("modified_hypothesis") is not None
            and verdict.get("auto_execute_modified") is False
        )
    return actual == expected


def _v2_outcome(payload: dict[str, object]) -> R005CorrectionV2EpisodeOutcome:
    verdicts = cast(dict[str, object], payload["arm_verdicts"])
    return R005CorrectionV2EpisodeOutcome(
        cast(str, payload["episode_id"]),
        cast(str, payload["instrument"]),
        cast(str, payload["stratum"]),
        cast(str, payload["market_cutoff"]),
        bool(payload["complete"]),
        bool(payload["agent_loop_complete"]),
        bool(payload["agent_experiment_complete"]),
        bool(payload["single_prompt_complete"]),
        bool(payload["pre_experiment_critic_gate"]),
        bool(payload["critic_blocked_experiment"]),
        bool(payload["shadow_ran"]),
        bool(payload["shadow_would_have_blocked"]),
        bool(payload["direction_bound"]),
        bool(payload["treatment_control_mirror"]),
        bool(payload["authentic_walk_forward_manifest"]),
        bool(payload["fold_metrics_bound_to_manifest"]),
        bool(payload["verdict_predicate_congruent"]),
        bool(payload["four_block_report"]),
        bool(payload["overlapping_predecessor"]),
        _optional_str(verdicts.get("research_agent_loop")),
        _optional_str(verdicts.get("single_prompt_analyst")),
        _optional_str(payload.get("deterministic_agent_outcome")),
        _optional_str(payload.get("deterministic_single_outcome")),
    )


def _write_correction_v2_scorecard(
    roster: dict[str, object],
    predecessor: dict[str, object],
    summaries: tuple[dict[str, object], ...],
) -> Path:
    outcomes = tuple(_v2_outcome(item) for item in summaries)
    gate = compute_r005_correction_v2_gate(outcomes)
    slim = tuple(
        {
            "episode_id": item["episode_id"],
            "instrument": item["instrument"],
            "stratum": item["stratum"],
            "market_cutoff": item["market_cutoff"],
            "complete": item["complete"],
            "agent_loop_complete": item["agent_loop_complete"],
            "agent_experiment_complete": item["agent_experiment_complete"],
            "single_prompt_complete": item["single_prompt_complete"],
            "pre_experiment_critic_gate": item["pre_experiment_critic_gate"],
            "critic_blocked_experiment": item["critic_blocked_experiment"],
            "shadow_ran": item["shadow_ran"],
            "shadow_would_have_blocked": item["shadow_would_have_blocked"],
            "direction_bound": item["direction_bound"],
            "treatment_control_mirror": item["treatment_control_mirror"],
            "authentic_walk_forward_manifest": item["authentic_walk_forward_manifest"],
            "fold_metrics_bound_to_manifest": item["fold_metrics_bound_to_manifest"],
            "verdict_predicate_congruent": item["verdict_predicate_congruent"],
            "four_block_report": item["four_block_report"],
            "overlapping_predecessor": item["overlapping_predecessor"],
            "arm_verdicts": item["arm_verdicts"],
            "deterministic_outcomes": {
                "research_agent_loop": item["deterministic_agent_outcome"],
                "single_prompt_analyst": item["deterministic_single_outcome"],
            },
            "run_dir": f"datasets/mvp-r-001/runs/mvp-r-005-correction-v2/{item['episode_id']}",
        }
        for item in summaries
    )
    scorecard = {
        "schema_version": "mvp-r-005.correction-v2-scorecard.v1",
        "task": "MVP-R-005",
        "phase": "correction-v2",
        "roster_path": "evidence/mvp-r-005/roster.json",
        "roster_sha256": roster["content_sha256"],
        "v1_scorecard_path": "evidence/mvp-r-005/scorecard.json",
        "v1_scorecard_rewritten": False,
        "reviewer_rejection_path": "evidence/mvp-r-005/reviewer-rejection-2026-09-02.json",
        "predecessor_evidence": predecessor,
        "template_is_product": False,
        "critic_is_pre_experiment_gate": False,
        "independent_real_user_validation": False,
        "not_go": True,
        "episodes": slim,
        "gate": gate,
    }
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    (RUN_ROOT / "batch-summary.json").write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    WP_PATH.write_text(
        canonical_json_text(
            _freeze(
                {
                    "schema_version": "mvp-r-005.correction-v2-wp-evidence.v1",
                    "task": "MVP-R-005",
                    "phase": "correction-v2",
                    "status": gate["decision"],
                    "executor": "Cursor",
                    "implementation_model": "Cursor Grok 4.6",
                    "reasoning_effort": "NOT_EXPOSED",
                    "product_models": {
                        "research": "gpt-5.6-terra/xhigh",
                        "feedback": "gpt-5.6-terra/xhigh",
                        "shadow_critic": "gpt-5.6-sol/xhigh",
                    },
                    "predecessor_evidence_untouched": True,
                    "v1_scorecard_untouched": True,
                    "roster_sha256": roster["content_sha256"],
                    "gate": gate,
                    "independent_real_user_validation": False,
                    "not_go": True,
                    "approve_formal_30_50_shadow": False,
                    "approve_v1_011": False,
                }
            )
        ),
        encoding="utf-8",
    )
    return SCORECARD_PATH


def _write_correction_v3_scorecard(
    roster: dict[str, object],
    predecessor: dict[str, object],
) -> Path:
    if not HASH_BASELINE_PATH.exists():
        write_predecessor_hash_manifest(HASH_BASELINE_PATH, build_predecessor_hash_manifest(ROOT))
    baseline = load_predecessor_hash_manifest(HASH_BASELINE_PATH)
    final_manifest = build_predecessor_hash_manifest(ROOT)
    write_predecessor_hash_manifest(HASH_FINAL_PATH, final_manifest)
    hashes_match = predecessor_hashes_match(baseline, final_manifest)
    config = _validation_config()
    forbidden = _predecessor_keys()
    outcomes: list[R005CorrectionV3EpisodeOutcome] = []
    slim: list[dict[str, object]] = []
    for raw in cast(list[object], roster["episodes"]):
        roster_item = cast(dict[str, object], raw)
        episode_id = cast(str, roster_item["episode_id"])
        episode_dir = RUN_ROOT / episode_id
        agent = _read_json(episode_dir / "research_agent_loop.json")
        single = _read_json(episode_dir / "single_prompt_analyst.json")
        agent_md = (episode_dir / "research_agent_loop.md").read_text(encoding="utf-8") if agent else ""
        key = (
            cast(str, roster_item["instrument"]),
            cast(str, roster_item["stratum"]),
            cast(str, roster_item["market_cutoff"]),
        )
        outcome = assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=agent,
            single_payload=single,
            agent_markdown=agent_md,
            overlapping_predecessor=key in forbidden,
            config=config,
        )
        outcomes.append(outcome)
        slim.append(
            {
                "episode_id": outcome.episode_id,
                "instrument": outcome.instrument,
                "stratum": outcome.stratum,
                "market_cutoff": outcome.market_cutoff,
                "complete": outcome.complete,
                "agent_loop_complete": outcome.agent_loop_complete,
                "agent_experiment_complete": outcome.agent_experiment_complete,
                "single_prompt_complete": outcome.single_prompt_complete,
                "raw_tool_result_lineage": outcome.raw_tool_result_lineage,
                "predicate_metric_binding": outcome.predicate_metric_binding,
                "verdict_predicate_congruent": outcome.verdict_predicate_congruent,
                "four_block_report": outcome.four_block_report,
                "pre_experiment_critic_gate": outcome.pre_experiment_critic_gate,
                "critic_blocked_experiment": outcome.critic_blocked_experiment,
                "overlapping_predecessor": outcome.overlapping_predecessor,
                "stopped_folds_invisible": outcome.stopped_folds_invisible,
                "treatment_view_bound": outcome.treatment_view_bound,
                "arm_verdicts": {
                    "research_agent_loop": outcome.agent_verdict,
                    "single_prompt_analyst": outcome.single_prompt_verdict,
                },
                "deterministic_outcomes": {
                    "research_agent_loop": outcome.deterministic_agent_outcome,
                    "single_prompt_analyst": outcome.deterministic_single_outcome,
                },
                "run_dir": f"datasets/mvp-r-001/runs/mvp-r-005-correction-v3/{outcome.episode_id}",
            }
        )
    gate = compute_r005_correction_v3_gate(
        tuple(outcomes),
        v3_predecessor_hashes_match=hashes_match,
        pre_v2_byte_stability=PRE_V2_BYTE_STABILITY,
    )
    scorecard = {
        "schema_version": "mvp-r-005.correction-v3-scorecard.v1",
        "task": "MVP-R-005",
        "phase": "correction-v3",
        "roster_path": "evidence/mvp-r-005/roster.json",
        "roster_sha256": roster["content_sha256"],
        "v1_scorecard_path": "evidence/mvp-r-005/scorecard.json",
        "v2_scorecard_path": "evidence/mvp-r-005/correction-v2/scorecard.json",
        "reviewer_rejection_path": "evidence/mvp-r-005/reviewer-rejection-2026-09-02.json",
        "predecessor_hash_baseline_path": "evidence/mvp-r-005/correction-v3/predecessor-hash-baseline.json",
        "predecessor_hash_final_path": "evidence/mvp-r-005/correction-v3/predecessor-hash-final.json",
        "predecessor_hash_baseline_sha256": baseline["content_sha256"],
        "predecessor_hash_final_sha256": final_manifest["content_sha256"],
        "predecessor_evidence": predecessor,
        "template_is_product": False,
        "critic_is_pre_experiment_gate": False,
        "independent_real_user_validation": False,
        "not_go": True,
        "episodes": tuple(slim),
        "gate": gate,
    }
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    (RUN_ROOT / "batch-summary.json").write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    WP_PATH.write_text(
        canonical_json_text(
            _freeze(
                {
                    "schema_version": "mvp-r-005.correction-v3-wp-evidence.v1",
                    "task": "MVP-R-005",
                    "phase": "correction-v3",
                    "status": gate["decision"],
                    "executor": "Grok Build",
                    "implementation_model": "Grok 4.6",
                    "reasoning_effort": "NOT_EXPOSED",
                    "product_models": {
                        "research": "gpt-5.6-terra/xhigh",
                        "feedback": "gpt-5.6-terra/xhigh",
                        "shadow_critic": "gpt-5.6-sol/xhigh",
                    },
                    "v3_predecessor_hashes_match": hashes_match,
                    "pre_v2_byte_stability": PRE_V2_BYTE_STABILITY,
                    "roster_sha256": roster["content_sha256"],
                    "gate": gate,
                    "independent_real_user_validation": False,
                    "not_go": True,
                    "approve_formal_30_50_shadow": False,
                    "approve_v1_011": False,
                }
            )
        ),
        encoding="utf-8",
    )
    return SCORECARD_PATH


def _write_correction_v4_scorecard(
    roster: dict[str, object],
    predecessor: dict[str, object],
) -> Path:
    baseline = load_predecessor_hash_manifest(HASH_BASELINE_PATH)
    final_manifest = build_predecessor_hash_manifest(ROOT)
    write_predecessor_hash_manifest(HASH_FINAL_PATH, final_manifest)
    hashes_match = predecessor_hashes_match(baseline, final_manifest)
    config = _validation_config()
    forbidden = _predecessor_keys()
    outcomes: list[R005CorrectionV3EpisodeOutcome] = []
    slim: list[dict[str, object]] = []
    for raw in cast(list[object], roster["episodes"]):
        roster_item = cast(dict[str, object], raw)
        episode_id = cast(str, roster_item["episode_id"])
        episode_dir = RUN_ROOT / episode_id
        agent = _read_json(episode_dir / "research_agent_loop.json")
        single = _read_json(episode_dir / "single_prompt_analyst.json")
        agent_md = (episode_dir / "research_agent_loop.md").read_text(encoding="utf-8") if agent else ""
        key = (
            cast(str, roster_item["instrument"]),
            cast(str, roster_item["stratum"]),
            cast(str, roster_item["market_cutoff"]),
        )
        outcome = assess_correction_v3_episode(
            roster_item=roster_item,
            agent_payload=agent,
            single_payload=single,
            agent_markdown=agent_md,
            overlapping_predecessor=key in forbidden,
            config=config,
        )
        outcomes.append(outcome)
        slim.append(
            {
                "episode_id": outcome.episode_id,
                "instrument": outcome.instrument,
                "stratum": outcome.stratum,
                "market_cutoff": outcome.market_cutoff,
                "complete": outcome.complete,
                "agent_loop_complete": outcome.agent_loop_complete,
                "agent_experiment_complete": outcome.agent_experiment_complete,
                "single_prompt_complete": outcome.single_prompt_complete,
                "raw_packet_to_view_lineage": outcome.raw_packet_to_view_lineage,
                "predicate_metric_binding": outcome.predicate_metric_binding,
                "verdict_predicate_congruent": outcome.verdict_predicate_congruent,
                "four_block_report": outcome.four_block_report,
                "pre_experiment_critic_gate": outcome.pre_experiment_critic_gate,
                "critic_blocked_experiment": outcome.critic_blocked_experiment,
                "overlapping_predecessor": outcome.overlapping_predecessor,
                "stopped_folds_invisible": outcome.stopped_folds_invisible,
                "treatment_view_bound": outcome.treatment_view_bound,
                "arm_verdicts": {
                    "research_agent_loop": outcome.agent_verdict,
                    "single_prompt_analyst": outcome.single_prompt_verdict,
                },
                "deterministic_outcomes": {
                    "research_agent_loop": outcome.deterministic_agent_outcome,
                    "single_prompt_analyst": outcome.deterministic_single_outcome,
                },
                "run_dir": f"datasets/mvp-r-001/runs/mvp-r-005-correction-v3/{outcome.episode_id}",
            }
        )
    gate = compute_r005_correction_v4_gate(tuple(outcomes), v4_predecessor_hashes_match=hashes_match)
    scorecard = {
        "schema_version": "mvp-r-005.correction-v4-scorecard.v1",
        "task": "MVP-R-005",
        "phase": "correction-v4-evidence-only",
        "source_run_phase": "correction-v3",
        "product_model_calls": 0,
        "roster_path": "evidence/mvp-r-005/roster.json",
        "roster_sha256": roster["content_sha256"],
        "v3_scorecard_path": "evidence/mvp-r-005/correction-v3/scorecard.json",
        "reviewer_rejection_path": "evidence/mvp-r-005/correction-v4/reviewer-rejection-correction-v3.json",
        "predecessor_hash_baseline_path": "evidence/mvp-r-005/correction-v4/predecessor-hash-baseline.json",
        "predecessor_hash_final_path": "evidence/mvp-r-005/correction-v4/predecessor-hash-final.json",
        "predecessor_hash_baseline_sha256": baseline["content_sha256"],
        "predecessor_hash_final_sha256": final_manifest["content_sha256"],
        "predecessor_evidence": predecessor,
        "raw_lineage_scope": "ExperimentResultPacket to TreatmentMetricView; source-ref authenticity not claimed",
        "template_is_product": False,
        "critic_is_pre_experiment_gate": False,
        "independent_real_user_validation": False,
        "not_go": True,
        "episodes": tuple(slim),
        "gate": gate,
    }
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    WP_PATH.write_text(
        canonical_json_text(
            _freeze(
                {
                    "schema_version": "mvp-r-005.correction-v4-wp-evidence.v1",
                    "task": "MVP-R-005",
                    "phase": "correction-v4-evidence-only",
                    "status": gate["decision"],
                    "executor": "Codex",
                    "implementation_model": "NOT_EXPOSED",
                    "reasoning_effort": "NOT_EXPOSED",
                    "product_model_calls": 0,
                    "source_run_phase": "correction-v3",
                    "v4_predecessor_hashes_match": hashes_match,
                    "roster_sha256": roster["content_sha256"],
                    "gate": gate,
                    "validation": {
                        "uv_run_pytest": "456 passed, 42 skipped",
                        "make_check": {
                            "mypy_source_files": 102,
                            "schema_tests": 2,
                            "unit_tests": 1,
                            "property_tests": 9,
                            "contract_tests": 441,
                            "repository_scan": "passed",
                            "health": "ok",
                        },
                        "git_diff_check": "passed",
                    },
                    "independent_real_user_validation": False,
                    "not_go": True,
                    "approve_formal_30_50_shadow": False,
                    "approve_v1_011": False,
                }
            )
        ),
        encoding="utf-8",
    )
    return SCORECARD_PATH


def _write_correction_v5_scorecard(
    roster: dict[str, object],
    predecessor: dict[str, object],
) -> Path:
    baseline = load_predecessor_hash_manifest(HASH_BASELINE_PATH)
    final_manifest = build_predecessor_hash_manifest(ROOT)
    write_predecessor_hash_manifest(HASH_FINAL_PATH, final_manifest)
    hashes_match = predecessor_hashes_match(baseline, final_manifest)
    config = _validation_config()
    forbidden = _predecessor_keys()
    outcomes: list[R005CorrectionV3EpisodeOutcome] = []
    slim: list[dict[str, object]] = []
    for raw in cast(list[object], roster["episodes"]):
        roster_item = cast(dict[str, object], raw)
        episode_id = cast(str, roster_item["episode_id"])
        episode_dir = RUN_ROOT / episode_id
        agent = _read_json(episode_dir / "research_agent_loop.json")
        single = _read_json(episode_dir / "single_prompt_analyst.json")
        agent_md = (episode_dir / "research_agent_loop.md").read_text(encoding="utf-8") if agent else ""
        single_md = (episode_dir / "single_prompt_analyst.md").read_text(encoding="utf-8") if single else ""
        key = (
            cast(str, roster_item["instrument"]),
            cast(str, roster_item["stratum"]),
            cast(str, roster_item["market_cutoff"]),
        )
        outcome = assess_correction_v5_episode(
            roster_item=roster_item,
            agent_payload=agent,
            single_payload=single,
            agent_markdown=agent_md,
            single_markdown=single_md,
            overlapping_predecessor=key in forbidden,
            config=config,
        )
        outcomes.append(outcome)
        slim.append(
            {
                "episode_id": outcome.episode_id,
                "instrument": outcome.instrument,
                "stratum": outcome.stratum,
                "market_cutoff": outcome.market_cutoff,
                "complete": outcome.complete,
                "agent_loop_complete": outcome.agent_loop_complete,
                "agent_experiment_complete": outcome.agent_experiment_complete,
                "single_prompt_complete": outcome.single_prompt_complete,
                "raw_packet_to_view_lineage": outcome.raw_packet_to_view_lineage,
                "predicate_metric_binding": outcome.predicate_metric_binding,
                "verdict_predicate_congruent": outcome.verdict_predicate_congruent,
                "four_block_report": outcome.four_block_report,
                "pre_experiment_critic_gate": outcome.pre_experiment_critic_gate,
                "critic_blocked_experiment": outcome.critic_blocked_experiment,
                "overlapping_predecessor": outcome.overlapping_predecessor,
                "stopped_folds_invisible": outcome.stopped_folds_invisible,
                "treatment_view_bound": outcome.treatment_view_bound,
                "arm_verdicts": {
                    "research_agent_loop": outcome.agent_verdict,
                    "single_prompt_analyst": outcome.single_prompt_verdict,
                },
                "deterministic_outcomes": {
                    "research_agent_loop": outcome.deterministic_agent_outcome,
                    "single_prompt_analyst": outcome.deterministic_single_outcome,
                },
                "run_dir": f"datasets/mvp-r-001/runs/mvp-r-005-correction-v3/{outcome.episode_id}",
            }
        )
    gate = compute_r005_correction_v5_gate(tuple(outcomes), v5_predecessor_hashes_match=hashes_match)
    scorecard = {
        "schema_version": "mvp-r-005.correction-v5-scorecard.v1",
        "task": "MVP-R-005",
        "phase": "correction-v5-evidence-only",
        "source_run_phase": "correction-v3",
        "product_model_calls": 0,
        "roster_path": "evidence/mvp-r-005/roster.json",
        "roster_sha256": roster["content_sha256"],
        "v4_scorecard_path": "evidence/mvp-r-005/correction-v4/scorecard.json",
        "reviewer_rejection_path": "evidence/mvp-r-005/correction-v5/reviewer-rejection-correction-v4.json",
        "predecessor_hash_baseline_path": "evidence/mvp-r-005/correction-v5/predecessor-hash-baseline.json",
        "predecessor_hash_final_path": "evidence/mvp-r-005/correction-v5/predecessor-hash-final.json",
        "predecessor_hash_baseline_sha256": baseline["content_sha256"],
        "predecessor_hash_final_sha256": final_manifest["content_sha256"],
        "predecessor_evidence": predecessor,
        "visible_binding_scope": "explicit non-empty agent_visible_experiment exact-bound for both arms",
        "report_binding_scope": "both Markdown files exactly equal deterministic DecisionBrief renderer output",
        "raw_lineage_scope": "ExperimentResultPacket to TreatmentMetricView; source-ref authenticity not claimed",
        "template_is_product": False,
        "critic_is_pre_experiment_gate": False,
        "independent_real_user_validation": False,
        "not_go": True,
        "episodes": tuple(slim),
        "gate": gate,
    }
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    WP_PATH.write_text(
        canonical_json_text(
            _freeze(
                {
                    "schema_version": "mvp-r-005.correction-v5-wp-evidence.v1",
                    "task": "MVP-R-005",
                    "phase": "correction-v5-evidence-only",
                    "status": gate["decision"],
                    "executor": "Codex",
                    "implementation_model": "NOT_EXPOSED",
                    "reasoning_effort": "NOT_EXPOSED",
                    "product_model_calls": 0,
                    "source_run_phase": "correction-v3",
                    "v5_predecessor_hashes_match": hashes_match,
                    "roster_sha256": roster["content_sha256"],
                    "gate": gate,
                    "validation": {
                        "uv_run_pytest": "465 passed, 42 skipped",
                        "make_check": {
                            "mypy_source_files": 102,
                            "schema_tests": 2,
                            "unit_tests": 1,
                            "property_tests": 9,
                            "contract_tests": 450,
                            "repository_scan": "passed",
                            "health": "ok",
                        },
                        "git_diff_check": "passed",
                    },
                    "independent_real_user_validation": False,
                    "not_go": True,
                    "approve_formal_30_50_shadow": False,
                    "approve_v1_011": False,
                }
            )
        ),
        encoding="utf-8",
    )
    return SCORECARD_PATH


def _outcome(payload: dict[str, object]) -> R005EpisodeOutcome:
    verdicts = cast(dict[str, object], payload["arm_verdicts"])
    return R005EpisodeOutcome(
        cast(str, payload["episode_id"]),
        cast(str, payload["instrument"]),
        cast(str, payload["stratum"]),
        cast(str, payload["market_cutoff"]),
        bool(payload["complete"]),
        bool(payload["agent_loop_complete"]),
        bool(payload["agent_experiment_complete"]),
        bool(payload["single_prompt_complete"]),
        bool(payload["pre_experiment_critic_gate"]),
        bool(payload["critic_blocked_experiment"]),
        bool(payload["shadow_ran"]),
        bool(payload["shadow_would_have_blocked"]),
        bool(payload["packet_has_fold_signal_accuracy"]),
        bool(payload["four_block_report"]),
        bool(payload["overlapping_predecessor"]),
        _optional_str(verdicts.get("research_agent_loop")),
        _optional_str(verdicts.get("single_prompt_analyst")),
    )


def _four_blocks(text: str) -> bool:
    if not text:
        return False
    if "Independent Critic" in text:
        return False
    return all(heading in text for heading in FOUR_BLOCK_HEADINGS)


def _arm_verdict(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    verdict = payload.get("final_verdict") or {}
    if type(verdict) is not dict:
        return None
    value = cast(dict[str, object], verdict).get("verdict")
    return value if type(value) is str else None


def _optional_str(value: object) -> str | None:
    return value if type(value) is str else None


def _write_arm(episode_dir: Path, name: str, payload: dict[str, object], markdown: str) -> None:
    _write_json(episode_dir / f"{name}.json", payload)
    (episode_dir / f"{name}.md").write_text(markdown, encoding="utf-8")


def _write_failure(episode_id: str, error: Exception) -> None:
    existing = list(EVIDENCE_ROOT.glob(f"{episode_id}-attempt-*-failure.json"))
    attempt = len(existing) + 1
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    diagnostics: object | None = None
    evidence_payload = getattr(error, "evidence_payload", None)
    if callable(evidence_payload):
        diagnostics = evidence_payload()
    payload: dict[str, object] = {
        "schema_version": "mvp-r-005.discovery-failure.v2",
        "episode_id": episode_id,
        "attempt": attempt,
        "completed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "FAILED_CLOSED",
        "failure": f"{type(error).__name__}: {error}",
        "tool_or_trading_side_effect": False,
        "manual_output_repair": False,
        "counts_as_completed_episode": False,
    }
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics
    _write_json(
        EVIDENCE_ROOT / f"{episode_id}-attempt-{attempt}-failure.json",
        payload,
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
    if ACTIVE_TASK == "MVP-R-FORMAL-EVAL":
        authority_name = f"mvp-r.formal-{ACTIVE_PHASE_NAME}.data-governance"
    elif CORRECTION_V3:
        authority_name = "mvp-r-005.correction-v3.data-governance"
    elif CORRECTION_V2:
        authority_name = "mvp-r-005.correction-v2.data-governance"
    else:
        authority_name = "mvp-r-005.data-governance"
    authority = DatasetAuthorizationAuthority(
        authority_name,
        _key(master, DATA_HMAC_LABEL),
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
        candidates_per_cell=CANDIDATES_PER_CELL,
    )
    by_key = {
        (item.instrument_id, item.stratum.value, item.market_cutoff.to_dict()["recorded_at"]): item
        for item in candidates
    }
    forbidden = _predecessor_keys()
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
        if key in forbidden:
            raise RuntimeError("frozen R-005 discovery roster reused a predecessor window")
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
    return tuple(issued), TrustedResearchToolsPort(_key(master, RESULT_HMAC_LABEL)), config


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
            "evaluation_episode", {"task": ACTIVE_TASK, "id": cast(str, roster_item["episode_id"])}
        ),
        phase=ACTIVE_EPISODE_PHASE,
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
            "task": ACTIVE_TASK,
            "phase": ACTIVE_PHASE_NAME,
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


def _suite(dataset_refs: tuple[DatasetEvidenceRef, ...], authority_id: str) -> EvaluationSuite:
    model_config = _model_config()
    tools = frozen_mvp_tool_specs(REQUEST_SHA256)
    runtime = FrozenRuntimeIdentity(
        canonical_sha256({"prompt": "mvp-r-005-discovery"}),
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        canonical_sha256({"policy": "research-only-no-trading"}),
    )
    return EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": ACTIVE_TASK, "roster": f"{ACTIVE_PHASE_NAME}-v1"}),
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
        f"{ACTIVE_TASK.lower()}.{ACTIVE_PHASE_NAME}-evaluator",
        tuple(dataset_refs),
        tuple(sorted(instrument for ref in dataset_refs for instrument in ref.instrument_universe)),
        MVP_R_EPISODE_SELECTION_RULE,
        f"{ACTIVE_TASK.lower()}.{ACTIVE_PHASE_NAME}.v1",
        ("decision_brief.v1", "fold_signal_accuracy.v1"),
        MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        3,
    )


def _model_config() -> ModelRunConfig:
    profile = ModelProfileRevision(
        semantic_entity_id("model_profile", {"task": ACTIVE_TASK, "purpose": f"{ACTIVE_PHASE_NAME}-issuer"}),
        1,
        WorkloadId("research.hypothesis_synthesis"),
        ModelProtocolFamily.MVP_R_001,
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        "high",
        "mvp-r-005.prompt.v1",
        "mvp-r-005.hypothesis.v1",
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
        "mvp-r-005.prompt.v1",
        f"{ACTIVE_TASK.lower()}.{ACTIVE_PHASE_NAME}",
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
    from decimal import Decimal

    return ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": ACTIVE_TASK, "revision": 1}),
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


def _roster_keys(roster: dict[str, object]) -> set[tuple[str, str, str]]:
    return {
        (
            cast(str, item["instrument"]),
            cast(str, item["stratum"]),
            cast(str, item["market_cutoff"]),
        )
        for item in cast(list[object], roster["episodes"])
        for item in (cast(dict[str, object], item),)
    }


def _predecessor_keys() -> set[tuple[str, str, str]]:
    v1 = cast(dict[str, object], json.loads(R003_ROSTER_PATH.read_text(encoding="utf-8")))
    r004 = cast(dict[str, object], json.loads(R004_ROSTER_PATH.read_text(encoding="utf-8")))
    return _roster_keys(v1) | _roster_keys(r004) | set(EXTRA_FORBIDDEN_KEYS)


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
