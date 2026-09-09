"""V3 plan-facing Pre-trade Critic contracts.

This is intentionally separate from the Catalog 1.5 V1 research Critic and
from Learning & Review's post-trade TradeReview/Reflection schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.shared_kernel import RecordedAt

from .catalog import AgentRoleId, V3_CATALOG_VERSION, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactKind, ArtifactRef


class CriticCategory(StrEnum):
    THESIS = "THESIS"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    DATA_LEAKAGE = "DATA_LEAKAGE"
    COST_COVERAGE = "COST_COVERAGE"
    REGIME_FIT = "REGIME_FIT"
    RISK_REWARD = "RISK_REWARD"
    HISTORICAL_FAILURE = "HISTORICAL_FAILURE"


class CriticFindingStatus(StrEnum):
    PASS = "PASS"
    CONCERN = "CONCERN"
    BLOCKER = "BLOCKER"
    UNKNOWN = "UNKNOWN"


class CriticSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CriticVerdict(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    REJECT = "REJECT"
    DEFER = "DEFER"


@dataclass(frozen=True, slots=True)
class CriticCheck:
    category: CriticCategory
    status: CriticFindingStatus
    severity: CriticSeverity
    summary: str
    evidence_refs: tuple[str, ...]
    required_validation: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.category) is not CriticCategory
            or type(self.status) is not CriticFindingStatus
            or type(self.severity) is not CriticSeverity
        ):
            raise TypeError("critic check requires typed category, status and severity")
        if type(self.summary) is not str or not self.summary.strip():
            raise ValueError("critic check requires a summary")
        _texts(self.evidence_refs, "check evidence")
        _texts(self.required_validation, "required validation", allow_empty=True)
        if self.status is not CriticFindingStatus.PASS and not self.required_validation:
            raise ValueError("non-pass critic checks require explicit follow-up validation")


@dataclass(frozen=True, slots=True)
class PlanCriticTaskSources:
    proposal: ArtifactRef
    evidence_synthesis: ArtifactRef
    regime: ArtifactRef
    cost_analysis: ArtifactRef
    leakage_assessment: ArtifactRef
    risk_reward_analysis: ArtifactRef
    historical_failures: ArtifactRef

    def __post_init__(self) -> None:
        if type(self.proposal) is not ArtifactRef or self.proposal.artifact_kind not in {
            ArtifactKind.STRATEGY_CANDIDATE,
            ArtifactKind.TRADE_PLAN_DRAFT,
        }:
            raise ValueError("plan critic requires exactly one strategy candidate or trade-plan draft")
        exact_kinds = (
            (self.evidence_synthesis, ArtifactKind.EVIDENCE_SYNTHESIS),
            (self.regime, ArtifactKind.MARKET_STATE_ASSESSMENT),
            (self.cost_analysis, ArtifactKind.COST_ANALYSIS),
            (self.leakage_assessment, ArtifactKind.LEAKAGE_ASSESSMENT),
            (self.risk_reward_analysis, ArtifactKind.RISK_REWARD_ANALYSIS),
            (self.historical_failures, ArtifactKind.HISTORICAL_FAILURES),
        )
        if any(type(ref) is not ArtifactRef or ref.artifact_kind is not kind for ref, kind in exact_kinds):
            raise ValueError("plan critic requires exact evidence, regime, cost, leakage, risk and failure inputs")
        if any(ref.as_of != self.proposal.as_of for ref in self.artifacts):
            raise ValueError("plan critic sources must share one point-in-time cutoff")

    @property
    def artifacts(self) -> tuple[ArtifactRef, ...]:
        return (
            self.proposal,
            self.evidence_synthesis,
            self.regime,
            self.cost_analysis,
            self.leakage_assessment,
            self.risk_reward_analysis,
            self.historical_failures,
        )


def _texts(value: tuple[str, ...], label: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, tuple)
        or (not allow_empty and not value)
        or any(type(item) is not str or not item.strip() for item in value)
    ):
        raise ValueError(f"pre-trade critique requires canonical {label}")


@dataclass(frozen=True, slots=True)
class PreTradeCritique:
    proposal_ref: ArtifactRef
    checks: tuple[CriticCheck, ...]
    verdict: CriticVerdict
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    gaps: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: Decimal
    iteration: int = 1

    def __post_init__(self) -> None:
        if type(self.proposal_ref) is not ArtifactRef or self.proposal_ref.artifact_kind not in {
            ArtifactKind.STRATEGY_CANDIDATE,
            ArtifactKind.TRADE_PLAN_DRAFT,
        }:
            raise ValueError("pre-trade critique requires a strategy proposal reference")
        if (
            not isinstance(self.checks, tuple)
            or len(self.checks) != len(CriticCategory)
            or any(type(check) is not CriticCheck for check in self.checks)
            or {check.category for check in self.checks} != set(CriticCategory)
        ):
            raise ValueError("pre-trade critique requires each mandatory check exactly once")
        if type(self.verdict) is not CriticVerdict:
            raise TypeError("pre-trade critique verdict must be typed")
        _texts(self.evidence, "evidence")
        _texts(self.counter_evidence, "counter evidence")
        _texts(self.gaps, "gaps", allow_empty=True)
        _texts(self.warnings, "warnings", allow_empty=True)
        if (
            type(self.confidence) is not Decimal
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("critic confidence must be a finite Decimal in [0, 1]")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration != 1:
            raise ValueError("V3 pre-trade critique permits exactly one bounded review iteration")
        statuses = {check.status for check in self.checks}
        if self.verdict is CriticVerdict.PASS and statuses != {CriticFindingStatus.PASS}:
            raise ValueError("PASS requires every mandatory critic check to pass")
        if self.verdict is CriticVerdict.REJECT and CriticFindingStatus.BLOCKER not in statuses:
            raise ValueError("REJECT requires an explicit blocking finding")
        if self.verdict in {CriticVerdict.REVISE, CriticVerdict.DEFER} and statuses == {CriticFindingStatus.PASS}:
            raise ValueError("REVISE or DEFER requires an explicit concern, blocker or unknown")


@dataclass(frozen=True, slots=True)
class PlanCriticResult:
    critique: PreTradeCritique
    source_refs: tuple[ArtifactRef, ...]
    as_of: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if type(self.critique) is not PreTradeCritique:
            raise TypeError("plan critic result requires an exact PreTradeCritique")
        if (
            not isinstance(self.source_refs, tuple)
            or not self.source_refs
            or any(type(ref) is not ArtifactRef for ref in self.source_refs)
        ):
            raise ValueError("plan critic result requires immutable source references")
        if type(self.as_of) is not RecordedAt or type(self.expires_at) is not RecordedAt:
            raise TypeError("plan critic result requires typed time bounds")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("plan critic result expiry must follow its PIT cutoff")
        if any(ref.as_of != self.as_of or ref.created_at.value > self.as_of.value for ref in self.source_refs):
            raise ValueError("plan critic sources must be available at one PIT cutoff")
        cited = set((*self.critique.evidence, *self.critique.counter_evidence))
        cited.update(ref for check in self.critique.checks for ref in check.evidence_refs)
        allowed = {str(ref.artifact_id) for ref in self.source_refs} | {ref.content_hash for ref in self.source_refs}
        if not cited.issubset(allowed):
            raise ValueError("critic evidence must bind immutable input sources")
        if any(str(ref.artifact_id) not in cited and ref.content_hash not in cited for ref in self.source_refs):
            raise ValueError("pre-trade critique must cite every task input")

    @property
    def can_advance(self) -> bool:
        return self.critique.verdict is CriticVerdict.PASS


class PreTradeCritic:
    def review(
        self,
        *,
        sources: PlanCriticTaskSources,
        checks: tuple[CriticCheck, ...],
        verdict: CriticVerdict,
        evidence: tuple[str, ...],
        counter_evidence: tuple[str, ...],
        confidence: Decimal,
        gaps: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> PreTradeCritique:
        if type(sources) is not PlanCriticTaskSources:
            raise TypeError("pre-trade review requires typed task sources")
        return PreTradeCritique(
            sources.proposal,
            checks,
            verdict,
            evidence,
            counter_evidence,
            gaps,
            warnings,
            confidence,
        )

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: PlanCriticTaskSources,
        critique: PreTradeCritique,
    ) -> PlanCriticResult:
        if type(task) is not AgentTaskEnvelope or type(sources) is not PlanCriticTaskSources:
            raise TypeError("pre-trade packaging requires typed task and sources")
        if task.catalog_version != V3_CATALOG_VERSION:
            raise ValueError("plan-facing pre-trade Critic requires V3 Catalog 1.6")
        if task.assigned_role_id != AgentRoleId.PRE_TRADE_CRITIC.value:
            raise ValueError("task must be assigned to pre-trade critic role")
        if task.input_artifacts != sources.artifacts:
            raise ValueError("task must name exact immutable critic source lineage")
        if task.as_of != sources.proposal.as_of:
            raise ValueError("critic task and sources must share a PIT cutoff")
        if any(ref.created_at.value > task.as_of.value for ref in sources.artifacts):
            raise ValueError("critic source was unavailable at task cutoff")
        validate_task_envelope(task)
        if type(critique) is not PreTradeCritique:
            raise TypeError("critic output must be a PreTradeCritique")
        if task.required_outputs != (ArtifactKind.PRE_TRADE_CRITIQUE,):
            raise ValueError("task must require exactly one V3 pre-trade critique")
        if critique.proposal_ref != sources.proposal:
            raise ValueError("critic cannot rewrite or replace its input proposal")
        return PlanCriticResult(critique, sources.artifacts, task.as_of, task.expires_at)
