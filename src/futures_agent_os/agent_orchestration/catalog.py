"""The V0 versioned catalog of logical agent roles, not a runtime permission engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from futures_agent_os.shared_kernel import SchemaVersion

from .contracts import AgentBudget, AgentTaskEnvelope, ArtifactKind, FailureDisposition, TriggerSource


class AgentRoleId(StrEnum):
    MAIN = "main"
    MARKET_REGIME = "market_regime"
    RESEARCH = "research"
    STRATEGY = "strategy"
    PORTFOLIO = "portfolio"
    RISK_ANALYST = "risk_analyst"
    EXECUTION_ADVISOR = "execution_advisor"
    PRE_TRADE_CRITIC = "pre_trade_critic"
    EXPERIMENT_MANAGER = "experiment_manager"
    POST_TRADE_REVIEWER = "post_trade_reviewer"
    MEMORY_CURATOR = "memory_curator"
    GOVERNANCE = "governance"


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """A governed role definition that V0 can validate but cannot yet activate."""

    role_id: AgentRoleId
    version: SchemaVersion
    enabled_from: str
    responsibilities: tuple[str, ...]
    non_responsibilities: tuple[str, ...]
    trigger_sources: tuple[TriggerSource, ...]
    trigger_examples: tuple[str, ...]
    input_kinds: tuple[ArtifactKind, ...]
    output_kinds: tuple[ArtifactKind, ...]
    declared_tools: tuple[str, ...]
    permission_boundary: str
    budget: AgentBudget
    failure_disposition: FailureDisposition
    metrics: tuple[str, ...]

    def __post_init__(self) -> None:
        required = (
            self.responsibilities, self.non_responsibilities, self.trigger_sources,
            self.trigger_examples, self.input_kinds, self.output_kinds,
            self.declared_tools, self.metrics,
        )
        if any(not value for value in required) or not self.permission_boundary or not self.enabled_from:
            raise ValueError("agent definitions must declare every catalog contract field")
        if set(self.trigger_sources) != set(TriggerSource):
            raise ValueError("each logical role must document all supported trigger sources")


CATALOG_VERSION = SchemaVersion(1, 0)
_ALL_TRIGGERS = tuple(TriggerSource)
_READ_BUDGET = AgentBudget(4, 16, 12_000, 120)
_RESEARCH_BUDGET = AgentBudget(6, 24, 18_000, 300, 2)


def _definition(
    role_id: AgentRoleId, enabled_from: str, responsibility: str, non_responsibility: str,
    inputs: tuple[ArtifactKind, ...], outputs: tuple[ArtifactKind, ...], tools: tuple[str, ...],
    failure: FailureDisposition, metrics: tuple[str, ...], budget: AgentBudget = _READ_BUDGET,
) -> AgentDefinition:
    return AgentDefinition(
        role_id=role_id,
        version=CATALOG_VERSION,
        enabled_from=enabled_from,
        responsibilities=(responsibility,),
        non_responsibilities=(non_responsibility,),
        trigger_sources=_ALL_TRIGGERS,
        trigger_examples=(
            "user request", "trading-calendar schedule", "market or data event",
            "account or position event", "system health or lifecycle event",
        ),
        input_kinds=inputs,
        output_kinds=outputs,
        declared_tools=tools,
        permission_boundary="Declared allowlist only; V0 grants no executable authority and all domain truth remains deterministic.",
        budget=budget,
        failure_disposition=failure,
        metrics=metrics,
    )


AGENT_CATALOG: tuple[AgentDefinition, ...] = (
    _definition(AgentRoleId.MAIN, "V1", "coordinate bounded cycles and issue TRADE/NO_TRADE/DEFER proposals", "does not schedule, authorize, or decide deterministic risk", (ArtifactKind.RESEARCH_BRIEF, ArtifactKind.MARKET_STATE_ASSESSMENT, ArtifactKind.CRITIQUE), (ArtifactKind.RESEARCH_BRIEF, ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.DECISION_DIGEST, ArtifactKind.ESCALATION_REQUEST), ("market_snapshot", "autonomy_mandate_status", "request_authorization_preflight", "create_trade_plan_draft"), FailureDisposition.DEFER, ("opportunity_coverage", "no_trade_quality", "permission_denials", "user_correction_rate"), _RESEARCH_BUDGET),
    _definition(AgentRoleId.MARKET_REGIME, "V1", "assess market regime and its uncertainty", "does not produce a trade direction or plan", (ArtifactKind.RESEARCH_BRIEF,), (ArtifactKind.MARKET_STATE_ASSESSMENT,), ("market_snapshot", "feature_query", "regime_analysis", "news_evidence_query"), FailureDisposition.DEFER, ("label_stability", "transition_lag", "confidence_calibration")),
    _definition(AgentRoleId.RESEARCH, "V1", "form falsifiable hypotheses and minimum sufficient research", "does not alter a strategy registry or select evidence", (ArtifactKind.MARKET_STATE_ASSESSMENT, ArtifactKind.REFLECTION), (ArtifactKind.HYPOTHESIS, ArtifactKind.RESEARCH_PLAN, ArtifactKind.EVIDENCE_SYNTHESIS), ("historical_data", "backtest", "walk_forward_test", "stress_test"), FailureDisposition.KEEP_DRAFT, ("falsifiability", "evidence_coverage", "failed_experiment_retention"), _RESEARCH_BUDGET),
    _definition(AgentRoleId.STRATEGY, "V3", "turn evidence into a candidate strategy or trade-plan draft", "does not set final quantity or modify active protection", (ArtifactKind.HYPOTHESIS, ArtifactKind.MARKET_STATE_ASSESSMENT, ArtifactKind.EVIDENCE_SYNTHESIS), (ArtifactKind.STRATEGY_CANDIDATE, ArtifactKind.TRADE_PLAN_DRAFT), ("market_snapshot", "feature_query", "strategy_compare", "cost_analysis"), FailureDisposition.DEFER, ("no_trade_quality", "plan_schema_pass_rate", "invalidation_symmetry")),
    _definition(AgentRoleId.PORTFOLIO, "V3", "propose portfolio-level exposure adjustments", "does not create or close positions", (ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.CRITIQUE), (ArtifactKind.PORTFOLIO_PROPOSAL,), ("portfolio_state", "exposure_analysis", "correlation_analysis", "stress_test"), FailureDisposition.FAIL_CLOSED, ("concentration_detection", "optimizer_agreement", "risk_budget_compliance")),
    _definition(AgentRoleId.RISK_ANALYST, "V3", "explain tail, event, and model risks", "does not issue RiskDecision or release a kill switch", (ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.PORTFOLIO_PROPOSAL, ArtifactKind.MARKET_STATE_ASSESSMENT), (ArtifactKind.RISK_ASSESSMENT,), ("risk_check", "stress_test", "scenario_replay", "contract_info"), FailureDisposition.FAIL_CLOSED, ("tail_risk_coverage", "hard_gate_deference", "explanation_accuracy")),
    _definition(AgentRoleId.EXECUTION_ADVISOR, "V3", "recommend a registered execution preference", "does not create orders or change a risk ceiling", (ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.RISK_ASSESSMENT), (ArtifactKind.EXECUTION_RECOMMENDATION,), ("execution_simulator", "cost_analysis", "liquidity_profile"), FailureDisposition.FALLBACK_READ_ONLY, ("cost_error", "fill_rate", "liquidity_robustness")),
    _definition(AgentRoleId.PRE_TRADE_CRITIC, "V1", "independently seek counter-evidence before a plan proceeds", "does not rewrite and silently approve a plan or replace Risk Constitution", (ArtifactKind.TRADE_PLAN_DRAFT, ArtifactKind.EVIDENCE_SYNTHESIS), (ArtifactKind.CRITIQUE,), ("backtest", "cost_analysis", "parameter_stability", "historical_data"), FailureDisposition.FAIL_CLOSED, ("high_risk_defect_recall", "false_veto_rate", "leakage_detection")),
    _definition(AgentRoleId.EXPERIMENT_MANAGER, "V1", "pre-register controlled experiments and evidence thresholds", "does not promote a strategy or hide failed experiments", (ArtifactKind.HYPOTHESIS, ArtifactKind.REFLECTION, ArtifactKind.STRATEGY_CANDIDATE), (ArtifactKind.EXPERIMENT_PLAN,), ("experiment_search", "backtest", "walk_forward_test", "strategy_compare"), FailureDisposition.KEEP_DRAFT, ("preregistration_completeness", "duplicate_rate", "threshold_adherence"), _RESEARCH_BUDGET),
    _definition(AgentRoleId.POST_TRADE_REVIEWER, "V3", "separate process quality from outcome quality after an episode", "does not rewrite historical trading facts or create a lesson", (ArtifactKind.DECISION_DIGEST, ArtifactKind.TRADE_PLAN_DRAFT), (ArtifactKind.TRADE_REVIEW, ArtifactKind.REFLECTION), ("trade_replay", "attribution", "counterfactual_test"), FailureDisposition.KEEP_PENDING_REVIEW, ("process_outcome_separation", "overattribution_rate", "evidence_reference_rate")),
    _definition(AgentRoleId.MEMORY_CURATOR, "V4", "propose evidence-backed lesson lifecycle changes", "does not validate a lesson or remove counterexamples", (ArtifactKind.REFLECTION, ArtifactKind.TRADE_REVIEW, ArtifactKind.EXPERIMENT_PLAN), (ArtifactKind.LESSON_CANDIDATE,), ("memory_search", "experiment_search", "lesson_conflict_check", "lesson_decay_check"), FailureDisposition.KEEP_EXISTING_STATE, ("unvalidated_leak_rate", "conflict_detection", "expiry_recall")),
    _definition(AgentRoleId.GOVERNANCE, "V4", "prepare governed change proposals and evidence requirements", "does not activate or alter prompts, models, strategies, policies, or configuration", (ArtifactKind.EXPERIMENT_PLAN, ArtifactKind.TRADE_REVIEW, ArtifactKind.LESSON_CANDIDATE), (ArtifactKind.CHANGE_PROPOSAL,), ("registry_query", "experiment_search", "audit_query", "deployment_evidence_query"), FailureDisposition.QUARANTINE_CANDIDATE, ("change_classification", "evidence_sufficiency", "privilege_escalation_rate")),
)

_BY_ROLE = {definition.role_id.value: definition for definition in AGENT_CATALOG}


def definition_for(role_id: str) -> AgentDefinition:
    """Resolve only a catalogued role; routing/activation is intentionally future work."""

    try:
        return _BY_ROLE[role_id]
    except KeyError as error:
        raise ValueError("agent role is not present in the versioned catalog") from error


def validate_task_envelope(envelope: AgentTaskEnvelope) -> None:
    """Check a task against its role contract before an orchestrator can dispatch it.

    This is deliberately a static contract check.  It neither resolves a Tool
    Grant nor decides whether an environment has activated the role; V0-006 and
    the Governance context own those future decisions.
    """

    definition = definition_for(envelope.assigned_role_id)
    if envelope.catalog_version != definition.version:
        raise ValueError("task envelope catalog version does not match its role definition")
    if not set(envelope.trigger_sources).issubset(definition.trigger_sources):
        raise ValueError("task envelope trigger is outside the role contract")
    if len(set(envelope.trigger_sources)) != len(envelope.trigger_sources):
        raise ValueError("task envelope trigger sources must be unique")
    if len(set(envelope.allowed_tools)) != len(envelope.allowed_tools):
        raise ValueError("task envelope allowed tools must be unique")
    if len(set(envelope.required_outputs)) != len(envelope.required_outputs):
        raise ValueError("task envelope required outputs must be unique")
    if not {artifact.artifact_kind for artifact in envelope.input_artifacts}.issubset(definition.input_kinds):
        raise ValueError("task envelope input artifact is outside the role contract")
    if not set(envelope.allowed_tools).issubset(definition.declared_tools):
        raise ValueError("task envelope tool is outside the role declaration")
    if not set(envelope.required_outputs).issubset(definition.output_kinds):
        raise ValueError("task envelope output is outside the role contract")
    limits = definition.budget
    requested = envelope.budget
    if any(
        actual > maximum
        for actual, maximum in zip(
            (
                requested.max_turns,
                requested.max_tool_calls,
                requested.max_tokens,
                requested.timeout_seconds,
                requested.max_parallel_tasks,
            ),
            (
                limits.max_turns,
                limits.max_tool_calls,
                limits.max_tokens,
                limits.timeout_seconds,
                limits.max_parallel_tasks,
            ),
            strict=True,
        )
    ):
        raise ValueError("task envelope budget exceeds the role contract")
    if envelope.may_delegate_research and definition.role_id not in {
        AgentRoleId.MAIN,
        AgentRoleId.RESEARCH,
        AgentRoleId.EXPERIMENT_MANAGER,
    }:
        raise ValueError("only bounded coordination and research roles may request sub-research")
