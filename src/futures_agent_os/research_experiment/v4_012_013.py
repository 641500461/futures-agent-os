"""Research drift triggers and proposal-only governance checks."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from futures_agent_os.shared_kernel import canonical_sha256


class DriftKind(StrEnum):
    OOS_DECAY = "OOS_DECAY"
    REGIME_CHANGE = "REGIME_CHANGE"
    RULE_CHANGE = "RULE_CHANGE"
    LESSON_EXPIRED = "LESSON_EXPIRED"


@dataclass(frozen=True, slots=True)
class ResearchTrigger:
    trigger_id: str
    kind: DriftKind
    subject_ref: str
    reason: str
    paused: bool = False

    def __post_init__(self):
        if not self.trigger_id.strip() or not self.subject_ref.strip() or not self.reason.strip():
            raise ValueError("trigger requires identity, subject and reason")
        if type(self.kind) is not DriftKind or type(self.paused) is not bool:
            raise TypeError("trigger fields are typed")

    @property
    def idempotency_key(self):
        return canonical_sha256({"kind": self.kind.value, "subject": self.subject_ref, "reason": self.reason})


class DriftTriggerEngine:
    def __init__(self):
        self._seen = {}
        self._paused = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def emit(self, kind: DriftKind, subject_ref: str, reason: str) -> ResearchTrigger | None:
        trigger = ResearchTrigger(
            "trigger:" + canonical_sha256({"kind": kind.value, "subject": subject_ref, "reason": reason}),
            kind,
            subject_ref,
            reason,
            self._paused,
        )
        if self._paused or trigger.idempotency_key in self._seen:
            return None
        self._seen[trigger.idempotency_key] = trigger
        return trigger


@dataclass(frozen=True, slots=True)
class GovernanceProposal:
    proposal_id: str
    subject_ref: str
    proposal_kind: str
    evidence_refs: tuple[str, ...]
    complete: bool

    def __post_init__(self):
        if not self.proposal_id.strip() or not self.subject_ref.strip() or not self.proposal_kind.strip():
            raise ValueError("proposal identity required")
        if not self.evidence_refs or not self.complete:
            raise ValueError("governance proposal requires complete evidence")


class GovernanceAgent:
    def inspect(
        self, subject_ref: str, evidence_refs: tuple[str, ...], required_refs: tuple[str, ...], proposal_kind: str
    ) -> GovernanceProposal:
        if not set(required_refs).issubset(evidence_refs):
            raise ValueError("governance evidence is incomplete")
        digest = canonical_sha256({"subject": subject_ref, "kind": proposal_kind, "evidence": evidence_refs})
        return GovernanceProposal("proposal:" + digest, subject_ref, proposal_kind, evidence_refs, True)


__all__ = ["DriftKind", "DriftTriggerEngine", "GovernanceAgent", "GovernanceProposal", "ResearchTrigger"]
