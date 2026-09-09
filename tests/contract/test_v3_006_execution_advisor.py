from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.agent_orchestration import (
    AgentTaskEnvelope,
    ArtifactKind,
    ArtifactRef,
    CATALOG_VERSION,
    ExecutionAdvisor,
    ExecutionAdvisorResult,
    ExecutionAlgorithmActivation,
    ExecutionSimulationEstimate,
    ExecutionTaskSources,
    ExecutionUrgency,
    RiskPreflightDisposition,
    SimulationFidelity,
    TriggerSource,
    definition_for,
)
from futures_agent_os.execution_simulation import FillOrderType
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion, TraceContext


class _Verifier:
    def __init__(
        self,
        active: tuple[FillOrderType, ...] = (
            FillOrderType.MARKET,
            FillOrderType.LIMIT,
            FillOrderType.STOP,
        ),
        *,
        simulations_valid: bool = True,
    ) -> None:
        self.active = active
        self.simulations_valid = simulations_valid

    def active_algorithms(self, reference, *, as_of):
        return self.active

    def verify_simulation(self, estimate, *, as_of):
        return self.simulations_valid


def _advisor(
    active: tuple[FillOrderType, ...] = (FillOrderType.MARKET, FillOrderType.LIMIT, FillOrderType.STOP),
    *,
    simulations_valid: bool = True,
) -> ExecutionAdvisor:
    return ExecutionAdvisor(_Verifier(active, simulations_valid=simulations_valid))


def _ref(kind: ArtifactKind, namespace: str, digit: str, now: RecordedAt) -> ArtifactRef:
    return ArtifactRef(EntityId.new(namespace), kind, SchemaVersion(1, 0), "sha256:" + digit * 64, now, now)


def _fixture():
    now = RecordedAt.from_datetime(datetime(2026, 9, 8, tzinfo=UTC))
    activation = ExecutionAlgorithmActivation(
        _ref(ArtifactKind.EXECUTION_ALGORITHM_ACTIVATION, "execution_algorithm_activation", "1", now),
        (FillOrderType.MARKET, FillOrderType.LIMIT, FillOrderType.STOP),
    )
    simulations = tuple(
        ExecutionSimulationEstimate(algorithm, cost, probability, SimulationFidelity.L2_EVENT, ref)
        for algorithm, cost, probability, ref in (
            (
                FillOrderType.MARKET,
                Decimal("12"),
                Decimal("0.98"),
                _ref(ArtifactKind.EXECUTION_SIMULATION_RESULT, "execution_simulation_result", "2", now),
            ),
            (
                FillOrderType.LIMIT,
                Decimal("5"),
                Decimal("0.65"),
                _ref(ArtifactKind.EXECUTION_SIMULATION_RESULT, "execution_simulation_result", "3", now),
            ),
            (
                FillOrderType.STOP,
                Decimal("15"),
                Decimal("0.80"),
                _ref(ArtifactKind.EXECUTION_SIMULATION_RESULT, "execution_simulation_result", "4", now),
            ),
        )
    )
    sources = ExecutionTaskSources(
        _ref(ArtifactKind.TRADE_PLAN_DRAFT, "artifact", "5", now),
        _ref(ArtifactKind.PORTFOLIO_PROPOSAL, "portfolio_proposal", "6", now),
        _ref(ArtifactKind.RISK_ASSESSMENT, "risk_assessment", "7", now),
        _ref(ArtifactKind.RISK_PREFLIGHT, "risk_preflight", "8", now),
        RiskPreflightDisposition.MODIFY,
        activation,
        _ref(ArtifactKind.LIQUIDITY_PROFILE, "liquidity_profile", "9", now),
        _ref(ArtifactKind.COST_ANALYSIS, "cost_analysis", "a", now),
        simulations,
    )
    correlation_id = EntityId.new("correlation")
    task = AgentTaskEnvelope(
        EntityId.new("agent_task"),
        EntityId.new("session"),
        correlation_id,
        TraceContext(correlation_id, EntityId.new("trace")),
        "execution_advisor",
        CATALOG_VERSION,
        "compare active execution intents",
        "produce one proposal-only execution recommendation",
        (TriggerSource.MARKET,),
        sources.artifacts,
        (),
        ("execution_simulator", "cost_analysis", "liquidity_profile"),
        definition_for("execution_advisor").budget,
        (ArtifactKind.EXECUTION_RECOMMENDATION,),
        now,
        RecordedAt.from_datetime(now.value + timedelta(minutes=2)),
    )
    recommendation = _advisor().recommend(
        sources=sources,
        algorithm=FillOrderType.LIMIT,
        urgency=ExecutionUrgency.NORMAL,
        rationale="lower simulated cost while fill probability remains acceptable",
        cancel_conditions=("liquidity profile expires", "risk preflight changes"),
        evidence=(
            str(sources.trade_plan.artifact_id),
            sources.portfolio_proposal.content_hash,
            str(sources.risk_assessment.artifact_id),
            sources.risk_preflight.content_hash,
            str(sources.activation.source_ref.artifact_id),
            sources.liquidity_profile.content_hash,
            str(sources.cost_analysis.artifact_id),
        ),
        counter_evidence=(sources.simulations[0].source_ref.content_hash,),
        unknowns=("queue position unavailable at L2 event fidelity",),
        warnings=("deterministic Execution Planner remains authoritative",),
        confidence=Decimal("0.72"),
    )
    return task, sources, recommendation


