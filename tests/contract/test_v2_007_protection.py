from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_agent_os.decision import PositionLot, StopPolicy, TradeDirection
from futures_agent_os.execution_simulation import (
    ProtectionTriggerKind,
    ProtectionValidator,
    RiskReductionRequest,
    ValidationOutcome,
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
