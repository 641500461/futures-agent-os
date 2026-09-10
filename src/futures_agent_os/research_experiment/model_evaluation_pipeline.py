"""Governed offline, shadow, canary, activation and rollback model lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.shared_kernel import RecordedAt, canonical_sha256


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical text")


class TrainingMethod(StrEnum):
    UNMODIFIED = "UNMODIFIED"
    CONTROLLED_SFT = "CONTROLLED_SFT"


class EvaluationPhase(StrEnum):
    OFFLINE = "OFFLINE"
    SHADOW = "SHADOW"
    CANARY = "CANARY"


class CandidateState(StrEnum):
    CANDIDATE = "CANDIDATE"
    OFFLINE_PASSED = "OFFLINE_PASSED"
    SHADOW_PASSED = "SHADOW_PASSED"
    APPROVED = "APPROVED"
    CANARY_RUNNING = "CANARY_RUNNING"
    CANARY_PASSED = "CANARY_PASSED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True, slots=True)
class TrainingDatasetEvidence:
    dataset_ref: str
    source_refs: tuple[str, ...]
    authorized: bool
    deidentified: bool
    validated: bool
    heldout_eval_ref: str

    def __post_init__(self) -> None:
        _text(self.dataset_ref, "dataset_ref")
        _text(self.heldout_eval_ref, "heldout_eval_ref")
        if not self.source_refs or len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("training dataset requires unique source references")
        if any(not isinstance(value, bool) for value in (self.authorized, self.deidentified, self.validated)):
            raise TypeError("training dataset controls must be boolean")


@dataclass(frozen=True, slots=True)
class SftAssessment:
    dataset_ref: str
    eligible: bool
    reason_codes: tuple[str, ...]
    evidence_digest: str


def assess_controlled_sft(evidence: TrainingDatasetEvidence) -> SftAssessment:
    if not isinstance(evidence, TrainingDatasetEvidence):
        raise TypeError("SFT assessment requires TrainingDatasetEvidence")
    reasons: list[str] = []
    if not evidence.authorized:
        reasons.append("DATA_NOT_AUTHORIZED")
    if not evidence.deidentified:
        reasons.append("DATA_NOT_DEIDENTIFIED")
    if not evidence.validated:
        reasons.append("DATA_NOT_VALIDATED")
    digest = canonical_sha256(
        cast(
            Any,
            {
                "dataset": evidence.dataset_ref,
                "sources": evidence.source_refs,
                "authorized": evidence.authorized,
                "deidentified": evidence.deidentified,
                "validated": evidence.validated,
                "heldout": evidence.heldout_eval_ref,
            },
        )
    )
    return SftAssessment(evidence.dataset_ref, not reasons, tuple(reasons) or ("CONTROLLED_SFT_ELIGIBLE",), digest)


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    candidate_ref: str
    base_model_ref: str
    training_method: TrainingMethod
    sft_assessment_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.candidate_ref, "candidate_ref")
        _text(self.base_model_ref, "base_model_ref")
        if self.candidate_ref == self.base_model_ref:
            raise ValueError("candidate must differ from base model")
        if not isinstance(self.training_method, TrainingMethod):
            raise TypeError("training_method must be typed")
        if self.training_method is TrainingMethod.CONTROLLED_SFT:
            if self.sft_assessment_digest is None or len(self.sft_assessment_digest) != 64:
                raise ValueError("controlled SFT candidate requires eligible assessment digest")
        elif self.sft_assessment_digest is not None:
            raise ValueError("unmodified candidate cannot carry SFT assessment")


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    candidate_ref: str
    phase: EvaluationPhase
    artifact_ref: str
    metric_refs: tuple[str, ...]
    passed: bool
    traffic_fraction: Decimal
    completed_at: RecordedAt

    def __post_init__(self) -> None:
        _text(self.candidate_ref, "candidate_ref")
        _text(self.artifact_ref, "artifact_ref")
        if not isinstance(self.phase, EvaluationPhase) or not isinstance(self.passed, bool):
            raise TypeError("evaluation phase and outcome must be typed")
        if not self.metric_refs or len(set(self.metric_refs)) != len(self.metric_refs):
            raise ValueError("evaluation evidence requires unique metric references")
        if any(not isinstance(item, str) or not item.strip() for item in self.metric_refs):
            raise ValueError("evaluation metric references must be non-empty")
        if not isinstance(self.traffic_fraction, Decimal) or not self.traffic_fraction.is_finite():
            raise ValueError("traffic fraction must be finite Decimal")
        if self.phase in {EvaluationPhase.OFFLINE, EvaluationPhase.SHADOW} and self.traffic_fraction != 0:
            raise ValueError("offline and shadow evaluation cannot receive active traffic")
        if self.phase is EvaluationPhase.CANARY and not Decimal("0") < self.traffic_fraction < Decimal("1"):
            raise ValueError("canary traffic fraction must be in (0,1)")
        if not isinstance(self.completed_at, RecordedAt):
            raise TypeError("completed_at must be RecordedAt")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "candidate": self.candidate_ref,
                    "phase": self.phase.value,
                    "artifact": self.artifact_ref,
                    "metrics": self.metric_refs,
                    "passed": self.passed,
                    "traffic_fraction": str(self.traffic_fraction),
                    "completed_at": self.completed_at.to_dict()["recorded_at"],
                },
            )
        )


@dataclass(frozen=True, slots=True)
class RollbackEvidence:
    target_model_ref: str
    runbook_ref: str
    compatibility_test_ref: str
    drill_ref: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.target_model_ref, "target_model_ref"),
            (self.runbook_ref, "runbook_ref"),
            (self.compatibility_test_ref, "compatibility_test_ref"),
            (self.drill_ref, "drill_ref"),
        ):
            _text(value, label)

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "target": self.target_model_ref,
                    "runbook": self.runbook_ref,
                    "compatibility": self.compatibility_test_ref,
                    "drill": self.drill_ref,
                },
            )
        )


@dataclass(frozen=True, slots=True)
class ModelChangeApproval:
    candidate_ref: str
    approved_by: str
    offline_evidence_digest: str
    shadow_evidence_digest: str
    approved_at: RecordedAt

    def __post_init__(self) -> None:
        _text(self.candidate_ref, "candidate_ref")
        if not self.approved_by.startswith("user:") or not isinstance(self.approved_at, RecordedAt):
            raise ValueError("approval requires human actor and typed time")
        if len(self.offline_evidence_digest) != 64 or len(self.shadow_evidence_digest) != 64:
            raise ValueError("approval requires offline and shadow evidence digests")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "candidate": self.candidate_ref,
                    "actor": self.approved_by,
                    "offline": self.offline_evidence_digest,
                    "shadow": self.shadow_evidence_digest,
                    "at": self.approved_at.to_dict()["recorded_at"],
                },
            )
        )


@dataclass(frozen=True, slots=True)
class ModelActivation:
    candidate_ref: str
    scope: tuple[str, ...]
    activated_by: str
    approval_digest: str
    canary_evidence_digest: str
    rollback_evidence_digest: str
    activated_at: RecordedAt

    def __post_init__(self) -> None:
        _text(self.candidate_ref, "candidate_ref")
        if not self.scope or len(set(self.scope)) != len(self.scope):
            raise ValueError("activation requires unique scope")
        if not self.activated_by.startswith("user:") or not isinstance(self.activated_at, RecordedAt):
            raise ValueError("activation requires human actor and typed time")
        if any(
            len(digest) != 64
            for digest in (self.approval_digest, self.canary_evidence_digest, self.rollback_evidence_digest)
        ):
            raise ValueError("activation requires complete evidence digests")


@dataclass(frozen=True, slots=True)
class RollbackDecision:
    candidate_ref: str
    target_model_ref: str
    rolled_back_by: str
    rollback_evidence_digest: str
    rolled_back_at: RecordedAt

    def __post_init__(self) -> None:
        if not self.rolled_back_by.startswith("user:") or not isinstance(self.rolled_back_at, RecordedAt):
            raise ValueError("rollback requires human actor and typed time")
        if len(self.rollback_evidence_digest) != 64:
            raise ValueError("rollback requires evidence digest")


@dataclass(frozen=True, slots=True)
class PipelineRecord:
    candidate: ModelCandidate
    state: CandidateState
    offline: EvaluationEvidence | None = None
    shadow: EvaluationEvidence | None = None
    approval: ModelChangeApproval | None = None
    rollback: RollbackEvidence | None = None
    canary: EvaluationEvidence | None = None
    activation: ModelActivation | None = None
    rollback_decision: RollbackDecision | None = None


class ModelEvaluationPipeline:
    """Single writer for gates; candidates have no method that changes traffic."""

    def __init__(self) -> None:
        self._records: dict[str, PipelineRecord] = {}

    def register(self, candidate: ModelCandidate, *, sft_assessment: SftAssessment | None = None) -> PipelineRecord:
        if not isinstance(candidate, ModelCandidate):
            raise TypeError("pipeline requires ModelCandidate")
        if candidate.candidate_ref in self._records:
            raise ValueError("candidate already registered")
        if candidate.training_method is TrainingMethod.CONTROLLED_SFT:
            if (
                not isinstance(sft_assessment, SftAssessment)
                or not sft_assessment.eligible
                or candidate.sft_assessment_digest != sft_assessment.evidence_digest
            ):
                raise ValueError("controlled SFT candidate requires matching eligible assessment")
        record = PipelineRecord(candidate, CandidateState.CANDIDATE)
        self._records[candidate.candidate_ref] = record
        return record

    def record_evaluation(self, evidence: EvaluationEvidence) -> PipelineRecord:
        record = self._require(evidence.candidate_ref)
        expected = {
            CandidateState.CANDIDATE: EvaluationPhase.OFFLINE,
            CandidateState.OFFLINE_PASSED: EvaluationPhase.SHADOW,
            CandidateState.CANARY_RUNNING: EvaluationPhase.CANARY,
        }.get(record.state)
        if evidence.phase is not expected:
            raise ValueError("evaluation phase is out of order")
        if not evidence.passed:
            if evidence.phase is EvaluationPhase.OFFLINE:
                updated = replace(record, state=CandidateState.REJECTED, offline=evidence)
            elif evidence.phase is EvaluationPhase.SHADOW:
                updated = replace(record, state=CandidateState.REJECTED, shadow=evidence)
            else:
                updated = replace(record, state=CandidateState.REJECTED, canary=evidence)
        elif evidence.phase is EvaluationPhase.OFFLINE:
            updated = replace(record, state=CandidateState.OFFLINE_PASSED, offline=evidence)
        elif evidence.phase is EvaluationPhase.SHADOW:
            updated = replace(record, state=CandidateState.SHADOW_PASSED, shadow=evidence)
        else:
            updated = replace(record, state=CandidateState.CANARY_PASSED, canary=evidence)
        self._records[evidence.candidate_ref] = updated
        return updated

    def approve(self, candidate_ref: str, *, actor: str, approved_at: RecordedAt) -> PipelineRecord:
        record = self._require(candidate_ref)
        if record.state is not CandidateState.SHADOW_PASSED or record.offline is None or record.shadow is None:
            raise ValueError("human approval requires passed offline and shadow evidence")
        if not actor.startswith("user:"):
            raise ValueError("model change approval requires human actor")
        approval = ModelChangeApproval(candidate_ref, actor, record.offline.digest, record.shadow.digest, approved_at)
        updated = replace(record, state=CandidateState.APPROVED, approval=approval)
        self._records[candidate_ref] = updated
        return updated

    def start_canary(self, candidate_ref: str, rollback: RollbackEvidence) -> PipelineRecord:
        record = self._require(candidate_ref)
        if record.state is not CandidateState.APPROVED or record.approval is None:
            raise ValueError("canary requires separate human approval")
        if not isinstance(rollback, RollbackEvidence) or rollback.target_model_ref != record.candidate.base_model_ref:
            raise ValueError("canary requires tested rollback evidence for the base model")
        updated = replace(record, state=CandidateState.CANARY_RUNNING, rollback=rollback)
        self._records[candidate_ref] = updated
        return updated

    def activate(
        self, candidate_ref: str, *, scope: tuple[str, ...], actor: str, activated_at: RecordedAt
    ) -> PipelineRecord:
        record = self._require(candidate_ref)
        if (
            record.state is not CandidateState.CANARY_PASSED
            or record.approval is None
            or record.canary is None
            or record.rollback is None
        ):
            raise ValueError("activation requires approval, passed canary and rollback evidence")
        if not actor.startswith("user:") or not scope:
            raise ValueError("independent activation requires human actor and scope")
        activation = ModelActivation(
            candidate_ref,
            scope,
            actor,
            record.approval.digest,
            record.canary.digest,
            record.rollback.digest,
            activated_at,
        )
        updated = replace(record, state=CandidateState.ACTIVE, activation=activation)
        self._records[candidate_ref] = updated
        return updated

    def rollback(self, candidate_ref: str, *, actor: str, rolled_back_at: RecordedAt) -> PipelineRecord:
        record = self._require(candidate_ref)
        if record.state is not CandidateState.ACTIVE or record.rollback is None or not actor.startswith("user:"):
            raise ValueError("rollback requires active candidate, evidence and human actor")
        decision = RollbackDecision(
            candidate_ref,
            record.rollback.target_model_ref,
            actor,
            record.rollback.digest,
            rolled_back_at,
        )
        updated = replace(record, state=CandidateState.ROLLED_BACK, rollback_decision=decision)
        self._records[candidate_ref] = updated
        return updated

    def resolve_active(self, candidate_ref: str) -> ModelActivation:
        record = self._require(candidate_ref)
        if record.state is not CandidateState.ACTIVE or record.activation is None:
            raise ValueError("candidate is not independently active")
        return record.activation

    def _require(self, candidate_ref: str) -> PipelineRecord:
        try:
            return self._records[candidate_ref]
        except KeyError as exc:
            raise ValueError("unknown model candidate") from exc


__all__ = [
    "CandidateState",
    "EvaluationEvidence",
    "EvaluationPhase",
    "ModelActivation",
    "ModelCandidate",
    "ModelChangeApproval",
    "ModelEvaluationPipeline",
    "PipelineRecord",
    "RollbackEvidence",
    "RollbackDecision",
    "SftAssessment",
    "TrainingDatasetEvidence",
    "TrainingMethod",
    "assess_controlled_sft",
]
