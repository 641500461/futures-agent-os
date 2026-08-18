"""Default-deny, deterministic ToolGrant authorization contracts.

This is intentionally a *pre-invocation* contract.  It validates a requested
tool capability and emits an auditable decision, but never invokes tools,
models, commands, databases, or any trading workflow.  Mandates, plan
approvals, risk decisions, and registry activations remain separate domain
facts and are not accepted as substitutes for a ToolGrant.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from futures_agent_os.governance_registry import ToolPermissionTier, ToolRef, ToolRegistry
from futures_agent_os.shared_kernel import EntityId, ReasonCode, RecordedAt, SchemaVersion, TraceContext

from .catalog import definition_for


_SCOPE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$")


class ToolGrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"


class ToolAuthorizationOutcome(StrEnum):
    PERMIT = "PERMIT"
    DENY = "DENY"


class SimulationEnvironment(StrEnum):
    """Only isolated environments are representable by this V0 contract."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    SIM_PROD = "sim_prod"


@dataclass(frozen=True, slots=True)
class ToolScope:
    """The resource dimensions over which a grant may be narrowed.

    An empty selector is intentionally unbounded for that one dimension.  V0
    rejects such broad selectors for simulation-or-higher grants, while lower
    risk tiers may use them.  A request can never expand a non-empty selector.
    """

    account_ids: frozenset[str] = frozenset()
    strategy_ids: frozenset[str] = frozenset()
    instrument_ids: frozenset[str] = frozenset()
    policy_refs: frozenset[str] = frozenset()
    governed_artifact_refs: frozenset[str] = frozenset()
    environments: frozenset[SimulationEnvironment] = frozenset()

    def __post_init__(self) -> None:
        for values in (
            self.account_ids,
            self.strategy_ids,
            self.instrument_ids,
            self.policy_refs,
            self.governed_artifact_refs,
        ):
            if not isinstance(values, frozenset):
                raise TypeError("tool scope selectors must be immutable frozensets")
            if any(not _SCOPE_TOKEN.fullmatch(value) for value in values):
                raise ValueError("tool scope identifiers must be stable non-empty tokens")
        if not isinstance(self.environments, frozenset):
            raise TypeError("tool scope environments must be an immutable frozenset")
        if any(not isinstance(value, SimulationEnvironment) for value in self.environments):
            raise ValueError("tool scope environments must be isolated simulation environments")

    def contains(self, requested: ToolScope) -> bool:
        """Return whether this grant selector contains every requested scope."""

        return all(
            not allowed or (bool(actual) and actual.issubset(allowed))
            for allowed, actual in (
                (self.account_ids, requested.account_ids),
                (self.strategy_ids, requested.strategy_ids),
                (self.instrument_ids, requested.instrument_ids),
                (self.policy_refs, requested.policy_refs),
                (self.governed_artifact_refs, requested.governed_artifact_refs),
                (self.environments, requested.environments),
            )
        )

    def has_fully_bounded_trading_scope(self) -> bool:
        return bool(
            self.account_ids and self.strategy_ids and self.instrument_ids and self.policy_refs and self.environments
        )

    def has_fully_bounded_governed_artifact_scope(self) -> bool:
        return bool(self.governed_artifact_refs and self.policy_refs and self.environments)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "account_ids": sorted(self.account_ids),
            "strategy_ids": sorted(self.strategy_ids),
            "instrument_ids": sorted(self.instrument_ids),
            "policy_refs": sorted(self.policy_refs),
            "governed_artifact_refs": sorted(self.governed_artifact_refs),
            "environments": sorted(environment.value for environment in self.environments),
        }