def test_execution_advisor_compares_all_active_v2_algorithms_and_packages_recommendation():
    task, sources, recommendation = _fixture()
    result = _advisor().package(task, sources, recommendation)
    assert tuple(item.algorithm for item in recommendation.comparisons) == (
        FillOrderType.MARKET,
        FillOrderType.LIMIT,
        FillOrderType.STOP,
    )
    assert result.source_refs == sources.artifacts
    assert result.as_of == task.as_of and result.expires_at == task.expires_at


def test_execution_output_is_recommendation_only_without_order_or_risk_mutation():
    _, _, recommendation = _fixture()
    for forbidden in (
        "order",
        "order_id",
        "quantity",
        "target_exposure",
        "max_loss",
        "risk_decision",
        "submit",
    ):
        assert not hasattr(recommendation, forbidden)


@pytest.mark.parametrize("advanced", ["TWAP", "VWAP", "ICEBERG", "BATCHED"])
def test_advanced_v5_algorithms_cannot_be_activated_or_recommended(advanced):
    _, sources, _ = _fixture()
    with pytest.raises(ValueError):
        FillOrderType(advanced)
    with pytest.raises(ValueError, match="active implemented"):
        _advisor().recommend(
            sources=sources,
            algorithm=advanced,
            urgency=ExecutionUrgency.NORMAL,
            rationale="unsupported",
            cancel_conditions=("cancel",),
            evidence=(str(sources.trade_plan.artifact_id),),
            counter_evidence=(sources.risk_preflight.content_hash,),
            confidence=Decimal("0.5"),
        )


def test_inactive_implemented_algorithm_cannot_be_selected():
    _, sources, _ = _fixture()
    activation = replace(sources.activation, active_algorithms=(FillOrderType.MARKET, FillOrderType.LIMIT))
    inactive_sources = replace(sources, activation=activation, simulations=sources.simulations[:2])
    with pytest.raises(ValueError, match="active implemented"):
        _advisor((FillOrderType.MARKET, FillOrderType.LIMIT)).recommend(
            sources=inactive_sources,
            algorithm=FillOrderType.STOP,
            urgency=ExecutionUrgency.NORMAL,
            rationale="inactive",
            cancel_conditions=("cancel",),
            evidence=(str(inactive_sources.trade_plan.artifact_id),),
            counter_evidence=(inactive_sources.risk_preflight.content_hash,),
            confidence=Decimal("0.5"),
        )


def test_activation_and_simulation_coverage_are_exact():
    _, sources, _ = _fixture()
    with pytest.raises(ValueError, match="at least two"):
        replace(sources.activation, active_algorithms=(FillOrderType.MARKET,))
    with pytest.raises(ValueError, match="exactly cover"):
        replace(sources, simulations=sources.simulations[:-1])
    with pytest.raises(ValueError, match="exactly cover"):
        replace(sources, simulations=tuple(reversed(sources.simulations)))


