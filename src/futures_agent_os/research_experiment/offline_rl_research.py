"""Governed, low-dimensional and reproducible Offline RL research boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from futures_agent_os.shared_kernel import canonical_sha256


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical text")


def _digest(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _human_actor(value: str, label: str) -> None:
    _text(value, label)
    if not value.startswith("user:") or len(value) == len("user:"):
        raise ValueError(f"{label} must identify a human user")


class OfflineRlModule(StrEnum):
    EXECUTION = "EXECUTION"
    PORTFOLIO_ALLOCATION = "PORTFOLIO_ALLOCATION"
    POSITION_ADJUSTMENT = "POSITION_ADJUSTMENT"


class RuntimeLane(StrEnum):
    RESEARCH_SHADOW = "RESEARCH_SHADOW"
    CONTROLLED_SIMULATION = "CONTROLLED_SIMULATION"
    DEFAULT_SIMULATION = "DEFAULT_SIMULATION"


class OfflineRlState(StrEnum):
    PLANNED = "PLANNED"
    EVALUATED = "EVALUATED"
    RESEARCH_REVIEWED = "RESEARCH_REVIEWED"
    GOVERNANCE_APPROVED = "GOVERNANCE_APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class OfflineRlPlan:
    plan_id: str
    module: OfflineRlModule
    state_features: tuple[str, ...]
    actions: tuple[str, ...]
    reward_spec_ref: str
    frozen_dataset_ref: str
    frozen_dataset_digest: str
    behavior_policy_ref: str
    evaluation_protocol_ref: str
    code_commit: str
    environment_ref: str
    seed: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.plan_id, "plan_id"),
            (self.reward_spec_ref, "reward_spec_ref"),
            (self.frozen_dataset_ref, "frozen_dataset_ref"),
            (self.behavior_policy_ref, "behavior_policy_ref"),
            (self.evaluation_protocol_ref, "evaluation_protocol_ref"),
            (self.code_commit, "code_commit"),
            (self.environment_ref, "environment_ref"),
        ):
            _text(value, label)
        _digest(self.frozen_dataset_digest, "frozen_dataset_digest")
        if not isinstance(self.module, OfflineRlModule):
            raise TypeError("Offline RL module must be a closed low-dimensional module")
        if not 1 <= len(self.state_features) <= 16 or len(set(self.state_features)) != len(self.state_features):
            raise ValueError("Offline RL state must contain 1-16 unique features")
        if not 2 <= len(self.actions) <= 16 or len(set(self.actions)) != len(self.actions):
            raise ValueError("Offline RL action set must contain 2-16 unique actions")
        if any(not isinstance(item, str) or not item.strip() for item in (*self.state_features, *self.actions)):
            raise ValueError("Offline RL state/action names must be non-empty")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("Offline RL seed must be a non-negative integer")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "plan_id": self.plan_id,
                    "module": self.module.value,
                    "state_features": self.state_features,
                    "actions": self.actions,
                    "reward": self.reward_spec_ref,
                    "dataset": self.frozen_dataset_ref,
                    "dataset_digest": self.frozen_dataset_digest,
                    "behavior_policy": self.behavior_policy_ref,
                    "evaluation_protocol": self.evaluation_protocol_ref,
                    "code_commit": self.code_commit,
                    "environment": self.environment_ref,
                    "seed": self.seed,
                    "training_mode": "OFFLINE_ONLY",
                    "output_kind": "MODULE_RECOMMENDATION",
                },
            )
        )


@dataclass(frozen=True, slots=True)
class OfflineRlEvaluation:
    plan_digest: str
    policy_artifact_ref: str
    dataset_digest: str
    episode_count: int
    off_policy_estimate: Decimal
    confidence_low: Decimal
    confidence_high: Decimal
    constraint_violations: int
    baseline_comparison_ref: str
    reproducibility_ref: str
    passed: bool

    def __post_init__(self) -> None:
        _digest(self.plan_digest, "plan_digest")
        _digest(self.dataset_digest, "dataset_digest")
        for value, label in (
            (self.policy_artifact_ref, "policy_artifact_ref"),
            (self.baseline_comparison_ref, "baseline_comparison_ref"),
            (self.reproducibility_ref, "reproducibility_ref"),
        ):
            _text(value, label)
        if self.episode_count < 1 or self.constraint_violations < 0:
            raise ValueError("evaluation counts must be valid")
        for metric in (self.off_policy_estimate, self.confidence_low, self.confidence_high):
            if not isinstance(metric, Decimal) or not metric.is_finite():
                raise ValueError("evaluation metrics must be finite Decimal")
        if not self.confidence_low <= self.off_policy_estimate <= self.confidence_high:
            raise ValueError("off-policy estimate must lie inside its confidence interval")
        if self.passed and self.constraint_violations != 0:
            raise ValueError("passing policy evaluation cannot have constraint violations")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "plan": self.plan_digest,
                    "policy": self.policy_artifact_ref,
                    "dataset": self.dataset_digest,
                    "episodes": self.episode_count,
                    "estimate": str(self.off_policy_estimate),
                    "low": str(self.confidence_low),
                    "high": str(self.confidence_high),
                    "violations": self.constraint_violations,
                    "baseline": self.baseline_comparison_ref,
                    "reproducibility": self.reproducibility_ref,
                    "passed": self.passed,
                },
            )
        )


@dataclass(frozen=True, slots=True)
class ResearchReview:
    plan_digest: str
    evaluation_digest: str
    reviewed_by: str
    decision: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.plan_digest, "plan_digest")
        _digest(self.evaluation_digest, "evaluation_digest")
        _human_actor(self.reviewed_by, "reviewed_by")
        if self.decision not in {"APPROVE", "REJECT"}:
            raise ValueError("research review requires APPROVE/REJECT decision")
        if not self.evidence_refs:
            raise ValueError("research review requires evidence")
        for evidence_ref in self.evidence_refs:
            _text(evidence_ref, "evidence_ref")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "plan": self.plan_digest,
                    "evaluation": self.evaluation_digest,
                    "actor": self.reviewed_by,
                    "decision": self.decision,
                    "evidence": self.evidence_refs,
                },
            )
        )


@dataclass(frozen=True, slots=True)
class GovernanceApproval:
    plan_digest: str
    evaluation_digest: str
    research_review_digest: str
    approved_by: str
    target_lane: RuntimeLane
    deterministic_override_ref: str
    fallback_ref: str

    def __post_init__(self) -> None:
        _digest(self.plan_digest, "plan_digest")
        _digest(self.evaluation_digest, "evaluation_digest")
        _digest(self.research_review_digest, "research_review_digest")
        _human_actor(self.approved_by, "approved_by")
        if not isinstance(self.target_lane, RuntimeLane):
            raise TypeError("governance approval requires typed runtime lane")
        _text(self.deterministic_override_ref, "deterministic_override_ref")
        _text(self.fallback_ref, "fallback_ref")

    @property
    def digest(self) -> str:
        return canonical_sha256(
            cast(
                Any,
                {
                    "plan": self.plan_digest,
                    "evaluation": self.evaluation_digest,
                    "review": self.research_review_digest,
                    "actor": self.approved_by,
                    "lane": self.target_lane.value,
                    "override": self.deterministic_override_ref,
                    "fallback": self.fallback_ref,
                },
            )
        )


@dataclass(frozen=True, slots=True)
class OfflineRlActivation:
    plan_digest: str
    policy_artifact_ref: str
    lane: RuntimeLane
    scope: tuple[str, ...]
    approval_digest: str
    activated_by: str

    def __post_init__(self) -> None:
        _digest(self.plan_digest, "plan_digest")
        _digest(self.approval_digest, "approval_digest")
        _text(self.policy_artifact_ref, "policy_artifact_ref")
        _human_actor(self.activated_by, "activated_by")
        if not isinstance(self.lane, RuntimeLane):
            raise TypeError("activation requires typed runtime lane")
        if not self.scope:
            raise ValueError("activation requires explicit scope")
        for scope_ref in self.scope:
            _text(scope_ref, "scope_ref")


@dataclass(frozen=True, slots=True)
class OfflineRlRecord:
    plan: OfflineRlPlan
    state: OfflineRlState
    evaluation: OfflineRlEvaluation | None = None
    review: ResearchReview | None = None
    approval: GovernanceApproval | None = None
    activation: OfflineRlActivation | None = None


class OfflineRlResearchRegistry:
    """Keeps research, review, approval and activation as separate writers."""

    def __init__(self) -> None:
        self._records: dict[str, OfflineRlRecord] = {}

    def register(self, plan: OfflineRlPlan) -> OfflineRlRecord:
        if not isinstance(plan, OfflineRlPlan):
            raise TypeError("registry requires OfflineRlPlan")
        if plan.digest in self._records:
            raise ValueError("Offline RL plan already registered")
        record = OfflineRlRecord(plan, OfflineRlState.PLANNED)
        self._records[plan.digest] = record
        return record

    def record_evaluation(self, evaluation: OfflineRlEvaluation) -> OfflineRlRecord:
        if not isinstance(evaluation, OfflineRlEvaluation):
            raise TypeError("registry requires OfflineRlEvaluation")
        record = self._require(evaluation.plan_digest)
        if record.state is not OfflineRlState.PLANNED:
            raise ValueError("evaluation is out of order")
        if evaluation.dataset_digest != record.plan.frozen_dataset_digest:
            raise ValueError("evaluation dataset does not match the frozen research plan")
        state = OfflineRlState.EVALUATED if evaluation.passed else OfflineRlState.REJECTED
        updated = replace(record, state=state, evaluation=evaluation)
        self._records[evaluation.plan_digest] = updated
        return updated

    def review(self, plan_digest: str, *, actor: str, decision: str, evidence_refs: tuple[str, ...]) -> OfflineRlRecord:
        record = self._require(plan_digest)
        if record.state is not OfflineRlState.EVALUATED or record.evaluation is None:
            raise ValueError("research review requires passed evaluation")
        review = ResearchReview(plan_digest, record.evaluation.digest, actor, decision, evidence_refs)
        state = OfflineRlState.RESEARCH_REVIEWED if decision == "APPROVE" else OfflineRlState.REJECTED
        updated = replace(record, state=state, review=review)
        self._records[plan_digest] = updated
        return updated

    def approve(
        self,
        plan_digest: str,
        *,
        actor: str,
        target_lane: RuntimeLane,
        deterministic_override_ref: str,
        fallback_ref: str,
    ) -> OfflineRlRecord:
        record = self._require(plan_digest)
        if record.state is not OfflineRlState.RESEARCH_REVIEWED or record.review is None or record.evaluation is None:
            raise ValueError("governance approval requires approved independent research review")
        approval = GovernanceApproval(
            plan_digest,
            record.evaluation.digest,
            record.review.digest,
            actor,
            target_lane,
            deterministic_override_ref,
            fallback_ref,
        )
        updated = replace(record, state=OfflineRlState.GOVERNANCE_APPROVED, approval=approval)
        self._records[plan_digest] = updated
        return updated

    def activate(self, plan_digest: str, *, actor: str, scope: tuple[str, ...]) -> OfflineRlRecord:
        record = self._require(plan_digest)
        if (
            record.state is not OfflineRlState.GOVERNANCE_APPROVED
            or record.approval is None
            or record.evaluation is None
        ):
            raise ValueError("runtime binding requires research review and governance approval")
        activation = OfflineRlActivation(
            plan_digest,
            record.evaluation.policy_artifact_ref,
            record.approval.target_lane,
            scope,
            record.approval.digest,
            actor,
        )
        updated = replace(record, state=OfflineRlState.ACTIVE, activation=activation)
        self._records[plan_digest] = updated
        return updated

    def resolve(self, plan_digest: str, lane: RuntimeLane) -> OfflineRlActivation:
        if not isinstance(lane, RuntimeLane):
            raise TypeError("resolve requires typed runtime lane")
        record = self._require(plan_digest)
        if record.state is not OfflineRlState.ACTIVE or record.activation is None or record.activation.lane is not lane:
            raise ValueError("Offline RL policy is not activated for this runtime lane")
        return record.activation

    def _require(self, plan_digest: str) -> OfflineRlRecord:
        try:
            return self._records[plan_digest]
        except KeyError as exc:
            raise ValueError("unknown Offline RL plan") from exc


__all__ = [
    "GovernanceApproval",
    "OfflineRlActivation",
    "OfflineRlEvaluation",
    "OfflineRlModule",
    "OfflineRlPlan",
    "OfflineRlRecord",
    "OfflineRlResearchRegistry",
    "OfflineRlState",
    "ResearchReview",
    "RuntimeLane",
]
