from dataclasses import replace
from decimal import Decimal

import pytest

from futures_agent_os.research_experiment import (
    ChangeRisk,
    EvaluationOutcome,
    EvaluationResult,
    GovernanceSteward,
    StewardEvaluationBundle,
    StewardEvaluationDimension,
    StewardRecommendation,
    StewardSubjectKind,
)
from futures_agent_os.shared_kernel import RecordedAt


def _bundle(
    kind: StewardSubjectKind = StewardSubjectKind.MODEL,
    override: tuple[StewardEvaluationDimension, EvaluationOutcome] | None = None,
) -> StewardEvaluationBundle:
    results = tuple(
        EvaluationResult(
            dimension,
            override[1] if override and override[0] is dimension else EvaluationOutcome.PASS,
            Decimal("0.8"),
            Decimal("0.9"),
            Decimal("0.75"),
            f"evaluation:{dimension.value.lower()}",
        )
        for dimension in StewardEvaluationDimension
    )
    return StewardEvaluationBundle(
        kind,
        f"{kind.value.lower()}:current:v1",
        f"{kind.value.lower()}:candidate:v2",
        ("simulation:SHFE",),
        results,
        RecordedAt.parse("2026-09-10T00:00:00Z"),
    )


@pytest.mark.parametrize("kind", tuple(StewardSubjectKind))
def test_prompt_model_strategy_proposals_require_complete_passing_evaluation(kind: StewardSubjectKind) -> None:
    steward = GovernanceSteward()
    first = steward.propose(
        _bundle(kind),
        recommendation=StewardRecommendation.ADOPT_CANDIDATE,
        risk=ChangeRisk.MEDIUM,
        rationale="all preregistered evaluation gates passed",
    )
    second = steward.propose(
        _bundle(kind),
        recommendation=StewardRecommendation.ADOPT_CANDIDATE,
        risk=ChangeRisk.MEDIUM,
        rationale="all preregistered evaluation gates passed",
    )
    assert first == second and first.proposal_id == second.proposal_id
    assert first.subject_kind is kind and len(first.evidence_refs) == len(StewardEvaluationDimension)
    assert "HUMAN_CHANGE_APPROVAL" in first.required_steps
    assert "INDEPENDENT_ACTIVATION" in first.required_steps


def test_failed_and_unknown_evaluations_only_support_matching_proposals() -> None:
    steward = GovernanceSteward()
    failed = _bundle(override=(StewardEvaluationDimension.REGRESSION, EvaluationOutcome.FAIL))
    rejected = steward.propose(
        failed,
        recommendation=StewardRecommendation.REJECT_CANDIDATE,
        risk=ChangeRisk.HIGH,
        rationale="regression failed",
    )
    assert rejected.recommendation is StewardRecommendation.REJECT_CANDIDATE
    with pytest.raises(ValueError, match="all evaluations"):
        steward.propose(
            failed,
            recommendation=StewardRecommendation.ADOPT_CANDIDATE,
            risk=ChangeRisk.LOW,
            rationale="invalid adoption",
        )
    unknown = _bundle(override=(StewardEvaluationDimension.COST_LATENCY, EvaluationOutcome.UNKNOWN))
    more = steward.propose(
        unknown,
        recommendation=StewardRecommendation.RUN_MORE_EVALUATION,
        risk=ChangeRisk.MEDIUM,
        rationale="latency remains unknown",
    )
    assert more.recommendation is StewardRecommendation.RUN_MORE_EVALUATION


def test_incomplete_duplicate_or_nonfinite_evaluation_evidence_fails_closed() -> None:
    bundle = _bundle()
    with pytest.raises(ValueError, match="every required dimension"):
        replace(bundle, results=bundle.results[:-1])
    with pytest.raises(ValueError, match="unique"):
        replace(
            bundle,
            results=(*bundle.results[:-1], replace(bundle.results[-1], evidence_ref=bundle.results[0].evidence_ref)),
        )
    with pytest.raises(ValueError, match="finite"):
        replace(bundle.results[0], candidate_value=Decimal("NaN"))


def test_steward_surface_is_read_only_and_has_no_risk_policy_target() -> None:
    steward = GovernanceSteward()
    assert {tool.value for tool in steward.allowed_tools} == {
        "proposal_search",
        "experiment_search",
        "model_registry_query",
        "audit_query",
        "deployment_evidence_query",
    }
    for forbidden in ("merge", "promote", "activate", "rollback", "modify_risk", "write_registry"):
        assert not hasattr(steward, forbidden)
    with pytest.raises(ValueError):
        StewardSubjectKind("RISK_POLICY")
    proposal = steward.propose(
        _bundle(),
        recommendation=StewardRecommendation.ADOPT_CANDIDATE,
        risk=ChangeRisk.LOW,
        rationale="proposal only",
    )
    for forbidden in ("approved", "active", "merged", "risk_policy", "activation_id"):
        assert not hasattr(proposal, forbidden)
