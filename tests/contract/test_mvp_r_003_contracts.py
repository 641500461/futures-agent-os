"""MVP-R-003 contracts keep the discovery loop bounded, PIT, and non-trading."""

from __future__ import annotations

from dataclasses import replace

import pytest

from futures_agent_os.research_experiment.mvp_r_003.contracts import (
    ArtifactRef,
    CriticDecision,
    CriticReview,
    ExecutableExperimentPlan,
    ExperimentResultPacket,
    FinalVerdict,
    HypothesisFamily,
    HypothesisSpec,
    HypothesisValidation,
    ResearchEpisodeInput,
    ResearchFinalVerdict,
    SignalOperator,
    ToolRunResult,
    ValidationStatus,
)
from futures_agent_os.research_experiment.mvp_r_003.hypothesis_validator import (
    HypothesisValidator,
    validate_hypothesis_batch,
)


def ref(kind: str, suffix: str) -> ArtifactRef:
    return ArtifactRef(kind, f"{kind}://{suffix}", suffix * 64)


def episode() -> ResearchEpisodeInput:
    return ResearchEpisodeInput(
        episode_id="episode-001",
        instrument="AG",
        as_of="2025-03-03T08:00:00Z",
        market_cutoff="2025-02-28T07:00:00Z",
        acquired_at="2026-08-28T04:01:01Z",
        dataset_ref=ref("dataset", "a"),
        market_snapshot_ref=ref("market-snapshot", "b"),
        feature_ref=ref("feature", "c"),
        rule_ref=ref("rule", "d"),
        cost_ref=ref("cost", "e"),
        toolset_ref=ref("toolset", "f"),
        signal_operators=(SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,),
        allowed_parameter_values=(("direction", ("FOLLOW", "INVERT")), ("threshold", ("0.005", "0.010", "0.020"))),
        market_state="TREND",
        warnings=(),
        unknowns=("intraday path unavailable",),
        evidence_refs=(ref("metric", "1"), ref("metric", "2")),
    )


def hypothesis(
    hypothesis_id: str = "hypothesis-001",
    *,
    operator: SignalOperator = SignalOperator.PRIOR_CLOSE_RETURN_THRESHOLD,
    supporting_refs: tuple[str, ...] = ("metric://1",),
    tradable: bool = False,
) -> HypothesisSpec:
    return HypothesisSpec(
        hypothesis_id=hypothesis_id,
        version=1,
        family=HypothesisFamily.MOMENTUM_CONTINUATION,
        market_condition="TREND",
        signal_operator=operator,
        parameters=(("direction", "FOLLOW"), ("threshold", "0.010")),
        expected_observable="L0 accuracy is at least the registered threshold",
        falsification_condition="L0 accuracy below 0.50000000 or stressed net mean not positive",
        supporting_evidence_refs=supporting_refs,
        strongest_counter_evidence_refs=("metric://2",),
        unknowns=("intraday path unavailable",),
        primary_metric="accuracy",
        control="inverted signal direction",
        cost_assumption_ref="cost://e",
        tradable=tradable,
    )


def validation() -> HypothesisValidation:
    return HypothesisValidator().validate(episode(), hypothesis())


def critic() -> CriticReview:
    return CriticReview(
        review_id="critic-001",
        hypothesis_id="hypothesis-001",
        decision=CriticDecision.SELECT,
        checks=(
            ("cost", "PASS"),
            ("falsifiability", "PASS"),
            ("leakage", "PASS"),
            ("multiple_testing", "PASS"),
            ("regime", "PASS"),
            ("sample", "PASS"),
        ),
        reason_codes=("CLEAN_EXECUTABLE_HYPOTHESIS",),
        source_refs=("metric://1", "metric://2"),
    )


