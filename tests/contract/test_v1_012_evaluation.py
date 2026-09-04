from datetime import UTC, datetime
from uuid import uuid7
import pytest
from futures_agent_os.research_experiment.v1_012_evaluation import (
    EvaluationCase,
    EvaluationDimension,
    EvaluationManager,
    EvaluationRun,
    EvidenceBinding,
    NumericGrounding,
    ResearchEvaluationSuite,
    ResearchOutcome,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt

NOW = RecordedAt(datetime(2026, 1, 1, tzinfo=UTC))
HASH = "a" * 64


def _suite():
    evidence = (EvidenceBinding("evidence://price", HASH, NOW), EvidenceBinding("evidence://counter", HASH, NOW))
    case = EvaluationCase(
        "case-1",
        "Should we trade?",
        ("market.snapshot",),
        evidence,
        ResearchOutcome.NO_TRADE,
        HASH,
        (NumericGrounding("return", "0.10", "ratio", "evidence://price"),),
        ("evidence://counter",),
    )
    return ResearchEvaluationSuite(EntityId("evaluation_suite", uuid7()), "v1", "dataset-1", "rubric-1", (case,))


def _score(manager, suite, payload=("same",), outcome=ResearchOutcome.NO_TRADE):
    case = suite.cases[0]
    return manager.score_case(
        case,
        selected_tools=case.required_tools,
        cited_evidence=case.evidence,
        numeric_groundings=case.numeric_groundings,
        counter_evidence_refs=case.counter_evidence_refs,
        outcome=outcome,
        evidence_payload=payload,
    )


def test_freeze_and_score_are_deterministic():
    manager, suite = EvaluationManager(), _suite()
    manager.freeze(suite)
    score = _score(manager, suite, payload={"price": 10})
    assert score.score(EvaluationDimension.TOOL_SELECTION) == 1
    with pytest.raises(ValueError):
        manager.freeze(suite)


def test_wrong_grounding_and_replay_fail_closed():
    suite = _suite()
    manager = EvaluationManager()
    manager.freeze(suite)
    bad = manager.score_case(
        suite.cases[0],
        selected_tools=("market.snapshot",),
        cited_evidence=suite.cases[0].evidence,
        numeric_groundings=(),
        counter_evidence_refs=(),
        outcome=ResearchOutcome.DEFER,
        evidence_payload={"other": 1},
    )
    assert (
        bad.score(EvaluationDimension.NUMERIC_GROUNDING) == 0 and bad.score(EvaluationDimension.REPLAY_CONSISTENCY) == 0
    )


def test_report_requires_frozen_cases_and_distinguishes_replay():
    manager, suite = EvaluationManager(), _suite()
    manager.freeze(suite)
    left = EvaluationRun(suite.content_sha256, "model-1", "prompt-1", "tools-1", (_score(manager, suite, {"x": 1}),))
    right = EvaluationRun(suite.content_sha256, "model-2", "prompt-2", "tools-2", (_score(manager, suite, {"x": 2}),))
    report = manager.report(left, right)
    assert report.replay_equal is False and report.content_sha256


def test_report_rejects_different_suite():
    manager, suite = EvaluationManager(), _suite()
    manager.freeze(suite)
    left = EvaluationRun(suite.content_sha256, "m", "p", "t", (_score(manager, suite),))
    other = _suite()
    with pytest.raises(ValueError):
        manager.report(left, EvaluationRun(other.content_sha256, "m", "p", "t", left.case_scores))
