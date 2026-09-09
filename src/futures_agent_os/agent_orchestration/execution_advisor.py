"""Proposal-only Execution Advisor bound to the implemented V2 fill semantics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from futures_agent_os.execution_simulation import FillOrderType
from futures_agent_os.shared_kernel import RecordedAt

from .catalog import AgentRoleId, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactKind, ArtifactRef
from .risk_analyst_agent import RiskPreflightDisposition


class ExecutionUrgency(StrEnum):
    PATIENT = "PATIENT"
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class SimulationFidelity(StrEnum):
    L1_BAR = "L1_BAR"
    L2_EVENT = "L2_EVENT"


@dataclass(frozen=True, slots=True)
class ExecutionAlgorithmActivation:
    """Governance-owned snapshot; the advisor cannot add algorithms to it."""

    source_ref: ArtifactRef
    active_algorithms: tuple[FillOrderType, ...]

    def __post_init__(self) -> None:
        if (
            type(self.source_ref) is not ArtifactRef
            or self.source_ref.artifact_kind is not ArtifactKind.EXECUTION_ALGORITHM_ACTIVATION
        ):
            raise ValueError("execution activation requires an exact governance artifact")
        if (
            not isinstance(self.active_algorithms, tuple)
            or len(self.active_algorithms) < 2
            or any(type(algorithm) is not FillOrderType for algorithm in self.active_algorithms)
            or len(set(self.active_algorithms)) != len(self.active_algorithms)
        ):
            raise ValueError("execution activation requires at least two unique implemented V2 algorithms")


@dataclass(frozen=True, slots=True)
class ExecutionSimulationEstimate:
    algorithm: FillOrderType
    estimated_cost: Decimal
    fill_probability: Decimal
    fidelity: SimulationFidelity
    source_ref: ArtifactRef

    def __post_init__(self) -> None:
        if type(self.algorithm) is not FillOrderType or type(self.fidelity) is not SimulationFidelity:
            raise TypeError("execution estimate requires typed V2 algorithm and fidelity")
        if type(self.estimated_cost) is not Decimal or not self.estimated_cost.is_finite() or self.estimated_cost < 0:
            raise ValueError("execution cost must be a finite non-negative Decimal")
        if (
            type(self.fill_probability) is not Decimal
            or not self.fill_probability.is_finite()
            or not Decimal("0") <= self.fill_probability <= Decimal("1")
        ):
            raise ValueError("fill probability must be a finite Decimal in [0, 1]")
        if (
            type(self.source_ref) is not ArtifactRef
            or self.source_ref.artifact_kind is not ArtifactKind.EXECUTION_SIMULATION_RESULT
        ):
            raise ValueError("execution estimate requires an exact simulation result artifact")


@dataclass(frozen=True, slots=True)
class ExecutionTaskSources:
    trade_plan: ArtifactRef
    portfolio_proposal: ArtifactRef
    risk_assessment: ArtifactRef
    risk_preflight: ArtifactRef
    risk_preflight_disposition: RiskPreflightDisposition
    activation: ExecutionAlgorithmActivation
    liquidity_profile: ArtifactRef
    cost_analysis: ArtifactRef
    simulations: tuple[ExecutionSimulationEstimate, ...]

    def __post_init__(self) -> None:
        exact_kinds = (
            (self.trade_plan, ArtifactKind.TRADE_PLAN_DRAFT),
            (self.portfolio_proposal, ArtifactKind.PORTFOLIO_PROPOSAL),
            (self.risk_assessment, ArtifactKind.RISK_ASSESSMENT),
            (self.risk_preflight, ArtifactKind.RISK_PREFLIGHT),
            (self.liquidity_profile, ArtifactKind.LIQUIDITY_PROFILE),
            (self.cost_analysis, ArtifactKind.COST_ANALYSIS),
        )
        if any(type(ref) is not ArtifactRef or ref.artifact_kind is not kind for ref, kind in exact_kinds):
            raise ValueError("execution sources require exact plan, portfolio, risk, liquidity and cost artifacts")
        if type(self.risk_preflight_disposition) is not RiskPreflightDisposition:
            raise TypeError("execution sources require a typed risk preflight disposition")
        if self.risk_preflight_disposition not in {
            RiskPreflightDisposition.PASS,
            RiskPreflightDisposition.MODIFY,
        }:
            raise ValueError("execution advice cannot run after a hard risk preflight outcome")
        if type(self.activation) is not ExecutionAlgorithmActivation:
            raise TypeError("execution sources require a typed activation snapshot")
        if (
            not isinstance(self.simulations, tuple)
            or any(type(item) is not ExecutionSimulationEstimate for item in self.simulations)
            or tuple(item.algorithm for item in self.simulations) != self.activation.active_algorithms
        ):
            raise ValueError("execution simulations must exactly cover active algorithms in activation order")
        if any(ref.as_of != self.trade_plan.as_of for ref in self.artifacts):
            raise ValueError("execution sources must share one point-in-time cutoff")

    @property
    def artifacts(self) -> tuple[ArtifactRef, ...]:
        return (
            self.trade_plan,
            self.portfolio_proposal,
            self.risk_assessment,
            self.risk_preflight,
            self.activation.source_ref,
            self.liquidity_profile,
            self.cost_analysis,
            *(item.source_ref for item in self.simulations),
        )


class ExecutionEvidenceVerifier(Protocol):
    """Read-only owner port for activation and deterministic simulator facts."""

    def active_algorithms(self, reference: ArtifactRef, *, as_of: RecordedAt) -> tuple[FillOrderType, ...]: ...

    def verify_simulation(self, estimate: ExecutionSimulationEstimate, *, as_of: RecordedAt) -> bool: ...


def _texts(value: tuple[str, ...], label: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, tuple)
        or (not allow_empty and not value)
        or any(type(item) is not str or not item.strip() for item in value)
    ):
        raise ValueError(f"execution recommendation requires canonical {label}")


@dataclass(frozen=True, slots=True)
class ExecutionRecommendation:
    algorithm: FillOrderType
    urgency: ExecutionUrgency
    rationale: str
    cancel_conditions: tuple[str, ...]
    comparisons: tuple[ExecutionSimulationEstimate, ...]
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    unknowns: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: Decimal

    def __post_init__(self) -> None:
        if type(self.algorithm) is not FillOrderType or type(self.urgency) is not ExecutionUrgency:
            raise TypeError("execution recommendation requires typed algorithm and urgency")
        if type(self.rationale) is not str or not self.rationale.strip():
            raise ValueError("execution recommendation requires a rationale")
        _texts(self.cancel_conditions, "cancel conditions")
        if (
            not isinstance(self.comparisons, tuple)
            or len(self.comparisons) < 2
            or any(type(item) is not ExecutionSimulationEstimate for item in self.comparisons)
            or self.algorithm not in {item.algorithm for item in self.comparisons}
        ):
            raise ValueError("execution recommendation requires comparable simulation estimates")
        _texts(self.evidence, "evidence")
        _texts(self.counter_evidence, "counter evidence")
        _texts(self.unknowns, "unknowns", allow_empty=True)
        _texts(self.warnings, "warnings", allow_empty=True)
        if (
            type(self.confidence) is not Decimal
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("execution confidence must be a finite Decimal in [0, 1]")


@dataclass(frozen=True, slots=True)
class ExecutionAdvisorResult:
    recommendation: ExecutionRecommendation
    source_refs: tuple[ArtifactRef, ...]
    as_of: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if type(self.recommendation) is not ExecutionRecommendation:
            raise TypeError("execution result requires an exact recommendation")
        if (
            not isinstance(self.source_refs, tuple)
            or not self.source_refs
            or any(type(ref) is not ArtifactRef for ref in self.source_refs)
        ):
            raise ValueError("execution result requires immutable source references")
        if type(self.as_of) is not RecordedAt or type(self.expires_at) is not RecordedAt:
            raise TypeError("execution result requires typed time bounds")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("execution result expiry must follow its PIT cutoff")
        if any(ref.as_of != self.as_of or ref.created_at.value > self.as_of.value for ref in self.source_refs):
            raise ValueError("execution result sources must be available at one PIT cutoff")
        cited = set((*self.recommendation.evidence, *self.recommendation.counter_evidence))
        cited.update(item.source_ref.content_hash for item in self.recommendation.comparisons)
        allowed = {str(ref.artifact_id) for ref in self.source_refs} | {ref.content_hash for ref in self.source_refs}
        if not cited.issubset(allowed):
            raise ValueError("execution evidence must bind immutable input sources")
        if any(str(ref.artifact_id) not in cited and ref.content_hash not in cited for ref in self.source_refs):
            raise ValueError("execution recommendation must cite every task input")


class ExecutionAdvisor:
    def __init__(self, verifier: ExecutionEvidenceVerifier) -> None:
        self._verifier = verifier

    def _verify_sources(self, sources: ExecutionTaskSources) -> None:
        as_of = sources.trade_plan.as_of
        active = self._verifier.active_algorithms(sources.activation.source_ref, as_of=as_of)
        if (
            not isinstance(active, tuple)
            or any(type(algorithm) is not FillOrderType for algorithm in active)
            or active != sources.activation.active_algorithms
        ):
            raise ValueError("execution activation snapshot is not current owner state")
        if any(not self._verifier.verify_simulation(estimate, as_of=as_of) for estimate in sources.simulations):
            raise ValueError("execution simulation result is not verified by its deterministic owner")

    def recommend(
        self,
        *,
        sources: ExecutionTaskSources,
        algorithm: FillOrderType,
        urgency: ExecutionUrgency,
        rationale: str,
        cancel_conditions: tuple[str, ...],
        evidence: tuple[str, ...],
        counter_evidence: tuple[str, ...],
        confidence: Decimal,
        unknowns: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> ExecutionRecommendation:
        if type(sources) is not ExecutionTaskSources:
            raise TypeError("execution recommendation requires typed sources")
        self._verify_sources(sources)
        if type(algorithm) is not FillOrderType or algorithm not in sources.activation.active_algorithms:
            raise ValueError("execution recommendation must select an active implemented V2 algorithm")
        return ExecutionRecommendation(
            algorithm,
            urgency,
            rationale,
            cancel_conditions,
            sources.simulations,
            evidence,
            counter_evidence,
            unknowns,
            warnings,
            confidence,
        )

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: ExecutionTaskSources,
        recommendation: ExecutionRecommendation,
    ) -> ExecutionAdvisorResult:
        if type(task) is not AgentTaskEnvelope or type(sources) is not ExecutionTaskSources:
            raise TypeError("execution packaging requires typed task and sources")
        if task.assigned_role_id != AgentRoleId.EXECUTION_ADVISOR.value:
            raise ValueError("task must be assigned to execution advisor role")
        if task.input_artifacts != sources.artifacts:
            raise ValueError("task must name exact immutable execution source lineage")
        if task.as_of != sources.trade_plan.as_of:
            raise ValueError("execution task and sources must share a PIT cutoff")
        if any(ref.created_at.value > task.as_of.value for ref in sources.artifacts):
            raise ValueError("execution source was unavailable at task cutoff")
        validate_task_envelope(task)
        self._verify_sources(sources)
        if type(recommendation) is not ExecutionRecommendation:
            raise TypeError("execution output must be an ExecutionRecommendation")
        if ArtifactKind.EXECUTION_RECOMMENDATION not in task.required_outputs:
            raise ValueError("task does not permit an execution recommendation")
        if recommendation.algorithm not in sources.activation.active_algorithms:
            raise ValueError("execution recommendation selected an inactive algorithm")
        if recommendation.comparisons != sources.simulations:
            raise ValueError("execution recommendation changed deterministic simulation comparisons")
        return ExecutionAdvisorResult(recommendation, sources.artifacts, task.as_of, task.expires_at)
