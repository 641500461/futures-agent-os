"""Derive research-only LessonCandidate objects; never publish lessons."""

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from futures_agent_os.shared_kernel import canonical_sha256
from .post_trade_reviewer import Reflection


@dataclass(frozen=True, slots=True)
class LessonCandidate:
    candidate_id: str
    reflection: Reflection
    evidence_requirements: tuple[str, ...]
    scope: tuple[str, ...]
    confidence: Decimal
    expiry_policy: str
    validation_plan: str

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.reflection.evidence_refs:
            raise ValueError("lesson candidate requires reflection and evidence")
        if (
            not self.evidence_requirements
            or not self.scope
            or not self.validation_plan.strip()
            or not self.expiry_policy.strip()
        ):
            raise ValueError("lesson candidate requires validation, scope and expiry")
        if type(self.confidence) is not Decimal or not self.confidence.is_finite() or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be a finite Decimal in [0,1]")
        if any(type(x) is not str or not x.strip() for x in (*self.evidence_requirements, *self.scope)):
            raise ValueError("candidate requirements must be non-empty")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "candidate_id": self.candidate_id,
                "reflection": self.reflection.episode_id,
                "evidence": self.evidence_requirements,
                "scope": self.scope,
                "confidence": format(self.confidence, "f"),
                "expiry": self.expiry_policy,
                "validation": self.validation_plan,
            }
        )


class MemoryCurator:
    def curate(
        self,
        reflection: Reflection,
        *,
        candidate_id: str,
        evidence_requirements: tuple[str, ...],
        scope: tuple[str, ...],
        confidence: Decimal,
        expiry_policy: str,
        validation_plan: str,
    ) -> LessonCandidate:
        if type(reflection) is not Reflection:
            raise TypeError("curator requires Reflection")
        return LessonCandidate(
            candidate_id, reflection, evidence_requirements, scope, confidence, expiry_policy, validation_plan
        )


__all__ = ["LessonCandidate", "MemoryCurator"]
