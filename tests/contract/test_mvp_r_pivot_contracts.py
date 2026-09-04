"""Contracts for the post-iteration MVP-R multi-family Pivot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.adapters.codex_app_server import CodexAppServerProvider
from futures_agent_os.adapters.research_model_payload import (
    CONCLUSION_SCHEMA,
    PIVOT_CONCLUSION_SCHEMA,
    PIVOT_CRITIQUE_SCHEMA,
)
from futures_agent_os.reference_market_data import PointInTimeRecord
from futures_agent_os.research_experiment import (
    PIVOT_HYPOTHESIS_FAMILIES,
    HypothesisFamily,
    GroundedClaim,
    PivotCriticAuthorizationAuthority,
    PivotCriticRequest,
    PivotMachineResearchHandoff,
    PivotNextExperimentRequest,
    ResearchConclusion,
    ResearchConclusionKind,
    ResearchHandoffDecision,
    ResearchHypothesisProposal,
    critique_pivot_conclusion,
    family_screen_metrics,
    requires_independent_pivot_critic,
    screen_hypothesis_families,
    strongest_deterministic_family,
)
from futures_agent_os.shared_kernel import RecordedAt, canonical_sha256


def _records(*, false_breakout_at_cutoff: bool = False) -> tuple[PointInTimeRecord, ...]:
    started = datetime(2026, 1, 1, tzinfo=UTC)
    records = []
    for index in range(40):
        close = Decimal(100 + index)
        high = close + 1
        low = close - 1
        if false_breakout_at_cutoff and index == 39:
            close = Decimal(137)
            high = Decimal(150)
            low = Decimal(136)
        event_time = RecordedAt(started + timedelta(days=index))
        records.append(
            PointInTimeRecord(
                event_time,
                event_time,
                {
                    "instrument_id": "SHFE.CU.DOMINANT_OI",
                    "open": str(close),
                    "high": str(high),
                    "low": str(low),
                    "close": str(close),
                    "volume": 1_000 + index,
                    "open_interest": 2_000 + index,
                },
            )
        )
    return tuple(records)


def test_pivot_screens_complete_frozen_family_roster_deterministically() -> None:
    records = _records()
    first = screen_hypothesis_families(
        records,
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )
    second = screen_hypothesis_families(
        records,
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )

    assert tuple(screen.family for screen in first) == PIVOT_HYPOTHESIS_FAMILIES
    assert tuple(screen.content_sha256 for screen in first) == tuple(screen.content_sha256 for screen in second)
    assert family_screen_metrics(first) == tuple(sorted(family_screen_metrics(first)))
    momentum = next(screen for screen in first if screen.family is HypothesisFamily.MOMENTUM_CONTINUATION)
    assert momentum.cutoff_direction == 1
    assert momentum.signal_accuracy == 1
    assert momentum.positive_fold_ratio == 1
    schema_families = CONCLUSION_SCHEMA["properties"]["hypothesis"]["properties"]["family"]["enum"]
    assert tuple(schema_families) == tuple(
        family.value for family in (*PIVOT_HYPOTHESIS_FAMILIES, HypothesisFamily.NONE)
    )
    pivot_properties = PIVOT_CONCLUSION_SCHEMA["properties"]
    assert isinstance(pivot_properties, dict)
    pivot_claims = pivot_properties["claims"]
    assert isinstance(pivot_claims, dict)
    pivot_claim = pivot_claims["items"]
    assert isinstance(pivot_claim, dict)
    pivot_claim_properties = pivot_claim["properties"]
    assert isinstance(pivot_claim_properties, dict)
    assert pivot_claim_properties["numeric_value"] == {"type": "null"}
    assert pivot_claim_properties["statement"] == {
        "type": "string",
        "minLength": 1,
        "pattern": "^[^0-9]*$",
    }


def test_pivot_false_breakout_family_uses_wick_and_close_without_future_data() -> None:
    screens = screen_hypothesis_families(
        _records(false_breakout_at_cutoff=True),
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )
    reversal = next(screen for screen in screens if screen.family is HypothesisFamily.FALSE_BREAKOUT_REVERSAL)

    assert reversal.cutoff_direction == -1


def test_pivot_baseline_requires_complete_roster_and_frozen_evidence_floors() -> None:
    screens = screen_hypothesis_families(
        _records(),
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )
    selected = strongest_deterministic_family(
        screens,
        minimum_signal_count=3,
        minimum_accuracy=Decimal("0.55"),
        minimum_positive_fold_ratio=Decimal("0.50"),
    )

    assert selected is not None
    assert selected.family in PIVOT_HYPOTHESIS_FAMILIES
    with pytest.raises(ValueError, match="complete frozen family roster"):
        strongest_deterministic_family(
            screens[:-1],
            minimum_signal_count=3,
            minimum_accuracy=Decimal("0.55"),
            minimum_positive_fold_ratio=Decimal("0.50"),
        )


def test_pivot_critic_rejects_unsupported_family_or_missing_feature_evidence() -> None:
    screens = screen_hypothesis_families(
        _records(),
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )
    evidence_sha256 = canonical_sha256(family_screen_metrics(screens))
    conclusion = ResearchConclusion(
        ResearchConclusionKind.OPPORTUNITY_CANDIDATE,
        "A participation-aware continuation remains eligible for research.",
        (GroundedClaim("The family evidence remains positive.", evidence_sha256, "/metrics/0/1"),),
        (evidence_sha256,),
        (),
        ResearchHypothesisProposal(
            HypothesisFamily.MOMENTUM_CONTINUATION,
            "The established directional effect persists in a new sealed window.",
            "A negative stressed result would falsify the hypothesis.",
            "Repeat the frozen family screen on a forward window.",
        ),
    )
    accepted = critique_pivot_conclusion(
        conclusion,
        screens,
        feature_evidence_sha256=evidence_sha256,
        minimum_signal_count=3,
        minimum_accuracy=Decimal("0.55"),
        minimum_positive_fold_ratio=Decimal("0.50"),
    )
    assert accepted.accepted
    assert requires_independent_pivot_critic(conclusion, accepted)

    unsupported = replace(
        conclusion,
        hypothesis=replace(conclusion.hypothesis, family=HypothesisFamily.VOLATILITY_COMPRESSION_BREAKOUT),
    )
    rejected = critique_pivot_conclusion(
        unsupported,
        screens,
        feature_evidence_sha256=evidence_sha256,
        minimum_signal_count=3,
        minimum_accuracy=Decimal("0.55"),
        minimum_positive_fold_ratio=Decimal("0.50"),
    )
    assert not rejected.accepted
    assert not requires_independent_pivot_critic(unsupported, rejected)
    assert not critique_pivot_conclusion(
        replace(conclusion, claims=(GroundedClaim("A legacy fact.", "f" * 64, "/metrics/0/1"),)),
        screens,
        feature_evidence_sha256=evidence_sha256,
        minimum_signal_count=3,
        minimum_accuracy=Decimal("0.55"),
        minimum_positive_fold_ratio=Decimal("0.50"),
    ).accepted


def test_codex_pivot_critic_uses_independent_closed_schema_and_binds_request() -> None:
    screens = screen_hypothesis_families(
        _records(),
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )
    evidence_sha256 = canonical_sha256(family_screen_metrics(screens))
    proposal = ResearchConclusion(
        ResearchConclusionKind.OPPORTUNITY_CANDIDATE,
        "A continuation remains eligible for independent criticism.",
        (GroundedClaim("The family evidence is present.", evidence_sha256, "/metrics/0/0"),),
        (evidence_sha256,),
        (),
        ResearchHypothesisProposal(
            HypothesisFamily.MOMENTUM_CONTINUATION,
            "The established direction persists in a forward sealed window.",
            "A negative stressed result would falsify the proposal.",
            "Repeat the fixed family screen on unseen observations.",
        ),
    )
    request = PivotCriticRequest(
        "evaluation_episode_test",
        "SHFE.CU.DOMINANT_OI",
        "UP_TREND",
        proposal,
        evidence_sha256,
        tuple(screen.payload() for screen in screens),
    )
    response = {
        "response_id": "critic-turn",
        "model": "gpt-5.6-terra",
        "model_provider": "openai",
        "status": "completed",
        "usage": {
            "inputTokens": 100,
            "outputTokens": 20,
            "totalTokens": 120,
            "reasoningOutputTokens": 5,
            "cacheWriteInputTokens": 0,
        },
        "final_texts": (
            '{"decision":"ACCEPT","proposal_sha256":"'
            + request.proposal_sha256
            + '","feature_evidence_sha256":"'
            + evidence_sha256
            + '","high_severity_defects":[],"counter_hypothesis_family":"NONE",'
            '"summary":"No high severity contradiction remains."}',
        ),
        "dynamic_calls": (),
        "server_requests": (),
        "item_types": ("agentMessage",),
        "reroutes": (),
        "timed_out": False,
    }
    captured: dict[str, object] = {}

    def transport(payload: Mapping[str, object]) -> Mapping[str, object]:
        captured.update(payload)
        return response

    turn = CodexAppServerProvider(transport).respond_pivot_critic(
        request=request,
        model_id="gpt-5.6-terra",
        reasoning_effort="medium",
        instructions="Independently review the proposal against every family screen.",
        timeout_seconds=120,
    )

    assert turn.failure_code is None
    assert turn.review is not None
    assert turn.review.decision.value == "ACCEPT"
    assert captured["output_schema"] == PIVOT_CRITIQUE_SCHEMA
    assert captured["tools"] == ()

    invalid_response = {**response, "final_texts": ("{",)}
    failed_turn = CodexAppServerProvider(lambda _: invalid_response).respond_pivot_critic(
        request=request,
        model_id="gpt-5.6-terra",
        reasoning_effort="medium",
        instructions="Independently review the proposal against every family screen.",
        timeout_seconds=120,
    )
    assert failed_turn.failure_code == "CODEX_CRITIC_RESPONSE_INVALID_JSON"

    authority = PivotCriticAuthorizationAuthority("mvp-r.pivot-critic-governance", bytes(range(32)))
    authorization = authority.issue(
        request,
        model_id="gpt-5.6-terra",
        prompt_sha256="a" * 64,
        runtime_sha256="b" * 64,
    )
    authority.verify(
        authorization,
        request,
        model_id="gpt-5.6-terra",
        prompt_sha256="a" * 64,
        runtime_sha256="b" * 64,
    )
    with pytest.raises(PermissionError, match="exact frozen invocation"):
        authority.verify(
            replace(authorization, model_id="gpt-5.6-sol"),
            request,
            model_id="gpt-5.6-terra",
            prompt_sha256="a" * 64,
            runtime_sha256="b" * 64,
        )


def test_pivot_rejects_cross_instrument_or_incomplete_ohlcv_oi_windows() -> None:
    records = _records()
    crossed = (
        *records[:-1],
        PointInTimeRecord(
            records[-1].event_time,
            records[-1].available_time,
            {**records[-1].values, "instrument_id": "SHFE.AG.DOMINANT_OI"},
        ),
    )
    with pytest.raises(PermissionError, match="cross instruments"):
        screen_hypothesis_families(
            crossed,
            signal_threshold=Decimal("0.0001"),
            per_signal_cost=Decimal("0.0003"),
        )
    incomplete = (
        *records[:-1],
        PointInTimeRecord(
            records[-1].event_time,
            records[-1].available_time,
            {key: value for key, value in records[-1].values.items() if key != "open_interest"},
        ),
    )
    with pytest.raises(ValueError, match="open_interest"):
        screen_hypothesis_families(
            incomplete,
            signal_threshold=Decimal("0.0001"),
            per_signal_cost=Decimal("0.0003"),
        )


def test_pivot_machine_handoff_round_trips_and_remains_non_trading() -> None:
    screens = screen_hypothesis_families(
        _records(),
        signal_threshold=Decimal("0.0001"),
        per_signal_cost=Decimal("0.0003"),
    )
    next_experiment = PivotNextExperimentRequest(
        "READY",
        HypothesisFamily.MOMENTUM_CONTINUATION,
        1,
        "mvp-r.multi-family-screen.v1",
        40,
        5,
        5,
        True,
    )
    payload = {
        "schema_version": "mvp-r.pivot-machine-handoff.v1",
        "episode_id": "evaluation_episode_test",
        "run_id": "model_run_test",
        "instrument_id": "SHFE.CU.DOMINANT_OI",
        "proposal_sha256": "a" * 64,
        "feature_evidence_sha256": "b" * 64,
        "deterministic_critique_sha256": "c" * 64,
        "independent_critic_review_sha256": "d" * 64,
        "decision": ResearchHandoffDecision.CONTINUE_TEST.value,
        "selected_family": HypothesisFamily.MOMENTUM_CONTINUATION.value,
        "cutoff_direction": 1,
        "family_screens": tuple(screen.payload() for screen in screens),
        "tradable": False,
        "approximate_backtest_only": True,
        "next_experiment": next_experiment.payload(),
    }
    handoff = PivotMachineResearchHandoff(
        "mvp-r.pivot-machine-handoff.v1",
        "evaluation_episode_test",
        "model_run_test",
        "SHFE.CU.DOMINANT_OI",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        ResearchHandoffDecision.CONTINUE_TEST,
        HypothesisFamily.MOMENTUM_CONTINUATION,
        1,
        screens,
        False,
        True,
        next_experiment,
        canonical_sha256(payload),
    )

    hydrated = PivotMachineResearchHandoff.hydrate(handoff.to_dict())
    assert hydrated == handoff
    assert hydrated.tradable is False
    assert hydrated.next_experiment.independent_forward_data_required is True
    with pytest.raises(PermissionError, match="research-only"):
        replace(handoff, tradable=True)
