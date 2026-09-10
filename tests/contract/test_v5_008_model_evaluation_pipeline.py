from dataclasses import replace
from decimal import Decimal

import pytest

from futures_agent_os.research_experiment import (
    CandidateState,
    EvaluationPhase,
    ModelCandidate,
    ModelEvaluationEvidence,
    ModelEvaluationPipeline,
    RollbackEvidence,
    TrainingDatasetEvidence,
    TrainingMethod,
    assess_controlled_sft,
)
from futures_agent_os.shared_kernel import RecordedAt


AT = RecordedAt.parse("2026-09-10T00:00:00Z")


def _evaluation(phase: EvaluationPhase, *, passed: bool = True) -> ModelEvaluationEvidence:
    return ModelEvaluationEvidence(
        "model:candidate:v2",
        phase,
        f"evaluation:{phase.value.lower()}",
        (f"metric:{phase.value.lower()}:quality", f"metric:{phase.value.lower()}:boundary"),
        passed,
        Decimal("0.05") if phase is EvaluationPhase.CANARY else Decimal("0"),
        AT,
    )


def _candidate(method: TrainingMethod = TrainingMethod.UNMODIFIED, digest: str | None = None) -> ModelCandidate:
    return ModelCandidate("model:candidate:v2", "model:active:v1", method, digest)


def _rollback() -> RollbackEvidence:
    return RollbackEvidence("model:active:v1", "runbook:model-rollback", "test:compatibility", "drill:rollback")


def test_complete_offline_shadow_approval_canary_activation_and_rollback_chain() -> None:
    pipeline = ModelEvaluationPipeline()
    assert pipeline.register(_candidate()).state is CandidateState.CANDIDATE
    assert pipeline.record_evaluation(_evaluation(EvaluationPhase.OFFLINE)).state is CandidateState.OFFLINE_PASSED
    assert pipeline.record_evaluation(_evaluation(EvaluationPhase.SHADOW)).state is CandidateState.SHADOW_PASSED
    approved = pipeline.approve("model:candidate:v2", actor="user:qiu", approved_at=AT)
    assert approved.state is CandidateState.APPROVED and approved.approval is not None
    assert pipeline.start_canary("model:candidate:v2", _rollback()).state is CandidateState.CANARY_RUNNING
    assert pipeline.record_evaluation(_evaluation(EvaluationPhase.CANARY)).state is CandidateState.CANARY_PASSED
    active = pipeline.activate("model:candidate:v2", scope=("simulation:SHFE",), actor="user:operator", activated_at=AT)
    assert active.state is CandidateState.ACTIVE
    activation = pipeline.resolve_active("model:candidate:v2")
    assert activation.approval_digest == approved.approval.digest and activation.rollback_evidence_digest
    rolled_back = pipeline.rollback("model:candidate:v2", actor="user:qiu", rolled_back_at=AT)
    assert rolled_back.state is CandidateState.ROLLED_BACK and rolled_back.rollback_decision is not None
    with pytest.raises(ValueError, match="not independently active"):
        pipeline.resolve_active("model:candidate:v2")


def test_candidate_cannot_enter_active_traffic_without_every_separate_gate() -> None:
    pipeline = ModelEvaluationPipeline()
    candidate = _candidate()
    pipeline.register(candidate)
    assert not hasattr(candidate, "activate") and not hasattr(candidate, "traffic_fraction")
    with pytest.raises(ValueError, match="approval, passed canary"):
        pipeline.activate("model:candidate:v2", scope=("simulation",), actor="user:qiu", activated_at=AT)
    pipeline.record_evaluation(_evaluation(EvaluationPhase.OFFLINE))
    with pytest.raises(ValueError, match="out of order"):
        pipeline.record_evaluation(_evaluation(EvaluationPhase.CANARY))
    pipeline.record_evaluation(_evaluation(EvaluationPhase.SHADOW))
    with pytest.raises(ValueError, match="human actor"):
        pipeline.approve("model:candidate:v2", actor="agent:steward", approved_at=AT)