@dataclass(frozen=True, slots=True)
class ToolGrant:
    """A revocable capability grant, distinct from all business authorizations."""

    grant_id: EntityId
    grantee_role_id: str
    grantee_node_id: str
    catalog_version: SchemaVersion
    registry_version: SchemaVersion
    tool_refs: frozenset[ToolRef]
    max_permission_tier: ToolPermissionTier
    scope: ToolScope
    status: ToolGrantStatus
    issued_at: RecordedAt
    expires_at: RecordedAt
    audit_ref: str

    def __post_init__(self) -> None:
        if not self.grantee_role_id or not _SCOPE_TOKEN.fullmatch(self.grantee_node_id):
            raise ValueError("tool grants require a role and canonical node id")
        if not isinstance(self.scope, ToolScope):
            raise TypeError("tool grants require a ToolScope")
        if not isinstance(self.tool_refs, frozenset) or not self.tool_refs:
            raise ValueError("tool grants must name exact tool versions")
        if any(not isinstance(ref, ToolRef) for ref in self.tool_refs):
            raise TypeError("tool grants must use immutable ToolRef values")
        if not isinstance(self.max_permission_tier, ToolPermissionTier) or not isinstance(self.status, ToolGrantStatus):
            raise TypeError("tool grant tier and status must use their explicit enums")
        if self.expires_at.value <= self.issued_at.value:
            raise ValueError("tool grant expiry must follow issuance")
        if not self.audit_ref:
            raise ValueError("tool grants require an audit reference")
        if (
            self.max_permission_tier
            in {
                ToolPermissionTier.MANDATE_SCOPED_SIMULATION,
                ToolPermissionTier.PLAN_APPROVAL,
            }
            and not self.scope.has_fully_bounded_trading_scope()
        ):
            raise ValueError(
                "simulation and plan-approval tool grants require bounded account, strategy, instrument, policy, and environment scope"
            )
        if self.max_permission_tier in {ToolPermissionTier.PROMOTION, ToolPermissionTier.ACTIVATION}:
            if not self.scope.has_fully_bounded_governed_artifact_scope():
                raise ValueError(
                    "promotion and activation tool grants require bounded governed-artifact, policy, and environment scope"
                )

    def is_active_at(self, called_at: RecordedAt) -> bool:
        return self.status is ToolGrantStatus.ACTIVE and self.issued_at.value <= called_at.value < self.expires_at.value

    def permits_tier(self, requested_tier: ToolPermissionTier) -> bool:
        """Preserve the boundary between trading and governance authority families."""

        if self.max_permission_tier in {ToolPermissionTier.PROMOTION, ToolPermissionTier.ACTIVATION}:
            return requested_tier is self.max_permission_tier
        return requested_tier <= self.max_permission_tier


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """An Agent's proposed Tool Gateway call; this is not a tool execution."""

    call_id: EntityId
    agent_role_id: str
    node_id: str
    catalog_version: SchemaVersion
    registry_version: SchemaVersion
    tool_ref: ToolRef
    scope: ToolScope
    called_at: RecordedAt
    correlation_id: EntityId
    trace: TraceContext

    def __post_init__(self) -> None:
        if not self.agent_role_id or not _SCOPE_TOKEN.fullmatch(self.node_id):
            raise ValueError("tool calls require a role and canonical node id")
        if not isinstance(self.scope, ToolScope):
            raise TypeError("tool calls require a ToolScope")
        if not isinstance(self.trace, TraceContext):
            raise TypeError("tool calls require a TraceContext")
        if self.trace.correlation_id != self.correlation_id:
            raise ValueError("tool call trace must carry the call correlation id")

    def fingerprint(self) -> str:
        payload = {
            "call_id": str(self.call_id),
            "agent_role_id": self.agent_role_id,
            "node_id": self.node_id,
            "catalog_version": str(self.catalog_version),
            "registry_version": str(self.registry_version),
            "tool_ref": str(self.tool_ref),
            "scope": self.scope.to_dict(),
            "called_at": self.called_at.to_dict()["recorded_at"],
            "correlation_id": str(self.correlation_id),
            "trace_id": str(self.trace.trace_id),
            "causation_id": str(self.trace.causation_id) if self.trace.causation_id else None,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """A stable, appendable audit fact for every attempted authorization."""

    outcome: ToolAuthorizationOutcome
    reason_code: ReasonCode
    call_id: EntityId
    correlation_id: EntityId
    trace: TraceContext
    agent_role_id: str
    node_id: str
    tool_ref: ToolRef
    request_fingerprint: str
    evaluated_at: RecordedAt
    matched_grant_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trace, TraceContext):
            raise TypeError("tool authorization decisions require a TraceContext")
        if self.trace.correlation_id != self.correlation_id:
            raise ValueError("tool authorization decision trace must carry the call correlation id")
        if self.outcome is ToolAuthorizationOutcome.PERMIT and self.matched_grant_id is None:
            raise ValueError("permitted tool calls require the matched ToolGrant audit reference")
        if self.outcome is ToolAuthorizationOutcome.DENY and self.matched_grant_id is not None:
            raise ValueError("denied tool calls must not imply that a ToolGrant was consumed")

    def to_dict(self) -> dict[str, str | None]:
        result = {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code.value,
            "call_id": str(self.call_id),
            "correlation_id": str(self.correlation_id),
            "trace_id": str(self.trace.trace_id),
            "causation_id": str(self.trace.causation_id) if self.trace.causation_id else None,
            "agent_role_id": self.agent_role_id,
            "node_id": self.node_id,
            "tool_ref": str(self.tool_ref),
            "request_fingerprint": self.request_fingerprint,
            "evaluated_at": self.evaluated_at.to_dict()["recorded_at"],
        }
        if self.matched_grant_id is not None:
            result["matched_grant_id"] = str(self.matched_grant_id)
        return result


