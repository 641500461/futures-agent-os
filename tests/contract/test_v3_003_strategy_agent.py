from decimal import Decimal
from dataclasses import replace

import pytest

from futures_agent_os.agent_orchestration import (
    ProtectionIntent,
    StrategyAgent,
    StrategyDecision,
    StrategyCandidate,
    TradePlanDraft,
)


def test_trade_candidate_has_thesis_invalidation_evidence_risk_and_protection():
    candidate = StrategyAgent().propose(
        thesis="trend persists",
        invalidation="close below regime floor",
        evidence=("market-snapshot:1", "backtest:2"),
        target_risk="bounded",
        exit_intent="take profit at target",
        protection_intent=ProtectionIntent("close below stop", "100"),
        target_exposure=Decimal("1.0"),
    )
    assert isinstance(candidate, StrategyCandidate)
    assert candidate.decision is StrategyDecision.TRADE
    assert not hasattr(candidate, "order")
    assert not hasattr(candidate, "ledger")


def test_no_trade_and_defer_are_explicit_and_do_not_need_protection():
    agent = StrategyAgent()
    assert (
        agent.decide_no_trade(thesis="none", invalidation="n/a", evidence=("snapshot:1",), reason="no edge").decision
        is StrategyDecision.NO_TRADE
    )
    assert (
        agent.defer(thesis="unclear", invalidation="unknown", evidence=("snapshot:1",), reason="stale data").decision
        is StrategyDecision.DEFER
    )


def test_trade_plan_draft_is_proposal_only_and_requires_protection():
    draft = StrategyAgent().draft_trade_plan(
        instrument="IF",
        direction="LONG",
        thesis="trend",
        invalidation="break",
        evidence=("snapshot:1",),
        target_risk="bounded",
        entry_intent="breakout",
        exit_intent="target or stop",
        protection_intent=ProtectionIntent("break", "100"),
    )
    assert isinstance(draft, TradePlanDraft)
    assert not hasattr(draft, "order")
    with pytest.raises(ValueError):
        ProtectionIntent("", "100")


def test_trade_candidate_rejects_missing_protection_and_empty_evidence():
    with pytest.raises(ValueError):
        StrategyCandidate("t", "i", ("e",), "r", "x")
    with pytest.raises(ValueError):
        StrategyCandidate("t", "i", (), "r", "x", StrategyDecision.NO_TRADE)


def test_propose_does_not_silently_change_decision_when_protection_missing():
    with pytest.raises(ValueError, match="protection"):
        StrategyAgent().propose(thesis="t", invalidation="i", evidence=("e",), target_risk="r", exit_intent="x")


@pytest.mark.parametrize("exposure", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), 1.0])
def test_reject_nonfinite_exposure(exposure):
    with pytest.raises((TypeError, ValueError)):
        StrategyCandidate(
            "t", "i", ("e",), "r", "x", protection_intent=ProtectionIntent("stop", "10"), target_exposure=exposure
        )


@pytest.mark.parametrize("bad", ["", " ", "NaN", "Infinity", "0", "-1", "unlimited", None])
def test_protection_has_positive_finite_loss(bad):
    with pytest.raises((TypeError, ValueError)):
        ProtectionIntent("stop", bad)


def test_candidate_rejects_fake_protection_and_promotion():
    candidate = StrategyCandidate("t", "i", ("e",), "r", "x", protection_intent=ProtectionIntent("stop", "10"))
    with pytest.raises(TypeError):
        replace(candidate, protection_intent={"stop_condition": "stop", "max_loss": "10"})
    from futures_agent_os.agent_orchestration import StrategyCandidateStatus

    with pytest.raises(ValueError):
        replace(candidate, status=StrategyCandidateStatus.SUBMITTED)


def test_no_trade_cannot_carry_positive_exposure_or_risk():
    candidate = StrategyAgent().decide_no_trade(thesis="t", invalidation="i", evidence=("e",), reason="no edge")
    with pytest.raises(ValueError):
        replace(candidate, target_exposure=Decimal("1"))
    with pytest.raises(ValueError):
        replace(candidate, target_risk="100")


@pytest.mark.parametrize(
    "updates", [{"direction": "BUY"}, {"evidence": ("",)}, {"evidence": ["e"]}, {"target_exposure": Decimal("NaN")}]
)
def test_draft_rejects_invalid_semantics(updates):
    draft = TradePlanDraft("IF", "LONG", "t", "i", ("e",), "r", "entry", "exit", ProtectionIntent("stop", "10"))
    with pytest.raises((ValueError, TypeError)):
        replace(draft, **updates)