def plan() -> ExecutableExperimentPlan:
    return ExecutableExperimentPlan(
        plan_id="plan-001",
        hypothesis_ref=hypothesis().identity,
        dataset_ref="dataset://a",
        window="all PIT-visible final daily bars",
        train_bars=20,
        test_bars=5,
        step_bars=5,
        embargo_bars=1,
        tool_requests=(
            "l0_signal_test",
            "l1_bar_backtest",
            "walk_forward_test",
            "cost_slippage_stress",
            "counterfactual_test",
        ),
        primary_metric="accuracy",
        control="inverted signal direction",
        stop_rule="stop after two failing chronological folds",
        config_ref="validation-config://v1-010",
        code_ref="git:d72afbeed54e83bb9bec4afdff9884a423cce0ac",
        tradable=False,
    )


def result_packet() -> ExperimentResultPacket:
    runs = tuple(
        ToolRunResult(
            tool=tool,
            status="SUCCESS",
            metrics=(("accuracy", "0.60000000"),) if tool == "l0_signal_test" else (("complete", "true"),),
            warnings=(),
            source_refs=("market-snapshot://b",),
        )
        for tool in plan().tool_requests
    )
    return ExperimentResultPacket(
        packet_id="packet-001",
        plan_ref=plan().identity,
        tool_runs=runs,
        limitations=("daily bars only",),
        complete=True,
        evaluator_future_data_present=False,
    )


def test_all_contracts_round_trip_with_content_hashes() -> None:
    objects = (
        episode(),
        hypothesis(),
        validation(),
        critic(),
        plan(),
        result_packet(),
        ResearchFinalVerdict(
            verdict_id="verdict-001",
            verdict=FinalVerdict.ACCEPT,
            hypothesis_ref=hypothesis().identity,
            falsification_condition=hypothesis().falsification_condition,
            result_refs=(result_packet().identity,),
            rationale="The registered threshold is met without a blocking counter-result.",
        ),
    )

    for value in objects:
        assert type(value).hydrate(value.to_dict()) == value


def test_candidate_batch_requires_two_or_three_distinct_hypotheses() -> None:
    with pytest.raises(ValueError, match="2 or 3"):
        validate_hypothesis_batch((hypothesis(),))
    with pytest.raises(ValueError, match="distinct"):
        validate_hypothesis_batch((hypothesis(), hypothesis()))
    validate_hypothesis_batch(
        (
            hypothesis(),
            replace(
                hypothesis("hypothesis-002"),
                parameters=(("direction", "INVERT"), ("threshold", "0.010")),
            ),
        )
    )


def test_future_leak_ungrounded_claim_unsupported_operator_and_trading_request_fail_closed() -> None:
    with pytest.raises(ValueError, match="future result"):
        replace(episode(), future_result_present=True)
    ungrounded = HypothesisValidator().validate(episode(), hypothesis(supporting_refs=("metric://not-in-episode",)))
    assert ungrounded.status is ValidationStatus.UNSUPPORTED
    assert "UNGROUNDED_EVIDENCE_REF" in ungrounded.reason_codes
    unsupported = HypothesisValidator().validate(episode(), hypothesis(operator=SignalOperator.VOLUME_CONFIRMATION))
    assert unsupported.status is ValidationStatus.UNSUPPORTED
    assert "UNSUPPORTED_SIGNAL_OPERATOR" in unsupported.reason_codes
    with pytest.raises(ValueError, match="non-trading"):
        hypothesis(tradable=True)


def test_modify_creates_a_new_version_without_mutating_or_reexecuting_the_original() -> None:
    original = hypothesis()
    modified = replace(
        original,
        hypothesis_id="hypothesis-001-modified",
        version=2,
        parent_hypothesis_ref=original.identity,
        parameters=(("direction", "FOLLOW"), ("threshold", "0.020")),
    )
    verdict = ResearchFinalVerdict(
        verdict_id="verdict-002",
        verdict=FinalVerdict.MODIFY,
        hypothesis_ref=original.identity,
        falsification_condition=original.falsification_condition,
        result_refs=(result_packet().identity,),
        rationale="The result supports only the narrower registered threshold.",
        modified_hypothesis=modified,
    )

    assert verdict.modified_hypothesis is not None
    assert verdict.modified_hypothesis.version == original.version + 1
    assert verdict.modified_hypothesis.parent_hypothesis_ref == original.identity
    assert verdict.auto_execute_modified is False
    assert original.version == 1