def test_owner_verifier_rejects_self_declared_activation_or_unverified_simulation():
    _, sources, _ = _fixture()
    with pytest.raises(ValueError, match="owner state"):
        _advisor((FillOrderType.MARKET, FillOrderType.LIMIT)).recommend(
            sources=sources,
            algorithm=FillOrderType.LIMIT,
            urgency=ExecutionUrgency.NORMAL,
            rationale="caller-declared activation",
            cancel_conditions=("cancel",),
            evidence=(str(sources.trade_plan.artifact_id),),
            counter_evidence=(sources.risk_preflight.content_hash,),
            confidence=Decimal("0.5"),
        )
    with pytest.raises(ValueError, match="deterministic owner"):
        _advisor(simulations_valid=False).recommend(
            sources=sources,
            algorithm=FillOrderType.LIMIT,
            urgency=ExecutionUrgency.NORMAL,
            rationale="unverified simulation",
            cancel_conditions=("cancel",),
            evidence=(str(sources.trade_plan.artifact_id),),
            counter_evidence=(sources.risk_preflight.content_hash,),
            confidence=Decimal("0.5"),
        )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("estimated_cost", Decimal("NaN")),
        ("estimated_cost", Decimal("Infinity")),
        ("estimated_cost", Decimal("-1")),
        ("estimated_cost", 1.0),
        ("fill_probability", Decimal("NaN")),
        ("fill_probability", Decimal("-0.1")),
        ("fill_probability", Decimal("1.1")),
        ("fill_probability", 0.5),
    ],
)
def test_simulation_numbers_are_finite_bounded_decimals(field, bad):
    _, sources, _ = _fixture()
    with pytest.raises(ValueError):
        replace(sources.simulations[0], **{field: bad})


def test_only_l1_or_l2_fidelity_can_be_claimed():
    _, sources, _ = _fixture()
    assert {item.value for item in SimulationFidelity} == {"L1_BAR", "L2_EVENT"}
    with pytest.raises(ValueError):
        SimulationFidelity("L4_ORDER_BOOK")
    assert "queue" not in sources.simulations[0].fidelity.value.lower()


@pytest.mark.parametrize(
    "hard",
    [RiskPreflightDisposition.REJECT, RiskPreflightDisposition.PROTECT_ONLY, RiskPreflightDisposition.HALT],
)
def test_execution_advice_does_not_run_after_hard_risk_preflight(hard):
    _, sources, _ = _fixture()
    with pytest.raises(ValueError, match="hard risk"):
        replace(sources, risk_preflight_disposition=hard)


def test_task_and_sources_fail_closed_on_future_or_mixed_pit_input():
    task, sources, recommendation = _fixture()
    future = replace(sources.liquidity_profile, created_at=task.expires_at)
    future_sources = replace(sources, liquidity_profile=future)
    future_recommendation = replace(
        recommendation,
        evidence=tuple(
            future.content_hash if item == sources.liquidity_profile.content_hash else item
            for item in recommendation.evidence
        ),
    )
    with pytest.raises(ValueError, match="unavailable"):
        _advisor().package(
            replace(task, input_artifacts=future_sources.artifacts), future_sources, future_recommendation
        )
    mixed = replace(sources.cost_analysis, as_of=task.expires_at, created_at=task.expires_at)
    with pytest.raises(ValueError, match="point-in-time"):
        replace(sources, cost_analysis=mixed)


def test_recommendation_cannot_replace_simulation_comparisons():
    task, sources, recommendation = _fixture()
    with pytest.raises(ValueError, match="changed"):
        _advisor().package(
            task, sources, replace(recommendation, comparisons=tuple(reversed(recommendation.comparisons)))
        )


def test_every_execution_input_must_be_cited_and_invented_evidence_fails():
    task, sources, recommendation = _fixture()
    with pytest.raises(ValueError, match="bind"):
        _advisor().package(task, sources, replace(recommendation, evidence=("invented",)))
    incomplete = replace(
        recommendation,
        evidence=(str(sources.trade_plan.artifact_id),),
        counter_evidence=(sources.simulations[0].source_ref.content_hash,),
    )
    with pytest.raises(ValueError, match="cite every"):
        _advisor().package(task, sources, incomplete)


def test_task_boundary_rejects_wrong_role_tool_and_output():
    task, sources, recommendation = _fixture()
    with pytest.raises(ValueError):
        _advisor().package(replace(task, assigned_role_id="risk_analyst"), sources, recommendation)
    with pytest.raises(ValueError, match="tool"):
        _advisor().package(replace(task, allowed_tools=("create_order",)), sources, recommendation)
    with pytest.raises(ValueError, match="output"):
        _advisor().package(replace(task, required_outputs=(ArtifactKind.RISK_ASSESSMENT,)), sources, recommendation)


def test_direct_result_construction_cannot_bypass_evidence_or_expiry():
    task, sources, recommendation = _fixture()
    with pytest.raises(ValueError, match="bind"):
        ExecutionAdvisorResult(
            replace(recommendation, counter_evidence=("invented",)),
            sources.artifacts,
            task.as_of,
            task.expires_at,
        )
    with pytest.raises(ValueError, match="expiry"):
        ExecutionAdvisorResult(recommendation, sources.artifacts, task.as_of, task.as_of)