class ToolAuthorizer:
    """Deterministically evaluates exact registry contracts and ToolGrants."""

    def __init__(self, registry: ToolRegistry, grants: tuple[ToolGrant, ...]) -> None:
        grant_ids = {grant.grant_id for grant in grants}
        if len(grant_ids) != len(grants):
            raise ValueError("tool grants must have unique identifiers")
        self._registry = registry
        self._grants = tuple(sorted(grants, key=lambda grant: str(grant.grant_id)))

    def authorize(self, request: ToolCallRequest) -> ToolAuthorizationDecision:
        """Fail closed with a stable reason code; never raises for authorization denial."""

        fingerprint = request.fingerprint()

        def deny(reason: ReasonCode) -> ToolAuthorizationDecision:
            return ToolAuthorizationDecision(
                ToolAuthorizationOutcome.DENY,
                reason,
                request.call_id,
                request.correlation_id,
                request.trace,
                request.agent_role_id,
                request.node_id,
                request.tool_ref,
                fingerprint,
                request.called_at,
            )

        if request.registry_version != self._registry.version:
            return deny(ReasonCode.TOOL_REGISTRY_VERSION_MISMATCH)
        definition = self._registry.resolve_exact(request.tool_ref)
        if definition is None:
            return deny(
                ReasonCode.TOOL_VERSION_MISMATCH
                if self._registry.has_tool_id(request.tool_ref.tool_id)
                else ReasonCode.TOOL_NOT_REGISTERED
            )
        try:
            role = definition_for(request.agent_role_id)
        except ValueError:
            return deny(ReasonCode.TOOL_ROLE_MISMATCH)
        if request.catalog_version != role.version:
            return deny(ReasonCode.TOOL_CATALOG_VERSION_MISMATCH)
        if request.tool_ref.tool_id not in role.declared_tools:
            return deny(ReasonCode.TOOL_NOT_DECLARED_FOR_ROLE)

        role_grants = tuple(grant for grant in self._grants if grant.grantee_role_id == request.agent_role_id)
        if not role_grants:
            return deny(ReasonCode.TOOL_GRANT_MISSING)
        catalog_grants = tuple(grant for grant in role_grants if grant.catalog_version == request.catalog_version)
        if not catalog_grants:
            return deny(ReasonCode.TOOL_CATALOG_VERSION_MISMATCH)
        registry_grants = tuple(grant for grant in catalog_grants if grant.registry_version == request.registry_version)
        if not registry_grants:
            return deny(ReasonCode.TOOL_REGISTRY_VERSION_MISMATCH)
        active_role_grants = tuple(grant for grant in registry_grants if grant.status is ToolGrantStatus.ACTIVE)
        if not active_role_grants:
            return deny(ReasonCode.TOOL_GRANT_INACTIVE)
        current_grants = tuple(
            grant
            for grant in active_role_grants
            if grant.issued_at.value <= request.called_at.value < grant.expires_at.value
        )
        if not current_grants:
            return deny(ReasonCode.TOOL_GRANT_EXPIRED)
        node_grants = tuple(grant for grant in current_grants if grant.grantee_node_id == request.node_id)
        if not node_grants:
            return deny(ReasonCode.TOOL_NODE_SCOPE_MISMATCH)
        exact_tool_grants = tuple(grant for grant in node_grants if request.tool_ref in grant.tool_refs)
        if not exact_tool_grants:
            return deny(ReasonCode.TOOL_VERSION_MISMATCH)
        tier_grants = tuple(grant for grant in exact_tool_grants if grant.permits_tier(definition.permission_tier))
        if not tier_grants:
            return deny(ReasonCode.TOOL_PERMISSION_TIER_DENIED)
        scope_grants = tuple(grant for grant in tier_grants if grant.scope.contains(request.scope))
        if not scope_grants:
            return deny(ReasonCode.TOOL_SCOPE_MISMATCH)
        return ToolAuthorizationDecision(
            ToolAuthorizationOutcome.PERMIT,
            ReasonCode.TOOL_AUTHORIZED,
            request.call_id,
            request.correlation_id,
            request.trace,
            request.agent_role_id,
            request.node_id,
            request.tool_ref,
            fingerprint,
            request.called_at,
            matched_grant_id=scope_grants[0].grant_id,
        )
