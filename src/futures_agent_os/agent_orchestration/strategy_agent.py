import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol, Tuple

from .catalog import AgentRoleId, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactKind, ArtifactRef
from futures_agent_os.shared_kernel import RecordedAt


class StrategyDecision(StrEnum):
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"
    DEFER = "DEFER"


class StrategyCandidateStatus(StrEnum):
    DRAFT = "DRAFT"
    HISTORICAL_SCREENING = "HISTORICAL_SCREENING"
    OOS_VALIDATION = "OOS_VALIDATION"
    PAPER_EXPERIMENT = "PAPER_EXPERIMENT"
    PROMOTION_CANDIDATE = "PROMOTION_CANDIDATE"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class ProtectionIntent:
    stop_condition: str
    max_loss: str

    def __post_init__(self):
        if any(type(v) is not str or not v.strip() for v in (self.stop_condition, self.max_loss)):
            raise ValueError("protection intent requires stop condition and max loss")
        try:
            loss = Decimal(self.max_loss)
        except InvalidOperation as exc:
            raise ValueError("protection max loss must be a finite positive amount") from exc
        if not loss.is_finite() or loss <= 0:
            raise ValueError("protection max loss must be a finite positive amount")


@dataclass(frozen=True)
class StrategyCandidate:
    thesis: str
    invalidation: str
    evidence: Tuple[str, ...]
    target_risk: str
    exit_intent: str
    decision: StrategyDecision = StrategyDecision.TRADE
    status: StrategyCandidateStatus = StrategyCandidateStatus.DRAFT
    protection_intent: ProtectionIntent | None = None
    target_exposure: Decimal | None = None

    def __post_init__(self):
        if any(
            not isinstance(v, str) or not v.strip()
            for v in (self.thesis, self.invalidation, self.target_risk, self.exit_intent)
        ):
            raise ValueError("strategy candidate requires thesis, invalidation, risk and exit intent")
        if (
            not isinstance(self.evidence, tuple)
            or not self.evidence
            or any(not isinstance(v, str) or not v.strip() for v in self.evidence)
        ):
            raise ValueError("strategy candidate requires non-empty evidence")
        if type(self.decision) is not StrategyDecision or type(self.status) is not StrategyCandidateStatus:
            raise TypeError("strategy candidate decision and status must be typed")
        if self.status is not StrategyCandidateStatus.DRAFT:
            raise ValueError("Strategy Agent can only create DRAFT candidates")
        if self.protection_intent is not None and type(self.protection_intent) is not ProtectionIntent:
            raise TypeError("candidate requires typed protection intent")
        if self.decision is StrategyDecision.TRADE and self.protection_intent is None:
            raise ValueError("TRADE candidate requires protection intent")
        if self.target_exposure is not None and not isinstance(self.target_exposure, Decimal):
            raise TypeError("target exposure must use Decimal")
        if self.target_exposure is not None and not self.target_exposure.is_finite():
            raise ValueError("target exposure must be finite")
        if self.decision is not StrategyDecision.TRADE and (
            self.target_risk != "0" or self.target_exposure not in (None, Decimal("0"))
        ):
            raise ValueError("NO_TRADE and DEFER cannot propose risk or exposure")


@dataclass(frozen=True)
class TradePlanDraft:
    instrument: str
    direction: str
    thesis: str
    invalidation: str
    evidence: tuple[str, ...]
    target_risk: str
    entry_intent: str
    exit_intent: str
    protection_intent: ProtectionIntent
    target_exposure: Decimal | None = None

    def __post_init__(self):
        if any(
            not isinstance(v, str) or not v.strip()
            for v in (
                self.instrument,
                self.direction,
                self.thesis,
                self.invalidation,
                self.target_risk,
                self.entry_intent,
                self.exit_intent,
            )
        ):
            raise ValueError("trade plan draft requires complete intents")
        if (
            not isinstance(self.evidence, tuple)
            or not self.evidence
            or any(type(v) is not str or not v.strip() for v in self.evidence)
        ):
            raise ValueError("trade plan draft requires evidence")
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError("draft direction must be LONG or SHORT")
        if type(self.protection_intent) is not ProtectionIntent:
            raise TypeError("trade plan draft requires protection intent")
        if self.target_exposure is not None and not isinstance(self.target_exposure, Decimal):
            raise TypeError("target exposure must use Decimal")
        if self.target_exposure is not None and not self.target_exposure.is_finite():
            raise ValueError("target exposure must be finite")


