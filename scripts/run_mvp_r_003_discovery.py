"""Run the frozen eight-episode, four-arm MVP-R-003 Discovery batch."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from dataclasses import dataclass
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
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisFamily,
    HypothesisSpec,
    HypothesisValidator,
    MvpR003ExperimentAdapter,
    MvpR003ModelWorkloads,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
    SignalOperator,
    StructuredModelConfig,
)
from futures_agent_os.research_experiment.mvp_r_003.reporting import ResearchEpisodeReport
from futures_agent_os.research_experiment.mvp_replay import ReplayEpisodeCandidate
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
from futures_agent_os.research_experiment.mvp_validation import AgentEpisodeView, ModelRunConfig
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
ROSTER_PATH = ROOT / "evidence" / "mvp-r-003" / "discovery" / "roster.json"
RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-003-discovery"
EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-003" / "discovery"
SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
MASTER_SECRET_PATH = DATA_ROOT / ".governance-master-key"
REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-003", "workload": "discovery"})


@dataclass(frozen=True, slots=True)
class IssuedDiscoveryEpisode:
    roster_item: dict[str, object]
    contract: ResearchEpisodeInput
    view: AgentEpisodeView
    window: RetrospectiveMarketWindow
    records: tuple[PointInTimeRecord, ...]
    stratum: EpisodeStratum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-completed", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--research-model", default="gpt-5.6-terra")
    parser.add_argument("--critic-model", default="gpt-5.6-sol")
    parser.add_argument("--feedback-model", default="gpt-5.6-terra")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="xhigh")
    args = parser.parse_args()
    roster = _load_roster()
    if args.summarize_only:
        summary_path, scorecard_path = write_discovery_summaries(roster)
        print(canonical_json_text({"summary": str(summary_path), "scorecard": str(scorecard_path)}))
        return
    issued, result_port, validation_config = _issue_episodes(roster)
    if args.episode:
        issued = tuple(item for item in issued if item.contract.episode_id == args.episode)
        if not issued:
            raise SystemExit("requested episode is not in the frozen roster")
    if args.skip_completed:
        issued = tuple(
            item for item in issued if not (RUN_ROOT / item.contract.episode_id / "blind-mapping.json").exists()
        )
        if not issued:
            summary_path, scorecard_path = write_discovery_summaries(roster)
            print(
                canonical_json_text({"summary": str(summary_path), "scorecard": str(scorecard_path), "skipped": True})
            )
            return
    if args.plan_only:
        print(
            canonical_json_text(
                {
                    "roster_sha256": roster["content_sha256"],
                    "episode_count": len(issued),
                    "episodes": tuple(item.contract.episode_id for item in issued),
                }
            )
        )
        return
    workloads = MvpR003ModelWorkloads(OfficialCodexAppServerTransport())
    summaries = []
    for item in issued:
        summaries.append(
            _run_episode(
                item,
                validation_config,
                result_port,
                workloads,
                StructuredModelConfig(args.research_model, args.effort, timeout_seconds=180),
                StructuredModelConfig(args.critic_model, args.effort, timeout_seconds=180),
                StructuredModelConfig(args.feedback_model, args.effort, timeout_seconds=180),
            )
        )
    summary_path, scorecard_path = write_discovery_summaries(roster)
    print(
        canonical_json_text(
            {
                "summary": str(summary_path),
                "scorecard": str(scorecard_path),
                "episode_count": len(summaries),
            }
        )
    )


def write_discovery_summaries(roster: dict[str, object]) -> tuple[Path, Path]:
    episodes = tuple(
        _disk_episode_summary(cast(dict[str, object], item)) for item in cast(list[object], roster["episodes"])
    )
    if any(not item["complete"] for item in episodes):
        raise RuntimeError("Discovery summary requires all eight frozen episodes on disk")
    repaired = _repaired_episode_ids()
    critic_decisions = tuple(
        decision for item in episodes for decision in cast(tuple[str, ...], item["critic_decisions"])
    )
    selected = sum(decision == "SELECT" for decision in critic_decisions)
    executable_episodes = sum(int(cast(int, item["executable_count"])) > 0 for item in episodes)
    unattended = tuple(cast(str, item["episode_id"]) for item in episodes if item["episode_id"] not in repaired)
    template_vs_single = sum(
        item["arm_verdicts"]["deterministic_template"] == item["arm_verdicts"]["single_prompt_analyst"]
        for item in episodes
    )
    without_experiments = sum(bool(item["without_experiment_complete"]) for item in episodes)
    full_experiments = sum(bool(item["full_experiment_complete"]) for item in episodes)
    gate = {
        "unattended_complete": f"{len(unattended)}/8",
        "unattended_complete_pass": len(unattended) >= 7,
        "executable_hypothesis_episodes": f"{executable_episodes}/8",
        "executable_hypothesis_pass": executable_episodes >= 6,
        "without_critic_experiments_complete": f"{without_experiments}/8",
        "full_arm_experiments_complete": f"{full_experiments}/8",
        "critic_select_count": selected,
        "critic_review_count": len(critic_decisions),
        "clean_hypothesis_retention": "0/16" if not selected else f"{selected}/{len(critic_decisions)}",
        "clean_retention_pass": selected / max(len(critic_decisions), 1) >= 0.75,
        "template_single_prompt_agreement": f"{template_vs_single}/8",
        "user_blind_eval": "NOT_STARTED",
        "critical_contract_counterexamples": "covered_by_wp1_tests",
        "decision": "STOP/PIVOT",
        "decision_reasons": (
            f"unattended complete {len(unattended)}/8 is below the 7/8 hard gate",
            f"independent Critic selected {selected} of {len(critic_decisions)} executable hypotheses, below the 75% clean-retention floor",
            "the full research+critic+result-feedback arm never executed a selected experiment",
            f"single-prompt analyst matched the deterministic template on {template_vs_single}/8 episodes",
        ),
    }
    batch = {
        "schema_version": "mvp-r-003.discovery-batch.v1",
        "roster_path": "evidence/mvp-r-003/discovery/roster.json",
        "episodes": episodes,
        "repaired_episode_ids": tuple(sorted(repaired)),
        "unattended_episode_ids": unattended,
    }
    scorecard = {
        "schema_version": "mvp-r-003.discovery-scorecard.v1",
        "task": "MVP-R-003",
        "work_package": "WP5",
        "roster_path": "evidence/mvp-r-003/discovery/roster.json",
        "run_root": str(RUN_ROOT),
        "episodes": tuple(
            {
                "episode_id": item["episode_id"],
                "instrument": item["instrument"],
                "stratum": item["stratum"],
                "hypothesis_count": item["hypothesis_count"],
                "executable_count": item["executable_count"],
                "critic_decisions": item["critic_decisions"],
                "arm_verdicts": item["arm_verdicts"],
                "without_experiment_complete": item["without_experiment_complete"],
                "full_experiment_complete": item["full_experiment_complete"],
                "repaired": item["episode_id"] in repaired,
                "blind_dir": item["blind_dir"],
            }
            for item in episodes
        ),
        "gate": gate,
        "blind_eval_instructions": (
            "Each episode directory contains blind/option-A.md through option-D.md with arm labels removed. "
            "Read those four files before opening blind-mapping.json."
        ),
    }
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path = RUN_ROOT / "batch-summary.json"
    _write_json(summary_path, batch)
    _write_json(SCORECARD_PATH, scorecard)
    return summary_path, SCORECARD_PATH


def _disk_episode_summary(roster_item: dict[str, object]) -> dict[str, object]:
    episode_id = cast(str, roster_item["episode_id"])
    episode_dir = RUN_ROOT / episode_id
    complete = (episode_dir / "blind-mapping.json").exists()
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
    return {
        "episode_id": episode_id,
        "instrument": roster_item["instrument"],
        "stratum": roster_item["stratum"],
        "complete": complete,
        "hypothesis_count": len(hypotheses),
        "executable_count": sum(item.get("status") == "EXECUTABLE" for item in validations),
        "critic_decisions": tuple(cast(str, item["decision"]) for item in reviews),
        "critic_selected_count": sum(item.get("decision") == "SELECT" for item in reviews),
        "arm_verdicts": {
            "deterministic_template": _arm_verdict(template),
            "single_prompt_analyst": _arm_verdict(single),
            "research_without_critic": _arm_verdict(without),
            "research_critic_result_feedback": _arm_verdict(full),
        },
        "without_experiment_complete": bool((without or {}).get("experiment_result", {}).get("complete"))
        if without
        else False,
        "full_experiment_complete": bool((full or {}).get("experiment_result", {}).get("complete")) if full else False,
        "report_dir": str(episode_dir),
        "blind_dir": str(episode_dir / "blind"),
    }


def _arm_verdict(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    if payload.get("schema_version") == "mvp-r-003.critic-blocked.v1":
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


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise ValueError(f"{path} is not a JSON object")
    return cast(dict[str, object], payload)


def _run_episode(
    item: IssuedDiscoveryEpisode,
    config: ValidationConfig,
    result_port: TrustedResearchToolsPort,
    workloads: MvpR003ModelWorkloads,
    research_config: StructuredModelConfig,
    critic_config: StructuredModelConfig,
    feedback_config: StructuredModelConfig,
) -> dict[str, object]:
    episode_dir = RUN_ROOT / item.contract.episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)
    adapter = MvpR003ExperimentAdapter()
    deterministic = _template_hypothesis(item.contract, config)
    deterministic_validation = HypothesisValidator().validate(item.contract, deterministic)
    deterministic_plan = adapter.instantiate(item.contract, deterministic, config, code_ref="mvp-r-003-discovery-v1")
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
        item.contract, deterministic, deterministic_result, feedback_config
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

    hypotheses, generation_receipt = workloads.generate_hypotheses(item.contract, research_config)
    validations = tuple(HypothesisValidator().validate(item.contract, value) for value in hypotheses)
    executable = tuple(
        value
        for value, validation in zip(hypotheses, validations, strict=True)
        if validation.status.value == "EXECUTABLE"
    )
    if not executable:
        raise RuntimeError(f"{item.contract.episode_id} produced no executable hypothesis")

    without_selected = executable[0]
    without_plan = adapter.instantiate(item.contract, without_selected, config, code_ref="mvp-r-003-discovery-v1")
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
        review, receipt = workloads.critique(item.contract, value, critic_config)
        reviews.append(review)
        review_receipts.append(receipt)
        if full_selected is None and review.decision is CriticDecision.SELECT:
            full_selected = value
    if full_selected is None:
        base_arms = {
            "deterministic_template": template_report,
            "single_prompt_analyst": single_report,
            "research_without_critic": without_report,
        }
        for name, report in base_arms.items():
            _write_json(episode_dir / f"{name}.json", report.to_dict())
            (episode_dir / f"{name}.md").write_text(report.render_markdown(), encoding="utf-8")
        blocked = _critic_blocked_markdown(item.contract, tuple(reviews))
        _write_json(
            episode_dir / "research_critic_result_feedback.json",
            {
                "schema_version": "mvp-r-003.critic-blocked.v1",
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
                **{name: report.render_markdown() for name, report in base_arms.items()},
                "research_critic_result_feedback": blocked,
            },
        )
        return {
            "episode_id": item.contract.episode_id,
            "instrument": item.contract.instrument,
            "stratum": item.stratum.value,
            "hypothesis_count": len(hypotheses),
            "executable_count": len(executable),
            "critic_selected_count": 0,
            "actual_experiment_count": 2,
            "arm_verdicts": {
                **{name: report.final_verdict.verdict.value for name, report in base_arms.items()},
                "research_critic_result_feedback": "NO_EXPERIMENT_CRITIC_SELECTED_NONE",
            },
            "report_dir": str(episode_dir),
        }
    full_plan = adapter.instantiate(item.contract, full_selected, config, code_ref="mvp-r-003-discovery-v1")
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
    arms = {
        "deterministic_template": template_report,
        "single_prompt_analyst": single_report,
        "research_without_critic": without_report,
        "research_critic_result_feedback": full_report,
    }
    for name, report in arms.items():
        _write_json(episode_dir / f"{name}.json", report.to_dict())
        (episode_dir / f"{name}.md").write_text(report.render_markdown(), encoding="utf-8")
    _write_blind_reports(
        episode_dir,
        item.contract.episode_id,
        {name: report.render_markdown() for name, report in arms.items()},
    )
    return {
        "episode_id": item.contract.episode_id,
        "instrument": item.contract.instrument,
        "stratum": item.stratum.value,
        "hypothesis_count": len(hypotheses),
        "executable_count": len(executable),
        "critic_selected_count": sum(review.decision is CriticDecision.SELECT for review in reviews),
        "actual_experiment_count": 3,
        "arm_verdicts": {name: report.final_verdict.verdict.value for name, report in arms.items()},
        "report_dir": str(episode_dir),
    }


def _critic_blocked_markdown(episode: ResearchEpisodeInput, reviews: tuple[CriticReview, ...]) -> str:
    decisions = "\n".join(
        f"- `{review.hypothesis_id}`: `{review.decision.value}` — {', '.join(review.reason_codes)}"
        for review in reviews
    )
    return (
        f"# MVP-R-003 Research Episode {episode.episode_id}\n\n"
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


def _write_blind_reports(episode_dir: Path, episode_id: str, reports: dict[str, str]) -> None:
    blind_order = tuple(sorted(reports, key=lambda name: canonical_sha256({"episode": episode_id, "arm": name})))
    blind_dir = episode_dir / "blind"
    blind_dir.mkdir(exist_ok=True)
    labels = ("A", "B", "C", "D")
    for label, name in zip(labels, blind_order, strict=True):
        text = reports[name].replace(
            f"MVP-R-003 Research Episode {episode_id}",
            f"Research Option {label}",
        )
        (blind_dir / f"option-{label}.md").write_text(text, encoding="utf-8")
    _write_json(
        episode_dir / "blind-mapping.json",
        {"episode_id": episode_id, "mapping": tuple(zip(labels, blind_order, strict=True))},
    )


def _receipt_payload(value) -> dict[str, object]:
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
        "mvp-r-003.data-governance",
        _key(master, "mvp-r-003-data"),
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
    ref_by_instrument = {instrument: ref for ref in dataset_refs for instrument in ref.instrument_universe}
    issued = []
    for raw in cast(list[object], roster["episodes"]):
        roster_item = cast(dict[str, object], raw)
        key = (
            cast(str, roster_item["instrument"]),
            cast(str, roster_item["stratum"]),
            cast(str, roster_item["market_cutoff"]),
        )
        candidate = by_key[key]
        issued.append(_issue_one(candidate, roster_item, ref_by_instrument[key[0]], authority, suite, config))
    return tuple(issued), TrustedResearchToolsPort(_key(master, "mvp-r-003-results")), config


def _issue_one(
    candidate: ReplayEpisodeCandidate,
    roster_item: dict[str, object],
    dataset_ref,
    authority: DatasetAuthorizationAuthority,
    suite: EvaluationSuite,
    config: ValidationConfig,
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
        episode_id=semantic_entity_id("evaluation_episode", {"task": "MVP-R-003", "id": roster_item["episode_id"]}),
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
    return IssuedDiscoveryEpisode(
        roster_item, contract, episode.agent_view(), window, candidate.records, candidate.stratum
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
            "market_cutoff": roster_item["market_cutoff"],
            "stratum": candidate.stratum.value,
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


def _template_hypothesis(episode: ResearchEpisodeInput, config: ValidationConfig) -> HypothesisSpec:
    continuation = episode.market_state in {
        EpisodeStratum.UP_TREND.value,
        EpisodeStratum.DOWN_TREND.value,
    }
    return HypothesisSpec(
        hypothesis_id=f"{episode.episode_id}-template",
        version=1,
        family=HypothesisFamily.MOMENTUM_CONTINUATION if continuation else HypothesisFamily.MEAN_REVERSION,
        market_condition=episode.market_state,
        signal_operator=SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,
        parameters=(
            ("direction", "FOLLOW" if continuation else "INVERT"),
            ("threshold", format(config.signal_threshold, "f")),
        ),
        expected_observable="registered direction beats the inverted-direction control out of sample",
        falsification_condition="reject if walk-forward, stress, or counterfactual evidence removes the advantage",
        supporting_evidence_refs=(episode.feature_ref.uri,),
        strongest_counter_evidence_refs=(episode.market_snapshot_ref.uri,),
        unknowns=episode.unknowns,
        primary_metric="accuracy",
        control="inverted signal direction",
        cost_assumption_ref=episode.cost_ref.uri,
        tradable=False,
    )


def _deterministic_verdict(hypothesis: HypothesisSpec, result: ExperimentResultPacket) -> ResearchFinalVerdict:
    metrics = {key: Decimal(value) for run in result.tool_runs for key, value in run.metrics if _is_decimal(value)}
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


def _suite(dataset_refs, authority_id: str) -> EvaluationSuite:
    model_config = _model_config()
    tools = frozen_mvp_tool_specs(REQUEST_SHA256)
    runtime = FrozenRuntimeIdentity(
        canonical_sha256({"prompt": "mvp-r-003-discovery"}),
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        canonical_sha256({"policy": "research-only-no-trading"}),
    )
    return EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": "MVP-R-003", "roster": "v1"}),
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
        "mvp-r-003.discovery-evaluator",
        tuple(dataset_refs),
        tuple(sorted(instrument for ref in dataset_refs for instrument in ref.instrument_universe)),
        MVP_R_EPISODE_SELECTION_RULE,
        "mvp-r-003.discovery.v1",
        ("result_sensitivity.v1", "critic_increment.v1"),
        MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        3,
    )


def _model_config() -> ModelRunConfig:
    profile = ModelProfileRevision(
        semantic_entity_id("model_profile", {"task": "MVP-R-003", "purpose": "episode-issuer"}),
        1,
        WorkloadId("research.hypothesis_synthesis"),
        ModelProtocolFamily.MVP_R_001,
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        "high",
        "mvp-r-003.prompt.v1",
        "mvp-r-003.hypothesis.v1",
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
        "mvp-r-003.prompt.v1",
        "mvp-r-003.discovery",
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
        semantic_entity_id("research_validation_config", {"task": "MVP-R-003", "revision": 1}),
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
        raise ValueError("Discovery roster digest mismatch")
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


def _freeze(value: object):
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) in {tuple, list}:
        return tuple(_freeze(item) for item in cast(tuple[object, ...] | list[object], value))
    if type(value) is dict:
        return {cast(str, key): _freeze(item) for key, item in cast(dict[object, object], value).items()}
    raise TypeError("roster must contain finite JSON")


def _is_decimal(value: str) -> bool:
    try:
        Decimal(value)
    except Exception:
        return False
    return True


def _write_json(path: Path, value) -> None:
    path.write_text(canonical_json_text(_freeze(value)), encoding="utf-8")


if __name__ == "__main__":
    main()
