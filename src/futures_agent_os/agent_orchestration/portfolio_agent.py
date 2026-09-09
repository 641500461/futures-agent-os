"""Bounded, proposal-only Portfolio Agent contracts for V3.

The objects in this module express portfolio advice. They deliberately carry
no final quantity, RiskDecision, reservation, Order, Position, or ledger write
authority; deterministic Portfolio & Risk services continue to own those facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.shared_kernel import EntityId, RecordedAt

from .catalog import AgentRoleId, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactKind, ArtifactRef


class PortfolioDisposition(StrEnum):
    ACCEPT = "ACCEPT"
    DOWNWEIGHT = "DOWNWEIGHT"
    HEDGE = "HEDGE"
    REPLACE = "REPLACE"
    REJECT = "REJECT"


class ExposureDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class TargetExposure:
    """A normalized risk-budget target, never an order or contract quantity."""

    instrument: str
    direction: ExposureDirection
    risk_budget_fraction: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.instrument) is not str
            or not self.instrument
            or self.instrument != self.instrument.strip()
            or any(character.isspace() for character in self.instrument)
        ):
            raise ValueError("target exposure requires a canonical instrument")
        if type(self.direction) is not ExposureDirection:
            raise TypeError("target exposure direction must be typed")
        if (
            type(self.risk_budget_fraction) is not Decimal
            or not self.risk_budget_fraction.is_finite()
            or not Decimal("0") <= self.risk_budget_fraction <= Decimal("1")
        ):
            raise ValueError("target exposure risk fraction must be a finite Decimal in [0, 1]")
        if (self.direction is ExposureDirection.FLAT) != (self.risk_budget_fraction == 0):
            raise ValueError("FLAT requires zero risk fraction and directional exposure requires positive risk")


@dataclass(frozen=True, slots=True)
class PortfolioTaskSources:
    """Exact PIT inputs used by a Portfolio Agent task."""

    account_id: EntityId
    trade_plan: ArtifactRef
    critique: ArtifactRef
    portfolio_snapshot: ArtifactRef
    strategy_budget: ArtifactRef
    correlations: tuple[ArtifactRef, ...]
    existing_exposure: Decimal

    def __post_init__(self) -> None:
        if type(self.account_id) is not EntityId or self.account_id.namespace != "account":
            raise ValueError("portfolio sources require a typed account identity")
        exact_kinds = (
            (self.trade_plan, ArtifactKind.TRADE_PLAN_DRAFT),
            (self.critique, ArtifactKind.PRE_TRADE_CRITIQUE),
            (self.portfolio_snapshot, ArtifactKind.PORTFOLIO_SNAPSHOT),
            (self.strategy_budget, ArtifactKind.STRATEGY_BUDGET),
        )
        if any(type(ref) is not ArtifactRef or ref.artifact_kind is not kind for ref, kind in exact_kinds):
            raise ValueError("portfolio sources require exact plan, critique, snapshot and budget artifacts")
        if (
            not isinstance(self.correlations, tuple)
            or not self.correlations
            or any(
                type(ref) is not ArtifactRef or ref.artifact_kind is not ArtifactKind.CORRELATION_ASSESSMENT
                for ref in self.correlations
            )
        ):
            raise ValueError("portfolio sources require correlation assessment artifacts")
        if type(self.existing_exposure) is not Decimal or not self.existing_exposure.is_finite():
            raise ValueError("existing exposure must be a finite Decimal")
        if any(ref.as_of != self.trade_plan.as_of for ref in self.artifacts):
            raise ValueError("portfolio sources must share one point-in-time cutoff")

    @property
    def artifacts(self) -> tuple[ArtifactRef, ...]:
        return (
            self.trade_plan,
            self.critique,
            self.portfolio_snapshot,
            self.strategy_budget,
            *self.correlations,
        )


def _text_tuple(value: tuple[str, ...], label: str, *, allow_empty: bool) -> None:
    if (
        not isinstance(value, tuple)
        or (not allow_empty and not value)
        or any(type(item) is not str or not item.strip() for item in value)
    ):
        raise ValueError(f"portfolio proposal requires canonical {label}")


@dataclass(frozen=True, slots=True)
class PortfolioProposal:
    target_exposure: TargetExposure
    disposition: PortfolioDisposition
    rationale: str
    account_id: EntityId
    strategy_budget_ref: ArtifactRef
    portfolio_snapshot_ref: ArtifactRef
    existing_exposure: Decimal
    correlation_refs: tuple[ArtifactRef, ...]
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    unknowns: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: Decimal

    def __post_init__(self) -> None:
        if type(self.target_exposure) is not TargetExposure or type(self.disposition) is not PortfolioDisposition:
            raise TypeError("portfolio proposal requires typed disposition and target exposure")
        if type(self.rationale) is not str or not self.rationale.strip():
            raise ValueError("portfolio proposal requires a rationale")
        if type(self.account_id) is not EntityId or self.account_id.namespace != "account":
            raise ValueError("portfolio proposal requires a typed account identity")
        if (
            type(self.strategy_budget_ref) is not ArtifactRef
            or self.strategy_budget_ref.artifact_kind is not ArtifactKind.STRATEGY_BUDGET
            or type(self.portfolio_snapshot_ref) is not ArtifactRef
            or self.portfolio_snapshot_ref.artifact_kind is not ArtifactKind.PORTFOLIO_SNAPSHOT
        ):
            raise ValueError("portfolio proposal requires exact budget and snapshot references")
        if type(self.existing_exposure) is not Decimal or not self.existing_exposure.is_finite():
            raise ValueError("portfolio proposal existing exposure must be finite")
        if (
            not isinstance(self.correlation_refs, tuple)
            or not self.correlation_refs
            or any(
                type(ref) is not ArtifactRef or ref.artifact_kind is not ArtifactKind.CORRELATION_ASSESSMENT
                for ref in self.correlation_refs
            )
        ):
            raise ValueError("portfolio proposal requires correlation references")
        _text_tuple(self.evidence, "evidence", allow_empty=False)
        _text_tuple(self.counter_evidence, "counter evidence", allow_empty=False)
        _text_tuple(self.unknowns, "unknowns", allow_empty=True)
        _text_tuple(self.warnings, "warnings", allow_empty=True)
        if (
            type(self.confidence) is not Decimal
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("portfolio confidence must be a finite Decimal in [0, 1]")
        if self.disposition is PortfolioDisposition.REJECT and (
            self.target_exposure.direction is not ExposureDirection.FLAT
            or self.target_exposure.risk_budget_fraction != 0
        ):
            raise ValueError("a rejected proposal cannot retain target risk exposure")


@dataclass(frozen=True, slots=True)
class PortfolioAgentResult:
    proposal: PortfolioProposal
    source_refs: tuple[ArtifactRef, ...]
    as_of: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if type(self.proposal) is not PortfolioProposal:
            raise TypeError("portfolio result requires an exact PortfolioProposal")
        if (
            not isinstance(self.source_refs, tuple)
            or not self.source_refs
            or any(type(ref) is not ArtifactRef for ref in self.source_refs)
        ):
            raise ValueError("portfolio result requires immutable source references")
        if type(self.as_of) is not RecordedAt or type(self.expires_at) is not RecordedAt:
            raise TypeError("portfolio result requires typed time bounds")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("portfolio result expiry must follow its PIT cutoff")
        if any(ref.as_of != self.as_of or ref.created_at.value > self.as_of.value for ref in self.source_refs):
            raise ValueError("portfolio result sources must be available at one PIT cutoff")
        allowed = {str(ref.artifact_id) for ref in self.source_refs} | {ref.content_hash for ref in self.source_refs}
        cited = set((*self.proposal.evidence, *self.proposal.counter_evidence))
        if not cited.issubset(allowed):
            raise ValueError("portfolio evidence must bind immutable input sources")
        if any(str(ref.artifact_id) not in cited and ref.content_hash not in cited for ref in self.source_refs):
            raise ValueError("portfolio result must cite every account, plan, critique, budget and correlation input")


class PortfolioAgent:
    def propose(
        self,
        *,
        sources: PortfolioTaskSources,
        target_exposure: TargetExposure,
        disposition: PortfolioDisposition,
        rationale: str,
        evidence: tuple[str, ...],
        counter_evidence: tuple[str, ...],
        confidence: Decimal,
        unknowns: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> PortfolioProposal:
        if type(sources) is not PortfolioTaskSources:
            raise TypeError("portfolio proposal requires typed source context")
        return PortfolioProposal(
            target_exposure,
            disposition,
            rationale,
            sources.account_id,
            sources.strategy_budget,
            sources.portfolio_snapshot,
            sources.existing_exposure,
            sources.correlations,
            evidence,
            counter_evidence,
            unknowns,
            warnings,
            confidence,
        )

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: PortfolioTaskSources,
        proposal: PortfolioProposal,
    ) -> PortfolioAgentResult:
        if type(task) is not AgentTaskEnvelope or type(sources) is not PortfolioTaskSources:
            raise TypeError("portfolio packaging requires typed task and sources")
        if task.assigned_role_id != AgentRoleId.PORTFOLIO.value:
            raise ValueError("task must be assigned to portfolio role")
        if task.input_artifacts != sources.artifacts:
            raise ValueError("task must name exact immutable portfolio source lineage")
        if task.as_of != sources.trade_plan.as_of:
            raise ValueError("portfolio task and sources must share a PIT cutoff")
        if any(ref.created_at.value > task.as_of.value for ref in sources.artifacts):
            raise ValueError("portfolio source was unavailable at task cutoff")
        validate_task_envelope(task)
        if type(proposal) is not PortfolioProposal:
            raise TypeError("portfolio output must be a PortfolioProposal")
        if ArtifactKind.PORTFOLIO_PROPOSAL not in task.required_outputs:
            raise ValueError("task does not permit a portfolio proposal")
        if (
            proposal.account_id != sources.account_id
            or proposal.strategy_budget_ref != sources.strategy_budget
            or proposal.portfolio_snapshot_ref != sources.portfolio_snapshot
            or proposal.existing_exposure != sources.existing_exposure
            or proposal.correlation_refs != sources.correlations
        ):
            raise ValueError("portfolio proposal context does not match its immutable task sources")
        return PortfolioAgentResult(proposal, sources.artifacts, task.as_of, task.expires_at)
