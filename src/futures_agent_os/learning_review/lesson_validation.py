"""Independent LessonCandidate validation lifecycle."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from decimal import Decimal
from futures_agent_os.shared_kernel import canonical_sha256
from .memory_curator import LessonCandidate


class CandidateStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"


class LessonStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class LessonValidation:
    validation_id: str
    candidate_sha256: str
    evidence_refs: tuple[str, ...]
    passed: bool
    notes: str

    def __post_init__(self):
        if (
            not self.validation_id.strip()
            or not self.candidate_sha256
            or not self.evidence_refs
            or not self.notes.strip()
        ):
            raise ValueError("validation requires candidate, evidence and notes")


@dataclass(frozen=True, slots=True)
class ValidatedLesson:
    lesson_id: str
    candidate_sha256: str
    validation: LessonValidation
    scope: tuple[str, ...]
    confidence: Decimal
    expires_at: datetime
    status: LessonStatus = LessonStatus.ACTIVE

    def __post_init__(self):
        if (
            self.validation.candidate_sha256 != self.candidate_sha256
            or not self.scope
            or self.expires_at.tzinfo is None
        ):
            raise ValueError("lesson must bind validation and scoped expiry")
        if type(self.confidence) is not Decimal or not self.confidence.is_finite() or not 0 <= self.confidence <= 1:
            raise ValueError("invalid lesson confidence")

    @property
    def content_sha256(self):
        return canonical_sha256(
            {
                "lesson": self.lesson_id,
                "candidate": self.candidate_sha256,
                "validation": self.validation.validation_id,
                "scope": self.scope,
                "confidence": format(self.confidence, "f"),
                "expires": self.expires_at.isoformat(),
                "status": self.status.value,
            }
        )


class LessonValidationService:
    def validate(
        self,
        candidate: LessonCandidate,
        validation_id: str,
        evidence_refs: tuple[str, ...],
        passed: bool,
        notes: str,
        now: datetime,
    ) -> ValidatedLesson:
        if type(candidate) is not LessonCandidate or now.tzinfo is None:
            raise TypeError("typed candidate and timezone-aware time required")
        v = LessonValidation(validation_id, candidate.content_sha256, evidence_refs, passed, notes)
        if not passed:
            raise ValueError("failed validation cannot create validated lesson")
        expiry = datetime.fromtimestamp(now.timestamp() + 30 * 86400, tz=UTC)
        return ValidatedLesson(
            "lesson:" + validation_id, candidate.content_sha256, v, candidate.scope, candidate.confidence, expiry
        )

    def expire(self, lesson: ValidatedLesson, now: datetime) -> ValidatedLesson:
        if lesson.status is not LessonStatus.ACTIVE:
            raise ValueError("lesson is not active")
        return (
            ValidatedLesson(
                lesson.lesson_id,
                lesson.candidate_sha256,
                lesson.validation,
                lesson.scope,
                lesson.confidence,
                lesson.expires_at,
                LessonStatus.EXPIRED,
            )
            if now >= lesson.expires_at
            else lesson
        )

    def revoke(self, lesson: ValidatedLesson) -> ValidatedLesson:
        return ValidatedLesson(
            lesson.lesson_id,
            lesson.candidate_sha256,
            lesson.validation,
            lesson.scope,
            lesson.confidence,
            lesson.expires_at,
            LessonStatus.REVOKED,
        )


__all__ = ["CandidateStatus", "LessonStatus", "LessonValidation", "LessonValidationService", "ValidatedLesson"]
