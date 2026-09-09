from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.agent_orchestration import (
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    CATALOG_VERSION,
    V3_CATALOG_VERSION,
    CriticCategory,
    CriticCheck,
    CriticFindingStatus,
    CriticSeverity,
    CriticVerdict,
    PlanCriticResult,
    PlanCriticTaskSources,
    PreTradeCritic,
    TriggerSource,
    definition_for,
)
from futures_agent_os.learning_review import Reflection, TradeReview
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext


def _ref(kind: ArtifactKind, namespace: str, digit: str, now: RecordedAt) -> ArtifactRef:
    return ArtifactRef(EntityId.new(namespace), kind, SchemaVersion(1, 0), "sha256:" + digit * 64, now, now)


def _fixture():
    now = RecordedAt.from_datetime(datetime(2026, 9, 8, tzinfo=UTC))
    sources = PlanCriticTaskSources(
        _ref(ArtifactKind.TRADE_PLAN_DRAFT, "artifact", "1", now),
        _ref(ArtifactKind.EVIDENCE_SYNTHESIS, "evidence_synthesis", "2", now),
        _ref(ArtifactKind.MARKET_STATE_ASSESSMENT, "market_state_assessment", "3", now),
        _ref(ArtifactKind.COST_ANALYSIS, "cost_analysis", "4", now),
        _ref(ArtifactKind.LEAKAGE_ASSESSMENT, "leakage_assessment", "5", now),
        _ref(ArtifactKind.RISK_REWARD_ANALYSIS, "risk_reward_analysis", "6", now),
        _ref(ArtifactKind.HISTORICAL_FAILURES, "historical_failures", "7", now),
    )
    evidence_by_category = {
        CriticCategory.THESIS: str(sources.proposal.artifact_id),
        CriticCategory.COUNTER_EVIDENCE: sources.evidence_synthesis.content_hash,
        CriticCategory.DATA_LEAKAGE: sources.leakage_assessment.content_hash,
        CriticCategory.COST_COVERAGE: str(sources.cost_analysis.artifact_id),
        CriticCategory.REGIME_FIT: sources.regime.content_hash,
        CriticCategory.RISK_REWARD: str(sources.risk_reward_analysis.artifact_id),
        CriticCategory.HISTORICAL_FAILURE: sources.historical_failures.content_hash,
    }
    checks = tuple(
        CriticCheck(
            category,
            CriticFindingStatus.PASS,
            CriticSeverity.LOW,
            f"{category.value} passed deterministic diagnostic",
            (evidence_by_category[category],),
        )
        for category in CriticCategory
    )
    correlation_id = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        "pre_trade_critic",
        V3_CATALOG_VERSION,
        "challenge a strategy proposal",
        "return a complete V3 pre-trade critique",
        (TriggerSource.MARKET,),
        sources.artifacts,
        (),
        ("historical_query", "cost_analysis", "stress_test", "parameter_stability"),
        definition_for("pre_trade_critic", V3_CATALOG_VERSION).budget,
        (ArtifactKind.PRE_TRADE_CRITIQUE,),
        now,
        RecordedAt.from_datetime(now.value + timedelta(minutes=2)),
    )
    critique = PreTradeCritic().review(
        sources=sources,
        checks=checks,
        verdict=CriticVerdict.PASS,
        evidence=tuple(evidence_by_category.values()),
        counter_evidence=(sources.evidence_synthesis.content_hash,),
        confidence=Decimal("0.80"),
        warnings=("Risk Engine remains independent",),
    )
    return task, sources, critique


def test_plan_critic_checks_every_required_dimension_and_packages_pass():
    task, sources, critique = _fixture()
    result = PreTradeCritic().package(task, sources, critique)
    assert {check.category for check in critique.checks} == set(CriticCategory)
    assert result.can_advance
    assert result.source_refs == sources.artifacts
    assert result.as_of == task.as_of and result.expires_at == task.expires_at


def test_blocker_cannot_pass_and_rejected_version_cannot_advance():
    task, sources, critique = _fixture()
    blocker = replace(
        critique.checks[2],
        status=CriticFindingStatus.BLOCKER,
        severity=CriticSeverity.CRITICAL,
        required_validation=("rebuild leakage-safe split",),
    )
    checks = (*critique.checks[:2], blocker, *critique.checks[3:])
    with pytest.raises(ValueError, match="PASS requires"):
        replace(critique, checks=checks)
    rejected = replace(critique, checks=checks, verdict=CriticVerdict.REJECT)
    result = PreTradeCritic().package(task, sources, rejected)
    assert not result.can_advance


def test_reject_requires_blocker_and_nonpass_check_requires_validation():
    _, _, critique = _fixture()
    with pytest.raises(ValueError, match="blocking"):
        replace(critique, verdict=CriticVerdict.REJECT)
    with pytest.raises(ValueError, match="follow-up"):
        replace(critique.checks[0], status=CriticFindingStatus.CONCERN)


def test_mandatory_categories_cannot_be_missing_duplicated_or_retyped():
    _, _, critique = _fixture()
    with pytest.raises(ValueError, match="each mandatory"):
        replace(critique, checks=critique.checks[:-1])
    with pytest.raises(ValueError, match="each mandatory"):
        replace(critique, checks=(*critique.checks[:-1], critique.checks[0]))
    with pytest.raises(TypeError, match="typed"):
        replace(critique.checks[0], category="THESIS")


