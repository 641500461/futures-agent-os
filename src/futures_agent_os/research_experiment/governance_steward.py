"""Proposal-only V5 Model/Policy Steward governance mode."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.shared_kernel import RecordedAt, canonical_sha256


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty canonical text")


class StewardSubjectKind(StrEnum):
    PROMPT = "PROMPT"
    MODEL = "MODEL"
    STRATEGY = "STRATEGY"


class StewardEvaluationDimension(StrEnum):
    QUALITY = "QUALITY"
    BOUNDARY_COMPLIANCE = "BOUNDARY_COMPLIANCE"
    REGRESSION = "REGRESSION"
    COST_LATENCY = "COST_LATENCY"
    ROLLBACK_READINESS = "ROLLBACK_READINESS"


REQUIRED_DIMENSIONS = tuple(StewardEvaluationDimension)


class EvaluationOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class StewardRecommendation(StrEnum):
    ADOPT_CANDIDATE = "ADOPT_CANDIDATE"
    REJECT_CANDIDATE = "REJECT_CANDIDATE"
    RUN_MORE_EVALUATION = "RUN_MORE_EVALUATION"
    PROPOSE_ROLLBACK = "PROPOSE_ROLLBACK"


class ChangeRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class StewardTool(StrEnum):
    PROPOSAL_SEARCH = "proposal_search"
    EXPERIMENT_SEARCH = "experiment_search"
    MODEL_REGISTRY_QUERY = "model_registry_query"
    AUDIT_QUERY = "audit_query"
    DEPLOYMENT_EVIDENCE_QUERY = "deployment_evidence_query"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    dimension: StewardEvaluationDimension
    outcome: EvaluationOutcome
    baseline_value: Decimal
    candidate_value: Decimal
    threshold: Decimal
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, StewardEvaluationDimension) or not isinstance(
            self.outcome, EvaluationOutcome
        ):
            raise TypeError("evaluation result requires typed dimension and outcome")
        for value in (self.baseline_value, self.candidate_value, self.threshold):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError("evaluation values must be finite Decimal")
        _text(self.evidence_ref, "evaluation evidence_ref")


@dataclass(frozen=True, slots=True)
class StewardEvaluationBundle:
    subject_kind: StewardSubjectKind
    current_version_ref: str
    candidate_version_ref: str
    target_scope: tuple[str, ...]
    results: tuple[EvaluationResult, ...]
    evaluated_at: RecordedAt

    def __post_init__(self) -> None:
        if not isinstance(self.subject_kind, StewardSubjectKind):
            raise TypeError("steward subject kind must be typed")
        _text(self.current_version_ref, "current version")
        _text(self.candidate_version_ref, "candidate version")
        if self.current_version_ref == self.candidate_version_ref:
            raise ValueError("candidate must differ from current version")
        if (
            not isinstance(self.target_scope, tuple)
            or not self.target_scope
            or any(not isinstance(item, str) or not item.strip() for item in self.target_scope)
            or len(set(self.target_scope)) != len(self.target_scope)
        ):
            raise ValueError("steward evaluation requires unique target scope")
        if (
            not isinstance(self.results, tuple)
            or any(not isinstance(result, EvaluationResult) for result in self.results)
            or tuple(result.dimension for result in self.results) != REQUIRED_DIMENSIONS
        ):
            raise ValueError("steward evaluation must cover every required dimension in canonical order")
        if len({result.evidence_ref for result in self.results}) != len(self.results):
            raise ValueError("evaluation evidence references must be unique")
        if not isinstance(self.evaluated_at, RecordedAt):
            raise TypeError("evaluated_at must be RecordedAt")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "subject_kind": self.subject_kind.value,
                    "current": self.current_version_ref,
                    "candidate": self.candidate_version_ref,
                    "scope": self.target_scope,
                    "results": tuple(
                        {
                            "dimension": result.dimension.value,
                            "outcome": result.outcome.value,
                            "baseline": str(result.baseline_value),
                            "candidate": str(result.candidate_value),
                            "threshold": str(result.threshold),
                            "evidence": result.evidence_ref,
                        }
                        for result in self.results
                    ),
                    "evaluated_at": self.evaluated_at.to_dict()["recorded_at"],
                },
            )
        )


@dataclass(frozen=True, slots=True)
class ChangeProposal:
    proposal_id: str
    subject_kind: StewardSubjectKind
    current_version_ref: str
    candidate_version_ref: str
    target_scope: tuple[str, ...]
    recommendation: StewardRecommendation
    risk: ChangeRisk
    evaluation_bundle_digest: str
    evidence_refs: tuple[str, ...]
    rationale: str
    required_steps: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.proposal_id, "proposal_id")
        if not self.proposal_id.startswith("change-proposal:"):
            raise ValueError("proposal ID must use change-proposal namespace")
        if (
            not isinstance(self.subject_kind, StewardSubjectKind)
            or not isinstance(self.recommendation, StewardRecommendation)
            or not isinstance(self.risk, ChangeRisk)
        ):
            raise TypeError("proposal subject, recommendation and risk must be typed")
        _text(self.current_version_ref, "current version")
        _text(self.candidate_version_ref, "candidate version")
        if not self.target_scope:
            raise ValueError("proposal requires target scope")
        if len(self.evaluation_bundle_digest) != 64:
            raise ValueError("proposal requires evaluation bundle digest")
        if not self.evidence_refs or not self.required_steps:
            raise ValueError("proposal requires evidence and independent governance steps")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("proposal requires rationale")


class GovernanceSteward:
    """Read-only evaluator that can only construct ChangeProposal facts."""

    allowed_tools = tuple(StewardTool)
    required_steps = (
        "DESIGN_REVIEW",
        "OFFLINE_TEST",
        "HUMAN_CHANGE_APPROVAL",
        "INDEPENDENT_REGISTRY_ACTION",
        "INDEPENDENT_ACTIVATION",
        "ROLLBACK_PLAN",
    )

    def propose(
        self,
        bundle: StewardEvaluationBundle,
        *,
        recommendation: StewardRecommendation,
        risk: ChangeRisk,
        rationale: str,
    ) -> ChangeProposal:
        if not isinstance(bundle, StewardEvaluationBundle):
            raise TypeError("steward requires StewardEvaluationBundle")
        if not isinstance(recommendation, StewardRecommendation) or not isinstance(risk, ChangeRisk):
            raise TypeError("steward recommendation and risk must be typed")
        outcomes = {result.outcome for result in bundle.results}
        if recommendation is StewardRecommendation.ADOPT_CANDIDATE and outcomes != {EvaluationOutcome.PASS}:
            raise ValueError("candidate adoption proposal requires all evaluations to pass")
        if recommendation in {StewardRecommendation.REJECT_CANDIDATE, StewardRecommendation.PROPOSE_ROLLBACK}:
            if EvaluationOutcome.FAIL not in outcomes:
                raise ValueError("reject or rollback proposal requires failed evaluation evidence")
        if recommendation is StewardRecommendation.RUN_MORE_EVALUATION and EvaluationOutcome.UNKNOWN not in outcomes:
            raise ValueError("more evaluation proposal requires unknown evidence")
        evidence_refs = tuple(result.evidence_ref for result in bundle.results)
        seed = canonical_sha256(
            cast(
                Any,
                {
                    "bundle": bundle.digest,
                    "recommendation": recommendation.value,
                    "risk": risk.value,
                    "rationale": rationale,
                    "steps": self.required_steps,
                },
            )
        )
        return ChangeProposal(
            f"change-proposal:{seed}",
            bundle.subject_kind,
            bundle.current_version_ref,
            bundle.candidate_version_ref,
            bundle.target_scope,
            recommendation,
            risk,
            bundle.digest,
            evidence_refs,
            rationale,
            self.required_steps,
        )


__all__ = [
    "ChangeProposal",
    "ChangeRisk",
    "EvaluationOutcome",
    "EvaluationResult",
    "GovernanceSteward",
    "REQUIRED_DIMENSIONS",
    "StewardEvaluationBundle",
    "StewardEvaluationDimension",
    "StewardRecommendation",
    "StewardSubjectKind",
    "StewardTool",
]