def test_shadow_has_zero_active_traffic_and_canary_is_strictly_bounded() -> None:
    assert _evaluation(EvaluationPhase.SHADOW).traffic_fraction == 0
    with pytest.raises(ValueError, match="cannot receive active traffic"):
        replace(_evaluation(EvaluationPhase.SHADOW), traffic_fraction=Decimal("0.01"))
    with pytest.raises(ValueError, match=r"in \(0,1\)"):
        replace(_evaluation(EvaluationPhase.CANARY), traffic_fraction=Decimal("1"))


def test_failed_evaluation_rejects_candidate_and_blocks_later_gates() -> None:
    pipeline = ModelEvaluationPipeline()
    pipeline.register(_candidate())
    rejected = pipeline.record_evaluation(_evaluation(EvaluationPhase.OFFLINE, passed=False))
    assert rejected.state is CandidateState.REJECTED
    with pytest.raises(ValueError, match="out of order"):
        pipeline.record_evaluation(_evaluation(EvaluationPhase.SHADOW))
    with pytest.raises(ValueError, match="human approval requires"):
        pipeline.approve("model:candidate:v2", actor="user:qiu", approved_at=AT)


def test_failed_canary_is_retained_as_evidence_and_never_activates() -> None:
    pipeline = ModelEvaluationPipeline()
    pipeline.register(_candidate())
    pipeline.record_evaluation(_evaluation(EvaluationPhase.OFFLINE))
    pipeline.record_evaluation(_evaluation(EvaluationPhase.SHADOW))
    pipeline.approve("model:candidate:v2", actor="user:qiu", approved_at=AT)
    pipeline.start_canary("model:candidate:v2", _rollback())
    rejected = pipeline.record_evaluation(_evaluation(EvaluationPhase.CANARY, passed=False))
    assert rejected.state is CandidateState.REJECTED and rejected.canary is not None
    assert rejected.canary.passed is False
    with pytest.raises(ValueError, match="approval, passed canary"):
        pipeline.activate("model:candidate:v2", scope=("simulation",), actor="user:qiu", activated_at=AT)


def test_canary_requires_approval_and_complete_rollback_evidence_for_base_model() -> None:
    pipeline = ModelEvaluationPipeline()
    pipeline.register(_candidate())
    pipeline.record_evaluation(_evaluation(EvaluationPhase.OFFLINE))
    pipeline.record_evaluation(_evaluation(EvaluationPhase.SHADOW))
    with pytest.raises(ValueError, match="separate human approval"):
        pipeline.start_canary("model:candidate:v2", _rollback())
    pipeline.approve("model:candidate:v2", actor="user:qiu", approved_at=AT)
    with pytest.raises(ValueError, match="base model"):
        pipeline.start_canary("model:candidate:v2", replace(_rollback(), target_model_ref="model:other"))


def test_controlled_sft_is_assessed_but_never_self_activates() -> None:
    evidence = TrainingDatasetEvidence("dataset:sft:v1", ("source:reviewed:1",), True, True, True, "eval:heldout:v1")
    assessment = assess_controlled_sft(evidence)
    assert assessment.eligible and assessment.reason_codes == ("CONTROLLED_SFT_ELIGIBLE",)
    candidate = _candidate(TrainingMethod.CONTROLLED_SFT, assessment.evidence_digest)
    assert ModelEvaluationPipeline().register(candidate, sft_assessment=assessment).state is CandidateState.CANDIDATE
    blocked = assess_controlled_sft(replace(evidence, authorized=False, deidentified=False))
    assert not blocked.eligible and "DATA_NOT_AUTHORIZED" in blocked.reason_codes
    with pytest.raises(ValueError, match="matching eligible"):
        ModelEvaluationPipeline().register(
            _candidate(TrainingMethod.CONTROLLED_SFT, blocked.evidence_digest), sft_assessment=blocked
        )
