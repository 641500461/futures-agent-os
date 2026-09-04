"""Run the two known-clean MVP-R-004 canary episodes. Does not touch R-003 Evidence."""

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
    MvpR003ExperimentAdapter,
    ResearchEpisodeInput,
    SignalOperator,
    StructuredModelConfig,
)
from futures_agent_os.research_experiment.mvp_r_003.model_workloads import ModelWorkloadReceipt
from futures_agent_os.research_experiment.mvp_r_003.reporting import ResearchEpisodeReport
from futures_agent_os.research_experiment.mvp_r_004 import (
    CanaryEpisodeOutcome,
    LabeledCriticOutcome,
    MvpR004HypothesisValidator,
    MvpR004ModelWorkloads,
    ResearchEvidenceBundle,
    ValidationProtocolDigest,
    build_research_evidence_bundle,
    build_validation_protocol_digest,
    compute_canary_gate,
    gold_cases,
)
from futures_agent_os.research_experiment.mvp_r_004.contracts import GoldLabel
from futures_agent_os.research_experiment.mvp_replay import ReplayEpisodeCandidate
from futures_agent_os.research_experiment.mvp_roster import EpisodeStratum
from futures_agent_os.research_experiment.mvp_validation import AgentEpisodeView, ModelRunConfig
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
ROSTER_PATH = ROOT / "evidence" / "mvp-r-004" / "canary" / "roster.json"
R003_EVIDENCE = ROOT / "evidence" / "mvp-r-003"
RUN_ROOT = DATA_ROOT / "runs" / "mvp-r-004-canary"
EVIDENCE_ROOT = ROOT / "evidence" / "mvp-r-004" / "canary"
SCORECARD_PATH = EVIDENCE_ROOT / "scorecard.json"
MASTER_SECRET_PATH = DATA_ROOT / ".governance-master-key"
REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-004", "workload": "canary"})


