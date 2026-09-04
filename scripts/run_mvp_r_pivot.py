"""Run the governed development diagnostic for the MVP-R multi-family Pivot."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import run_mvp_r_replay as legacy

from futures_agent_os.adapters import CodexAppServerProvider, OFFICIAL_RESEARCH_SERIES_NORMALIZER
from futures_agent_os.reference_market_data import (
    DatasetLayer,
    LocalFileDataStore,
    StoredDataset,
    dataset_manifest_sha256,
    sha256_digest,
)
from futures_agent_os.research_experiment import (
    DatasetAuthorizationAuthority,
    EpisodeIssuer,
    EpisodeMode,
    EpisodePhase,
    EpisodeRosterAuthority,
    EpisodeRosterCandidate,
    EvaluationSuite,
    FrozenRuntimeIdentity,
    HypothesisFamily,
    ModelActivationBinding,
    ModelAuthenticationMode,
    ModelCostAccountingMode,
    ModelProfileRevision,
    ModelQualificationState,
    ModelRunConfig,
    ModelRunnerCapabilities,
    ModelRunnerKind,
    MVP_R_EPISODE_SELECTION_RULE,
    MVP_R_REQUIRED_BASELINES,
    MVP_R_TOOLSET_VERSION,
    PivotCriticAuthorizationAuthority,
    PivotCriticDecision,
    PivotCriticRequest,
    PivotDeterministicCritique,
    PrefetchedResearchReportLoop,
    ReplayEpisodeCandidate,
    ResearchConclusionKind,
    ResearchHypothesisProposal,
    ResolvedRunConfig,
    RetrospectiveMarketWindow,
    RetrospectiveWindowIssuer,
    RunAuthorizationAuthority,
    TrustedResearchToolsPort,
    V1010ExecutorBinding,
    V1010ResultOwnerAuthority,
    WorkloadId,
    build_pivot_machine_handoff,
    critique_pivot_conclusion,
    frozen_mvp_tool_specs,
    issue_replay_tool_results,
    requires_independent_pivot_critic,
    screen_hypothesis_families,
    stratified_replay_candidates,
)
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
RESEARCH_PROMPT_PATH = ROOT / "prompts" / "mvp-r" / "research-agent-pivot-v1.md"
CRITIC_PROMPT_PATH = ROOT / "prompts" / "mvp-r" / "research-critic-pivot-v1.md"
REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-001-PIVOT", "request": "multi-family-development-v1"})
PREFETCHED_TOOLS = ("historical_query", "l0_signal_test", "l1_bar_backtest", "feature_query")
MINIMUM_SIGNAL_COUNT = 3
MINIMUM_ACCURACY = Decimal("0.55")
MINIMUM_POSITIVE_FOLD_RATIO = Decimal("0.50")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--critical-probe", action="store_true")
    parser.add_argument("--probe-roster-index", type=int)
    parser.add_argument("--skip-critical", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--historical-holdout", action="store_true")
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.critical_probe and args.limit is None:
        raise SystemExit("--critical-probe requires --limit")
    if args.critical_probe and args.skip_critical:
        raise SystemExit("--critical-probe and --skip-critical cannot be combined")
    if args.probe_roster_index is not None and args.probe_roster_index < 1:
        raise SystemExit("--probe-roster-index must be positive")
    if args.probe_roster_index is not None and (args.limit is not None or args.critical_probe or args.skip_critical):
        raise SystemExit("--probe-roster-index cannot be combined with other probe selectors")
    if args.data_root is not None and not args.historical_holdout:
        raise SystemExit("--data-root is reserved for the historical holdout")

    historical_holdout = args.historical_holdout
    data_root = (
        args.data_root or DATA_ROOT / "pivot-retrospective-2025" if historical_holdout else DATA_ROOT
    ).resolve()
    phase = EpisodePhase.HOLDOUT if historical_holdout else EpisodePhase.DIAGNOSTIC
    request_sha256 = (
        canonical_sha256({"task": "MVP-R-001-PIVOT", "request": "retrospective-confirmation-2025-v1"})
        if historical_holdout
        else REQUEST_SHA256
    )
    suite_revision = "retrospective-confirmation-2025-v1" if historical_holdout else "development-v1"
    stored = _stored_datasets(data_root) if historical_holdout else legacy._stored_datasets()
    records_by_manifest = {dataset_manifest_sha256(item.manifest): legacy._records(item) for item in stored}
    all_records = tuple(record for records in records_by_manifest.values() for record in records)
    master = legacy._master_secret()
    result_port = TrustedResearchToolsPort(legacy._key(master, "pivot-result-port"))
    result_owner = V1010ResultOwnerAuthority(
        "mvp-r.pivot-v1-010-owner", legacy._key(master, "pivot-result-owner"), result_port
    )
    contracts = {
        dataset_manifest_sha256(item.manifest): canonical_sha256(
            {
                "source_uri": item.manifest.provenance.source_uri,
                "source_revision": item.manifest.provenance.source_revision,
                "license": "personal-non-commercial-research-no-redistribution",
                "governance_authorized_at": "2026-08-31" if historical_holdout else "2026-08-30",
                "purpose": (
                    "user-authorized-retrospective-confirmation-holdout"
                    if historical_holdout
                    else "contaminated-development-diagnostic-only"
                ),
            }
        )
        for item in stored
    }
    data_authority = DatasetAuthorizationAuthority(
        "mvp-r.pivot-data-governance",
        legacy._key(master, "pivot-data-authority"),
        contracts,
        frozenset({sha256_digest(b"MVP-R Pivot known synthetic denylist sentinel")}),
        frozenset({OFFICIAL_RESEARCH_SERIES_NORMALIZER}),
    )
    dataset_refs = tuple(
        data_authority.authorize(
            item,
            provider_contract_sha256=contracts[dataset_manifest_sha256(item.manifest)],
            records=records_by_manifest[dataset_manifest_sha256(item.manifest)],
        )
        for item in stored
    )
    config = _model_config()
    validation_config = legacy._validation_config()
    tools = frozen_mvp_tool_specs(request_sha256)
    research_prompt = RESEARCH_PROMPT_PATH.read_text(encoding="utf-8")
    critic_prompt = CRITIC_PROMPT_PATH.read_text(encoding="utf-8")
    research_prompt_sha256 = hashlib.sha256(research_prompt.encode()).hexdigest()
    critic_prompt_sha256 = hashlib.sha256(critic_prompt.encode()).hexdigest()
    runtime = _runtime(research_prompt_sha256, critic_prompt_sha256, study_revision=suite_revision)
    suite = EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": "MVP-R-001-PIVOT", "revision": suite_revision}),
        9 if historical_holdout else 8,
        config.content_sha256,
        research_prompt_sha256,
        legacy._tool_specs_sha256(tools),
        runtime.content_sha256,
        data_authority.authority_id,
        "mvp-r.pivot-evaluator",
        dataset_refs,
        tuple(sorted(instrument for ref in dataset_refs for instrument in ref.instrument_universe)),
        MVP_R_EPISODE_SELECTION_RULE,
        "multi_family_selection_precision.v1",
        ("critic_increment.v1", "machine_handoff.v2", "research_latency.v1"),
        MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        1,
    )
    candidates = stratified_replay_candidates(
        all_records,
        cutoff_start=RecordedAt.parse("2025-03-03T00:00:00Z" if historical_holdout else "2026-03-01T00:00:00Z"),
        cutoff_end=RecordedAt.parse("2025-06-20T23:59:59Z" if historical_holdout else "2026-08-20T23:59:59Z"),
        candidates_per_cell=4 if historical_holdout else 2,
    )
    ref_by_manifest = {ref.manifest_sha256: ref for ref in dataset_refs}
    manifest_by_instrument = {
        instrument: manifest_sha256
        for manifest_sha256, records in records_by_manifest.items()
        for instrument in {cast(str, record.values["instrument_id"]) for record in records}
    }
    issued: dict[str, tuple[ReplayEpisodeCandidate, RetrospectiveMarketWindow]] = {}
    roster_candidates = []
    for candidate in candidates:
        manifest_sha256 = manifest_by_instrument[candidate.instrument_id]
        dataset_ref = ref_by_manifest[manifest_sha256]
        artifacts = tuple(
            data_authority.issue_artifact(dataset_ref, candidate.instrument_id, record) for record in candidate.records
        )
        window = RetrospectiveWindowIssuer().issue(
            instrument_id=candidate.instrument_id,
            acquisition_as_of=candidate.records[-1].available_time,
            market_cutoff=candidate.market_cutoff,
            artifacts=artifacts,
        )
        episode_id = semantic_entity_id(
            "evaluation_episode",
            {
                "suite_sha256": suite.content_sha256,
                "phase": phase.value,
                "instrument_id": candidate.instrument_id,
                "stratum": candidate.stratum.value,
                "market_cutoff": candidate.market_cutoff.to_dict()["recorded_at"],
            },
        )
        episode = EpisodeIssuer().issue(
            suite=suite,
            episode_id=episode_id,
            phase=phase,
            mode=EpisodeMode.RETROSPECTIVE_SEALED_REPLAY,
            instrument_id=candidate.instrument_id,
            as_of=candidate.records[-1].available_time,
            market_cutoff=candidate.market_cutoff,
            future_reveal_at=candidate.future_record.event_time,
            artifacts=artifacts,
            retrospective_window=window,
        )
        roster_candidates.append(EpisodeRosterCandidate(episode, candidate.stratum))
        issued[str(episode_id)] = (candidate, window)

    roster_authority = EpisodeRosterAuthority(
        "mvp-r.pivot-episode-roster",
        legacy._key(master, "pivot-roster-retrospective-2025" if historical_holdout else "pivot-roster-diagnostic"),
    )
    roster = roster_authority.freeze(suite, phase, tuple(roster_candidates))
    roster_authority.verify(roster)
    if args.plan_only:
        print(
            json.dumps(
                {
                    "task": "MVP-R-001-PIVOT",
                    "suite_sha256": suite.content_sha256,
                    "research_prompt_sha256": research_prompt_sha256,
                    "critic_prompt_sha256": critic_prompt_sha256,
                    "runtime_sha256": runtime.content_sha256,
                    "request_sha256": request_sha256,
                    "roster_sha256": roster.content_sha256,
                    "selected_count": len(roster.selected),
                    "future_values_read": False,
                    "holdout_status": (
                        "FROZEN_RETROSPECTIVE_CONFIRMATION_READY_TO_RUN"
                        if historical_holdout
                        else "BLOCKED_UNTIL_POST_PIVOT_FORWARD_DATA_EXISTS"
                    ),
                },
                indent=2,
            )
        )
        return

    selected: tuple[EpisodeRosterCandidate, ...]
    if args.probe_roster_index is not None:
        if args.probe_roster_index > len(roster.selected):
            raise SystemExit("--probe-roster-index exceeds the frozen roster")
        selected = (roster.selected[args.probe_roster_index - 1],)
    else:
        selected = roster.selected[4:] if args.skip_critical else roster.selected
        selected = selected[: args.limit] if args.limit is not None else selected
    scope = (
        "critical-probe"
        if args.critical_probe
        else "indexed-research-probe"
        if args.probe_roster_index is not None
        else "research-probe"
        if args.skip_critical
        else "probe"
        if args.limit is not None
        else "historical-holdout"
        if historical_holdout
        else "development"
    )
    output_dir = (
        data_root
        / "runs"
        / suite.content_sha256
        / ("pivot-historical-holdout" if historical_holdout else "pivot-diagnostic")
        / scope
    )
    if args.probe_roster_index is not None:
        output_dir /= f"roster-{args.probe_roster_index:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    legacy._write_json(
        output_dir / "roster.json",
        {
            **roster.unsigned_payload(),
            "signature_sha256": roster.signature_sha256,
            "content_sha256": roster.content_sha256,
        },
    )
    run_authority = RunAuthorizationAuthority(
        "mvp-r.pivot-run-governance", legacy._key(master, "pivot-run-authority"), data_authority, result_owner
    )
    critic_authority = PivotCriticAuthorizationAuthority(
        "mvp-r.pivot-critic-governance", legacy._key(master, "pivot-critic-authority")
    )
    binding = V1010ExecutorBinding(result_owner)
    provider = CodexAppServerProvider.official()
    completed = 0
    independent_vetoes = 0
    critical_scenarios = 0
    critical_correct_refusals = 0
    critic_injected_defects = 0
    critic_injected_defects_caught = 0
    for index, roster_candidate in enumerate(selected, start=1):
        episode = roster_candidate.episode
        candidate, window = issued[str(episode.episode_id)]
        roster_index = next(
            position
            for position, item in enumerate(roster.selected, start=1)
            if item.episode.episode_id == episode.episode_id
        )
        critical_scenario = (args.limit is None and not args.skip_critical and roster_index <= 4) or (
            args.critical_probe and roster_index == 1
        )
        if args.probe_roster_index is not None:
            critical_scenario = False
        run_id = semantic_entity_id(
            "research_validation_run", {"episode_id": str(episode.episode_id), "request_sha256": request_sha256}
        )
        owner_results = issue_replay_tool_results(
            episode=episode.agent_view(),
            window=window,
            records=candidate.records,
            market_state=candidate.stratum,
            request_sha256=request_sha256,
            config=validation_config,
            run_id=run_id,
            result_authority=result_port,
            inject_insufficient_l1=critical_scenario,
            include_pivot_family_screen=True,
        )
        executor = binding.bind(
            episode=episode,
            request_sha256=request_sha256,
            snapshot_sha256=window.content_sha256,
            owner_verified_results=owner_results,
        )
        evidence: JsonValue = {window.content_sha256: window.payload()}
        authorization = run_authority.issue(
            model_config=config,
            evaluation_suite=suite,
            credential_resolved=True,
            prompt_content_sha256=research_prompt_sha256,
            episode=episode.agent_view(),
            evidence=evidence,
            tool_specs=tools,
            executor_sha256=executor.content_sha256,
            runtime=runtime,
        )
        run = PrefetchedResearchReportLoop(
            provider,
            executor,
            run_authority,
            runtime,
            lambda: EntityId.new("model_run"),
            prefetched_tools=PREFETCHED_TOOLS,
        ).run(
            config=config,
            episode=episode.agent_view(),
            instructions=research_prompt,
            evidence=evidence,
            tools=tools,
            request_sha256=request_sha256,
            authorization=authorization,
        )
        records = candidate.records
        screens = screen_hypothesis_families(
            records,
            signal_threshold=validation_config.signal_threshold,
            per_signal_cost=(validation_config.round_trip_cost_bps + validation_config.slippage_bps) / Decimal(10_000),
        )
        feature_execution = next((item for item in run.tool_executions if item.tool_name == "feature_query"), None)
        deterministic_critique = (
            critique_pivot_conclusion(
                run.conclusion,
                screens,
                feature_evidence_sha256=feature_execution.result_sha256,
                minimum_signal_count=MINIMUM_SIGNAL_COUNT,
                minimum_accuracy=MINIMUM_ACCURACY,
                minimum_positive_fold_ratio=MINIMUM_POSITIVE_FOLD_RATIO,
            )
            if run.conclusion is not None and feature_execution is not None
            else None
        )
        critic_request = None
        critic_review = None
        critic_turn = None
        if (
            run.conclusion is not None
            and deterministic_critique is not None
            and feature_execution is not None
            and requires_independent_pivot_critic(run.conclusion, deterministic_critique)
        ):
            critic_request = PivotCriticRequest(
                str(episode.episode_id),
                episode.instrument_id,
                roster_candidate.stratum.value,
                run.conclusion,
                feature_execution.result_sha256,
                tuple(screen.payload() for screen in screens),
            )
            critic_authorization = critic_authority.issue(
                critic_request,
                model_id=config.model_id,
                prompt_sha256=critic_prompt_sha256,
                runtime_sha256=runtime.content_sha256,
            )
            critic_authority.verify(
                critic_authorization,
                critic_request,
                model_id=config.model_id,
                prompt_sha256=critic_prompt_sha256,
                runtime_sha256=runtime.content_sha256,
            )
            critic_turn = provider.respond_pivot_critic(
                request=critic_request,
                model_id=config.model_id,
                reasoning_effort=config.reasoning_effort.value,
                instructions=critic_prompt,
                timeout_seconds=config.timeout_seconds,
            )
            critic_review = critic_turn.review
            independent_vetoes += bool(critic_review is not None and critic_review.decision is PivotCriticDecision.VETO)
        handoff = (
            build_pivot_machine_handoff(
                episode=episode.agent_view(),
                run=run,
                screens=screens,
                feature_evidence_sha256=feature_execution.result_sha256,
                deterministic_critique=deterministic_critique,
                critic_request=critic_request,
                critic_review=critic_review,
            )
            if run.conclusion is not None and feature_execution is not None and deterministic_critique is not None
            else None
        )
        fault_critiques: tuple[tuple[str, PivotDeterministicCritique], ...] = ()
        if run.conclusion is not None and feature_execution is not None:
            none_hypothesis = ResearchHypothesisProposal(
                HypothesisFamily.NONE,
                "The injected proposal claims an opportunity without a registered family.",
                "Any registered directional evidence would falsify the injected proposal.",
                "Reject this malformed proposal before any further research.",
            )
            mutants = (
                ("missing_hypothesis", replace(run.conclusion, hypothesis=None)),
                (
                    "opportunity_without_registered_family",
                    replace(
                        run.conclusion,
                        kind=ResearchConclusionKind.OPPORTUNITY_CANDIDATE,
                        hypothesis=none_hypothesis,
                    ),
                ),
            )
            fault_critiques = tuple(
                (
                    mutation_id,
                    critique_pivot_conclusion(
                        mutant,
                        screens,
                        feature_evidence_sha256=feature_execution.result_sha256,
                        minimum_signal_count=MINIMUM_SIGNAL_COUNT,
                        minimum_accuracy=MINIMUM_ACCURACY,
                        minimum_positive_fold_ratio=MINIMUM_POSITIVE_FOLD_RATIO,
                    ),
                )
                for mutation_id, mutant in mutants
            )
            critic_injected_defects += len(fault_critiques)
            critic_injected_defects_caught += sum(not item.accepted for _, item in fault_critiques)
        critical_scenarios += critical_scenario
        critical_correct_refusals += bool(
            critical_scenario
            and run.status.value == "COMPLETED"
            and run.conclusion is not None
            and run.conclusion.kind.value == "DEFER"
            and all(turn.usage.total_tokens == 0 for turn in run.turns)
        )
        legacy._write_json(
            output_dir / f"{episode.episode_id}.json",
            {
                "episode_id": str(episode.episode_id),
                "instrument_id": episode.instrument_id,
                "stratum": roster_candidate.stratum.value,
                "critical_scenario": critical_scenario,
                "market_cutoff": episode.market_cutoff.to_dict()["recorded_at"],
                "future_reveal_at": episode.future_reveal_at.to_dict()["recorded_at"],
                "status": run.status.value,
                "failure_code": run.failure_code,
                "conclusion": run.conclusion.to_dict() if run.conclusion is not None else None,
                "deterministic_critique": (
                    {**deterministic_critique.payload(), "content_sha256": deterministic_critique.content_sha256}
                    if deterministic_critique is not None
                    else None
                ),
                "independent_critic": critic_review.payload() if critic_review is not None else None,
                "independent_critic_failure": critic_turn.failure_code if critic_turn is not None else None,
                "machine_handoff": handoff.to_dict() if handoff is not None else None,
                "critic_fault_injections": tuple(
                    {
                        "mutation_id": mutation_id,
                        **item.payload(),
                        "content_sha256": item.content_sha256,
                    }
                    for mutation_id, item in fault_critiques
                ),
                "family_screens": tuple(screen.payload() for screen in screens),
                "semantic_replay_sha256": run.semantic_replay_sha256,
                "audit_sha256": run.audit_sha256,
                "duration_ms": run.duration_ms,
                "research_usage": tuple(turn.usage.to_tuple() for turn in run.turns),
                "research_turns": tuple(
                    {
                        "response_id": turn.response_id,
                        "model_id": turn.provider_model_id,
                        "kind": turn.kind.value,
                        "failure_code": turn.failure_code,
                        "conclusion": turn.conclusion.to_dict() if turn.conclusion is not None else None,
                    }
                    for turn in run.turns
                ),
                "critic_usage": critic_turn.usage.to_tuple() if critic_turn is not None else None,
            },
        )
        completed += run.status.value == "COMPLETED"
        print(
            f"episode={index}/{len(selected)} id={episode.episode_id} status={run.status.value} "
            f"critic={critic_review.decision.value if critic_review is not None else 'NOT_RUN'}",
            flush=True,
        )
    summary: dict[str, JsonValue] = {
        "task": "MVP-R-001-PIVOT",
        "suite_sha256": suite.content_sha256,
        "roster_sha256": roster.content_sha256,
        "selected_count": len(selected),
        "completed_count": completed,
        "independent_critic_veto_count": independent_vetoes,
        "critical_scenario_count": critical_scenarios,
        "critical_correct_refusal_count": critical_correct_refusals,
        "critic_injected_defect_count": critic_injected_defects,
        "critic_injected_defect_caught_count": critic_injected_defects_caught,
        "model_id": config.model_id,
        "reasoning_effort": config.reasoning_effort.value,
        "run_scope": scope,
        "probe_roster_index": args.probe_roster_index,
        "output_directory": str(output_dir.relative_to(ROOT)),
    }
    legacy._write_json(output_dir / "run-summary.json", {**summary, "summary_sha256": canonical_sha256(summary)})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _stored_datasets(data_root: Path) -> tuple[StoredDataset, ...]:
    summary = json.loads((data_root / "collection-summary.json").read_text(encoding="utf-8"))
    store = LocalFileDataStore(data_root / "normalized", DatasetLayer.NORMALIZED_PIT)
    return tuple(store.get(EntityId.parse(item["normalized_dataset_id"])) for item in summary["sources"])


def _model_config() -> ModelRunConfig:
    profile_id = semantic_entity_id("model_profile", {"task": "MVP-R-001-PIVOT", "profile": "terra-medium-v1"})
    profile = ModelProfileRevision(
        profile_id,
        1,
        WorkloadId("research.hypothesis_synthesis"),
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        "medium",
        "mvp-r.pivot-research.v1",
        "mvp-r.pivot-conclusion.v1",
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
        semantic_entity_id("model_activation", {"profile_sha256": profile.content_sha256}), profile
    )
    return ModelRunConfig(
        semantic_entity_id("model_run_config", {"profile_sha256": profile.content_sha256, "revision": 5}),
        5,
        ResolvedRunConfig.resolve(binding, profile),
        "mvp-r.pivot-research.v1",
        "research-agent.pivot.v1",
        MVP_R_TOOLSET_VERSION,
        1,
        1,
        2_000,
        40_000,
        180,
        1_000_000,
        0,
        0,
        1,
        1,
        0,
    )


def _runtime(
    research_prompt_sha256: str,
    critic_prompt_sha256: str,
    *,
    study_revision: str = "pivot-development-v1",
) -> FrozenRuntimeIdentity:
    code_paths = (
        ROOT / "src/futures_agent_os/research_experiment/mvp_validation.py",
        ROOT / "src/futures_agent_os/research_experiment/mvp_replay.py",
        ROOT / "src/futures_agent_os/research_experiment/mvp_pivot.py",
        ROOT / "src/futures_agent_os/research_experiment/mvp_pivot_critic.py",
        ROOT / "src/futures_agent_os/research_experiment/mvp_pivot_handoff.py",
        ROOT / "src/futures_agent_os/adapters/codex_app_server.py",
        ROOT / "scripts/summarize_mvp_r_pivot.py",
        Path(__file__),
    )
    code_sha256 = hashlib.sha256(
        b"".join(path.read_bytes() for path in code_paths) + critic_prompt_sha256.encode()
    ).hexdigest()
    return FrozenRuntimeIdentity(
        research_prompt_sha256,
        code_sha256,
        canonical_sha256(
            {
                "policy": "future-blind-multi-family-research-with-independent-critic",
                "revision": study_revision,
                "critic_prompt_sha256": critic_prompt_sha256,
                "holdout": "post-pivot-forward-data-only",
            }
        ),
    )


if __name__ == "__main__":
    main()
