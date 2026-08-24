"""Bounded-agent orchestration contracts; no model or trading runtime."""

from .catalog import (
    AGENT_CATALOG,
    CATALOG_VERSION,
    AgentDefinition,
    AgentRoleId,
    definition_for,
    validate_task_envelope,
)
from .contracts import (
    AgentBudget,
    AgentHandoff,
    AgentTaskEnvelope,
    ArtifactClaim,
    ArtifactKind,
    ArtifactRef,
    FailureDisposition,
    ResultStatus,
    SpecialistResult,
    StructuredArtifact,
    TriggerSource,
)
from .tool_permissions import (
    SimulationEnvironment,
    ToolAuthorizationDecision,
    ToolAuthorizationOutcome,
    ToolAuthorizer,
    ToolCallRequest,
    ToolGrant,
    ToolGrantStatus,
    ToolScope,
)
from .market_regime_agent import (
    MarketRegimeAgent,
    MarketRegimeTaskSources,
)
from .research_agent import ResearchAgent, ResearchAgentResult, ResearchTaskSources

__all__ = [
    "AGENT_CATALOG",
    "CATALOG_VERSION",
    "AgentBudget",
    "AgentDefinition",
    "AgentHandoff",
    "AgentRoleId",
    "AgentTaskEnvelope",
    "ArtifactClaim",
    "ArtifactKind",
    "ArtifactRef",
    "FailureDisposition",
    "ResultStatus",
    "SpecialistResult",
    "StructuredArtifact",
    "TriggerSource",
    "definition_for",
    "validate_task_envelope",
    "SimulationEnvironment",
    "ToolAuthorizationDecision",
    "ToolAuthorizationOutcome",
    "ToolAuthorizer",
    "ToolCallRequest",
    "ToolGrant",
    "ToolGrantStatus",
    "ToolScope",
    "MarketRegimeAgent",
    "MarketRegimeTaskSources",
    "ResearchAgent",
    "ResearchAgentResult",
    "ResearchTaskSources",
]
