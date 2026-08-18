"""Versioned, static Tool Registry contracts owned by Governance & Registry.

The registry describes what a tool contract is.  It deliberately does not
activate an implementation, issue a ToolGrant, invoke a tool, or make a
trading decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from futures_agent_os.shared_kernel import SchemaVersion


_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolPermissionTier(IntEnum):
    """Ordered capability tiers; a grant still names exact tool versions."""

    READ_ONLY = 0
    RESEARCH_REQUEST = 1
    PROPOSAL = 2
    MANDATE_SCOPED_SIMULATION = 3
    PLAN_APPROVAL = 4
    PROMOTION = 5
    ACTIVATION = 6


@dataclass(frozen=True, slots=True, order=True)
class ToolRef:
    """An immutable exact ToolVersion reference; never resolves ``latest``."""

    tool_id: str
    version: SchemaVersion

    def __post_init__(self) -> None:
        if not _TOOL_ID.fullmatch(self.tool_id):
            raise ValueError("tool id must be canonical lower_snake_case")

    def __str__(self) -> str:
        return f"{self.tool_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """The immutable contract for a single version of a Tool."""

    ref: ToolRef
    permission_tier: ToolPermissionTier
    request_schema: SchemaVersion
    response_schema: SchemaVersion
    owner_context: str
    description: str

    def __post_init__(self) -> None:
        if not self.owner_context or not self.description:
            raise ValueError("tool definitions require an owner context and description")


class ToolRegistry:
    """An immutable registry that only permits exact version resolution."""

    def __init__(self, version: SchemaVersion, definitions: tuple[ToolDefinition, ...]) -> None:
        if not definitions:
            raise ValueError("tool registry requires at least one definition")
        by_ref = {definition.ref: definition for definition in definitions}
        if len(by_ref) != len(definitions):
            raise ValueError("tool registry cannot contain duplicate tool versions")
        self._version = version
        self._definitions = tuple(
            sorted(definitions, key=lambda definition: (definition.ref.tool_id, definition.ref.version))
        )
        self._by_ref = by_ref

    @property
    def version(self) -> SchemaVersion:
        return self._version

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    def resolve_exact(self, ref: ToolRef) -> ToolDefinition | None:
        return self._by_ref.get(ref)

    def has_tool_id(self, tool_id: str) -> bool:
        return any(definition.ref.tool_id == tool_id for definition in self._definitions)


TOOL_REGISTRY_VERSION = SchemaVersion(1, 0)
_V1 = SchemaVersion(1, 0)


def _tool(
    tool_id: str,
    tier: ToolPermissionTier,
    owner_context: str,
    description: str | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        ref=ToolRef(tool_id, _V1),
        permission_tier=tier,
        request_schema=_V1,
        response_schema=_V1,
        owner_context=owner_context,
        description=description or f"V0 static contract for {tool_id}",
    )


# This covers every catalog declaration plus the later governed lifecycle
# contracts.  Definitions describe potential capability only; nothing here is
# enabled or executable in V0.
TOOL_REGISTRY = ToolRegistry(
    TOOL_REGISTRY_VERSION,
    (
        *(
            _tool(name, ToolPermissionTier.READ_ONLY, "Reference & Market Data")
            for name in (
                "market_snapshot",
                "historical_data",
                "contract_info",
            )
        ),
        *(
            _tool(name, ToolPermissionTier.READ_ONLY, "Market Intelligence")
            for name in (
                "feature_query",
                "regime_analysis",
                "news_evidence_query",
                "liquidity_profile",
            )
        ),
        *(
            _tool(name, ToolPermissionTier.READ_ONLY, "Research & Experiment")
            for name in (
                "strategy_compare",
                "cost_analysis",
                "scenario_replay",
                "parameter_stability",
                "experiment_search",
            )
        ),
        *(
            _tool(name, ToolPermissionTier.READ_ONLY, "Portfolio & Risk")
            for name in (
                "portfolio_state",
                "exposure_analysis",
                "correlation_analysis",
            )
        ),
        _tool(
            "risk_check",
            ToolPermissionTier.READ_ONLY,
            "Portfolio & Risk",
            "Non-authoritative read-only Risk Constitution preview; only Portfolio & Risk may issue a formal RiskDecision.",
        ),
        _tool("execution_simulator", ToolPermissionTier.READ_ONLY, "Execution & Simulation"),
        *(
            _tool(name, ToolPermissionTier.READ_ONLY, "Learning & Review")
            for name in (
                "trade_replay",
                "attribution",
                "memory_search",
                "lesson_conflict_check",
                "lesson_decay_check",
            )
        ),
        *(
            _tool(name, ToolPermissionTier.READ_ONLY, "Governance & Registry")
            for name in (
                "registry_query",
                "audit_query",
                "deployment_evidence_query",
            )
        ),
        _tool("autonomy_mandate_status", ToolPermissionTier.READ_ONLY, "Decision"),
        *(
            _tool(name, ToolPermissionTier.RESEARCH_REQUEST, "Research & Experiment")
            for name in (
                "backtest",
                "walk_forward_test",
                "stress_test",
                "counterfactual_test",
            )
        ),
        _tool("create_trade_plan_draft", ToolPermissionTier.PROPOSAL, "Decision"),
        _tool("create_change_proposal", ToolPermissionTier.PROPOSAL, "Governance & Registry"),
        _tool("request_authorization_preflight", ToolPermissionTier.MANDATE_SCOPED_SIMULATION, "Decision"),
        _tool("reserve_risk_budget", ToolPermissionTier.MANDATE_SCOPED_SIMULATION, "Portfolio & Risk"),
        _tool("request_final_autonomy_gate", ToolPermissionTier.MANDATE_SCOPED_SIMULATION, "Decision"),
        _tool("submit_trade_plan", ToolPermissionTier.MANDATE_SCOPED_SIMULATION, "Execution & Simulation"),
        _tool("request_plan_approval", ToolPermissionTier.PLAN_APPROVAL, "Decision"),
        _tool("submit_improvement_proposal", ToolPermissionTier.PROMOTION, "Governance & Registry"),
        _tool("request_activation", ToolPermissionTier.ACTIVATION, "Governance & Registry"),
    ),
)