@dataclass(frozen=True, slots=True)
class IssuedCanaryEpisode:
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
    parser.add_argument("--episode")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--research-model", default="gpt-5.6-terra")
    parser.add_argument("--critic-model", default="gpt-5.6-sol")
    parser.add_argument("--feedback-model", default="gpt-5.6-terra")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="xhigh")
    args = parser.parse_args()
    _assert_r003_evidence_untouched()
    roster = _load_roster()
    if args.summarize_only:
        print(canonical_json_text({"scorecard": str(_write_scorecard_from_disk(roster))}))
        return
    issued, result_port, validation_config = _issue_episodes(roster)
    if args.episode:
        issued = tuple(item for item in issued if item.contract.episode_id == args.episode)
        if not issued:
            raise SystemExit("requested episode is not in the frozen canary roster")
    if args.plan_only:
        print(
            canonical_json_text(
                {
                    "roster_sha256": cast(str, roster["content_sha256"]),
                    "episode_count": len(issued),
                    "episodes": tuple(item.contract.episode_id for item in issued),
                    "r003_evidence_untouched": True,
                }
            )
        )
        return
    workloads = MvpR004ModelWorkloads(OfficialCodexAppServerTransport())
    outcomes = []
    for item in issued:
        outcomes.append(
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
    scorecard_path = _write_scorecard(roster, tuple(outcomes))
    print(canonical_json_text({"scorecard": str(scorecard_path), "decision": _read_decision(scorecard_path)}))


def _run_episode(
    item: IssuedCanaryEpisode,
    config: ValidationConfig,
    result_port: TrustedResearchToolsPort,
    workloads: MvpR004ModelWorkloads,
    research_config: StructuredModelConfig,
    critic_config: StructuredModelConfig,
    feedback_config: StructuredModelConfig,
) -> dict[str, object]:
    episode_dir = RUN_ROOT / item.contract.episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)
    threshold = format(config.signal_threshold, "f")
    clean, bad = gold_cases(item.contract, threshold)
    validator = MvpR004HypothesisValidator()
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
    agent_payload: dict[str, object] = {"status": "NOT_RUN"}
    try:
        hypotheses, generation_receipt = workloads.generate_hypotheses(
            item.contract, item.bundle, item.protocol, research_config
        )
        agent_payload = {
            "status": "COMPLETED",
            "hypothesis_count": len(hypotheses),
            "hypotheses": tuple(value.to_dict() for value in hypotheses),
            "receipt": _receipt_payload(generation_receipt),
        }
    except Exception as error:
        agent_payload = {"status": "FAILED", "error": f"{type(error).__name__}: {error}"}

    adapter = MvpR003ExperimentAdapter()
    full_arm_complete = False
    experiment_ran = False
    feedback_present = False
    if clean_review.decision is CriticDecision.SELECT:
        plan = adapter.instantiate(item.contract, clean.hypothesis, config, code_ref="mvp-r-004-canary-v1")
        result = adapter.execute_replay(
            plan=plan,
            episode=item.view,
            window=item.window,
            records=item.records,
            market_state=item.stratum,
            config=config,
            result_authority=result_port,
            hypothesis=clean.hypothesis,
        )
        experiment_ran = result.complete
        final, feedback_receipt = workloads.final_verdict(clean.hypothesis, result, feedback_config)
        feedback_present = True
        full_arm_complete = clean_review.decision is CriticDecision.SELECT and experiment_ran and feedback_present
        report = ResearchEpisodeReport(
            "DISCOVERY_EXECUTED",
            item.contract,
            (clean.hypothesis,),
            (clean_validation,),
            (clean_review,),
            clean.hypothesis,
            plan,
            result,
            final,
            (clean_receipt, feedback_receipt),
        )
        _write_json(episode_dir / "research_critic_result_feedback.json", report.to_dict())
        (episode_dir / "research_critic_result_feedback.md").write_text(report.render_markdown(), encoding="utf-8")
    else:
        _write_json(
            episode_dir / "research_critic_result_feedback.json",
            {
                "schema_version": "mvp-r-004.critic-blocked.v1",
                "execution_mode": "CANARY_EXECUTED",
                "outcome": "NO_EXPERIMENT_GOLD_CLEAN_NOT_SELECTED",
                "gold_clean_decision": clean_review.decision.value,
                "critic_review": clean_review.to_dict(),
            },
        )

    payload: dict[str, object] = {
        "schema_version": "mvp-r-004.canary-episode.v1",
        "episode_id": item.contract.episode_id,
        "instrument": item.contract.instrument,
        "stratum": item.stratum.value,
        "evidence_bundle": item.bundle.to_dict(),
        "validation_protocol": item.protocol.to_dict(),
        "gold_clean": {
            "hypothesis": clean.hypothesis.to_dict(),
            "validation": clean_validation.to_dict(),
            "review": clean_review.to_dict(),
            "receipt": _receipt_payload(clean_receipt),
        },
        "gold_bad": {
            "hypothesis": bad.hypothesis.to_dict(),
            "validation": bad_validation.to_dict(),
            "review": bad_review.to_dict(),
            "receipt": _receipt_payload(bad_receipt),
        },
        "agent_generation": agent_payload,
        "full_arm_complete": full_arm_complete,
        "experiment_ran": experiment_ran,
        "result_feedback_present": feedback_present,
    }
    _write_json(episode_dir / "canary.json", payload)
    return payload


def _write_scorecard(roster: dict[str, object], raw_episodes: tuple[dict[str, object], ...]) -> Path:
    episodes = tuple(_outcome(item) for item in raw_episodes)
    labeled = tuple(case for item in raw_episodes for case in _labeled(item))
    gate = compute_canary_gate(episodes, labeled)
    slim_episodes = tuple(
        {
            "episode_id": item.episode_id,
            "instrument": item.instrument,
            "stratum": item.stratum,
            "gold_clean_decision": item.gold_clean_decision,
            "gold_bad_decision": item.gold_bad_decision,
            "full_arm_complete": item.full_arm_complete,
            "experiment_ran": item.experiment_ran,
            "result_feedback_present": item.result_feedback_present,
            "agent_hypothesis_count": item.agent_hypothesis_count,
            "run_dir": f"datasets/mvp-r-001/runs/mvp-r-004-canary/{item.episode_id}",
        }
        for item in episodes
    )
    scorecard = {
        "schema_version": "mvp-r-004.canary-scorecard.v1",
        "task": "MVP-R-004",
        "phase": "canary",
        "roster_path": "evidence/mvp-r-004/canary/roster.json",
        "roster_sha256": roster["content_sha256"],
        "r003_evidence_untouched": True,
        "episodes": slim_episodes,
        "gate": gate,
    }
    full = {
        **scorecard,
        "full_episodes": raw_episodes,
    }
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(canonical_json_text(_freeze(scorecard)), encoding="utf-8")
    (RUN_ROOT / "batch-summary.json").write_text(canonical_json_text(_freeze(full)), encoding="utf-8")
    return SCORECARD_PATH


