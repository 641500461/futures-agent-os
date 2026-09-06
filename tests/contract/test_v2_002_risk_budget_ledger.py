from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_agent_os.portfolio_risk import RiskBudgetLedger, RiskBudgetReservation, ReservationStatus
from futures_agent_os.shared_kernel import EntityId, RecordedAt


def _reservation(now: RecordedAt, *, loss: str = "6") -> RiskBudgetReservation:
    return RiskBudgetReservation(
        EntityId.new("risk_reservation"),
        EntityId.new("simulation_account"),
        EntityId.new("trade_plan"),
        1,
        "a" * 64,
        "SHFE_AG_2601",
        "strategy:test",
        "day",
        EntityId.new("authorization_basis"),
        "b" * 64,
        "risk:test",
        1,
        "c" * 64,
        Decimal("10"),
        Decimal(loss),
        Decimal("1"),
        RecordedAt.from_datetime(now.value + timedelta(hours=1)),
        risk_dimensions=(("instrument", "SHFE_AG_2601"),),
        quantity=Decimal("1"),
        source_ref=EntityId.new("authorization_basis"),
        source_hash="b" * 64,
    )


def test_concurrent_reservations_never_oversell_immutable_ceiling() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    ledger = RiskBudgetLedger(Decimal("10"), "risk:test", 1, "c" * 64)
    reservations = [_reservation(now), _reservation(now)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(lambda item: ledger.reserve(item, now), reservations))
    assert sum(accepted) == 1
    assert ledger.held_amount(now) == Decimal("6")
    ledger.assert_invariants(now)


def test_reservation_lifecycle_is_idempotent_and_restorable() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    ledger = RiskBudgetLedger(Decimal("10"), "risk:test", 1, "c" * 64)
    reservation = _reservation(now)
    assert ledger.reserve(reservation, now)
    assert ledger.reserve(reservation, now)
    shrunk = ledger.shrink(reservation.reservation_id, Decimal("4"))
    assert shrunk is not None and shrunk.worst_case_loss == Decimal("4")
    consumed = ledger.consume(reservation.reservation_id, now)
    assert consumed is not None and consumed.status is ReservationStatus.CONSUMED
    assert ledger.reconcile(reservation.reservation_id).status is ReservationStatus.RECONCILED
    restored = RiskBudgetLedger.restore(
        ledger.snapshot(),
        total_ceiling=Decimal("10"),
        constitution_ref="risk:test",
        constitution_version=1,
        constitution_hash="c" * 64,
    )
    assert restored.reservation(reservation.reservation_id).status is ReservationStatus.RECONCILED


def test_reservation_shrink_cannot_increase_worst_case_loss() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    ledger = RiskBudgetLedger(Decimal("10"), "risk:test", 1, "c" * 64)
    reservation = _reservation(now, loss="4")
    assert ledger.reserve(reservation, now)
    assert ledger.shrink(reservation.reservation_id, Decimal("5")) is None


def test_consume_with_commit_is_retryable_when_coupled_commit_fails() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    ledger = RiskBudgetLedger(Decimal("10"), "risk:test", 1, "c" * 64)
    reservation = _reservation(now)
    assert ledger.reserve(reservation, now)
    assert ledger.consume_with_commit(reservation.reservation_id, now, lambda: False) is None
    assert ledger.reservation(reservation.reservation_id).status is ReservationStatus.HELD
    consumed = ledger.consume_with_commit(reservation.reservation_id, now, lambda: True)
    assert consumed is not None and consumed.status is ReservationStatus.CONSUMED


def test_restore_rejects_snapshot_that_exceeds_ceiling() -> None:
    now = RecordedAt.from_datetime(datetime.now(UTC))
    first = _reservation(now)
    second = _reservation(now)
    ledger = RiskBudgetLedger.restore(
        (first, second),
        total_ceiling=Decimal("20"),
        constitution_ref="risk:test",
        constitution_version=1,
        constitution_hash="c" * 64,
    )
    with pytest.raises(ValueError, match="ceiling"):
        RiskBudgetLedger.restore(
            ledger.snapshot(),
            total_ceiling=Decimal("10"),
            constitution_ref="risk:test",
            constitution_version=1,
            constitution_hash="c" * 64,
        )


@pytest.mark.parametrize("scenario", ["LONG", "SHORT", "PARTIAL_TAKE_PROFIT", "ADD_ON", "GAP"])
def test_worst_loss_never_exceeds_ceiling_across_position_scenarios(scenario: str) -> None:
    """The reservation ledger is direction/exit agnostic and remains the hard cap."""
    now = RecordedAt.from_datetime(datetime.now(UTC))
    ledger = RiskBudgetLedger(Decimal("10"), "risk:test", 1, "c" * 64)
    loss = {"LONG": "7", "SHORT": "8", "PARTIAL_TAKE_PROFIT": "3", "ADD_ON": "6", "GAP": "9"}[scenario]
    reservation = _reservation(now, loss=loss)
    assert ledger.reserve(reservation, now)
    assert ledger.held_amount(now) <= ledger.total_ceiling
    ledger.assert_invariants(now)
