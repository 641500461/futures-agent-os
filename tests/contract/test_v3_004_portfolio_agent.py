from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.agent_orchestration import (
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    CATALOG_VERSION,
    ExposureDirection,
    PortfolioAgent,
    PortfolioAgentResult,
    PortfolioDisposition,
    PortfolioTaskSources,
    TargetExposure,
    TriggerSource,
    definition_for,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext


def _ref(kind: ArtifactKind, namespace: str, digit: str, now: RecordedAt) -> ArtifactRef:
    return ArtifactRef(
        EntityId.new(namespace),
        kind,
        SchemaVersion(1, 0),
        "sha256:" + digit * 64,
        now,
        now,
    )


def _fixture():
    now = RecordedAt.from_datetime(datetime(2026, 9, 8, tzinfo=UTC))
    sources = PortfolioTaskSources(
        EntityId.new("account"),
        _ref(ArtifactKind.TRADE_PLAN_DRAFT, "artifact", "1", now),
        _ref(ArtifactKind.PRE_TRADE_CRITIQUE, "pre_trade_critique", "2", now),
        _ref(ArtifactKind.PORTFOLIO_SNAPSHOT, "portfolio_snapshot", "3", now),
        _ref(ArtifactKind.STRATEGY_BUDGET, "strategy_budget", "4", now),
        (_ref(ArtifactKind.CORRELATION_ASSESSMENT, "correlation_assessment", "5", now),),
        Decimal("0.20"),
    )
    correlation_id = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        "portfolio",
        CATALOG_VERSION,
        "assess candidate in portfolio context",
        "produce proposal-only target risk exposure",
        (TriggerSource.MARKET,),
        sources.artifacts,
        (),
        ("portfolio_state", "correlation_analysis"),
        definition_for("portfolio").budget,
        (ArtifactKind.PORTFOLIO_PROPOSAL,),
        now,
        RecordedAt.from_datetime(now.value + timedelta(minutes=2)),
    )
    proposal = PortfolioAgent().propose(
        sources=sources,
        target_exposure=TargetExposure("IF", ExposureDirection.LONG, Decimal("0.10")),
        disposition=PortfolioDisposition.DOWNWEIGHT,
        rationale="correlation cluster is already concentrated",
        evidence=(
            str(sources.trade_plan.artifact_id),
            str(sources.portfolio_snapshot.artifact_id),
            sources.strategy_budget.content_hash,
            sources.correlations[0].content_hash,
        ),
        counter_evidence=(sources.critique.content_hash,),
        unknowns=("overnight correlation stability",),
        warnings=("optimizer output is advisory",),
        confidence=Decimal("0.70"),
    )
    return task, sources, proposal


def test_portfolio_agent_packages_account_budget_correlation_and_existing_exposure():
    task, sources, proposal = _fixture()
    result = PortfolioAgent().package(task, sources, proposal)
    assert result.proposal.account_id == sources.account_id
    assert result.proposal.strategy_budget_ref == sources.strategy_budget
    assert result.proposal.portfolio_snapshot_ref == sources.portfolio_snapshot
    assert result.proposal.existing_exposure == Decimal("0.20")
    assert result.proposal.correlation_refs == sources.correlations
    assert result.as_of == task.as_of and result.expires_at == task.expires_at


def test_portfolio_output_is_proposal_only_and_cannot_set_final_quantity_or_risk_truth():
    _, _, proposal = _fixture()
    for forbidden in ("quantity", "risk_decision", "reservation", "order", "position", "ledger"):
        assert not hasattr(proposal, forbidden)
        assert not hasattr(proposal.target_exposure, forbidden)


@pytest.mark.parametrize(
    ("direction", "fraction"),
    [
        (ExposureDirection.LONG, Decimal("NaN")),
        (ExposureDirection.LONG, Decimal("Infinity")),
        (ExposureDirection.LONG, Decimal("-0.1")),
        (ExposureDirection.LONG, Decimal("1.1")),
        (ExposureDirection.LONG, Decimal("0")),
        (ExposureDirection.FLAT, Decimal("0.1")),
        ("LONG", Decimal("0.1")),
        (ExposureDirection.LONG, 0.1),
    ],
)
def test_target_exposure_rejects_invalid_or_quantity_like_values(direction, fraction):
    with pytest.raises((TypeError, ValueError)):
        TargetExposure("IF", direction, fraction)


def test_reject_disposition_must_remove_target_risk():
    _, _, proposal = _fixture()
    with pytest.raises(ValueError, match="rejected"):
        replace(proposal, disposition=PortfolioDisposition.REJECT)
    rejected = replace(
        proposal,
        disposition=PortfolioDisposition.REJECT,
        target_exposure=TargetExposure("IF", ExposureDirection.FLAT, Decimal("0")),
    )
    assert rejected.disposition is PortfolioDisposition.REJECT


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), 1.0])
def test_sources_reject_nonfinite_or_float_existing_exposure(bad):
    _, sources, _ = _fixture()
    with pytest.raises(ValueError):
        replace(sources, existing_exposure=bad)


def test_sources_require_exact_complete_pit_artifacts():
    task, sources, _ = _fixture()
    with pytest.raises(ValueError, match="correlation"):
        replace(sources, correlations=())
    future = replace(sources.portfolio_snapshot, created_at=task.expires_at)
    future_sources = replace(sources, portfolio_snapshot=future)
    proposal = PortfolioAgent().propose(
        sources=future_sources,
        target_exposure=TargetExposure("IF", ExposureDirection.LONG, Decimal("0.1")),
        disposition=PortfolioDisposition.ACCEPT,
        rationale="bounded",
        evidence=(str(future.artifact_id),),
        counter_evidence=(future.content_hash,),
        confidence=Decimal("0.5"),
    )
    with pytest.raises(ValueError, match="unavailable"):
        PortfolioAgent().package(replace(task, input_artifacts=future_sources.artifacts), future_sources, proposal)


def test_package_rejects_wrong_role_tool_output_and_context_drift():
    task, sources, proposal = _fixture()
    with pytest.raises(ValueError):
        PortfolioAgent().package(replace(task, assigned_role_id="strategy"), sources, proposal)
    with pytest.raises(ValueError, match="tool"):
        PortfolioAgent().package(replace(task, allowed_tools=("position_sizing",)), sources, proposal)
    with pytest.raises(ValueError, match="output"):
        PortfolioAgent().package(replace(task, required_outputs=(ArtifactKind.RISK_ASSESSMENT,)), sources, proposal)
    with pytest.raises(ValueError, match="context"):
        PortfolioAgent().package(task, sources, replace(proposal, existing_exposure=Decimal("0.30")))


def test_result_and_package_reject_unbound_evidence():
    task, sources, proposal = _fixture()
    invented = replace(proposal, evidence=("invented",))
    with pytest.raises(ValueError, match="evidence"):
        PortfolioAgentResult(invented, sources.artifacts, task.as_of, task.expires_at)
    with pytest.raises(ValueError, match="evidence"):
        PortfolioAgent().package(task, sources, invented)
    incomplete = replace(proposal, evidence=(str(sources.trade_plan.artifact_id),))
    with pytest.raises(ValueError, match="cite every"):
        PortfolioAgent().package(task, sources, incomplete)


def test_proposal_requires_counter_evidence_and_bounded_confidence():
    _, _, proposal = _fixture()
    with pytest.raises(ValueError, match="counter evidence"):
        replace(proposal, counter_evidence=())
    for bad in (Decimal("NaN"), Decimal("-0.1"), Decimal("1.1"), 0.5):
        with pytest.raises(ValueError, match="confidence"):
            replace(proposal, confidence=bad)
