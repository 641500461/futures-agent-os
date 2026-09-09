from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.agent_orchestration import (
    ArtifactKind,
    ArtifactRef,
    ProtectionIntent,
    StrategyAgentResult,
    StrategyCandidate,
)

from futures_agent_os.research_experiment import (
    ArtifactEntry,
    ArtifactManifest,
    BatchResearchPlan,
    BatchResearchScheduler,
    ConnectorOutput,
    ConnectorRef,
    CostRef,
    DatasetRef,
    DeterministicContractVerifier,
    FunnelCandidate,
    GateDecision,
    ModelRef,
    PinnedRef,
    PromptRef,
    RuleRef,
    SeedBundle,
    UnifiedExperimentPlan,
    ValidationLevel,
    current_engine_ref,
    installed_v1_v2_connectors,
    standard_level_contracts,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, canonical_sha256


def _plan(seed: str) -> UnifiedExperimentPlan:
    return UnifiedExperimentPlan(
        EntityId.deterministic("experiment", seed),
        SchemaVersion(4, 0),
        DatasetRef("bars", "1", "a" * 64),
        RuleRef("rules", "1", "b" * 64),
        CostRef("cost", "1", "c" * 64),
        current_engine_ref(),
        ModelRef("model", "1", "d" * 64),
        PromptRef("prompt", "1", "e" * 64),
        SeedBundle({"simulation": 7}),
        {"seed": seed},
    )


def _candidate(seed: str, levels: tuple[ValidationLevel, ...] | None = None) -> FunnelCandidate:
    return FunnelCandidate(
        PinnedRef(f"candidate-{seed}", "1", canonical_sha256({"candidate": seed})),
        _plan(seed),
        (PinnedRef(f"snapshot-{seed}", "1", canonical_sha256({"snapshot": seed})),),
        levels or tuple(ValidationLevel),
    )


def _connectors(*, external: bool = False) -> tuple[ConnectorRef, ...]:
    return tuple(
        ConnectorRef(
            f"connector-{level.value.lower()}",
            "1.0.0",
            canonical_sha256({"implementation": level.value}),
            canonical_sha256({"input": level.value}),
            canonical_sha256({"output": level.value}),
            (level,),
            external,
        )
        for level in ValidationLevel
    )


def _output(task: object, *, pass_checks: bool = True, summary_pass: bool = False) -> ConnectorOutput:
    level = getattr(task, "level")
    contract = next(item for item in standard_level_contracts() if item.level is level)
    input_sha = getattr(task, "input_sha256")
    connector = getattr(task, "connector")
    entries = tuple(
        ArtifactEntry(
            name,
            canonical_sha256({"task": input_sha, "name": name}),
            f"artifact://{name}",
        )
        for name in sorted(contract.required_artifacts)
    )
    metrics = {f"contract_check:{name}": pass_checks for name in contract.required_checks}
    return ConnectorOutput(
        input_sha,
        connector.content_sha256,
        connector.output_schema_sha256,
        ArtifactManifest(entries),
        metrics,
        external_summary={"promotion_decision": "PASS"} if summary_pass else {},
    )


def _scheduler(candidates: tuple[FunnelCandidate, ...], *, external: bool = False) -> BatchResearchScheduler:
    plan = BatchResearchPlan(EntityId.new("research_batch"), SchemaVersion(4, 2), candidates)
    verifier = DeterministicContractVerifier(PinnedRef("local-level-verifier", "1", "f" * 64))
    return BatchResearchScheduler(plan, _connectors(external=external), verifier)


def test_batch_starts_every_candidate_at_l0() -> None:
    scheduler = _scheduler((_candidate("a"), _candidate("b")))
    assert [item.level for item in scheduler.queued()] == [ValidationLevel.L0, ValidationLevel.L0]


def test_each_candidate_advances_sequentially() -> None:
    scheduler = _scheduler((_candidate("a"),))
    l0_task = scheduler.queued()[0]
    l0 = scheduler.accept(l0_task, _output(l0_task))
    assert l0.decision is GateDecision.PASS
    l1_task = scheduler.queued()[0]
    assert l1_task.level is ValidationLevel.L1
    assert l1_task.predecessor_evidence_sha256 == l0.content_sha256
    l1 = scheduler.accept(l1_task, _output(l1_task))
    l2_task = scheduler.queued()[0]
    assert l2_task.level is ValidationLevel.L2
    assert l2_task.predecessor_evidence_sha256 == l1.content_sha256


def test_external_summary_cannot_bypass_local_gate() -> None:
    scheduler = _scheduler((_candidate("external"),), external=True)
    task = scheduler.queued()[0]
    evidence = scheduler.accept(task, _output(task, pass_checks=False, summary_pass=True))
    assert evidence.decision is GateDecision.FAIL
    assert scheduler.queued() == ()


def test_connector_schema_and_exact_task_are_bound() -> None:
    scheduler = _scheduler((_candidate("binding"),))
    task = scheduler.queued()[0]
    with pytest.raises(ValueError, match="schema"):
        scheduler.accept(task, replace(_output(task), output_schema_sha256="0" * 64))
    with pytest.raises(ValueError, match="scheduled input"):
        scheduler.accept(task, replace(_output(task), task_input_sha256="0" * 64))


def test_standard_contracts_expose_semls_and_gates() -> None:
    contracts = standard_level_contracts()
    assert tuple(item.level for item in contracts) == tuple(ValidationLevel)
    assert all(item.input_semantics and item.purpose for item in contracts)
    assert all(item.limitations and item.required_artifacts and item.required_checks for item in contracts)
    assert "does not claim tradable returns" in contracts[0].limitations
    assert "fill semantics are approximate" in contracts[1].limitations
    assert "not tick/queue fidelity" in contracts[2].limitations


def test_funnel_levels_must_be_contiguous() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        _candidate("skip", (ValidationLevel.L0, ValidationLevel.L2))


def test_v3_single_candidate_preserves_digest_and_pit_lineage() -> None:
    at = RecordedAt(datetime(2026, 1, 1, tzinfo=UTC))
    source = ArtifactRef(
        EntityId.new("market_snapshot"),
        ArtifactKind.MARKET_SNAPSHOT,
        SchemaVersion(1, 0),
        "sha256:" + "a" * 64,
        at,
        at,
    )
    candidate = StrategyCandidate(
        "thesis",
        "invalidation",
        (str(source.artifact_id),),
        "10",
        "exit",
        protection_intent=ProtectionIntent("stop", "10"),
    )
    result = StrategyAgentResult(
        candidate,
        None,
        (source,),
        at,
        RecordedAt(at.value + timedelta(hours=1)),
    )
    adapted = FunnelCandidate.from_v3(result, _plan("v3"))
    assert adapted.candidate_ref.content_sha256 == result.content_sha256()
    assert adapted.source_lineage[0].content_sha256 == source.content_hash.removeprefix("sha256:")


def test_installed_connectors_pin_existing_v1_and_v2_engines() -> None:
    connectors = installed_v1_v2_connectors()
    assert connectors[0].levels == (ValidationLevel.L0, ValidationLevel.L1)
    assert connectors[1].levels == (ValidationLevel.L2,)
    assert all(not item.external and len(item.content_sha256) == 64 for item in connectors)