@dataclass(frozen=True)
class StrategyTaskSources:
    """Immutable input lineage required before a strategy proposal is packaged."""

    artifacts: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        if not self.artifacts or any(type(item) is not ArtifactRef for item in self.artifacts):
            raise ValueError("strategy sources require immutable artifact references")
        if any(item.as_of != self.artifacts[0].as_of for item in self.artifacts):
            raise ValueError("strategy sources must share one point-in-time cutoff")


@dataclass(frozen=True)
class StrategyAgentResult:
    candidate: StrategyCandidate | None
    draft: TradePlanDraft | None
    source_refs: tuple[ArtifactRef, ...]
    as_of: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if (self.candidate is None) == (self.draft is None):
            raise ValueError("strategy result requires exactly one proposal and immutable sources")
        if self.candidate is not None and type(self.candidate) is not StrategyCandidate:
            raise TypeError("strategy result candidate must use the exact StrategyCandidate contract")
        if self.draft is not None and type(self.draft) is not TradePlanDraft:
            raise TypeError("strategy result draft must use the exact TradePlanDraft contract")
        if (
            not isinstance(self.source_refs, tuple)
            or not self.source_refs
            or any(type(item) is not ArtifactRef for item in self.source_refs)
        ):
            raise ValueError("strategy result requires exactly one proposal and immutable sources")
        if type(self.as_of) is not RecordedAt or type(self.expires_at) is not RecordedAt:
            raise TypeError("strategy result requires typed point-in-time bounds")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("strategy result expiry must follow its point-in-time cutoff")
        if any(item.as_of != self.as_of or item.created_at.value > self.as_of.value for item in self.source_refs):
            raise ValueError("strategy result sources must be available at one point-in-time cutoff")
        allowed_evidence = {str(item.artifact_id) for item in self.source_refs} | {
            item.content_hash for item in self.source_refs
        }
        proposal = self.candidate if self.candidate is not None else self.draft
        if proposal is None or not set(proposal.evidence).issubset(allowed_evidence):
            raise ValueError("strategy result evidence must bind immutable source identities")

    def content_sha256(self) -> str:
        """Return a process-stable digest for the proposal and its exact lineage."""

        if self.candidate is not None:
            candidate = self.candidate
            proposal_payload: dict[str, object] = {
                "kind": "STRATEGY_CANDIDATE",
                "thesis": candidate.thesis,
                "invalidation": candidate.invalidation,
                "evidence": list(candidate.evidence),
                "target_risk": candidate.target_risk,
                "exit_intent": candidate.exit_intent,
                "decision": candidate.decision.value,
                "status": candidate.status.value,
                "protection_intent": (
                    None
                    if candidate.protection_intent is None
                    else {
                        "stop_condition": candidate.protection_intent.stop_condition,
                        "max_loss": candidate.protection_intent.max_loss,
                    }
                ),
                "target_exposure": None if candidate.target_exposure is None else str(candidate.target_exposure),
            }
        else:
            draft = self.draft
            assert draft is not None
            proposal_payload = {
                "kind": "TRADE_PLAN_DRAFT",
                "instrument": draft.instrument,
                "direction": draft.direction,
                "thesis": draft.thesis,
                "invalidation": draft.invalidation,
                "evidence": list(draft.evidence),
                "target_risk": draft.target_risk,
                "entry_intent": draft.entry_intent,
                "exit_intent": draft.exit_intent,
                "protection_intent": {
                    "stop_condition": draft.protection_intent.stop_condition,
                    "max_loss": draft.protection_intent.max_loss,
                },
                "target_exposure": None if draft.target_exposure is None else str(draft.target_exposure),
            }
        payload = {
            "proposal": proposal_payload,
            "source_refs": [
                {
                    "artifact_id": str(item.artifact_id),
                    "artifact_kind": item.artifact_kind.value,
                    "schema_version": str(item.schema_version),
                    "content_hash": item.content_hash,
                    "created_at": str(item.created_at),
                    "as_of": str(item.as_of),
                }
                for item in self.source_refs
            ],
            "as_of": str(self.as_of),
            "expires_at": str(self.expires_at),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class _StrategyOwnerPort(Protocol):
    def execute(self, command: object) -> object: ...
    def revalidate(self, reference: object, *, completed_stage: object, as_of: object) -> bool: ...


class StrategyAgent:
    def package(
        self,
        task: AgentTaskEnvelope,
        sources: StrategyTaskSources,
        proposal: StrategyCandidate | TradePlanDraft,
    ) -> StrategyAgentResult:
        if type(task) is not AgentTaskEnvelope or type(sources) is not StrategyTaskSources:
            raise TypeError("strategy packaging requires typed task and sources")
        if task.assigned_role_id != AgentRoleId.STRATEGY.value:
            raise ValueError("task must be assigned to strategy role")
        if task.input_artifacts != sources.artifacts:
            raise ValueError("task must name exact immutable strategy source lineage")
        if task.as_of != sources.artifacts[0].as_of:
            raise ValueError("strategy task and sources must share point-in-time cutoff")
        if any(ref.created_at.value > task.as_of.value for ref in sources.artifacts):
            raise ValueError("strategy source was unavailable at task cutoff")
        validate_task_envelope(task)
        if type(proposal) not in (StrategyCandidate, TradePlanDraft):
            raise TypeError("strategy output must be a candidate or plan draft")
        allowed_evidence = {str(item.artifact_id) for item in sources.artifacts} | {
            item.content_hash for item in sources.artifacts
        }
        proposal_evidence = proposal.evidence
        if not set(proposal_evidence).issubset(allowed_evidence):
            raise ValueError("strategy evidence must reference an input artifact identity or content hash")
        if task.expires_at.value <= task.as_of.value:
            raise ValueError("strategy task must expire after its point-in-time cutoff")
        expected = (
            ArtifactKind.STRATEGY_CANDIDATE if type(proposal) is StrategyCandidate else ArtifactKind.TRADE_PLAN_DRAFT
        )
        if expected not in task.required_outputs:
            raise ValueError("task does not permit this strategy output")
        return StrategyAgentResult(
            proposal if type(proposal) is StrategyCandidate else None,
            proposal if type(proposal) is TradePlanDraft else None,
            sources.artifacts,
            task.as_of,
            task.expires_at,
        )

    def propose(
        self,
        *,
        thesis: str,
        invalidation: str,
        evidence: tuple[str, ...],
        target_risk: str,
        exit_intent: str,
        decision: StrategyDecision | None = None,
        protection_intent: ProtectionIntent | None = None,
        target_exposure: Decimal | None = None,
    ) -> StrategyCandidate:
        resolved = StrategyDecision.TRADE if decision is None else decision
        return StrategyCandidate(
            thesis,
            invalidation,
            evidence,
            target_risk,
            exit_intent,
            resolved,
            protection_intent=protection_intent,
            target_exposure=target_exposure,
        )

    def draft_trade_plan(
        self,
        *,
        instrument: str,
        direction: str,
        thesis: str,
        invalidation: str,
        evidence: tuple[str, ...],
        target_risk: str,
        entry_intent: str,
        exit_intent: str,
        protection_intent: ProtectionIntent,
        target_exposure: Decimal | None = None,
    ) -> TradePlanDraft:
        return TradePlanDraft(
            instrument,
            direction,
            thesis,
            invalidation,
            evidence,
            target_risk,
            entry_intent,
            exit_intent,
            protection_intent,
            target_exposure,
        )

    def decide_no_trade(
        self, *, thesis: str, invalidation: str, evidence: tuple[str, ...], reason: str
    ) -> StrategyCandidate:
        return self.propose(
            thesis=thesis,
            invalidation=invalidation,
            evidence=evidence,
            target_risk="0",
            exit_intent=reason,
            decision=StrategyDecision.NO_TRADE,
        )

    def defer(self, *, thesis: str, invalidation: str, evidence: tuple[str, ...], reason: str) -> StrategyCandidate:
        return self.propose(
            thesis=thesis,
            invalidation=invalidation,
            evidence=evidence,
            target_risk="0",
            exit_intent=reason,
            decision=StrategyDecision.DEFER,
        )


class StrategyDelegationOwner:
    """Adapter that lets the durable workflow own the Strategy handoff.

    It only materializes a delegation reference.  The workflow checkpoint keeps
    the reference and the injected downstream owner remains responsible for all
    domain effects.
    """

    def __init__(self, downstream: _StrategyOwnerPort, result: StrategyAgentResult) -> None:
        if type(result) is not StrategyAgentResult:
            raise TypeError("strategy delegation requires a validated StrategyAgentResult")
        self._downstream = downstream
        self._result = result

    def execute(self, command: object) -> object:
        from .v3_durable import ReferenceKind, StageDisposition, StageResult, StateReference, WorkflowStage

        if getattr(command, "stage", None) is WorkflowStage.DELEGATION_AND_CHALLENGE:
            digest = self._result.content_sha256()
            return StageResult(
                StageDisposition.ADVANCE, (StateReference(ReferenceKind.DELEGATION, "strategy:" + digest, 1, digest),)
            )
        return self._downstream.execute(command)

    def revalidate(self, reference: object, *, completed_stage: object, as_of: object) -> bool:
        return self._downstream.revalidate(reference, completed_stage=completed_stage, as_of=as_of)
