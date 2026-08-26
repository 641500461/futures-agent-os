"""Focused V1-010 replay, typed-search, and version contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_agent_os.agent_orchestration import AgentRoleId, ArtifactKind, definition_for
from futures_agent_os.governance_registry import TOOL_REGISTRY, ToolRef
from futures_agent_os.research_experiment import (
    ExperimentOutcome,
    ExperimentSearchBatch,
    ExperimentSearchRecord,
    LessonActivationState,
    MemorySearchRecord,
    MemorySearchBatch,
    ResearchArtifactRef,
    TrustedExperimentSearchPort,
    TrustedMemorySearchPort,
    ValidationConfig,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt, SchemaVersion


def _at(hour: int) -> RecordedAt:
    return RecordedAt(datetime(2026, 8, 25, hour, tzinfo=UTC))


def _ref(kind: str, at: RecordedAt, valid: RecordedAt, digest: str = "a" * 64) -> ResearchArtifactRef:
    return ResearchArtifactRef(EntityId.new("artifact"), kind, SchemaVersion(1, 5), digest, at, valid)


def _config() -> ValidationConfig:
    return ValidationConfig(
        EntityId.new("research_validation_config"),
        1,
        20,
        5,
        5,
        20,
        Decimal("0.00010000"),
        Decimal("2.00000000"),
        Decimal("1.00000000"),
        (Decimal("1.00000000"), Decimal("2.00000000")),
        2,
    )


def test_catalog_1_5_adds_diagnostics_without_reinterpreting_1_4() -> None:
    current = definition_for(AgentRoleId.PRE_TRADE_CRITIC.value, SchemaVersion(1, 5))
    historical = definition_for(AgentRoleId.PRE_TRADE_CRITIC.value, SchemaVersion(1, 4))
    assert current.input_kinds == (
        ArtifactKind.MARKET_SNAPSHOT,
        ArtifactKind.HYPOTHESIS,
        ArtifactKind.EVIDENCE_SYNTHESIS,
        ArtifactKind.EXPERIMENT_REQUEST,
        ArtifactKind.RESEARCH_DIAGNOSTIC,
    )
    assert historical.input_kinds == (
        ArtifactKind.HYPOTHESIS,
        ArtifactKind.EVIDENCE_SYNTHESIS,
        ArtifactKind.EXPERIMENT_REQUEST,
    )
    assert historical.declared_tools == ()
    assert all(
        TOOL_REGISTRY.resolve_exact(ToolRef(tool, SchemaVersion(1, 5))) is not None
        for tool in definition_for(AgentRoleId.RESEARCH.value, SchemaVersion(1, 5)).declared_tools
    )
    assert not {"historical_data", "backtest", "stress_test"} & set(
        definition_for(AgentRoleId.RESEARCH.value, SchemaVersion(1, 5)).declared_tools
    )
    assert {"historical_data", "backtest", "stress_test"} <= set(
        definition_for(AgentRoleId.RESEARCH.value, SchemaVersion(1, 4)).declared_tools
    )


def test_config_registry_identity_does_not_pollute_semantic_hash_and_rules_are_pinned() -> None:
    first = _config()
    second = replace(first, config_id=EntityId.new("research_validation_config"))
    assert first.config_id != second.config_id
    assert first.content_sha256 == second.content_sha256
    assert ValidationConfig.hydrate(first.to_dict()) == first
    with pytest.raises(ValueError, match="rules are pinned"):
        replace(first, signal_rule="caller_strategy")
    with pytest.raises(ValueError, match=">=20"):
        replace(first, minimum_samples=5, train_bars=5)


def test_memory_and_experiment_records_are_typed_and_failed_experiments_are_preserved() -> None:
    scope_sha = "1" * 64
    lesson = MemorySearchRecord(_ref("validated_lesson", _at(8), _at(14)), ("AG",), scope_sha256=scope_sha)
    provenance = _ref("dataset", _at(7), _at(14), "b" * 64)
    failed = ExperimentSearchRecord(
        _ref("experiment_result", _at(9), _at(14), "c" * 64),
        ("AG",),
        ExperimentOutcome.FAILED,
        _at(10),
        (provenance,),
        scope_sha,
    )
    assert lesson.activation_state is LessonActivationState.ACTIVE
    assert failed.outcome is ExperimentOutcome.FAILED
    with pytest.raises(ValueError, match="ValidatedLesson"):
        MemorySearchRecord(_ref("reflection", _at(8), _at(14)), ("AG",))
    with pytest.raises(ValueError, match="revoked"):
        replace(lesson, revoked_at=_at(10))
    with pytest.raises(ValueError, match="ExperimentResult"):
        replace(failed, ref=_ref("reflection", _at(9), _at(14)))
    first = MemorySearchRecord(_ref("validated_lesson", _at(7), _at(14), "d" * 64), ("AG",), scope_sha256=scope_sha)
    memory_port = TrustedMemorySearchPort(b"memory-owner-secret-for-v1-010-tests-")
    experiment_port = TrustedExperimentSearchPort(b"experiment-owner-secret-v1-010-tests")
    ordered = memory_port.issue((lesson, first))
    replayed = memory_port.issue((first, lesson))
    assert ordered == replayed
    assert MemorySearchBatch.hydrate(ordered.to_dict()) == ordered
    with pytest.raises(ValueError, match="duplicate"):
        memory_port.issue((lesson, lesson))
    with pytest.raises(PermissionError, match="TrustedMemorySearchPort"):
        MemorySearchBatch.seal((lesson,))
    with pytest.raises(ValueError, match="identity must bind"):
        replace(ordered, batch_id=EntityId.new("memory_search_batch"))
    experiment_batch = experiment_port.issue((failed,))
    assert ExperimentSearchBatch.hydrate(experiment_batch.to_dict()) == experiment_batch
    with pytest.raises(ValueError, match="immutable PIT provenance"):
        replace(failed, provenance_refs=(replace(provenance, valid_until=_at(13)),))
    with pytest.raises(ValueError, match="immutable PIT provenance"):
        replace(failed, completed_at=_at(8))