def test_v3_plan_critic_catalog_does_not_reinterpret_v1_research_critic():
    v1 = definition_for("pre_trade_critic", CATALOG_VERSION)
    v3 = definition_for("pre_trade_critic", V3_CATALOG_VERSION)
    assert v1.output_kinds == (ArtifactKind.CRITIQUE,)
    assert ArtifactKind.RESEARCH_DIAGNOSTIC in v1.input_kinds
    assert v3.output_kinds == (ArtifactKind.PRE_TRADE_CRITIQUE,)
    assert ArtifactKind.TRADE_PLAN_DRAFT in v3.input_kinds
    assert v1.version != v3.version


def test_pre_trade_and_post_trade_roles_states_and_schemas_are_distinct():
    _, _, critique = _fixture()
    critic_fields = {item.name for item in fields(type(critique))}
    trade_review_fields = {item.name for item in fields(TradeReview)}
    reflection_fields = {item.name for item in fields(Reflection)}
    assert "checks" in critic_fields and "verdict" in critic_fields and "proposal_ref" in critic_fields
    assert "episode_id" not in critic_fields
    assert {"process_quality", "outcome_quality", "execution_quality"}.issubset(trade_review_fields)
    assert "lesson_candidate" in reflection_fields
    assert not critic_fields == trade_review_fields == reflection_fields
    assert (
        definition_for("pre_trade_critic", V3_CATALOG_VERSION).role_id.value
        != definition_for("post_trade_reviewer", V3_CATALOG_VERSION).role_id.value
    )


def test_critic_cannot_rewrite_proposal_or_emit_risk_order_review_truth():
    task, sources, critique = _fixture()
    other = replace(sources.proposal, artifact_id=EntityId.new("artifact"))
    with pytest.raises(ValueError, match="rewrite"):
        PreTradeCritic().package(task, sources, replace(critique, proposal_ref=other))
    for forbidden in (
        "trade_plan",
        "order",
        "risk_decision",
        "episode_id",
        "process_quality",
        "outcome_quality",
        "reflection",
    ):
        assert not hasattr(critique, forbidden)


def test_package_rejects_v1_catalog_wrong_role_tool_and_output():
    task, sources, critique = _fixture()
    with pytest.raises(ValueError, match="Catalog 1.6"):
        PreTradeCritic().package(replace(task, catalog_version=CATALOG_VERSION), sources, critique)
    with pytest.raises(ValueError):
        PreTradeCritic().package(replace(task, assigned_role_id="post_trade_reviewer"), sources, critique)
    with pytest.raises(ValueError, match="tool"):
        PreTradeCritic().package(replace(task, allowed_tools=("submit_trade_plan",)), sources, critique)
    with pytest.raises(ValueError, match="output"):
        PreTradeCritic().package(replace(task, required_outputs=(ArtifactKind.TRADE_REVIEW,)), sources, critique)


def test_sources_and_result_fail_closed_on_future_or_mixed_pit_data():
    task, sources, critique = _fixture()
    future = replace(sources.cost_analysis, created_at=task.expires_at)
    future_sources = replace(sources, cost_analysis=future)
    future_checks = tuple(
        replace(check, evidence_refs=(future.content_hash,))
        if check.category is CriticCategory.COST_COVERAGE
        else check
        for check in critique.checks
    )
    future_critique = replace(
        critique,
        checks=future_checks,
        evidence=tuple(
            future.content_hash if ref == str(sources.cost_analysis.artifact_id) else ref for ref in critique.evidence
        ),
    )
    with pytest.raises(ValueError, match="unavailable"):
        PreTradeCritic().package(
            replace(task, input_artifacts=future_sources.artifacts), future_sources, future_critique
        )
    mixed = replace(sources.regime, as_of=task.expires_at, created_at=task.expires_at)
    with pytest.raises(ValueError, match="point-in-time"):
        replace(sources, regime=mixed)


def test_all_inputs_must_be_cited_and_invented_evidence_fails():
    task, sources, critique = _fixture()
    with pytest.raises(ValueError, match="bind"):
        PreTradeCritic().package(task, sources, replace(critique, evidence=("invented",)))
    checks = tuple(replace(check, evidence_refs=(str(sources.proposal.artifact_id),)) for check in critique.checks)
    incomplete = replace(
        critique,
        checks=checks,
        evidence=(str(sources.proposal.artifact_id),),
        counter_evidence=(str(sources.proposal.artifact_id),),
    )
    with pytest.raises(ValueError, match="cite every"):
        PreTradeCritic().package(task, sources, incomplete)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), Decimal("1.1"), 0.5])
def test_confidence_is_bounded_finite_decimal(bad):
    _, _, critique = _fixture()
    with pytest.raises(ValueError, match="confidence"):
        replace(critique, confidence=bad)


def test_iteration_is_hard_bounded_and_result_construction_revalidates_lineage():
    task, sources, critique = _fixture()
    with pytest.raises(ValueError, match="one bounded"):
        replace(critique, iteration=2)
    with pytest.raises(ValueError, match="bind"):
        PlanCriticResult(
            replace(critique, counter_evidence=("invented",)),
            sources.artifacts,
            task.as_of,
            task.expires_at,
        )
