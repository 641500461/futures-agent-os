"""Run the governed MVP-R retrospective replay through the Codex session."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

from futures_agent_os.adapters import (
    OFFICIAL_RESEARCH_SERIES_NORMALIZER,
    CodexAppServerProvider,
)
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
    PrefetchedResearchReportLoop,
    ReplayCritique,
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
    ValidationConfig,
    WorkloadId,
    critique_replay_conclusion,
    build_machine_research_handoff,
    frozen_mvp_tool_specs,
    issue_replay_tool_results,
    stratified_replay_candidates,
)
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "datasets" / "mvp-r-001"
PROMPT_PATH = ROOT / "prompts" / "mvp-r" / "research-agent-v4.md"
MASTER_SECRET_PATH = DATA_ROOT / ".governance-master-key"
REQUEST_SHA256 = canonical_sha256({"task": "MVP-R-001", "request": "residual-research-v4"})
ITERATION_THREE_SUITE_SHA256 = (
    "e1789aff7f92b2de3c526e0d9f08574c0008fce6e3e3978d97c9a12d7f7a05ee"  # pragma: allowlist secret
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("diagnostic", "holdout"), default="diagnostic")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--critical-probe", action="store_true")
    parser.add_argument("--skip-critical", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    phase = EpisodePhase.DIAGNOSTIC if args.phase == "diagnostic" else EpisodePhase.HOLDOUT
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.critical_probe and args.limit is None:
        raise SystemExit("--critical-probe requires --limit")
    if args.critical_probe and args.skip_critical:
        raise SystemExit("--critical-probe and --skip-critical cannot be combined")

    stored = _stored_datasets()
    records_by_manifest = {dataset_manifest_sha256(item.manifest): _records(item) for item in stored}
    all_records = tuple(record for records in records_by_manifest.values() for record in records)
    master = _master_secret()
    result_port = TrustedResearchToolsPort(_key(master, "result-port"))
    result_owner = V1010ResultOwnerAuthority("mvp-r.v1-010-owner", _key(master, "result-owner"), result_port)
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
    data_authority = DatasetAuthorizationAuthority(
        "mvp-r.data-governance",
        _key(master, "data-authority"),
        contracts,
        frozenset({sha256_digest(b"MVP-R known synthetic denylist sentinel")}),
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
    validation_config = _validation_config()
    tools = frozen_mvp_tool_specs(REQUEST_SHA256)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    runtime = _runtime(prompt_sha256)
    suite = EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": "MVP-R-001", "revision": "4"}),
        7,
        config.content_sha256,
        prompt_sha256,
        _tool_specs_sha256(tools),
        runtime.content_sha256,
        data_authority.authority_id,
        "mvp-r.hard-gate-evaluator",
        dataset_refs,
        tuple(sorted(instrument for ref in dataset_refs for instrument in ref.instrument_universe)),
        MVP_R_EPISODE_SELECTION_RULE,
        "evidence_quality.v1",
        ("bad_candidate_escape.v1", "research_latency.v1"),
        MVP_R_REQUIRED_BASELINES,
        30,
        50,
        10,
        4,
    )
    candidate_specs = stratified_replay_candidates(
        all_records,
        cutoff_start=RecordedAt.parse(
            "2026-03-01T00:00:00Z" if phase is EpisodePhase.DIAGNOSTIC else "2026-06-01T00:00:00Z"
        ),
        cutoff_end=RecordedAt.parse(
            "2026-05-29T23:59:59Z" if phase is EpisodePhase.DIAGNOSTIC else "2026-08-20T23:59:59Z"
        ),
        candidates_per_cell=2 if phase is EpisodePhase.DIAGNOSTIC else 6,
    )
    if phase is EpisodePhase.HOLDOUT:
        previously_revealed = _iteration_three_holdout_keys()
        candidate_specs = tuple(
            candidate
            for candidate in candidate_specs
            if (candidate.instrument_id, candidate.market_cutoff.to_dict()["recorded_at"]) not in previously_revealed
        )
    ref_by_manifest = {ref.manifest_sha256: ref for ref in dataset_refs}
    manifest_by_instrument = {
        instrument: manifest_sha256
        for manifest_sha256, records in records_by_manifest.items()
        for instrument in {cast(str, record.values["instrument_id"]) for record in records}
    }
    issued: dict[
        str,
        tuple[ReplayEpisodeCandidate, RetrospectiveMarketWindow, tuple[object, ...]],
    ] = {}
    roster_candidates = []
    for candidate in candidate_specs:
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
        issued[str(episode_id)] = (candidate, window, artifacts)

    roster_authority = EpisodeRosterAuthority("mvp-r.episode-roster", _key(master, f"roster-{phase.value}"))
    roster = roster_authority.freeze(suite, phase, tuple(roster_candidates))
    roster_authority.verify(roster)
    if args.plan_only:
        print(
            json.dumps(
                {
                    "task": "MVP-R-001",
                    "revision": 4,
                    "phase": phase.value,
                    "suite_sha256": suite.content_sha256,
                    "prompt_sha256": prompt_sha256,
                    "runtime_sha256": runtime.content_sha256,
                    "request_sha256": REQUEST_SHA256,
                    "candidate_count": len(roster_candidates),
                    "roster_sha256": roster.content_sha256,
                    "selected_count": len(roster.selected),
                    "maximum_iterations": suite.maximum_iterations,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    selected = roster.selected[4:] if args.skip_critical else roster.selected
    selected = selected[: args.limit] if args.limit is not None else selected
    # A probe or a later suite revision must never mingle artifacts with the
    # frozen batch it was intended to validate.
    run_scope = (
        "critical-probe"
        if args.critical_probe
        else "model-probe"
        if args.skip_critical
        else "probe"
        if args.limit is not None
        else "official"
    )
    output_dir = DATA_ROOT / "runs" / suite.content_sha256 / phase.value.lower() / run_scope
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_dir / "roster.json",
        {
            **roster.unsigned_payload(),
            "signature_sha256": roster.signature_sha256,
            "content_sha256": roster.content_sha256,
        },
    )
    run_authority = RunAuthorizationAuthority(
        "mvp-r.run-governance",
        _key(master, "run-authority"),
        data_authority,
        result_owner,
    )
    binding = V1010ExecutorBinding(result_owner)
    provider = CodexAppServerProvider.official()
    completed = 0
    critic_vetoed = 0
    critical_scenarios = 0
    critical_correct_refusals = 0
    critic_injected_defects = 0
    critic_injected_defects_caught = 0
    for index, roster_candidate in enumerate(selected, start=1):
        episode = roster_candidate.episode
        candidate, window, _ = issued[str(episode.episode_id)]
        run_id = semantic_entity_id(
            "research_validation_run",
            {"episode_id": str(episode.episode_id), "request_sha256": REQUEST_SHA256},
        )
        roster_index = next(
            position
            for position, item in enumerate(roster.selected, start=1)
            if item.episode.episode_id == episode.episode_id
        )
        critical_scenario = (args.limit is None and not args.skip_critical and roster_index <= 4) or (
            args.critical_probe and roster_index == 1
        )
        owner_results = issue_replay_tool_results(
            episode=episode.agent_view(),
            window=window,
            records=candidate.records,
            market_state=candidate.stratum,
            request_sha256=REQUEST_SHA256,
            config=validation_config,
            run_id=run_id,
            result_authority=result_port,
            inject_insufficient_l1=critical_scenario,
        )
        executor = binding.bind(
            episode=episode,
            request_sha256=REQUEST_SHA256,
            snapshot_sha256=window.content_sha256,
            owner_verified_results=owner_results,
        )
        evidence: JsonValue = {window.content_sha256: window.payload()}
        authorization = run_authority.issue(
            model_config=config,
            evaluation_suite=suite,
            credential_resolved=True,
            prompt_content_sha256=prompt_sha256,
            episode=episode.agent_view(),
            evidence=evidence,
            tool_specs=tools,
            executor_sha256=executor.content_sha256,
            runtime=runtime,
        )
        loop = PrefetchedResearchReportLoop(
            provider, executor, run_authority, runtime, lambda: EntityId.new("model_run")
        )
        run = loop.run(
            config=config,
            episode=episode.agent_view(),
            instructions=prompt,
            evidence=evidence,
            tools=tools,
            request_sha256=REQUEST_SHA256,
            authorization=authorization,
        )
        critique = (
            critique_replay_conclusion(run.conclusion, candidate.stratum, run.tool_executions)
            if run.conclusion is not None
            else None
        )
        machine_handoff = (
            build_machine_research_handoff(
                episode=episode.agent_view(),
                window=window,
                records=candidate.records,
                market_state=candidate.stratum,
                run=run,
                critique=critique,
                config=validation_config,
            )
            if run.conclusion is not None and critique is not None and not critical_scenario
            else None
        )
        fault_critiques: tuple[tuple[str, ReplayCritique], ...] = ()
        if run.conclusion is not None:
            none_hypothesis = ResearchHypothesisProposal(
                HypothesisFamily.NONE,
                "The injected proposal claims an opportunity without a directional hypothesis.",
                "Any accepted directional evidence would falsify the injected proposal.",
                "Reject this malformed proposal before any further research.",
            )
            mutants = (
                ("missing_hypothesis", replace(run.conclusion, hypothesis=None)),
                (
                    "opportunity_without_direction",
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
                    critique_replay_conclusion(mutant, candidate.stratum, run.tool_executions),
                )
                for mutation_id, mutant in mutants
            )
            critic_injected_defects += len(fault_critiques)
            critic_injected_defects_caught += sum(not item.accepted for _, item in fault_critiques)
        critic_vetoed += bool(critique is not None and not critique.accepted)
        critical_scenarios += critical_scenario
        critical_correct_refusals += bool(
            critical_scenario
            and run.conclusion is not None
            and run.conclusion.kind.value == "DEFER"
            and critique is not None
            and critique.accepted
        )
        _write_json(
            output_dir / f"{episode.episode_id}.json",
            {
                "episode_id": str(episode.episode_id),
                "phase": phase.value,
                "instrument_id": episode.instrument_id,
                "stratum": roster_candidate.stratum.value,
                "critical_scenario": critical_scenario,
                "market_cutoff": episode.market_cutoff.to_dict()["recorded_at"],
                "future_reveal_at": episode.future_reveal_at.to_dict()["recorded_at"],
                "window_sha256": window.content_sha256,
                "run_id": str(run.run_id),
                "status": run.status.value,
                "failure_code": run.failure_code,
                "conclusion": run.conclusion.to_dict() if run.conclusion else None,
                "critique": (
                    {**critique.payload(), "content_sha256": critique.content_sha256} if critique is not None else None
                ),
                "machine_handoff": machine_handoff.to_dict() if machine_handoff is not None else None,
                "critic_fault_injections": tuple(
                    {
                        "mutation_id": mutation_id,
                        **item.payload(),
                        "content_sha256": item.content_sha256,
                    }
                    for mutation_id, item in fault_critiques
                ),
                "semantic_replay_sha256": run.semantic_replay_sha256,
                "audit_sha256": run.audit_sha256,
                "duration_ms": run.duration_ms,
                "turns": tuple(
                    {
                        "response_id": turn.response_id,
                        "model_id": turn.provider_model_id,
                        "kind": turn.kind.value,
                        "usage": turn.usage.to_tuple(),
                        "tool_name": turn.tool_call.name if turn.tool_call else None,
                        "conclusion": turn.conclusion.to_dict() if turn.conclusion else None,
                        "failure_code": turn.failure_code,
                    }
                    for turn in run.turns
                ),
                "tool_result_sha256s": tuple(item.result_sha256 for item in run.tool_executions),
                "authorization_sha256": canonical_sha256(authorization.unsigned_payload()),
            },
        )
        completed += run.status.value == "COMPLETED"
        print(
            f"episode={index}/{len(selected)} id={episode.episode_id} instrument={episode.instrument_id} "
            f"stratum={roster_candidate.stratum.value} status={run.status.value} failure={run.failure_code}",
            flush=True,
        )
    summary = {
        "task": "MVP-R-001",
        "phase": phase.value,
        "suite_sha256": suite.content_sha256,
        "roster_sha256": roster.content_sha256,
        "selected_count": len(selected),
        "full_roster_count": len(roster.selected),
        "completed_count": completed,
        "critic_vetoed_count": critic_vetoed,
        "critical_scenario_count": critical_scenarios,
        "critical_correct_refusal_count": critical_correct_refusals,
        "critic_high_severity_defect_count": critic_injected_defects,
        "critic_high_severity_caught_count": critic_injected_defects_caught,
        "model_id": config.model_id,
        "reasoning_effort": config.reasoning_effort.value,
        "run_scope": run_scope,
        "output_directory": str(output_dir.relative_to(ROOT)),
    }
    _write_json(output_dir / "run-summary.json", {**summary, "summary_sha256": canonical_sha256(summary)})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _stored_datasets() -> tuple[StoredDataset, ...]:
    summary = json.loads((DATA_ROOT / "collection-summary.json").read_text(encoding="utf-8"))
    store = LocalFileDataStore(DATA_ROOT / "normalized", DatasetLayer.NORMALIZED_PIT)
    return tuple(store.get(EntityId.parse(item["normalized_dataset_id"])) for item in summary["sources"])


def _records(dataset: StoredDataset) -> tuple[PointInTimeRecord, ...]:
    values = json.loads(dataset.content)
    return tuple(
        PointInTimeRecord(
            RecordedAt.parse(item["event_time"]), RecordedAt.parse(item["available_time"]), item["values"]
        )
        for item in values
    )


def _iteration_three_holdout_keys() -> frozenset[tuple[str, str]]:
    roster_path = DATA_ROOT / "runs" / ITERATION_THREE_SUITE_SHA256 / "holdout" / "official" / "roster.json"
    payload = json.loads(roster_path.read_text(encoding="utf-8"))
    selected = payload.get("selected")
    if type(selected) is not list or len(selected) != 50:
        raise ValueError("iteration-three holdout commitment is unavailable or malformed")
    keys = frozenset(
        (item["instrument_id"], item["market_cutoff"])
        for item in selected
        if type(item) is dict and type(item.get("instrument_id")) is str and type(item.get("market_cutoff")) is str
    )
    if len(keys) != 50:
        raise ValueError("iteration-three holdout commitment contains duplicate or malformed episodes")
    return keys


def _model_config() -> ModelRunConfig:
    profile_id = semantic_entity_id("model_profile", {"task": "MVP-R-001", "profile": "codex-terra-medium-v4"})
    profile = ModelProfileRevision(
        profile_id,
        1,
        WorkloadId("research.hypothesis_synthesis"),
        "openai",
        ModelRunnerKind.CODEX_LOCAL,
        ModelAuthenticationMode.CHATGPT_SESSION,
        "gpt-5.6-terra",
        "medium",
        "mvp-r.prompt.v4",
        "mvp-r.conclusion.v4",
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
    resolved = ResolvedRunConfig.resolve(binding, profile)
    return ModelRunConfig(
        semantic_entity_id("model_run_config", {"profile_sha256": profile.content_sha256, "revision": 4}),
        4,
        resolved,
        "mvp-r.prompt.v4",
        "research-agent.v4",
        MVP_R_TOOLSET_VERSION,
        1,
        1,
        2_000,
        30_000,
        120,
        1_000_000,
        0,
        0,
        1,
        1,
        0,
    )


def _validation_config() -> ValidationConfig:
    return ValidationConfig(
        semantic_entity_id("research_validation_config", {"task": "MVP-R-001", "revision": 1}),
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


def _runtime(prompt_sha256: str) -> FrozenRuntimeIdentity:
    code_paths = (
        ROOT / "src/futures_agent_os/research_experiment/mvp_validation.py",
        ROOT / "src/futures_agent_os/research_experiment/mvp_replay.py",
        ROOT / "src/futures_agent_os/adapters/codex_app_server.py",
        ROOT / "src/futures_agent_os/adapters/research_model_payload.py",
        Path(__file__),
    )
    code_sha256 = hashlib.sha256(b"".join(path.read_bytes() for path in code_paths)).hexdigest()
    return FrozenRuntimeIdentity(
        prompt_sha256,
        code_sha256,
        canonical_sha256({"policy": "fail-closed-no-trading-residual-research", "revision": "4"}),
    )


def _tool_specs_sha256(tools: tuple[object, ...]) -> str:
    return canonical_sha256(
        tuple(
            {
                "name": getattr(tool, "name"),
                "description": getattr(tool, "description"),
                "parameters_json": getattr(tool, "parameters_json"),
            }
            for tool in tools
        )
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


def _write_json(path: Path, value: JsonValue) -> None:
    path.write_text(canonical_json_text(value) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
