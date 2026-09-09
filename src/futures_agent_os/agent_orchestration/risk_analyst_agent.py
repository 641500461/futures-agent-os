"""Non-authoritative V3 Risk Analyst contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from futures_agent_os.shared_kernel import RecordedAt

from .catalog import AgentRoleId, validate_task_envelope
from .contracts import AgentTaskEnvelope, ArtifactKind, ArtifactRef


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskAdvisory(StrEnum):
    """Advice only; intentionally contains no APPROVE/PERMIT outcome."""

    CONTINUE_REVIEW = "CONTINUE_REVIEW"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    REQUEST_EXPERIMENT = "REQUEST_EXPERIMENT"
    DEFER = "DEFER"
    REJECT_PROPOSAL = "REJECT_PROPOSAL"


class RiskPreflightDisposition(StrEnum):
    PASS = "PASS"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    PROTECT_ONLY = "PROTECT_ONLY"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class RiskScenario:
    name: str
    description: str
    severity: RiskSeverity
    evidence_ref: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value.strip() for value in (self.name, self.description, self.evidence_ref)
        ):
            raise ValueError("risk scenario requires a name, description and evidence reference")
        if type(self.severity) is not RiskSeverity:
            raise TypeError("risk scenario severity must be typed")


@dataclass(frozen=True, slots=True)
class RiskTaskSources:
    trade_plan: ArtifactRef
    portfolio_proposal: ArtifactRef
    regime: ArtifactRef
    risk_preflight: ArtifactRef
    stress_results: tuple[ArtifactRef, ...]
    preflight_disposition: RiskPreflightDisposition

    def __post_init__(self) -> None:
        exact_kinds = (
            (self.trade_plan, ArtifactKind.TRADE_PLAN_DRAFT),
            (self.portfolio_proposal, ArtifactKind.PORTFOLIO_PROPOSAL),
            (self.regime, ArtifactKind.MARKET_STATE_ASSESSMENT),
            (self.risk_preflight, ArtifactKind.RISK_PREFLIGHT),
        )
        if any(type(ref) is not ArtifactRef or ref.artifact_kind is not kind for ref, kind in exact_kinds):
            raise ValueError("risk sources require exact plan, portfolio, regime and preflight artifacts")
        if (
            not isinstance(self.stress_results, tuple)
            or not self.stress_results
            or any(
                type(ref) is not ArtifactRef or ref.artifact_kind is not ArtifactKind.STRESS_TEST_RESULT
                for ref in self.stress_results
            )
        ):
            raise ValueError("risk sources require stress-test result artifacts")
        if type(self.preflight_disposition) is not RiskPreflightDisposition:
            raise TypeError("risk sources require a typed preflight disposition")
        if any(ref.as_of != self.trade_plan.as_of for ref in self.artifacts):
            raise ValueError("risk sources must share one point-in-time cutoff")

    @property
    def artifacts(self) -> tuple[ArtifactRef, ...]:
        return (self.trade_plan, self.portfolio_proposal, self.regime, self.risk_preflight, *self.stress_results)


def _texts(value: tuple[str, ...], label: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, tuple)
        or (not allow_empty and not value)
        or any(type(item) is not str or not item.strip() for item in value)
    ):
        raise ValueError(f"risk assessment requires canonical {label}")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    main_risks: tuple[str, ...]
    scenarios: tuple[RiskScenario, ...]
    mitigations: tuple[str, ...]
    unknowns: tuple[str, ...]
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: Decimal
    advisory: RiskAdvisory
    observed_preflight: RiskPreflightDisposition

    def __post_init__(self) -> None:
        _texts(self.main_risks, "main risks")
        if (
            not isinstance(self.scenarios, tuple)
            or not self.scenarios
            or any(type(scenario) is not RiskScenario for scenario in self.scenarios)
        ):
            raise ValueError("risk assessment requires typed tail scenarios")
        _texts(self.mitigations, "mitigations")
        _texts(self.unknowns, "unknown risks")
        _texts(self.evidence, "evidence")
        _texts(self.counter_evidence, "counter evidence")
        _texts(self.warnings, "warnings", allow_empty=True)
        if (
            type(self.confidence) is not Decimal
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("risk confidence must be a finite Decimal in [0, 1]")
        if type(self.advisory) is not RiskAdvisory or type(self.observed_preflight) is not RiskPreflightDisposition:
            raise TypeError("risk assessment requires typed advisory and preflight disposition")
        if self.observed_preflight in {
            RiskPreflightDisposition.REJECT,
            RiskPreflightDisposition.PROTECT_ONLY,
            RiskPreflightDisposition.HALT,
        } and self.advisory not in {RiskAdvisory.DEFER, RiskAdvisory.REJECT_PROPOSAL}:
            raise ValueError("risk advice cannot soften a hard preflight outcome")


@dataclass(frozen=True, slots=True)
class RiskAnalystResult:
    assessment: RiskAssessment
    source_refs: tuple[ArtifactRef, ...]
    as_of: RecordedAt
    expires_at: RecordedAt

    def __post_init__(self) -> None:
        if type(self.assessment) is not RiskAssessment:
            raise TypeError("risk result requires an exact RiskAssessment")
        if (
            not isinstance(self.source_refs, tuple)
            or not self.source_refs
            or any(type(ref) is not ArtifactRef for ref in self.source_refs)
        ):
            raise ValueError("risk result requires immutable source references")
        if type(self.as_of) is not RecordedAt or type(self.expires_at) is not RecordedAt:
            raise TypeError("risk result requires typed time bounds")
        if self.expires_at.value <= self.as_of.value:
            raise ValueError("risk result expiry must follow its PIT cutoff")
        if any(ref.as_of != self.as_of or ref.created_at.value > self.as_of.value for ref in self.source_refs):
            raise ValueError("risk result sources must be available at one PIT cutoff")
        cited = set((*self.assessment.evidence, *self.assessment.counter_evidence))
        cited.update(scenario.evidence_ref for scenario in self.assessment.scenarios)
        allowed = {str(ref.artifact_id) for ref in self.source_refs} | {ref.content_hash for ref in self.source_refs}
        if not cited.issubset(allowed):
            raise ValueError("risk evidence must bind immutable input sources")
        if any(str(ref.artifact_id) not in cited and ref.content_hash not in cited for ref in self.source_refs):
            raise ValueError("risk assessment must cite every plan, portfolio, regime, preflight and stress input")


class RiskAnalystAgent:
    def assess(
        self,
        *,
        sources: RiskTaskSources,
        main_risks: tuple[str, ...],
        scenarios: tuple[RiskScenario, ...],
        mitigations: tuple[str, ...],
        unknowns: tuple[str, ...],
        evidence: tuple[str, ...],
        counter_evidence: tuple[str, ...],
        confidence: Decimal,
        advisory: RiskAdvisory,
        warnings: tuple[str, ...] = (),
    ) -> RiskAssessment:
        if type(sources) is not RiskTaskSources:
            raise TypeError("risk assessment requires typed sources")
        return RiskAssessment(
            main_risks,
            scenarios,
            mitigations,
            unknowns,
            evidence,
            counter_evidence,
            warnings,
            confidence,
            advisory,
            sources.preflight_disposition,
        )

    def package(
        self,
        task: AgentTaskEnvelope,
        sources: RiskTaskSources,
        assessment: RiskAssessment,
    ) -> RiskAnalystResult:
        if type(task) is not AgentTaskEnvelope or type(sources) is not RiskTaskSources:
            raise TypeError("risk packaging requires typed task and sources")
        if task.assigned_role_id != AgentRoleId.RISK_ANALYST.value:
            raise ValueError("task must be assigned to risk analyst role")
        if task.input_artifacts != sources.artifacts:
            raise ValueError("task must name exact immutable risk source lineage")
        if task.as_of != sources.trade_plan.as_of:
            raise ValueError("risk task and sources must share a PIT cutoff")
        if any(ref.created_at.value > task.as_of.value for ref in sources.artifacts):
            raise ValueError("risk source was unavailable at task cutoff")
        validate_task_envelope(task)
        if type(assessment) is not RiskAssessment:
            raise TypeError("risk output must be a RiskAssessment")
        if ArtifactKind.RISK_ASSESSMENT not in task.required_outputs:
            raise ValueError("task does not permit a risk assessment")
        if assessment.observed_preflight is not sources.preflight_disposition:
            raise ValueError("risk assessment cannot replace the observed preflight outcome")
        return RiskAnalystResult(assessment, sources.artifacts, task.as_of, task.expires_at)
