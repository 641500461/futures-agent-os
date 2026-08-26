"""Negative-first contracts for V0's static Tool Registry and ToolGrant model."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.agent_orchestration import (
    AGENT_CATALOG,
    CATALOG_VERSION,
    SimulationEnvironment,
    ToolAuthorizationOutcome,
    ToolAuthorizer,
    ToolCallRequest,
    ToolGrant,
    ToolGrantStatus,
    ToolScope,
)
from futures_agent_os.governance_registry import TOOL_REGISTRY, TOOL_REGISTRY_VERSION, ToolPermissionTier, ToolRef
from futures_agent_os.shared_kernel import EntityId, ReasonCode, RecordedAt, SchemaVersion, TraceContext


TOOL_V1 = SchemaVersion(1, 0)


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 18, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _scope(**changes: object) -> ToolScope:
    values: dict[str, object] = {
        "account_ids": frozenset({"sim-account-a"}),
        "strategy_ids": frozenset({"strategy-a@1.0"}),
        "instrument_ids": frozenset({"SHFE:CU"}),
        "policy_refs": frozenset({"risk-policy@1.0"}),
        "governed_artifact_refs": frozenset({"agent:main@1.0"}),
        "environments": frozenset({SimulationEnvironment.TEST}),
    }
    values.update(changes)
    return ToolScope(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> ToolCallRequest:
    correlation_id = EntityId.new("correlation")
    values: dict[str, object] = {
        "call_id": EntityId.new("tool_call"),
        "agent_role_id": "main",
        "node_id": "agent_worker_a",
        "catalog_version": CATALOG_VERSION,
        "registry_version": TOOL_REGISTRY_VERSION,
        "tool_ref": ToolRef("market_snapshot", TOOL_V1),
        "scope": _scope(),
        "called_at": _at(10),
        "correlation_id": correlation_id,
        "trace": TraceContext(correlation_id, EntityId.new("trace")),
    }
    values.update(changes)
    return ToolCallRequest(**values)  # type: ignore[arg-type]


def _grant(**changes: object) -> ToolGrant:
    values: dict[str, object] = {
        "grant_id": EntityId.new("tool_grant"),
        "grantee_role_id": "main",
        "grantee_node_id": "agent_worker_a",
        "catalog_version": CATALOG_VERSION,
        "registry_version": TOOL_REGISTRY_VERSION,
        "tool_refs": frozenset({ToolRef("market_snapshot", TOOL_V1)}),
        "max_permission_tier": ToolPermissionTier.READ_ONLY,
        "scope": _scope(),
        "status": ToolGrantStatus.ACTIVE,
        "issued_at": _at(),
        "expires_at": _at(30),
        "audit_ref": "audit://grant/approved-1",
    }
    values.update(changes)
    return ToolGrant(**values)  # type: ignore[arg-type]


def _reason(authorizer: ToolAuthorizer, request: ToolCallRequest) -> ReasonCode:
    decision = authorizer.authorize(request)
    assert decision.outcome is ToolAuthorizationOutcome.DENY
    return decision.reason_code


def test_registry_covers_every_permission_tier_and_resolves_exact_versions_only() -> None:
    assert {definition.permission_tier for definition in TOOL_REGISTRY.definitions} == set(ToolPermissionTier)
    assert {tool for role in AGENT_CATALOG for tool in role.declared_tools} <= {
        definition.ref.tool_id for definition in TOOL_REGISTRY.definitions
    }
    assert TOOL_REGISTRY.resolve_exact(ToolRef("market_snapshot", TOOL_V1)) is not None
    assert TOOL_REGISTRY.resolve_exact(ToolRef("market_snapshot", SchemaVersion(1, 1))) is None
    assert TOOL_REGISTRY.has_tool_id("market_snapshot")


def test_registry_owners_follow_bounded_context_ownership_and_risk_check_is_preview_only() -> None:
    owners = {definition.ref.tool_id: definition.owner_context for definition in TOOL_REGISTRY.definitions}

    assert owners["market_snapshot"] == "Reference & Market Data"
    assert owners["regime_analysis"] == "Market Intelligence"
    assert owners["backtest"] == "Research & Experiment"
    assert owners["portfolio_state"] == "Portfolio & Risk"
    assert owners["execution_simulator"] == "Execution & Simulation"
    assert owners["trade_replay"] == "Learning & Review"
    assert owners["autonomy_mandate_status"] == "Decision"
    assert owners["registry_query"] == "Governance & Registry"
    assert (
        TOOL_REGISTRY.resolve_exact(ToolRef("market_query", SchemaVersion(1, 5))).owner_context
        == "Reference & Market Data"
    )  # type: ignore[union-attr]
    assert (
        TOOL_REGISTRY.resolve_exact(ToolRef("feature_query", SchemaVersion(1, 5))).owner_context
        == "Market Intelligence"
    )  # type: ignore[union-attr]
    assert (
        TOOL_REGISTRY.resolve_exact(ToolRef("memory_search", SchemaVersion(1, 5))).owner_context == "Learning & Review"
    )  # type: ignore[union-attr]
    risk_check = TOOL_REGISTRY.resolve_exact(ToolRef("risk_check", TOOL_V1))
    assert risk_check is not None
    assert risk_check.owner_context == "Portfolio & Risk"
    assert "Non-authoritative" in risk_check.description and "RiskDecision" in risk_check.description


def test_catalog_1_5_requires_exact_1_5_research_tool_ref_and_minimum_grant() -> None:
    old_ref = ToolRef("feature_query", TOOL_V1)
    exact_ref = ToolRef("feature_query", SchemaVersion(1, 5))
    request = _request(agent_role_id="research", catalog_version=SchemaVersion(1, 5), tool_ref=old_ref)
    old_grant = _grant(
        grantee_role_id="research",
        catalog_version=SchemaVersion(1, 5),
        tool_refs=frozenset({old_ref}),
        max_permission_tier=ToolPermissionTier.READ_ONLY,
    )
    assert _reason(ToolAuthorizer(TOOL_REGISTRY, (old_grant,)), request) is ReasonCode.TOOL_VERSION_MISMATCH

    exact_request = replace(request, tool_ref=exact_ref)
    exact_grant = replace(old_grant, tool_refs=frozenset({exact_ref}))
    assert (
        ToolAuthorizer(TOOL_REGISTRY, (exact_grant,)).authorize(exact_request).outcome
        is ToolAuthorizationOutcome.PERMIT
    )


@pytest.mark.parametrize("tool_id", ["historical_data", "backtest", "stress_test"])
def test_catalog_1_5_rejects_legacy_research_surface_even_with_matching_grant(tool_id: str) -> None:
    legacy_ref = ToolRef(tool_id, TOOL_V1)
    request = _request(agent_role_id="research", catalog_version=SchemaVersion(1, 5), tool_ref=legacy_ref)
    matching_grant = _grant(
        grantee_role_id="research",
        catalog_version=SchemaVersion(1, 5),
        tool_refs=frozenset({legacy_ref}),
    )
    assert _reason(ToolAuthorizer(TOOL_REGISTRY, (matching_grant,)), request) is ReasonCode.TOOL_NOT_DECLARED_FOR_ROLE


def test_default_deny_and_unknown_or_undeclared_agents_are_stably_audited() -> None:
    request = _request()
    authorizer = ToolAuthorizer(TOOL_REGISTRY, ())
    first = authorizer.authorize(request)
    second = authorizer.authorize(request)

    assert first.outcome is ToolAuthorizationOutcome.DENY
    assert first.reason_code is ReasonCode.TOOL_GRANT_MISSING
    assert first.to_dict() == second.to_dict()
    assert _reason(authorizer, replace(request, agent_role_id="forged_agent")) is ReasonCode.TOOL_ROLE_MISMATCH
    assert _reason(authorizer, replace(request, agent_role_id="research")) is ReasonCode.TOOL_NOT_DECLARED_FOR_ROLE


def test_tool_call_trace_must_match_correlation_and_fingerprints_immediate_causation() -> None:
    request = _request()
    with pytest.raises(ValueError, match="correlation"):
        replace(request, trace=TraceContext(EntityId.new("correlation"), EntityId.new("trace")))

    caused = replace(request, trace=request.trace.caused_by(request.call_id))
    assert caused.fingerprint() != request.fingerprint()
    decision = ToolAuthorizer(TOOL_REGISTRY, ()).authorize(caused)
    assert decision.trace == caused.trace
    assert decision.to_dict()["trace_id"] == str(caused.trace.trace_id)
    assert decision.to_dict()["causation_id"] == str(request.call_id)


def test_foreign_role_grant_cannot_authorize_another_agent() -> None:
    request = _request()
    foreign_grant = _grant(grantee_role_id="research")

    assert _reason(ToolAuthorizer(TOOL_REGISTRY, (foreign_grant,)), request) is ReasonCode.TOOL_GRANT_MISSING


def test_registry_and_catalog_version_drift_fail_closed_before_grant_matching() -> None:
    grant = _grant()
    authorizer = ToolAuthorizer(TOOL_REGISTRY, (grant,))

    assert (
        _reason(authorizer, _request(tool_ref=ToolRef("market_snapshot", SchemaVersion(1, 1))))
        is ReasonCode.TOOL_VERSION_MISMATCH
    )
    assert (
        _reason(authorizer, _request(catalog_version=SchemaVersion(1, 0))) is ReasonCode.TOOL_CATALOG_VERSION_MISMATCH
    )
    assert (
        _reason(authorizer, _request(registry_version=SchemaVersion(1, 2))) is ReasonCode.TOOL_REGISTRY_VERSION_MISMATCH
    )
    assert (
        _reason(
            ToolAuthorizer(TOOL_REGISTRY, (_grant(catalog_version=SchemaVersion(1, 0)),)),
            _request(),
        )
        is ReasonCode.TOOL_CATALOG_VERSION_MISMATCH
    )
    assert (
        _reason(
            ToolAuthorizer(TOOL_REGISTRY, (_grant(registry_version=SchemaVersion(1, 2)),)),
            _request(),
        )
        is ReasonCode.TOOL_REGISTRY_VERSION_MISMATCH
    )


def test_expired_inactive_node_and_tier_mismatches_are_all_denied() -> None:
    request = _request()
    assert (
        _reason(ToolAuthorizer(TOOL_REGISTRY, (_grant(expires_at=_at(10)),)), request) is ReasonCode.TOOL_GRANT_EXPIRED
    )
    assert (
        _reason(ToolAuthorizer(TOOL_REGISTRY, (_grant(status=ToolGrantStatus.REVOKED),)), request)
        is ReasonCode.TOOL_GRANT_INACTIVE
    )
    assert (
        _reason(ToolAuthorizer(TOOL_REGISTRY, (_grant(grantee_node_id="agent_worker_b"),)), request)
        is ReasonCode.TOOL_NODE_SCOPE_MISMATCH
    )
    legacy = SchemaVersion(1, 2)
    proposal = ToolRef("create_trade_plan_draft", TOOL_V1)
    assert (
        _reason(
            ToolAuthorizer(
                TOOL_REGISTRY,
                (
                    _grant(
                        catalog_version=legacy,
                        tool_refs=frozenset({proposal}),
                        max_permission_tier=ToolPermissionTier.READ_ONLY,
                    ),
                ),
            ),
            _request(catalog_version=legacy, tool_ref=proposal),
        )
        is ReasonCode.TOOL_PERMISSION_TIER_DENIED
    )


@pytest.mark.parametrize(
    "scope_change",
    [
        {"account_ids": frozenset({"sim-account-b"})},
        {"strategy_ids": frozenset({"strategy-b@1.0"})},
        {"instrument_ids": frozenset({"DCE:I"})},
        {"policy_refs": frozenset({"risk-policy@2.0"})},
        {"environments": frozenset({SimulationEnvironment.STAGING})},
    ],
)
def test_every_resource_scope_dimension_rejects_cross_scope_calls(scope_change: dict[str, object]) -> None:
    authorizer = ToolAuthorizer(TOOL_REGISTRY, (_grant(),))

    assert _reason(authorizer, _request(scope=_scope(**scope_change))) is ReasonCode.TOOL_SCOPE_MISMATCH


def test_governed_artifact_scope_rejects_cross_artifact_and_allows_governance_grants_without_trade_scope() -> None:
    governance_scope = ToolScope(
        governed_artifact_refs=frozenset({"agent:main@1.0", "prompt:main@1.0"}),
        policy_refs=frozenset({"tool-policy@1.0"}),
        environments=frozenset({SimulationEnvironment.STAGING}),
    )
    promotion_grant = _grant(
        max_permission_tier=ToolPermissionTier.PROMOTION,
        scope=governance_scope,
        tool_refs=frozenset({ToolRef("submit_improvement_proposal", TOOL_V1)}),
    )

    assert promotion_grant.scope.contains(governance_scope)
    assert not promotion_grant.scope.contains(
        replace(governance_scope, governed_artifact_refs=frozenset({"agent:other@1.0"}))
    )
    with pytest.raises(ValueError, match="governed-artifact"):
        _grant(
            max_permission_tier=ToolPermissionTier.ACTIVATION,
            scope=ToolScope(
                account_ids=frozenset({"sim-account-a"}),
                strategy_ids=frozenset({"strategy-a@1.0"}),
                instrument_ids=frozenset({"SHFE:CU"}),
                policy_refs=frozenset({"tool-policy@1.0"}),
                environments=frozenset({SimulationEnvironment.STAGING}),
            ),
        )


def test_permitted_call_has_a_grant_reference_and_no_business_authorization_is_a_tool_grant() -> None:
    request = _request()
    decision = ToolAuthorizer(TOOL_REGISTRY, (_grant(),)).authorize(request)

    assert decision.outcome is ToolAuthorizationOutcome.PERMIT
    assert decision.reason_code is ReasonCode.TOOL_AUTHORIZED
    assert decision.matched_grant_id is not None
    assert decision.to_dict()["tool_ref"] == "market_snapshot@1.0"
    assert decision.to_dict()["call_id"] == str(request.call_id)
    assert decision.to_dict()["trace_id"] == str(request.trace.trace_id)
    field_names = {field.name for field in fields(ToolGrant)}
    assert {"mandate_id", "plan_approval_id", "risk_decision_id", "activation_id"}.isdisjoint(field_names)
    assert _reason(ToolAuthorizer(TOOL_REGISTRY, ()), request) is ReasonCode.TOOL_GRANT_MISSING


def test_simulation_and_plan_approval_grants_cannot_be_created_with_broad_trading_scope() -> None:
    with pytest.raises(ValueError, match="simulation and plan-approval"):
        _grant(max_permission_tier=ToolPermissionTier.MANDATE_SCOPED_SIMULATION, scope=ToolScope())
    with pytest.raises(ValueError, match="simulation and plan-approval"):
        _grant(max_permission_tier=ToolPermissionTier.PLAN_APPROVAL, scope=ToolScope())

    with pytest.raises(TypeError, match="immutable frozensets"):
        ToolScope(account_ids={"sim-account-a"})  # type: ignore[arg-type]


def test_registry_is_static_contract_only_and_cannot_be_mutated_through_the_public_api() -> None:
    assert isinstance(TOOL_REGISTRY.definitions, tuple)
    with pytest.raises(AttributeError):
        TOOL_REGISTRY.definitions += ()  # type: ignore[misc]
