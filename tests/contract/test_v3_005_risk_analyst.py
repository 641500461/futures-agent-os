from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.agent_orchestration import (
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    CATALOG_VERSION,
    RiskAdvisory,
    RiskAnalystAgent,
    RiskAnalystResult,
    RiskPreflightDisposition,
    RiskScenario,
    RiskSeverity,
    RiskTaskSources,
    TriggerSource,
    definition_for,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext


def _ref(kind: ArtifactKind, namespace: str, digit: str, now: RecordedAt) -> ArtifactRef:
    return ArtifactRef(EntityId.new(namespace), kind, SchemaVersion(1, 0), "sha256:" + digit * 64, now, now)


def _fixture(preflight: RiskPreflightDisposition = RiskPreflightDisposition.MODIFY):
    now = RecordedAt.from_datetime(datetime(2026, 9, 8, tzinfo=UTC))
    sources = RiskTaskSources(
        _ref(ArtifactKind.TRADE_PLAN_DRAFT, "artifact", "1", now),
        _ref(ArtifactKind.PORTFOLIO_PROPOSAL, "portfolio_proposal", "2", now),
        _ref(ArtifactKind.MARKET_STATE_ASSESSMENT, "market_state_assessment", "3", now),
        _ref(ArtifactKind.RISK_PREFLIGHT, "risk_preflight", "4", now),
        (_ref(ArtifactKind.STRESS_TEST_RESULT, "stress_test_result", "5", now),),
        preflight,
    )
    correlation_id = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        "risk_analyst",
        CATALOG_VERSION,
        "explain tail risks",
        "produce non-authoritative risk assessment",
        (TriggerSource.MARKET,),
        sources.artifacts,
        (),
        ("risk_check", "stress_test", "scenario_replay"),
        definition_for("risk_analyst").budget,
        (ArtifactKind.RISK_ASSESSMENT,),
        now,
        RecordedAt.from_datetime(now.value + timedelta(minutes=2)),
    )
    assessment = RiskAnalystAgent().assess(
        sources=sources,
        main_risks=("correlation convergence", "limit-lock liquidity"),
        scenarios=(
            RiskScenario(
                "limit lock",
                "protective exit cannot fill during a one-sided limit market",
                RiskSeverity.CRITICAL,
                sources.stress_results[0].content_hash,
            ),
        ),
        mitigations=("reduce proposed exposure", "defer near delivery"),
        unknowns=("overnight gap distribution",),
        evidence=(
            str(sources.trade_plan.artifact_id),
            sources.portfolio_proposal.content_hash,
            str(sources.regime.artifact_id),
        ),
        counter_evidence=(sources.risk_preflight.content_hash,),
        confidence=Decimal("0.70"),
        advisory=(
            RiskAdvisory.REDUCE_EXPOSURE
            if preflight in {RiskPreflightDisposition.PASS, RiskPreflightDisposition.MODIFY}
            else RiskAdvisory.DEFER
        ),
        warnings=("Risk Engine remains authoritative",),
    )
    return task, sources, assessment


def test_risk_analyst_packages_complete_non_authoritative_assessment():
    task, sources, assessment = _fixture()
    result = RiskAnalystAgent().package(task, sources, assessment)
    assert result.assessment.scenarios[0].severity is RiskSeverity.CRITICAL
    assert result.assessment.counter_evidence == (sources.risk_preflight.content_hash,)
    assert result.assessment.observed_preflight is RiskPreflightDisposition.MODIFY
    assert result.source_refs == sources.artifacts
    assert result.as_of == task.as_of and result.expires_at == task.expires_at


def test_risk_assessment_has_no_formal_risk_or_kill_switch_authority():
    _, _, assessment = _fixture()
    assert "APPROVE" not in {item.value for item in RiskAdvisory}
    for forbidden in ("risk_decision", "permit", "approve", "kill_switch", "release_kill_switch", "order"):
        assert not hasattr(assessment, forbidden)


