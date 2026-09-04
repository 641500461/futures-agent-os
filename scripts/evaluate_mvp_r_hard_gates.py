"""Rebuild signed MVP-R hard-gate evidence from frozen local run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from typing import cast

from futures_agent_os.adapters import OFFICIAL_RESEARCH_SERIES_NORMALIZER
from futures_agent_os.reference_market_data import dataset_manifest_sha256, sha256_digest
from futures_agent_os.research_experiment import (
    DatasetAuthorizationAuthority,
    EpisodeIssuer,
    EpisodeMode,
    EpisodePhase,
    EpisodeRosterAuthority,
    EpisodeRosterCandidate,
    EvaluationSuite,
    HardGateEvaluator,
    HardGateEvent,
    HardGateEventFact,
    HardGateEvidenceAuthority,
    ModelRunRecord,
    ModelTurn,
    ModelTurnKind,
    ModelUsage,
    MVP_R_EPISODE_SELECTION_RULE,
    MVP_R_REQUIRED_BASELINES,
    ResearchConclusion,
    RetrospectiveWindowIssuer,
    RunAuthorizationAuthority,
    RunStatus,
    ToolCall,
    TrustedResearchToolsPort,
    V1010ExecutorBinding,
    V1010ResultOwnerAuthority,
    frozen_mvp_tool_specs,
    issue_replay_tool_results,
    stratified_replay_candidates,
)
from futures_agent_os.research_experiment.validation_tools import semantic_entity_id
from futures_agent_os.shared_kernel import EntityId, RecordedAt, canonical_json_text, canonical_sha256
from futures_agent_os.shared_kernel.observability import JsonValue

import run_mvp_r_replay as runner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("diagnostic", "holdout"), required=True)
    parser.add_argument("--suite-sha256", required=True)
    args = parser.parse_args()
    phase = EpisodePhase.DIAGNOSTIC if args.phase == "diagnostic" else EpisodePhase.HOLDOUT

    stored = runner._stored_datasets()
    records_by_manifest = {dataset_manifest_sha256(item.manifest): runner._records(item) for item in stored}
    all_records = tuple(record for records in records_by_manifest.values() for record in records)
    master = runner._master_secret()
    result_port = TrustedResearchToolsPort(runner._key(master, "result-port"))
    result_owner = V1010ResultOwnerAuthority("mvp-r.v1-010-owner", runner._key(master, "result-owner"), result_port)
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
        runner._key(master, "data-authority"),
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
    config = runner._model_config()
    validation_config = runner._validation_config()
    tools = frozen_mvp_tool_specs(runner.REQUEST_SHA256)
    prompt = runner.PROMPT_PATH.read_text(encoding="utf-8")
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    runtime = runner._runtime(prompt_sha256)
    suite = EvaluationSuite(
        semantic_entity_id("evaluation_suite", {"task": "MVP-R-001", "revision": 2}),
        2,
        config.content_sha256,
        prompt_sha256,
        runner._tool_specs_sha256(tools),
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
        2,
    )
    if suite.content_sha256 != args.suite_sha256:
        raise SystemExit("current frozen runtime no longer matches the requested suite")

    start, end = (
        ("2026-03-01T00:00:00Z", "2026-05-29T23:59:59Z")
        if phase is EpisodePhase.DIAGNOSTIC
        else ("2026-06-01T00:00:00Z", "2026-08-20T23:59:59Z")
    )
    candidates = stratified_replay_candidates(
        all_records,
        cutoff_start=RecordedAt.parse(start),
        cutoff_end=RecordedAt.parse(end),
        candidates_per_cell=2,
    )
    ref_by_manifest = {ref.manifest_sha256: ref for ref in dataset_refs}
    manifest_by_instrument = {
        instrument: manifest_sha256
        for manifest_sha256, records in records_by_manifest.items()
        for instrument in {cast(str, record.values["instrument_id"]) for record in records}
    }
    contexts: dict[str, tuple[object, ...]] = {}
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
        contexts[str(episode_id)] = (candidate, window)

    roster_authority = EpisodeRosterAuthority("mvp-r.episode-roster", runner._key(master, f"roster-{phase.value}"))
    episode_roster = roster_authority.freeze(suite, phase, tuple(roster_candidates))
    run_authority = RunAuthorizationAuthority(
        "mvp-r.run-governance",
        runner._key(master, "run-authority"),
        data_authority,
        result_owner,
    )
    binding = V1010ExecutorBinding(result_owner)
    run_dir = runner.DATA_ROOT / "runs" / args.suite_sha256 / args.phase / "official"
    runs = []
    authorizations = []
    evidences = []
    evaluator_authority = HardGateEvidenceAuthority(
        "mvp-r.hard-gate-evaluator", runner._key(master, "hard-gate-evaluator")
    )
    for index, roster_item in enumerate(episode_roster.selected, start=1):
        episode = roster_item.episode
        candidate, window = contexts[str(episode.episode_id)]
        result_run_id = semantic_entity_id(
            "research_validation_run",
            {"episode_id": str(episode.episode_id), "request_sha256": runner.REQUEST_SHA256},
        )
        owner_results = issue_replay_tool_results(
            episode=episode.agent_view(),
            window=cast(object, window),
            records=getattr(candidate, "records"),
            market_state=getattr(candidate, "stratum"),
            request_sha256=runner.REQUEST_SHA256,
            config=validation_config,
            run_id=result_run_id,
            result_authority=result_port,
            inject_insufficient_l1=index <= 4,
        )
        executor = binding.bind(
            episode=episode,
            request_sha256=runner.REQUEST_SHA256,
            snapshot_sha256=getattr(window, "content_sha256"),
            owner_verified_results=owner_results,
        )
        visible_evidence: JsonValue = {getattr(window, "content_sha256"): getattr(window, "payload")()}
        authorization = run_authority.issue(
            model_config=config,
            evaluation_suite=suite,
            credential_resolved=True,
            prompt_content_sha256=prompt_sha256,
            episode=episode.agent_view(),
            evidence=visible_evidence,
            tool_specs=tools,
            executor_sha256=executor.content_sha256,
            runtime=runtime,
        )
        path = run_dir / f"{episode.episode_id}.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        conclusion = (
            ResearchConclusion.hydrate(cast(dict[str, object], _freeze(artifact["conclusion"])))
            if artifact["conclusion"] is not None
            else None
        )
        turns = tuple(_turn(item, conclusion) for item in artifact["turns"])
        executions = tuple(
            executor.execute(
                ToolCall(f"prefetched-{position}", name, {"request_sha256": runner.REQUEST_SHA256}),
                episode.agent_view(),
            )
            for position, name in enumerate(("historical_query", "l0_signal_test", "l1_bar_backtest"), start=1)
        )
        run = ModelRunRecord(
            EntityId.parse(artifact["run_id"]),
            episode.episode_id,
            config.content_sha256,
            canonical_sha256(authorization.unsigned_payload()),
            RunStatus(artifact["status"]),
            turns,
            executions,
            artifact["duration_ms"],
            conclusion,
            artifact["failure_code"],
        )
        if (
            run.semantic_replay_sha256 != artifact["semantic_replay_sha256"]
            or run.audit_sha256 != artifact["audit_sha256"]
        ):
            raise PermissionError("saved run artifact does not reproduce its signed replay identity")
        events, sources = _hard_gate_events(artifact, run, suite.content_sha256)
        evidences.append(
            evaluator_authority.issue(
                suite_sha256=suite.content_sha256,
                phase=phase,
                run=run,
                events=events,
                event_sources=sources,
            )
        )
        runs.append(run)
        authorizations.append(authorization)

    frozen_roster = run_authority.issue_roster(
        suite=suite,
        phase=phase,
        runs=tuple(runs),
        authorizations=tuple(authorizations),
    )
    score = HardGateEvaluator(evaluator_authority, frozen_roster, run_authority).score(tuple(evidences))
    output: dict[str, JsonValue] = {
        "task": "MVP-R-001",
        "phase": phase.value,
        "suite_sha256": suite.content_sha256,
        "passed": score.passed,
        "failures": tuple(item.value for item in score.failures),
        "episode_count": score.episode_count,
        "critical_correct_refusal_ratio": str(score.critical_correct_refusal_ratio),
        "critic_high_severity_recall": str(score.critic_high_severity_recall),
        "frozen_run_roster": frozen_roster.unsigned_payload(),
        "frozen_run_roster_signature_sha256": frozen_roster.signature_sha256,
        "episode_evidence": tuple(
            {
                **item.unsigned_payload(),
                "signature_sha256": item.signature_sha256,
            }
            for item in evidences
        ),
    }
    output["scorecard_sha256"] = canonical_sha256(output)
    (run_dir / "hard-gate-scorecard.json").write_text(canonical_json_text(output) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _turn(value: dict[str, object], conclusion: ResearchConclusion | None) -> ModelTurn:
    usage = cast(list[int], value["usage"])
    kind = ModelTurnKind(cast(str, value["kind"]))
    return ModelTurn(
        cast(str, value["response_id"]),
        cast(str, value["model_id"]),
        kind,
        ModelUsage(*usage),
        conclusion=conclusion if kind is ModelTurnKind.FINAL else None,
        failure_code=cast(str | None, value["failure_code"]),
    )


def _hard_gate_events(
    artifact: dict[str, object], run: ModelRunRecord, suite_sha256: str
) -> tuple[tuple[HardGateEventFact, ...], dict[str, JsonValue]]:
    kinds = []
    if artifact.get("critical_scenario") is True:
        kinds.append(HardGateEvent.CRITICAL_SCENARIO)
        kinds.append(HardGateEvent.INSUFFICIENT_EVIDENCE_CASE)
        conclusion = cast(dict[str, object] | None, artifact.get("conclusion"))
        if conclusion is not None and conclusion.get("kind") == "DEFER":
            kinds.append(HardGateEvent.CRITICAL_CORRECT_REFUSAL)
            kinds.append(HardGateEvent.EXPLICIT_DEFER_OR_INCOMPLETE)
    for injected in cast(list[dict[str, object]], artifact.get("critic_fault_injections", [])):
        kinds.append(HardGateEvent.CRITIC_HIGH_SEVERITY_DEFECT)
        if injected.get("accepted") is False:
            kinds.append(HardGateEvent.CRITIC_HIGH_SEVERITY_CAUGHT)
    events = []
    sources: dict[str, JsonValue] = {}
    for index, kind in enumerate(kinds, start=1):
        source: dict[str, JsonValue] = {
            "event_id": f"{run.episode_id}-{index}",
            "kind": kind.value,
            "episode_id": str(run.episode_id),
            "suite_sha256": suite_sha256,
            "run_replay_sha256": run.semantic_replay_sha256,
            "run_audit_sha256": run.audit_sha256,
        }
        digest = canonical_sha256(source)
        sources[digest] = source
        events.append(HardGateEventFact(kind, digest, "/kind"))
    return tuple(events), sources


def _freeze(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return cast(JsonValue, value)
    if type(value) is list:
        return tuple(_freeze(item) for item in cast(list[object], value))
    if type(value) is dict:
        return {cast(str, key): _freeze(item) for key, item in cast(dict[object, object], value).items()}
    raise TypeError("saved artifact contains non-JSON content")


if __name__ == "__main__":
    main()
