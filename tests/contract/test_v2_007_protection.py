from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_agent_os.decision import PositionLot, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import ThesisInvalidationSpec
from futures_agent_os.execution_simulation import (
    ProtectionTriggerEvaluator,
    ProtectionTriggerKind,
    ProtectionValidator,
    RiskReductionRequest,
    ValidationOutcome,
    ProtectiveActionRegistry,
    DurableProtectiveActionRegistry,
)
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def test_protection_validator_only_allows_monotonic_reduction() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    position = EntityId.new("position_lot")
    lot = PositionLot(
        position,
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("5"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(EntityId.new("stop_policy"), position, Decimal("95"), Decimal("25"))
    request = RiskReductionRequest(
        EntityId.new("reduction_request"),
        position,
        1,
        Decimal("2"),
        Decimal("97"),
        ProtectionTriggerKind.INITIAL_STOP,
        "idem-1",
        now,
    )
    validation = ProtectionValidator().validate(request, lot, policy, position_version=1, now=now)
    assert validation.outcome is ValidationOutcome.VALIDATED


def test_protection_validator_rejects_increase_and_stale_version() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    position = EntityId.new("position_lot")
    lot = PositionLot(
        position,
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("5"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(EntityId.new("stop_policy"), position, Decimal("95"), Decimal("25"))
    validator = ProtectionValidator()
    increase = RiskReductionRequest(
        EntityId.new("reduction_request"),
        position,
        1,
        Decimal("6"),
        None,
        ProtectionTriggerKind.KILL_SWITCH,
        "idem-2",
        now,
    )
    stale = RiskReductionRequest(
        EntityId.new("reduction_request"),
        position,
        2,
        Decimal("2"),
        None,
        ProtectionTriggerKind.KILL_SWITCH,
        "idem-3",
        now,
    )
    assert validator.validate(increase, lot, policy, position_version=1, now=now).reason == "EXPOSURE_INCREASE"
    assert validator.validate(stale, lot, policy, position_version=1, now=now).outcome is ValidationOutcome.STALE


def test_unvalidated_request_cannot_create_action() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    request = RiskReductionRequest(
        EntityId.new("reduction_request"),
        EntityId.new("position_lot"),
        1,
        Decimal("0"),
        None,
        ProtectionTriggerKind.KILL_SWITCH,
        "idem-4",
        now,
    )
    with pytest.raises(ValueError):
        ProtectionValidator().action(request, type("V", (), {"outcome": ValidationOutcome.REJECTED})(), now=now)


def test_price_trigger_and_action_registry_are_idempotent() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    position = EntityId.new("position_lot")
    lot = PositionLot(
        position,
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("5"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(EntityId.new("stop_policy"), position, Decimal("95"), Decimal("25"))
    request = ProtectionTriggerEvaluator().price_stop(lot, policy, Decimal("94"), now)
    assert request is not None and request.trigger is ProtectionTriggerKind.INITIAL_STOP
    validation = ProtectionValidator().validate(request, lot, policy, position_version=1, now=now)
    registry = ProtectiveActionRegistry()
    first = registry.issue(request, validation, now=now)
    restored = ProtectiveActionRegistry.restore(registry.snapshot())
    assert first == restored.issue(request, validation, now=now)
    with pytest.raises(ValueError):
        ProtectiveActionRegistry.restore(registry.snapshot() + registry.snapshot())


def test_protective_action_id_and_unprotected_fault_are_deterministic() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    position = EntityId.new("position_lot")
    lot = PositionLot(
        position,
        EntityId.new("simulation_account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(EntityId.new("stop_policy"), position, Decimal("95"), Decimal("5"), active=False)
    evaluator = ProtectionTriggerEvaluator()
    assert evaluator.is_unprotected_open(lot, policy)
    request = evaluator.kill_switch(lot, now)
    validation = ProtectionValidator().validate(request, lot, policy, position_version=1, now=now)
    action_a = ProtectionValidator().action(request, validation, now=now)
    action_b = ProtectionValidator().action(request, validation, now=now)
    assert action_a.action_id == action_b.action_id


def test_protection_idempotency_key_cannot_alias_a_different_reduction() -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    position = EntityId.deterministic("position_lot", "idempotency-conflict-position")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "idempotency-conflict-account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("5"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "idempotency-conflict-policy"), position, Decimal("95"), Decimal("25")
    )
    validator = ProtectionValidator()
    first_request = RiskReductionRequest(
        EntityId.deterministic("reduction_request", "idempotency-conflict-first"),
        position,
        1,
        Decimal("2"),
        Decimal("97"),
        ProtectionTriggerKind.INITIAL_STOP,
        "same-idempotency-key",
        now,
    )
    second_request = RiskReductionRequest(
        EntityId.deterministic("reduction_request", "idempotency-conflict-second"),
        position,
        1,
        Decimal("1"),
        Decimal("98"),
        ProtectionTriggerKind.KILL_SWITCH,
        "same-idempotency-key",
        now,
    )
    first_validation = validator.validate(first_request, lot, policy, position_version=1, now=now)
    second_validation = validator.validate(second_request, lot, policy, position_version=1, now=now)
    registry = ProtectiveActionRegistry()
    registry.issue(first_request, first_validation, now=now)
    with pytest.raises(ValueError, match="idempotency key conflict"):
        registry.issue(second_request, second_validation, now=now)


def test_durable_protection_action_survives_restart_and_rejects_corruption(tmp_path) -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    position = EntityId.deterministic("position_lot", "durable-protection-position")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "durable-protection-account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("2"),
        Decimal("100"),
        now,
    )
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "durable-protection-policy"), position, Decimal("95"), Decimal("10")
    )
    request = ProtectionTriggerEvaluator().price_stop(lot, policy, Decimal("94"), now)
    assert request is not None
    validation = ProtectionValidator().validate(request, lot, policy, position_version=1, now=now)
    path = tmp_path / "protection.json"
    first = DurableProtectiveActionRegistry(path).issue(request, validation, now=now)
    restarted = DurableProtectiveActionRegistry(path)
    assert restarted.issue(request, validation, now=now) == first
    payload = path.read_text(encoding="utf-8").replace(first.source_ref, "source:altered")
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="cannot load"):
        DurableProtectiveActionRegistry(path)


def test_all_six_protection_triggers_bind_the_current_position_version() -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    position = EntityId.deterministic("position_lot", "six-trigger-position")
    lot = PositionLot(
        position,
        EntityId.deterministic("simulation_account", "six-trigger-account"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("3"),
        Decimal("100"),
        now,
        version=4,
    )
    policy = StopPolicy(
        EntityId.deterministic("stop_policy", "six-trigger-policy"), position, Decimal("95"), Decimal("10")
    )
    evaluator = ProtectionTriggerEvaluator()
    requests = (
        evaluator.price_stop(lot, policy, Decimal("94"), now),
        evaluator.trailing_stop(lot, policy, Decimal("94"), now),
        evaluator.time_stop(lot, now),
        evaluator.portfolio_stop(lot, now),
        evaluator.kill_switch(lot, now),
        evaluator.thesis_invalidation(lot, now),
    )
    assert all(request is not None for request in requests)
    assert {request.trigger for request in requests if request is not None} == {
        ProtectionTriggerKind.INITIAL_STOP,
        ProtectionTriggerKind.TRAILING_STOP,
        ProtectionTriggerKind.TIME_STOP,
        ProtectionTriggerKind.PORTFOLIO_STOP,
        ProtectionTriggerKind.KILL_SWITCH,
        ProtectionTriggerKind.THESIS_INVALIDATION,
    }
    assert {request.expected_position_version for request in requests if request is not None} == {4}


def test_thesis_invalidation_uses_explicit_replayable_predicate() -> None:
    now = RecordedAt.from_datetime(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    lot = PositionLot(
        EntityId.deterministic("position_lot", "thesis"),
        EntityId.deterministic("simulation_account", "thesis"),
        "SHFE_AG_2601",
        TradeDirection.LONG,
        Decimal("1"),
        Decimal("100"),
        now,
        version=2,
    )
    spec = ThesisInvalidationSpec("signal_accuracy", "LT", Decimal("0.5"))
    evaluator = ProtectionTriggerEvaluator()
    assert evaluator.thesis_invalidation(lot, now, spec=spec, observations={"signal_accuracy": Decimal("0.6")}) is None
    request = evaluator.thesis_invalidation(lot, now, spec=spec, observations={"signal_accuracy": Decimal("0.4")})
    assert request is not None and request.trigger is ProtectionTriggerKind.THESIS_INVALIDATION
    assert spec.spec_hash == ThesisInvalidationSpec("signal_accuracy", "LT", Decimal("0.5")).spec_hash
