"""Acceptance and adversarial contracts for V1-009 research Critic."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from futures_agent_os.agent_orchestration import (
    CATALOG_VERSION,
    AgentRoleId,
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    ArtifactClaim,
    CriticTaskSources,
    PreTradeCriticAgent,
    StructuredArtifact,
    TriggerSource,
    definition_for,
    validate_task_envelope,
)
from futures_agent_os.governance_registry import TOOL_REGISTRY, ToolPermissionTier
from futures_agent_os.research_experiment import (
    CritiqueCategory,
    CritiqueComposer,
    CritiqueFinding,
    CritiquePolicy,
    CritiqueRevisionStore,
    CritiqueStatus,
    DiagnosticEvidence,
    EvidenceGap,
    ExperimentRequestSpec,
    FalsifiableHypothesisSpec,
    FindingState,
    HypothesisProposalSource,
    IssueResolution,
    IssueSeverity,
    MarketStateAssessmentRef,
    ResearchSynthesisComposer,
    ResearchSynthesisInput,
    V1_009_REQUIRED_VALIDATIONS,
    v1_009_critique_policy,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext, canonical_sha256


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 25, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _research():  # type: ignore[no-untyped-def]
    market = MarketStateAssessmentRef(
        EntityId.new("market_state_assessment"), CATALOG_VERSION, _at(1), _at(60), "a" * 64
    )
    values = ResearchSynthesisInput(
        "A regime-conditioned effect differs from its prespecified control.",
        ("CU",),
        "Held-out next-window return differs from the control.",
        "The held-out interval includes the control effect.",
        ("feature_observation", "historical_data"),
        HypothesisProposalSource.MARKET_STATE_ASSESSMENT,
        ("Cost coverage is not yet known.",),
        ("The source assessment has immutable support evidence.",),
        (),
        ("Run the preregistered bounded comparison.",),
        (EvidenceGap("cost_coverage", "No cost diagnostic has been supplied."),),
        "Regime-matched control.",
        "Prespecified train and held-out windows.",
        "Directional comparison without execution.",
        ("effect_size",),
        ("Report support and refutation.",),
        "Stop at the held-out window boundary.",
        ("selection_bias",),
    )
    return ResearchSynthesisComposer().compose(
        FalsifiableHypothesisSpec(EntityId.new("hypothesis_spec"), 1, CATALOG_VERSION),
        ExperimentRequestSpec(EntityId.new("experiment_request_spec"), 1, CATALOG_VERSION),
        market,
        values,
        _at(50),
    )


def _policy(max_iterations: int = 3) -> CritiquePolicy:
    assert max_iterations in {1, 2, 3}  # callers cannot vary the pinned policy.
    return v1_009_critique_policy()


def _diagnostics(
    research,
    *,
    category: CritiqueCategory | None = None,
    state: FindingState = FindingState.CLEAR,
    severity: IssueSeverity = IssueSeverity.INFO,
    resolution: IssueResolution = IssueResolution.RESOLVED,
) -> tuple[DiagnosticEvidence, ...]:
    # V1-010 is the sole producer for deterministic diagnostics.  V1-009
    # deliberately has none, including in fixtures: missing proof is a GAP.
    return ()


def _compose(  # type: ignore[no-untyped-def]
    research,
    policy: CritiquePolicy,
    findings: tuple[DiagnosticEvidence, ...],
    iteration: int = 1,
    validations: tuple[str, ...] = (),
):
    return CritiqueComposer().compose(
        policy,
        research.hypothesis,
        research.evidence_synthesis,
        research.experiment_request,
        _at(10),
        _at(45),
        iteration,
        findings,
        V1_009_REQUIRED_VALIDATIONS if not validations else validations,
    )


def _refs(critique) -> tuple[ArtifactRef, ...]:  # type: ignore[no-untyped-def]
    return tuple(
        ArtifactRef(
            identity.artifact_id,
            ArtifactKind(identity.artifact_kind.value),
            identity.schema_version,
            "sha256:" + identity.content_sha256,
            _at(10),
            identity.as_of,
        )
        for identity in (critique.hypothesis, critique.evidence_synthesis, critique.experiment_request)
    )


def _task(refs: tuple[ArtifactRef, ...], expires_at: RecordedAt) -> AgentTaskEnvelope:
    correlation_id = EntityId.new("correlation")
    return AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        AgentRoleId.PRE_TRADE_CRITIC.value,
        SchemaVersion(1, 4),
        "independently challenge the supplied research",
        "return one deterministic research critique",
        (TriggerSource.DATA,),
        refs,
        (),
        (),
        definition_for(AgentRoleId.PRE_TRADE_CRITIC.value, SchemaVersion(1, 4)).budget,
        (ArtifactKind.CRITIQUE,),
        refs[0].as_of,
        expires_at,
    )


def _sources(refs: tuple[ArtifactRef, ...]) -> CriticTaskSources:
    origin = ArtifactRef(
        EntityId.new("market_state_assessment"),
        ArtifactKind.MARKET_STATE_ASSESSMENT,
        CATALOG_VERSION,
        "sha256:" + "d" * 64,
        _at(1),
        _at(1),
    )
    producer_run = EntityId.new("agent_run")
    return CriticTaskSources(
        tuple(
            StructuredArtifact(
                ref,
                AgentRoleId.RESEARCH.value,
                producer_run,
                (origin,),
                (ArtifactClaim("research", "verified source", (origin,), True),),
                (),
                _at(50),
            )
            for ref in refs
        )
    )


def test_v1_009_critique_is_content_addressed_but_fixed_to_closed_gaps_and_defer() -> None:
    research = _research()
    policy = _policy()
    findings = _diagnostics(research)
    first = _compose(research, policy, findings)
    second = _compose(research, policy, findings)

    assert first.status is CritiqueStatus.DEFER
    assert first.content_sha256 == second.content_sha256
    assert first.content_sha256 == canonical_sha256(first.payload())
    assert {item.category for item in first.findings} == set(CritiqueCategory)
    assert all(
        item.state is FindingState.GAP and item.resolution is IssueResolution.UNRESOLVED for item in first.findings
    )
    assert first.required_validations == V1_009_REQUIRED_VALIDATIONS
    assert first.hypothesis.content_sha256 == research.hypothesis.content_sha256
    assert first.evidence_synthesis.content_sha256 == research.evidence_synthesis.content_sha256
    assert first.experiment_request.content_sha256 == research.experiment_request.content_sha256


def test_missing_or_caller_supplied_diagnostics_cannot_escape_fixed_defer() -> None:
    research = _research()
    high_gap = _diagnostics(
        research,
        category=CritiqueCategory.DATA_LEAKAGE,
        state=FindingState.UNKNOWN,
        severity=IssueSeverity.HIGH,
        resolution=IssueResolution.UNRESOLVED,
    )
    deferred = _compose(research, _policy(), high_gap)
    assert deferred.status is CritiqueStatus.DEFER
    with pytest.raises(ValueError, match="fixed closed diagnostic validation"):
        _compose(research, _policy(), high_gap, validations=("caller says resolved",))


def test_v1_009_rejects_unimplemented_diagnostics_and_caller_verdict_override() -> None:
    research = _research()
    critique = _compose(research, _policy(), ())
    with pytest.raises(ValueError, match="fixed diagnostic gaps|deterministic gate"):
        replace(
            critique,
            status=CritiqueStatus.PASS,
            content_sha256=canonical_sha256({**critique.payload(), "status": "PASS"}),
        )


def test_missing_evidence_stays_gap_or_unknown_and_cannot_be_fabricated() -> None:
    research = _research()
    with pytest.raises(ValueError, match="cannot claim evidence"):
        CritiqueFinding(
            CritiqueCategory.PARAMETER_STABILITY,
            FindingState.GAP,
            IssueSeverity.HIGH,
            IssueResolution.UNRESOLVED,
            "No stability diagnostic was supplied.",
            (research.hypothesis.content_sha256,),
        )
    with pytest.raises(ValueError, match="explicit evidence"):
        CritiqueFinding(
            CritiqueCategory.HISTORICAL_FAILURE,
            FindingState.CLEAR,
            IssueSeverity.INFO,
            IssueResolution.RESOLVED,
            "No historical failure found.",
            (),
        )
    with pytest.raises(ValueError, match="only reference"):
        ArtifactRef(
            EntityId.new("critique"),
            ArtifactKind.HYPOTHESIS,
            CATALOG_VERSION,
            "sha256:" + "a" * 64,
            _at(2),
            _at(1),
        )


def test_critique_rejects_future_inconsistent_mutable_and_authority_shaped_inputs() -> None:
    research = _research()
    findings = _diagnostics(research)
    with pytest.raises(ValueError, match="PIT-valid source snapshots"):
        CritiqueComposer().compose(
            _policy(),
            research.hypothesis,
            research.evidence_synthesis,
            research.experiment_request,
            _at(0),
            _at(45),
            1,
            findings,
            V1_009_REQUIRED_VALIDATIONS,
        )
    with pytest.raises(TypeError, match="exact V1 research artifacts"):
        CritiqueComposer().compose(
            _policy(),
            research.hypothesis,
            research.evidence_synthesis,
            object(),  # type: ignore[arg-type]
            _at(10),
            _at(45),
            1,
            findings,
            V1_009_REQUIRED_VALIDATIONS,
        )
    with pytest.raises(TypeError, match="immutable typed diagnostics"):
        CritiqueComposer().compose(
            _policy(),
            research.hypothesis,
            research.evidence_synthesis,
            research.experiment_request,
            _at(10),
            _at(45),
            1,
            list(findings),  # type: ignore[arg-type]
            (),
        )
    with pytest.raises(ValueError, match="PIT-valid source snapshots"):
        _compose(research, _policy(), findings, True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="iteration limit"):
        _compose(research, _policy(), findings, 2)


def test_critic_adapter_binds_exact_sources_and_has_no_authority_or_tool_surface() -> None:
    research = _research()
    critique = _compose(research, _policy(), _diagnostics(research))
    refs = _refs(critique)
    task = _task(refs, critique.expires_at)
    result = PreTradeCriticAgent().package(task, _sources(refs), critique, EntityId.new("agent_run"))

    assert result.status is CritiqueStatus.DEFER
    assert result.artifact.ref.artifact_kind is ArtifactKind.CRITIQUE
    assert result.artifact.ref.content_hash == "sha256:" + critique.content_sha256
    assert result.artifact.source_refs == refs
    assert result.unresolved_categories == tuple(sorted(category.value for category in CritiqueCategory))

    with pytest.raises(ValueError, match="shared Research run"):
        CriticTaskSources(
            (
                replace(_sources(refs).artifacts[0], producer_run_id=EntityId.new("agent_run")),
                *_sources(refs).artifacts[1:],
            )
        )
    with pytest.raises(ValueError, match="lineage"):
        forged = replace(refs[0], content_hash="sha256:" + "f" * 64)
        PreTradeCriticAgent().package(
            _task((forged, *refs[1:]), critique.expires_at),
            _sources((forged, *refs[1:])),
            critique,
            EntityId.new("agent_run"),
        )
    object.__setattr__(critique.hypothesis_snapshot, "statement", "tampered after composition")
    with pytest.raises(ValueError, match="complete verified source snapshots"):
        PreTradeCriticAgent().package(task, _sources(refs), critique, EntityId.new("agent_run"))
    with pytest.raises(ValueError, match="tool"):
        validate_task_envelope(replace(task, allowed_tools=("backtest",)))

    role = definition_for(AgentRoleId.PRE_TRADE_CRITIC.value, SchemaVersion(1, 4))
    assert role.input_kinds == (
        ArtifactKind.HYPOTHESIS,
        ArtifactKind.EVIDENCE_SYNTHESIS,
        ArtifactKind.EXPERIMENT_REQUEST,
    )
    assert role.output_kinds == (ArtifactKind.CRITIQUE,)
    assert role.declared_tools == ()
    assert all(
        definition.permission_tier <= ToolPermissionTier.RESEARCH_REQUEST
        for definition in TOOL_REGISTRY.definitions
        if definition.ref.tool_id in {"historical_data", "backtest", "cost_analysis", "parameter_stability"}
    )

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "futures_agent_os"
        / "agent_orchestration"
        / "pre_trade_critic_agent.py"
    )
    text = source.read_text(encoding="utf-8")
    for forbidden in (
        "futures_agent_os.decision",
        "portfolio_risk",
        "execution_simulation",
        "accounting_settlement",
        "TradePlan",
        "StrategyCandidate",
        "RiskDecision",
        "Order",
        "LedgerEntry",
    ):
        assert forbidden not in text


def test_catalog_1_3_replay_is_not_reinterpreted_by_research_critic_upgrade() -> None:
    legacy = definition_for(AgentRoleId.PRE_TRADE_CRITIC.value, type(CATALOG_VERSION)(1, 3))
    current = definition_for(AgentRoleId.PRE_TRADE_CRITIC.value)
    assert legacy.input_kinds == (ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.EVIDENCE_SYNTHESIS)
    assert legacy.declared_tools == ("backtest", "cost_analysis", "parameter_stability", "historical_data")
    assert current.input_kinds != legacy.input_kinds
    assert current.declared_tools == ()


def test_critique_revisions_are_episode_policy_scoped_monotonic_and_exact_retry_idempotent() -> None:
    research, store, policy = _research(), CritiqueRevisionStore(), _policy(2)
    episode = EntityId.new("decision_episode")
    first = store.reserve(episode, research.hypothesis.content_sha256, policy, "1" * 64)
    assert first.iteration == 1
    assert store.reserve(episode, research.hypothesis.content_sha256, policy, "1" * 64) == first
    with pytest.raises(ValueError, match="reserved hypothesis"):
        store.reserve(episode, "b" * 64, policy, "1" * 64)
    with pytest.raises(ValueError, match="completion hypothesis"):
        store.require(episode, "b" * 64, policy, "1" * 64)
    with pytest.raises(ValueError, match="iteration limit"):
        store.reserve(episode, "2" * 64, policy, "2" * 64)
