"""Machine-checkable V0 contracts for the bounded logical-agent catalog."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from futures_agent_os.agent_orchestration import (
    AGENT_CATALOG,
    CATALOG_VERSION,
    AgentHandoff,
    AgentBudget,
    AgentRoleId,
    AgentTaskEnvelope,
    ArtifactClaim,
    ArtifactKind,
    ArtifactRef,
    ResultStatus,
    SpecialistResult,
    StructuredArtifact,
    TriggerSource,
    definition_for,
    validate_task_envelope,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def _at(minutes: int = 0) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 18, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes))


def _ref(kind: ArtifactKind = ArtifactKind.RESEARCH_BRIEF) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=EntityId.new("artifact"), artifact_kind=kind,
        schema_version=SchemaVersion(1, 0), content_hash="sha256:" + "a" * 64,
        created_at=_at(2), as_of=_at(1),
    )


def test_catalog_has_the_complete_machine_checkable_twelve_role_roster() -> None:
    assert {definition.role_id for definition in AGENT_CATALOG} == set(AgentRoleId)
    assert len(AGENT_CATALOG) == 12

    for definition in AGENT_CATALOG:
        assert definition.version == CATALOG_VERSION
        assert definition.responsibilities and definition.non_responsibilities
        assert set(definition.trigger_sources) == set(TriggerSource)
        assert definition.trigger_examples and definition.input_kinds and definition.output_kinds
        assert definition.declared_tools and definition.permission_boundary
        assert definition.budget.max_turns > 0 and definition.metrics and definition.enabled_from


def test_main_and_deterministic_orchestrator_remain_separate() -> None:
    main = definition_for(AgentRoleId.MAIN.value)

    assert "does not schedule" in main.non_responsibilities[0]
    assert "deterministic" in main.non_responsibilities[0]
    assert "Order" not in {kind.value for kind in main.output_kinds}
    assert "submit_trade_plan" not in main.declared_tools


def test_task_envelope_is_bounded_by_the_versioned_role_contract() -> None:
    task = AgentTaskEnvelope(
        task_id=EntityId.new("agent_task"), session_id=EntityId.new("session"),
        correlation_id=EntityId.new("correlation"), assigned_role_id=AgentRoleId.MARKET_REGIME.value,
        catalog_version=CATALOG_VERSION, objective="assess regime", completion_definition="return assessment",
        trigger_sources=(TriggerSource.MARKET,), input_artifacts=(_ref(),), policy_refs=(),
        allowed_tools=("market_snapshot",), budget=definition_for("market_regime").budget,
        required_outputs=(ArtifactKind.MARKET_STATE_ASSESSMENT,), as_of=_at(3), expires_at=_at(30),
    )
    validate_task_envelope(task)

    invalid_tool = AgentTaskEnvelope(
        task_id=task.task_id, session_id=task.session_id, correlation_id=task.correlation_id,
        assigned_role_id=task.assigned_role_id, catalog_version=task.catalog_version, objective=task.objective,
        completion_definition=task.completion_definition, trigger_sources=task.trigger_sources,
        input_artifacts=task.input_artifacts, policy_refs=task.policy_refs, allowed_tools=("submit_trade_plan",),
        budget=task.budget, required_outputs=task.required_outputs, as_of=task.as_of, expires_at=task.expires_at,
    )
    with pytest.raises(ValueError, match="tool"):
        validate_task_envelope(invalid_tool)

    with pytest.raises(ValueError, match="input artifact"):
        validate_task_envelope(replace(task, input_artifacts=(_ref(ArtifactKind.HYPOTHESIS),)))

    for budget in (
        AgentBudget(5, 16, 12_000, 120), AgentBudget(4, 17, 12_000, 120),
        AgentBudget(4, 16, 12_001, 120), AgentBudget(4, 16, 12_000, 121),
        AgentBudget(4, 16, 12_000, 120, 2),
    ):
        with pytest.raises(ValueError, match="budget exceeds"):
            validate_task_envelope(replace(task, budget=budget))

    for field, duplicate_value, message in (
        ("trigger_sources", (TriggerSource.MARKET, TriggerSource.MARKET), "trigger sources"),
        ("allowed_tools", ("market_snapshot", "market_snapshot"), "allowed tools"),
        ("required_outputs", (ArtifactKind.MARKET_STATE_ASSESSMENT, ArtifactKind.MARKET_STATE_ASSESSMENT), "required outputs"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(task, **{field: duplicate_value})

    with pytest.raises(ValueError, match="sub-research"):
        validate_task_envelope(
            AgentTaskEnvelope(
                task_id=task.task_id, session_id=task.session_id, correlation_id=task.correlation_id,
                assigned_role_id=task.assigned_role_id, catalog_version=task.catalog_version, objective=task.objective,
                completion_definition=task.completion_definition, trigger_sources=task.trigger_sources,
                input_artifacts=task.input_artifacts, policy_refs=task.policy_refs, allowed_tools=task.allowed_tools,
                budget=task.budget, required_outputs=task.required_outputs, as_of=task.as_of, expires_at=task.expires_at,
                may_delegate_research=True,
            )
        )


def test_specialist_result_requires_evidence_for_success_and_explanation_for_non_success() -> None:
    task_id = EntityId.new("agent_task")
    for status in (ResultStatus.COMPLETED, ResultStatus.PARTIAL):
        with pytest.raises(ValueError, match="output artifact"):
            SpecialistResult(task_id, "research", status, (), (), (), (), _at(40))

    for status, unknowns, warnings in (
        (ResultStatus.DEFERRED, ("data unavailable",), ()),
        (ResultStatus.FAILED, (), ("tool timeout",)),
    ):
        result = SpecialistResult(task_id, "research", status, (), (), unknowns, warnings, _at(40))
        assert result.artifacts == ()

    with pytest.raises(ValueError, match="unknown or warning"):
        SpecialistResult(task_id, "research", ResultStatus.DEFERRED, (), (), (), (), _at(40))


def test_handoffs_and_artifacts_are_immutable_referenced_evidence_not_peer_chat() -> None:
    source = _ref()
    claim = ArtifactClaim("assessment", "regime uncertain", (source,), is_inference=True)
    artifact = StructuredArtifact(
        ref=_ref(ArtifactKind.MARKET_STATE_ASSESSMENT), producer_role_id="market_regime",
        producer_run_id=EntityId.new("agent_run"), source_refs=(source,), claims=(claim,), warnings=("data_stale",),
        expires_at=_at(40),
    )
    handoff = AgentHandoff(
        handoff_id=EntityId.new("handoff"), from_task_id=EntityId.new("agent_task"),
        to_task_id=EntityId.new("agent_task"), from_role_id="market_regime", to_role_id="main",
        artifacts=(artifact.ref,), unresolved_questions=("confirm data refresh",),
        authorization_boundary="analysis only; no authority is transferred", created_at=_at(4),
    )
    result = SpecialistResult(
        task_id=handoff.from_task_id, role_id="market_regime", status=ResultStatus.COMPLETED,
        artifacts=(artifact.ref,), counter_evidence_refs=(), unknowns=("next release",), warnings=(), expires_at=_at(40),
    )

    assert handoff.artifacts == result.artifacts
    with pytest.raises(ValueError, match="sha256"):
        ArtifactRef(EntityId.new("artifact"), ArtifactKind.RESEARCH_BRIEF, SchemaVersion(1, 0), "mutable", _at(2), _at(1))
    with pytest.raises(ValueError, match="own task"):
        AgentHandoff(EntityId.new("handoff"), handoff.from_task_id, handoff.from_task_id, "main", "main", (source,), (), "none", _at())