def _write_scorecard_from_disk(roster: dict[str, object]) -> Path:
    raw = []
    for item in cast(list[object], roster["episodes"]):
        episode_id = cast(str, cast(dict[str, object], item)["episode_id"])
        payload = json.loads((RUN_ROOT / episode_id / "canary.json").read_text(encoding="utf-8"))
        raw.append(payload)
    return _write_scorecard(roster, tuple(raw))


def _outcome(payload: dict[str, object]) -> CanaryEpisodeOutcome:
    agent = cast(dict[str, object], payload["agent_generation"])
    hypothesis_count = cast(int, agent["hypothesis_count"]) if agent.get("status") == "COMPLETED" else 0
    return CanaryEpisodeOutcome(
        cast(str, payload["episode_id"]),
        cast(str, payload["instrument"]),
        cast(str, payload["stratum"]),
        _review_decision(payload, "gold_clean"),
        _review_decision(payload, "gold_bad"),
        bool(payload["full_arm_complete"]),
        bool(payload["experiment_ran"]),
        bool(payload["result_feedback_present"]),
        hypothesis_count,
    )


def _review_decision(payload: dict[str, object], field: str) -> str:
    review = cast(dict[str, object], cast(dict[str, object], payload[field])["review"])
    return cast(str, review["decision"])


def _labeled(payload: dict[str, object]) -> tuple[LabeledCriticOutcome, LabeledCriticOutcome]:
    episode_id = cast(str, payload["episode_id"])
    return (
        LabeledCriticOutcome(episode_id, GoldLabel.CLEAN, "SELECT", _review_decision(payload, "gold_clean")),
        LabeledCriticOutcome(episode_id, GoldLabel.BAD, "REJECT", _review_decision(payload, "gold_bad")),
    )


def _issue_episodes(
    roster: dict[str, object],
) -> tuple[tuple[IssuedCanaryEpisode, ...], TrustedResearchToolsPort, ValidationConfig]:
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
    ref_by_instrument = {instrument: ref for ref in dataset_refs for instrument in ref.instrument_universe}
    issued = []
    protocol = build_validation_protocol_digest(config, sample_count=40)
    for raw in cast(list[object], roster["episodes"]):
        roster_item = cast(dict[str, object], raw)
        key = (
            cast(str, roster_item["instrument"]),
            cast(str, roster_item["stratum"]),
            cast(str, roster_item["market_cutoff"]),
        )
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
) -> IssuedCanaryEpisode:
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
    return IssuedCanaryEpisode(
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
        canonical_sha256({"prompt": "mvp-r-004-canary"}),
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        canonical_sha256({"policy": "research-only-no-trading"}),
    )
    return EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": "MVP-R-004", "roster": "canary-v1"}),
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
        "mvp-r-004.canary-evaluator",
        tuple(dataset_refs),
        tuple(sorted(instrument for ref in dataset_refs for instrument in ref.instrument_universe)),
        MVP_R_EPISODE_SELECTION_RULE,
        "mvp-r-004.canary.v1",
        ("gold_label_critic.v1", "result_packet_metric_map.v1"),
        MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        3,
    )


def _model_config() -> ModelRunConfig:
    profile = ModelProfileRevision(
        semantic_entity_id("model_profile", {"task": "MVP-R-004", "purpose": "episode-issuer"}),
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
        "mvp-r-004.canary",
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
        raise ValueError("canary roster digest mismatch")
    return roster


def _assert_r003_evidence_untouched() -> None:
    scorecard = R003_EVIDENCE / "discovery" / "scorecard.json"
    if not scorecard.exists():
        raise FileNotFoundError("R-003 v1 scorecard must remain on disk")
    payload = json.loads(scorecard.read_text(encoding="utf-8"))
    if payload.get("gate", {}).get("decision") != "STOP/PIVOT":
        raise RuntimeError("R-004 must not rewrite the R-003 v1 scorecard decision")


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
