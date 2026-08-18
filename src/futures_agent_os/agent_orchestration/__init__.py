"""Bounded-agent orchestration contracts; no model or trading runtime."""

from .catalog import AGENT_CATALOG, CATALOG_VERSION, AgentDefinition, AgentRoleId, definition_for, validate_task_envelope
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

__all__ = [
    "AGENT_CATALOG", "CATALOG_VERSION", "AgentBudget", "AgentDefinition", "AgentHandoff",
    "AgentRoleId", "AgentTaskEnvelope", "ArtifactClaim", "ArtifactKind", "ArtifactRef",
    "FailureDisposition", "ResultStatus", "SpecialistResult", "StructuredArtifact", "TriggerSource",
    "definition_for", "validate_task_envelope",
]