@pytest.mark.parametrize(
    "preflight",
    [RiskPreflightDisposition.REJECT, RiskPreflightDisposition.PROTECT_ONLY, RiskPreflightDisposition.HALT],
)
def test_risk_advice_cannot_soften_hard_preflight(preflight):
    task, sources, assessment = _fixture(preflight)
    with pytest.raises(ValueError, match="soften"):
        replace(assessment, advisory=RiskAdvisory.CONTINUE_REVIEW)
    rejected = replace(assessment, advisory=RiskAdvisory.REJECT_PROPOSAL)
    assert RiskAnalystAgent().package(task, sources, rejected).assessment is rejected


def test_package_rejects_preflight_rewrite():
    task, sources, assessment = _fixture()
    with pytest.raises(ValueError, match="replace"):
        RiskAnalystAgent().package(
            task,
            sources,
            replace(assessment, observed_preflight=RiskPreflightDisposition.PASS),
        )


def test_risk_sources_require_plan_portfolio_regime_preflight_and_stress():
    _, sources, _ = _fixture()
    with pytest.raises(ValueError, match="stress"):
        replace(sources, stress_results=())
    with pytest.raises(ValueError, match="exact"):
        replace(sources, risk_preflight=sources.regime)
    with pytest.raises(TypeError, match="typed"):
        replace(sources, preflight_disposition="REJECT")


def test_risk_sources_and_result_fail_closed_on_future_or_mixed_pit_data():
    task, sources, assessment = _fixture()
    future = replace(sources.stress_results[0], created_at=task.expires_at)
    future_sources = replace(sources, stress_results=(future,))
    future_assessment = replace(
        assessment,
        scenarios=(replace(assessment.scenarios[0], evidence_ref=future.content_hash),),
    )
    with pytest.raises(ValueError, match="unavailable"):
        RiskAnalystAgent().package(
            replace(task, input_artifacts=future_sources.artifacts), future_sources, future_assessment
        )
    mixed = replace(sources.stress_results[0], as_of=task.expires_at, created_at=task.expires_at)
    with pytest.raises(ValueError, match="point-in-time"):
        replace(sources, stress_results=(mixed,))


def test_every_risk_input_must_be_cited_and_invented_evidence_is_rejected():
    task, sources, assessment = _fixture()
    with pytest.raises(ValueError, match="bind"):
        RiskAnalystAgent().package(task, sources, replace(assessment, evidence=("invented",)))
    incomplete = replace(
        assessment,
        evidence=(str(sources.trade_plan.artifact_id),),
        counter_evidence=(sources.risk_preflight.content_hash,),
    )
    with pytest.raises(ValueError, match="cite every"):
        RiskAnalystAgent().package(task, sources, incomplete)


def test_task_boundary_rejects_wrong_role_tool_and_output():
    task, sources, assessment = _fixture()
    with pytest.raises(ValueError):
        RiskAnalystAgent().package(replace(task, assigned_role_id="portfolio"), sources, assessment)
    with pytest.raises(ValueError, match="tool"):
        RiskAnalystAgent().package(replace(task, allowed_tools=("issue_risk_decision",)), sources, assessment)
    with pytest.raises(ValueError, match="output"):
        RiskAnalystAgent().package(
            replace(task, required_outputs=(ArtifactKind.PORTFOLIO_PROPOSAL,)), sources, assessment
        )


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), Decimal("1.1"), 0.5])
def test_confidence_is_bounded_finite_decimal(bad):
    _, _, assessment = _fixture()
    with pytest.raises(ValueError, match="confidence"):
        replace(assessment, confidence=bad)


def test_risk_assessment_requires_scenarios_counter_evidence_mitigation_and_unknowns():
    _, _, assessment = _fixture()
    for field in ("scenarios", "counter_evidence", "mitigations", "unknowns", "main_risks"):
        with pytest.raises(ValueError):
            replace(assessment, **{field: ()})


def test_direct_result_construction_cannot_bypass_lineage_validation():
    task, sources, assessment = _fixture()
    with pytest.raises(ValueError, match="bind"):
        RiskAnalystResult(
            replace(assessment, counter_evidence=("invented",)),
            sources.artifacts,
            task.as_of,
            task.expires_at,
        )
